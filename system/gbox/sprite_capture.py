"""`sprite_capture`: a sprite's animation out of a running 2D game, from the point or box the operator highlighted
(pick whip #1438 scope b; animation extraction #1384).

The game is never paused. Frames are pulled from the session at the requested rate (the live MJPEG stream when the
session has one, else the adapter's get_frame), the sprite under the seed is tracked across them, every frame is
cropped to the tracked box and its background made transparent, and the result is written as

  frame_0000.png ...  the PNG sequence (RGBA, one canvas size, anchored on the sprite's centroid); consecutive
                      identical frames are merged into durations
  sheet.png + sheet.json  a sprite-sheet grid and its index: frame boxes on the sheet, durations, the tracked box per
                      source frame, and the loop found by frame similarity
  preview.apng (+ preview.webp when Pillow has libwebp)  a looping preview the app shows as an <img>
  clip.mp4            through ffmpeg when it is on the worker's PATH; otherwise reported as unavailable, never a failure
  frames.zip          the sequence and its index in one download

Background estimate: the per-pixel median of a sample of frames. When the camera scrolls, consecutive frames are
registered first (phase correlation over the whole picture) and the median is taken in world coordinates, so the
sprite is what differs from the scenery whether it moves across the screen or the camera follows it. When no such
estimate explains the picture (one frame; a sprite that never moves), the dominant colour around the seed is the
background instead.

Captures stay on the worker under <cache>/sprite_captures/<id>/ for op=list and op=export (MP4 / GIF / WebP / APNG at
a scale and loop count). With save=true the clip also goes into the character collection as a 2D "sprites" entry
(gbox.characters: a PNG model, meta.animations[] = its clips), so one character can hold walk, jump, idle, ...
"""
from __future__ import annotations

import io
import json
import math
import shutil
import subprocess
import sys
import tempfile
import time
import warnings
import zipfile
from pathlib import Path

import numpy as np
from pydantic import BaseModel, Field

from .registry import Ctx, Unsupported, tool
from .store import sha256

VERSION = "1.0"
MAX_SECONDS = 20.0
MAX_FPS = 60.0
MAX_FRAMES = 900               # one capture's frame budget (20 s at 45 fps): the rate drops to fit, never the length
MAX_BYTES = 512 * 2 ** 20      # ... and its memory budget (frames stay as the encoder's bytes until they are needed)
BG_SAMPLES = 24                # frames in the background median
LOOP_SEARCH = 240              # unique frames searched for a loop
PNG_SIG = b"\x89PNG\r\n\x1a\n"
PAL_MARKS = ("(europe)", "(pal)", "(germany)", "(france)", "(spain)", "(italy)", "(australia)", "(netherlands)",
             "(sweden)", "(uk)")

_clock, _sleep = time.monotonic, time.sleep      # patched by tests


# ------------------------------------------------------------------------------------------------ frames

def decode(payload) -> np.ndarray:
    """RGB uint8 HxWx3 from PNG/JPEG bytes or an array (HxW, HxWx3, HxWx4)."""
    if isinstance(payload, np.ndarray):
        a = payload
        if a.ndim == 2:
            a = np.stack([a, a, a], axis=-1)
        return np.ascontiguousarray(a[..., :3]).astype(np.uint8, copy=False)
    from PIL import Image
    with Image.open(io.BytesIO(bytes(payload))) as im:
        return np.asarray(im.convert("RGB"), dtype=np.uint8)


class Frames:
    """Captured frames as the encoder's bytes (PNG / JPEG) or arrays, decoded on access with a small cache: a 20 s
    capture at 60 fps would be more than a gigabyte of raw pixels."""
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self._cache: dict[int, np.ndarray] = {}

    def __len__(self):
        return len(self.payloads)

    def __getitem__(self, i: int) -> np.ndarray:
        if i < 0:
            i += len(self.payloads)
        if i not in self._cache:
            if len(self._cache) >= 4:
                self._cache.pop(next(iter(self._cache)))
            self._cache[i] = decode(self.payloads[i])
        return self._cache[i]


def game_fps(g: dict | None) -> float:
    """The game's picture rate when it is known: an explicit catalog value, else 50 for PAL releases and 60 for any
    console / arcade platform; 0 when nothing is known (the tool then samples at 30)."""
    g = g or {}
    for k in ("fps", "frame_rate"):
        try:
            if float(g.get(k) or 0) > 0:
                return float(g[k])
        except (TypeError, ValueError):
            pass
    title = str(g.get("title") or "").lower()
    if any(m in title for m in PAL_MARKS):
        return 50.0
    return 60.0 if g.get("platform") else 0.0


def frame_getter(ad):
    """The cheapest live picture of a session: its MJPEG stream when one is running (Spark sessions), else get_frame."""
    st = getattr(ad, "stream", None)
    if st is not None and hasattr(st, "wait") and hasattr(st, "latest"):
        seen = [-1]

        def get():
            st.wait(seen[0], 1.0)
            seen[0] = getattr(st, "seq", seen[0])
            if st.latest is None:
                raise RuntimeError("the session stream has not produced a frame")
            return st.latest
        return get
    if not hasattr(ad, "get_frame"):
        raise Unsupported("this session's emulator cannot provide frames")
    return ad.get_frame


def grab_frames(get_frame, seconds: float, fps: float, progress=None) -> tuple[list, list[float]]:
    """Pull frames at `fps` for `seconds` without touching the game: (payloads, seconds since the first grab).
    The budget (MAX_FRAMES / MAX_BYTES) lowers the rate, never the length. Stops early after 5 failed grabs in a row;
    a first grab that fails is the session telling us it cannot provide frames."""
    seconds = max(0.05, min(float(seconds), MAX_SECONDS))
    fps = max(1.0, min(float(fps), MAX_FPS))
    want = max(1, min(int(round(seconds * fps)), MAX_FRAMES))
    interval = seconds / want if want > 1 else 1.0 / fps
    out, times, failures = [], [], 0
    t0 = _clock()
    while len(out) < want:
        target = t0 + len(out) * interval
        now = _clock()
        if target > now:
            _sleep(target - now)
        try:
            payload = get_frame()
            if payload is None or (isinstance(payload, (bytes, bytearray)) and not payload):
                raise RuntimeError("empty frame")
        except Exception as e:                      # noqa: BLE001 - a grab that fails is data, up to a point
            if not out:
                raise Unsupported(f"the session cannot provide frames ({type(e).__name__}: {e})") from e
            failures += 1
            if failures >= 5:
                break
            continue
        failures = 0
        if not out and isinstance(payload, (bytes, bytearray)):
            want = max(1, min(want, MAX_BYTES // max(1, len(payload))))
            interval = seconds / want if want > 1 else interval
        out.append(payload)
        times.append(_clock() - t0)
        if progress and len(out) % 10 == 1:
            progress(5 + 35 * len(out) / want, f"Watching the game ({len(out)}/{want} frames, not pausing it)")
        if _clock() - t0 > seconds + interval:
            break
    return out, times


# ------------------------------------------------------------------------------------------------ registration

def _gray(a: np.ndarray) -> np.ndarray:
    return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114


def shift_between(fa: np.ndarray, fb: np.ndarray, shape: tuple[int, int]) -> tuple[int, int]:
    """(dx, dy) such that picture b is picture a moved right by dx and down by dy, from the pictures' rfft2s
    (phase correlation)."""
    r = fb * np.conj(fa)
    r /= np.abs(r) + 1e-9
    r[0, 0] = 0
    c = np.fft.irfft2(r, s=shape)
    y, x = np.unravel_index(int(np.argmax(c)), c.shape)
    h, w = shape
    return int(x - w if x > w // 2 else x), int(y - h if y > h // 2 else y)


def register(frames, tolerance: int, sample: int = 8) -> list[tuple[int, int]]:
    """Camera offset of every frame relative to the first, in integer pixels: (0, 0) everywhere when nothing moves
    between sampled consecutive frames or the picture has no texture to register on. A sprite moving over a static
    scenery registers as (0, 0) too: the scenery dominates the correlation."""
    n = len(frames)
    zeros = [(0, 0)] * n
    if n < 2:
        return zeros
    first = frames[0]
    h, w = first.shape[:2]
    g0 = _gray(first)
    if g0.std() < 3.0:
        return zeros
    idx = sorted(set(np.linspace(0, n - 2, min(sample, n - 1)).round().astype(int).tolist()))
    moved = []
    for i in idx:
        a, b = frames[i], frames[i + 1]
        if b.shape == a.shape:
            moved.append(float((np.abs(a.astype(np.int16) - b.astype(np.int16)).sum(-1) > tolerance).mean()))
    if not moved or max(moved) < 0.02:
        return zeros
    offsets, ox, oy = [(0, 0)], 0, 0
    prev = np.fft.rfft2(g0)
    for i in range(1, n):
        f = frames[i]
        if f.shape[:2] != (h, w):
            offsets.append((ox, oy))
            continue
        cur = np.fft.rfft2(_gray(f))
        dx, dy = shift_between(prev, cur, (h, w))
        if abs(dx) > w // 4 or abs(dy) > h // 4:         # a cut, not a scroll
            dx = dy = 0
        ox, oy = ox + dx, oy + dy
        offsets.append((ox, oy))
        prev = cur
    return offsets


# ------------------------------------------------------------------------------------------------ background

class Background:
    """Per-pixel median of sampled frames in world coordinates (the camera offsets undo scrolling). `quality` is the
    share of the sampled frames' pixels the model explains within the tolerance."""
    def __init__(self, frames, offsets: list[tuple[int, int]], tolerance: int):
        self.tolerance = tolerance
        n = len(frames)
        self.h, self.w = frames[0].shape[:2]
        xs = [-ox for ox, _ in offsets]
        ys = [-oy for _, oy in offsets]
        x0, y0 = min(xs), min(ys)
        W, H = max(xs) + self.w - x0, max(ys) + self.h - y0
        self.positions = [(xs[i] - x0, ys[i] - y0) for i in range(n)]
        idx = sorted(set(np.linspace(0, n - 1, min(n, BG_SAMPLES)).round().astype(int).tolist()))
        stack = np.zeros((len(idx), H, W, 3), np.uint8)
        valid = np.zeros((len(idx), H, W), bool)
        for k, i in enumerate(idx):
            f = frames[i]
            if f.shape[:2] != (self.h, self.w):
                continue
            px, py = self.positions[i]
            stack[k, py:py + self.h, px:px + self.w] = f
            valid[k, py:py + self.h, px:px + self.w] = True
        self.model = np.full((H, W, 3), np.nan, np.float32)
        band = max(1, (8 << 20) // max(1, len(idx) * W * 3 * 4))        # rows per ~8 MB float32 chunk
        for y in range(0, H, band):
            s = stack[:, y:y + band].astype(np.float32)
            v = valid[:, y:y + band]
            if v.all():
                self.model[y:y + band] = np.median(s, axis=0)
            else:
                s[~v] = np.nan
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    self.model[y:y + band] = np.nanmedian(s, axis=0)
        self.known = ~np.isnan(self.model[..., 0])
        q = [1.0 - float(self.foreground(frames[i], i).mean()) for i in idx if frames[i].shape[:2] == (self.h, self.w)]
        self.quality = float(np.mean(q)) if q else 0.0

    def foreground(self, frame: np.ndarray, i: int) -> np.ndarray:
        """Pixels of frame i that differ from the scenery (unknown scenery counts as background)."""
        px, py = self.positions[i]
        bg = self.model[py:py + self.h, px:px + self.w]
        known = self.known[py:py + self.h, px:px + self.w]
        d = np.abs(frame.astype(np.float32) - bg).sum(-1)
        return (d > self.tolerance) & known


def border_colour(frame: np.ndarray, seed: tuple[int, int], radius: int = 64) -> tuple[np.ndarray, float]:
    """The dominant colour on the border of a window around the seed and the share of the border it covers:
    the background, when that share says the scenery there is flat."""
    h, w = frame.shape[:2]
    sx, sy = seed
    x0, y0 = max(0, sx - radius), max(0, sy - radius)
    x1, y1 = min(w, sx + radius + 1), min(h, sy + radius + 1)
    win = frame[y0:y1, x0:x1]
    ring = np.concatenate([win[0], win[-1], win[:, 0], win[:, -1]]).astype(np.int64)
    packed = (ring[:, 0] << 16) | (ring[:, 1] << 8) | ring[:, 2]
    vals, counts = np.unique(packed, return_counts=True)
    k = int(np.argmax(counts))
    v = int(vals[k])
    return np.array([(v >> 16) & 255, (v >> 8) & 255, v & 255], np.uint8), float(counts[k] / len(packed))


def flat_foreground(frame: np.ndarray, colour: np.ndarray, tolerance: int) -> np.ndarray:
    return np.abs(frame.astype(np.int16) - colour.astype(np.int16)).sum(-1) > tolerance


# ------------------------------------------------------------------------------------------------ tracking

def _fill(cur: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Grow `cur` to its 8-connected component within `mask`: whole horizontal and vertical runs per pass (a blob
    takes a handful of passes, not one per pixel of its diameter) plus one plain dilation for diagonal links."""
    while True:
        before = int(cur.sum())
        for axis in (1, 0):
            m = mask if axis == 1 else np.ascontiguousarray(mask.T)
            c = cur if axis == 1 else np.ascontiguousarray(cur.T)
            starts = m.copy()
            starts[:, 1:] &= ~m[:, :-1]
            run = np.cumsum(starts.ravel()).reshape(m.shape)
            hit = np.zeros(int(run.max()) + 1, bool)
            hit[run[c]] = True
            grown = m & hit[run]
            cur = grown if axis == 1 else np.ascontiguousarray(grown.T)
        d = cur.copy()
        d[1:, 1:] |= cur[:-1, :-1]
        d[1:, :-1] |= cur[:-1, 1:]
        d[:-1, 1:] |= cur[1:, :-1]
        d[:-1, :-1] |= cur[1:, 1:]
        cur = d & mask
        if int(cur.sum()) == before:
            return cur


def component(mask: np.ndarray, seed: tuple[int, int], radius: int):
    """The 8-connected foreground component at the seed (the nearest foreground pixel within `radius`):
    (component window, x0, y0), or None. The window grows while the component touches its edge."""
    h, w = mask.shape
    sx, sy = seed
    r = max(2, int(radius))
    pick = None
    while True:
        x0, y0 = max(0, sx - r), max(0, sy - r)
        x1, y1 = min(w, sx + r + 1), min(h, sy + r + 1)
        win = mask[y0:y1, x0:x1]
        if pick is None:
            ys, xs = np.nonzero(win)
            if not len(ys):
                return None
            d = (ys + y0 - sy) ** 2 + (xs + x0 - sx) ** 2
            k = int(np.argmin(d))
            if d[k] > radius * radius:
                return None
            pick = (int(xs[k] + x0), int(ys[k] + y0))
        cur = np.zeros(win.shape, bool)
        cur[pick[1] - y0, pick[0] - x0] = True
        comp = _fill(cur, win)
        full = x0 == 0 and y0 == 0 and x1 == w and y1 == h
        touches = ((comp[0].any() and y0 > 0) or (comp[-1].any() and y1 < h)
                   or (comp[:, 0].any() and x0 > 0) or (comp[:, -1].any() and x1 < w))
        if touches and not full:
            r *= 2
            continue
        return comp, x0, y0


def _track_frame(frame: np.ndarray, fg: np.ndarray, seed: tuple[int, int], radius: int) -> dict | None:
    c = component(fg, seed, radius)
    if c is None:
        return None
    comp, wx, wy = c
    ys, xs = np.nonzero(comp)
    x0, x1 = int(xs.min() + wx), int(xs.max() + wx + 1)
    y0, y1 = int(ys.min() + wy), int(ys.max() + wy + 1)
    m = comp[y0 - wy:y1 - wy, x0 - wx:x1 - wx]
    return {"box": (x0, y0, x1, y1), "centroid": (float(xs.mean() + wx), float(ys.mean() + wy)),
            "mask": m.copy(), "rgb": frame[y0:y1, x0:x1].copy()}


def _anchor(t: dict) -> tuple[int, int]:
    """The canvas anchor: the centroid rounded half up (round-half-even would put the same pose one pixel apart
    on alternate positions, and identical frames would stop deduplicating)."""
    cx, cy = t["centroid"]
    return int(math.floor(cx + 0.5)), int(math.floor(cy + 0.5))


def same(a: np.ndarray, b: np.ndarray, tolerance: int) -> bool:
    """Identical frames, allowing a few stray pixels (JPEG streams)."""
    if a.shape != b.shape:
        return False
    if np.array_equal(a, b):
        return True
    d = np.abs(a.astype(np.int16) - b.astype(np.int16)).sum(-1) > tolerance
    return float(d.mean()) < 0.002


def find_loop(uniq: list[np.ndarray], tolerance: int) -> dict | None:
    """The shortest period, from the earliest start, that the unique-frame sequence repeats with to its end. The
    repeat must be seen for at least two frames and half a period (ABCAB loops with period 3; ABCA is not evidence).
    None when the sequence does not repeat."""
    n = min(len(uniq), LOOP_SEARCH)
    if n < 2:
        return None
    digests = [sha256(u.tobytes()) for u in uniq[:n]]
    cache: dict[tuple[int, int], bool] = {}

    def eq(i, j):
        if digests[i] == digests[j]:
            return True
        if (i, j) not in cache:
            cache[(i, j)] = same(uniq[i], uniq[j], tolerance)
        return cache[(i, j)]
    for p in range(1, n):
        need = max(2, math.ceil(p / 2))
        for s in range(0, n - p - need + 1):
            if all(eq(k, k + p) for k in range(s, n - p)):
                return {"start": s, "length": p, "repeats": round((n - s) / p, 2), "frames": list(range(s, s + p))}
    return None


def analyze(frames, times: list[float] | None = None, seed: tuple[int, int] | None = None,
            box: tuple[int, int, int, int] | None = None, margin: int = 2, tolerance: int = 24, fps: float = 30.0,
            progress=None) -> dict:
    """Track the sprite at the seed point (or inside the box) through the frames and cut it out: unique RGBA frames on
    one canvas (anchored on the sprite's centroid), their durations, the tracked box per source frame, the loop."""
    n = len(frames)
    if n == 0:
        raise Unsupported("no frames to analyse")
    first = frames[0]
    h, w = first.shape[:2]
    if box is not None:
        bx, by, bw, bh = box
        seed = (int(bx + bw / 2), int(by + bh / 2))
        radius0 = max(8, int(max(bw, bh) / 2))
    else:
        if seed is None:
            raise ValueError("give the highlighted point (x, y) or box [x, y, w, h]")
        radius0 = 24
    seed = (min(max(int(seed[0]), 0), w - 1), min(max(int(seed[1]), 0), h - 1))
    if progress:
        progress(42, "Estimating the scenery behind the sprite")
    colour, share = border_colour(first, seed)
    offsets, scrolling, bg, t = [(0, 0)] * n, False, None, None
    if share >= 0.9:                                       # a flat colour around the seed: it is the background
        mode = "flat"
    else:
        offsets = register(frames, tolerance)
        scrolling = any(o != (0, 0) for o in offsets)
        bg = Background(frames, offsets, tolerance) if n >= 2 else None
        mode = ("scrolling" if scrolling else "static") if bg is not None and bg.quality >= 0.5 else "flat"
        if mode != "flat":
            t = _track_frame(first, bg.foreground(first, 0), seed, radius0)
            if t is None or int(t["mask"].sum()) < 4:
                mode = "flat"                              # nothing moves there: a flat colour is the only background left
    if mode == "flat":
        if share < 0.5:
            raise Unsupported("no sprite at that point: nothing there differs from the scenery and the scenery is not "
                              "a flat colour (the sprite must move against the background, or stand on a flat colour)")
        t = _track_frame(first, flat_foreground(first, colour, tolerance), seed, radius0)
        if t is None:
            raise Unsupported("no sprite at that point: only the flat background colour is there")

    def fg_of(frame, i):
        return flat_foreground(frame, colour, tolerance) if mode == "flat" else bg.foreground(frame, i)

    tracks, lost, last = [t], [], t
    for i in range(1, n):
        f = frames[i]
        if f.shape[:2] != (h, w):
            tracks.append(None)
            lost.append(i)
            continue
        cx, cy = last["centroid"]
        x0, y0, x1, y1 = last["box"]
        ti = _track_frame(f, fg_of(f, i), (int(round(cx)), int(round(cy))), max(16, x1 - x0, y1 - y0))
        tracks.append(ti)
        if ti is None:
            lost.append(i)
        else:
            last = ti
        if progress and i % 25 == 0:
            progress(45 + 35 * i / n, f"Tracking the sprite ({i}/{n})")
    L = R = U = D = 0
    for t in tracks:
        if t is None:
            continue
        ax, ay = _anchor(t)
        x0, y0, x1, y1 = t["box"]
        L, R, U, D = max(L, ax - x0), max(R, x1 - ax), max(U, ay - y0), max(D, y1 - ay)
    L, R, U, D = L + margin, R + margin, U + margin, D + margin
    cw, ch = L + R, U + D
    crops, boxes, placements = [], [], []
    for t in tracks:
        if t is None:
            crops.append(None)
            boxes.append(None)
            placements.append(None)
            continue
        ax, ay = _anchor(t)
        x0, y0, x1, y1 = t["box"]
        canvas = np.zeros((ch, cw, 4), np.uint8)
        px, py = x0 - (ax - L), y0 - (ay - U)
        m, rgb = t["mask"], t["rgb"]
        sub = canvas[py:py + m.shape[0], px:px + m.shape[1]]
        sub[..., :3][m] = rgb[m]
        sub[..., 3][m] = 255
        crops.append(canvas)
        bx0, by0 = max(0, x0 - margin), max(0, y0 - margin)
        boxes.append([bx0, by0, min(w, x1 + margin) - bx0, min(h, y1 + margin) - by0])
        placements.append([ax - L, ay - U])
    interval_ms = 1000.0 / fps
    uniq, runs = [], []
    for i, c in enumerate(crops):
        if c is None:
            continue
        if uniq and same(uniq[-1], c, tolerance):
            runs[-1].append(i)
        else:
            uniq.append(c)
            runs.append([i])
    durations = [int(round(len(r) * interval_ms)) for r in runs]
    if progress:
        progress(80, f"{len(uniq)} distinct frames; looking for the loop")
    loop = find_loop(uniq, tolerance)
    captured_fps = fps
    if times and len(times) > 1 and times[-1] > times[0]:
        captured_fps = (len(times) - 1) / (times[-1] - times[0])
    return {"frames": uniq, "runs": runs, "durations_ms": durations, "boxes": boxes, "placements": placements,
            "lost": lost, "loop": loop, "canvas": [cw, ch], "anchor": [L, U], "background": mode,
            "bg_quality": round(bg.quality, 3) if bg is not None else None, "scrolling": scrolling,
            "offsets": offsets, "fps": fps, "captured_fps": round(captured_fps, 2), "source_frames": n,
            "picture": [w, h]}


# ------------------------------------------------------------------------------------------------ encoding

def png_bytes(rgba: np.ndarray) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(rgba), "RGBA").save(b, "PNG")
    return b.getvalue()


def build_sheet(uniq: list[np.ndarray]) -> tuple[np.ndarray, list[list[int]], int, int]:
    """A grid of the unique frames (no padding: cell = canvas) and each frame's [x, y, w, h] on it."""
    n = len(uniq)
    ch, cw = uniq[0].shape[:2]
    cols = max(1, math.ceil(math.sqrt(n)))
    rows = math.ceil(n / cols)
    sheet = np.zeros((rows * ch, cols * cw, 4), np.uint8)
    cells = []
    for k, u in enumerate(uniq):
        x, y = (k % cols) * cw, (k // cols) * ch
        sheet[y:y + ch, x:x + cw] = u
        cells.append([x, y, cw, ch])
    return sheet, cells, cols, rows


def _gif_frames(ims):
    from PIL import Image
    out = []
    for im in ims:
        alpha = np.asarray(im.getchannel("A"))
        p = im.convert("RGB").quantize(colors=255, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
        pal = (p.getpalette() or [])[:765]
        pal += [0] * (765 - len(pal)) + [0, 0, 0]
        arr = np.asarray(p).copy()
        arr[alpha == 0] = 255
        q = Image.fromarray(arr, "P")
        q.putpalette(pal)
        out.append(q)
    return out


def preview_bytes(uniq: list[np.ndarray], durations: list[int], fmt: str = "apng", loop: int = 0) -> bytes:
    """A looping animation: apng (always), webp (lossless; needs libwebp) or gif (255 colours + transparency)."""
    from PIL import Image
    ims = [Image.fromarray(np.ascontiguousarray(u), "RGBA") for u in uniq]
    b = io.BytesIO()
    if fmt == "webp":
        ims[0].save(b, "WEBP", save_all=True, append_images=ims[1:], duration=durations, loop=loop, lossless=True,
                    quality=100)
    elif fmt == "gif":
        g = _gif_frames(ims)
        g[0].save(b, "GIF", save_all=True, append_images=g[1:], duration=durations, loop=loop, disposal=2,
                  transparency=255, optimize=False)
    elif len(ims) == 1:
        ims[0].save(b, "PNG")
    else:
        ims[0].save(b, "PNG", save_all=True, append_images=ims[1:], duration=durations, loop=loop, disposal=1, blend=0)
    return b.getvalue()


def expand(durations: list[int], fps: float, loops: int = 1, loop: dict | None = None) -> list[int]:
    """Unique-frame index per output frame at a constant `fps`: each frame repeated for its duration; the detected loop
    section played `loops` times (the whole sequence when there is none)."""
    interval = 1000.0 / fps
    order = list(range(len(durations)))
    if loops > 1:
        if loop:
            s, p = int(loop["start"]), int(loop["length"])
            order = order[:s] + order[s:s + p] * loops
        else:
            order = order * loops
    seq = []
    for i in order:
        seq += [i] * max(1, int(round(durations[i] / interval)))
    return seq


def mp4_bytes(uniq: list[np.ndarray], durations: list[int], fps: float, loops: int = 1, loop: dict | None = None,
              background: tuple[int, int, int] = (0, 0, 0)) -> bytes:
    """H.264 MP4 through ffmpeg (the frames over a flat colour: MP4 has no alpha). Unsupported when ffmpeg is not on
    this worker's PATH."""
    exe = shutil.which("ffmpeg")
    if not exe:
        raise Unsupported("ffmpeg is not on this worker's PATH")
    from PIL import Image
    h, w = uniq[0].shape[:2]
    seq = expand(durations, fps, loops, loop)
    bg = Image.new("RGBA", (w, h), (*background, 255))
    rendered: dict[int, bytes] = {}
    with tempfile.TemporaryDirectory(prefix="gbox-sprite-") as td:
        for k, idx in enumerate(seq):
            if idx not in rendered:
                im = Image.alpha_composite(bg, Image.fromarray(np.ascontiguousarray(uniq[idx]), "RGBA")).convert("RGB")
                b = io.BytesIO()
                im.save(b, "PNG")
                rendered[idx] = b.getvalue()
            (Path(td) / f"f_{k:05d}.png").write_bytes(rendered[idx])
        out = Path(td) / "clip.mp4"
        r = subprocess.run([exe, "-loglevel", "error", "-y", "-framerate", f"{fps:g}", "-i", str(Path(td) / "f_%05d.png"),
                            "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
                           capture_output=True, text=True, timeout=300,
                           creationflags=0x08000000 if sys.platform == "win32" else 0)
        if r.returncode or not out.is_file():
            raise RuntimeError("ffmpeg could not write the MP4: " + (r.stderr or "")[-400:].strip())
        return out.read_bytes()


def package(a: dict, meta: dict, want_mp4: bool = True) -> tuple[dict, dict[str, bytes], str | None]:
    """Everything a capture produces: (sheet index, {file name: bytes}, why there is no MP4 or None)."""
    uniq, runs = a["frames"], a["runs"]
    files: dict[str, bytes] = {}
    for k, u in enumerate(uniq):
        files[f"frame_{k:04d}.png"] = png_bytes(u)
    sheet, cells, cols, rows = build_sheet(uniq)
    files["sheet.png"] = png_bytes(sheet)
    index = {"tool": f"sprite_capture {VERSION}", **meta, "canvas": a["canvas"], "anchor": a["anchor"],
             "picture": a["picture"], "columns": cols, "rows": rows, "fps": a["fps"], "captured_fps": a["captured_fps"],
             "source_frames": a["source_frames"], "loop": a["loop"], "background": a["background"],
             "bg_quality": a["bg_quality"], "scrolling": a["scrolling"], "lost_frames": a["lost"],
             "boxes": a["boxes"], "placements": a["placements"],
             "frames": [{"index": k, "file": f"frame_{k:04d}.png", "sheet": cells[k], "duration_ms": a["durations_ms"][k],
                         "source_frames": runs[k], "box": a["boxes"][runs[k][0]], "placement": a["placements"][runs[k][0]]}
                        for k in range(len(uniq))]}
    files["sheet.json"] = json.dumps(index, indent=1).encode()
    files["preview.apng"] = preview_bytes(uniq, a["durations_ms"], "apng")
    try:
        from PIL import features
        if features.check("webp_anim"):
            files["preview.webp"] = preview_bytes(uniq, a["durations_ms"], "webp")
    except Exception:                                     # noqa: BLE001 - the WebP preview is a bonus
        pass
    reason = None
    if want_mp4:
        try:
            files["clip.mp4"] = mp4_bytes(uniq, a["durations_ms"], a["fps"])
        except (Unsupported, RuntimeError, OSError, subprocess.SubprocessError) as e:
            reason = str(e)
    else:
        reason = "not requested"
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w", zipfile.ZIP_DEFLATED) as z:
        for k in range(len(uniq)):
            z.writestr(f"frame_{k:04d}.png", files[f"frame_{k:04d}.png"])
        z.writestr("sheet.json", files["sheet.json"])
    files["frames.zip"] = zb.getvalue()
    return index, files, reason


MEDIA = {".png": "image/png", ".json": "application/json", ".apng": "image/apng", ".webp": "image/webp",
         ".mp4": "video/mp4", ".zip": "application/zip", ".gif": "image/gif"}


# ------------------------------------------------------------------------------------------------ storage

def captures_root(cfg) -> Path:
    return Path(cfg.cache) / "sprite_captures"


def _slug(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


def save_to_collection(cfg, name: str, clip: str, game: dict, files: dict[str, bytes], index: dict) -> dict:
    """The clip into the character collection as a 2D entry: kind "sprites" (its model is the sprite sheet), the clips
    under <slug>/clips/<clip>/ and listed in meta.animations[] so one character holds walk, jump, idle, ..."""
    from . import characters as C
    root = C.library_root(cfg)
    slug = C.slugify(name)[:48] or "sprite"
    existing = None
    try:
        existing = C.get(root, slug)
    except KeyError:
        pass
    if existing is not None and existing.get("kind") != "sprites":
        slug, existing = C.free_slug(root, name), None
    clip_slug = C.slugify(clip) or "clip"
    dest = Path(root) / slug / "clips" / clip_slug
    dest.mkdir(parents=True, exist_ok=True)
    for n in ("sheet.png", "sheet.json", "preview.apng", "preview.webp", "clip.mp4", "frames.zip"):
        if n in files:
            (dest / n).write_bytes(files[n])
    if existing is None:
        src = {"game_title": game.get("title"), "game_id": game.get("game_id"), "platform": game.get("platform"),
               "from": "sprite_capture", "session": index.get("session")}
        meta = C.add(root, slug, name, [dest / "sheet.png"], src, f"sprite_capture {VERSION}", kind="sprites",
                     aliases=[name], notes="2D sprite captured from the running game (pick whip)",
                     extra={"picture": "2d", "animations": []})
    else:
        meta = existing
    entry = {"clip": clip_slug, "name": clip, "dir": f"clips/{clip_slug}", "sheet": f"clips/{clip_slug}/sheet.png",
             "index": f"clips/{clip_slug}/sheet.json", "preview": f"clips/{clip_slug}/preview.apng",
             "webp": f"clips/{clip_slug}/preview.webp" if "preview.webp" in files else None,
             "mp4": f"clips/{clip_slug}/clip.mp4" if "clip.mp4" in files else None,
             "frames": len(index["frames"]), "fps": index["fps"], "loop": index["loop"], "canvas": index["canvas"],
             "capture": index.get("capture"), "captured": time.time()}
    anims = [x for x in meta.get("animations", []) if x.get("clip") != clip_slug] + [entry]
    meta["animations"], meta["picture"] = anims, "2d"
    C.put_meta(root, meta)
    return {"slug": slug, "root": str(root), "clip": clip_slug, "animations": len(anims), "kind": "sprites"}


# ------------------------------------------------------------------------------------------------ worker tool

class SpriteIn(BaseModel):
    op: str = "capture"                    # capture | list | export
    session_id: str = ""                   # capture: the running 2D game (the job runs on its worker)
    x: float | None = None                 # capture: the highlighted point; fractions of the picture (0..1) or pixels
    y: float | None = None
    box: list[float] | None = None         # capture: or the highlighted box [x, y, w, h] (fractions or pixels)
    seconds: float = Field(default=4, gt=0, le=MAX_SECONDS)    # capture: how long to watch
    fps: float = Field(default=0, ge=0, le=MAX_FPS)            # capture: sampling rate; 0 = the game's rate (else 30)
    name: str = ""                         # capture: the sprite / character ("Sonic") = the collection entry
    clip: str = ""                         # capture: this animation's name ("walk"); one entry holds many clips
    margin: int = Field(default=2, ge=0, le=32)       # capture: transparent pixels kept around the sprite
    tolerance: int = Field(default=24, ge=0, le=255)  # capture: RGB distance (sum) a pixel may stray from the background
    save: bool = True                      # capture: add the clip to the character collection (kind sprites)
    capture: str = ""                      # export: a capture id (op=capture result / op=list); list: filter by name
    fmt: str = "mp4"                       # export: mp4 | gif | webp | apng
    scale: int = Field(default=1, ge=1, le=8)         # export: integer upscale (nearest neighbour)
    loops: int = Field(default=0, ge=0, le=100)       # export: gif/webp/apng loop count (0 = forever); mp4: plays of the loop (0 = once)


class SpriteOut(BaseModel):
    result: dict


def _validate(out: SpriteOut, arts: dict[str, bytes]) -> list[str]:
    r = out.result
    if r.get("op") != "capture":
        return []
    d = arts.get("sheet.png", b"")
    if d[:8] != PNG_SIG:
        return ["sheet.png is not a PNG"]
    return [] if sha256(d) == (r.get("artifacts") or {}).get("sheet") else ["sheet.png hash mismatch"]


def picture_coords(inp: SpriteIn, w: int, h: int):
    """The seed point or box in picture pixels: values all within 0..1 are fractions of the picture (what the desktop
    app's pick whip reports), anything else is pixels."""
    def px(v, size, frac):
        return int(round(v * (size - 1))) if frac else int(round(v))
    if inp.box is not None:
        if len(inp.box) != 4:
            raise ValueError("box is [x, y, w, h]")
        bx, by, bw, bh = inp.box
        frac = all(0 <= v <= 1 for v in inp.box)
        return None, (px(bx, w, frac), px(by, h, frac), max(1, int(round(bw * w)) if frac else int(round(bw))),
                      max(1, int(round(bh * h)) if frac else int(round(bh))))
    if inp.x is None or inp.y is None:
        raise ValueError("give the highlighted point (x, y) or box [x, y, w, h]")
    frac = 0 <= inp.x <= 1 and 0 <= inp.y <= 1
    return (px(inp.x, w, frac), px(inp.y, h, frac)), None


def capture(inp: SpriteIn, ctx: Ctx) -> dict:
    from .tools import SESSIONS
    session = SESSIONS.get(inp.session_id)
    if session is None:
        raise Unsupported("This game session is no longer available on its worker. Open the running game in Sessions.")
    ad, g = session
    if inp.box is None and (inp.x is None or inp.y is None):
        raise ValueError("give the highlighted point (x, y) or box [x, y, w, h]")
    fps = max(1.0, min(float(inp.fps) if inp.fps else (game_fps(g) or 30.0), MAX_FPS))
    ctx.progress(2, "Watching the game: pulling frames without pausing it")
    payloads, times = grab_frames(frame_getter(ad), inp.seconds, fps, ctx.progress)
    frames = Frames(payloads)
    h, w = frames[0].shape[:2]
    seed, box = picture_coords(inp, w, h)
    a = analyze(frames, times, seed=seed, box=box, margin=inp.margin, tolerance=inp.tolerance, fps=fps,
                progress=ctx.progress)
    name = (inp.name or "sprite").strip()
    clip = (inp.clip or "clip").strip()
    cid = f"{_slug(name) or 'sprite'}-{_slug(clip) or 'clip'}-{int(time.time())}-{ctx.job_id[:8]}"
    game = {"game_id": g.get("game_id"), "title": g.get("title"), "platform": g.get("platform")}
    meta = {"capture": cid, "name": name, "clip": clip, "game": game, "session": inp.session_id, "created": time.time(),
            "seconds": float(inp.seconds), "seed": seed, "seed_box": box, "margin": inp.margin, "tolerance": inp.tolerance}
    ctx.progress(84, "Writing the PNG sequence, the sprite sheet, the preview and the MP4")
    index, files, reason = package(a, meta)
    d = captures_root(ctx.config) / cid
    d.mkdir(parents=True, exist_ok=True)
    for n, data in files.items():
        (d / n).write_bytes(data)
    prov = {"session": inp.session_id, "game": game["game_id"], "capture": cid, "sprite": name, "clip": clip}
    shas = {}
    for n, data in files.items():
        ctx.artifact(n, data, MEDIA.get(Path(n).suffix, "application/octet-stream"), **prov)
        shas[n] = sha256(data)
    artifacts = {"sheet": shas["sheet.png"], "index": shas["sheet.json"], "preview": shas["preview.apng"],
                 "webp": shas.get("preview.webp"), "mp4": shas.get("clip.mp4"), "zip": shas["frames.zip"],
                 "frames": [shas[f"frame_{k:04d}.png"] for k in range(len(a["frames"]))]}
    res = {"op": "capture", "capture": cid, "name": name, "clip": clip, "session": inp.session_id, "game": game,
           "frames": len(a["frames"]), "source_frames": a["source_frames"], "fps": fps, "captured_fps": a["captured_fps"],
           "seconds": float(inp.seconds), "picture": a["picture"], "canvas": a["canvas"], "anchor": a["anchor"],
           "loop": a["loop"], "durations_ms": a["durations_ms"], "boxes": a["boxes"], "lost_frames": a["lost"],
           "background": a["background"], "bg_quality": a["bg_quality"], "scrolling": a["scrolling"],
           "artifacts": artifacts, "mp4": shas.get("clip.mp4") or "unavailable", "mp4_reason": reason,
           "collection": None, "collection_error": None, "stored": str(d)}
    if inp.save:
        try:
            ctx.progress(95, "Adding the clip to the character collection")
            res["collection"] = save_to_collection(ctx.config, name, clip, game, files, index)
        except Exception as e:                            # noqa: BLE001 - the capture stands on its own
            res["collection_error"] = f"{type(e).__name__}: {e}"
    (d / "capture.json").write_text(json.dumps(res, indent=1))
    return res


def list_captures(cfg, name: str = "") -> dict:
    root = captures_root(cfg)
    items = []
    for p in sorted(root.glob("*/capture.json")):
        try:
            c = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if name and name.lower() not in f"{c.get('name', '')} {c.get('clip', '')} {c.get('capture', '')}".lower():
            continue
        items.append({k: c.get(k) for k in ("capture", "name", "clip", "game", "session", "frames", "source_frames",
                                             "fps", "loop", "canvas", "mp4", "collection", "stored")})
    return {"op": "list", "captures": items, "root": str(root)}


def export(inp: SpriteIn, ctx: Ctx) -> dict:
    d = captures_root(ctx.config) / (inp.capture or "")
    if not inp.capture or not (d / "sheet.json").is_file():
        raise ValueError(f"no capture {inp.capture!r} on this worker (sprite_capture op=list shows them)")
    index = json.loads((d / "sheet.json").read_text())
    from PIL import Image
    uniq = [np.asarray(Image.open(d / f["file"]).convert("RGBA")) for f in index["frames"]]
    durations = [int(f["duration_ms"]) for f in index["frames"]]
    fmt, scale, loops = inp.fmt.lower(), int(inp.scale), int(inp.loops)
    if scale > 1:
        uniq = [np.kron(u, np.ones((scale, scale, 1), np.uint8)) for u in uniq]
    res = {"op": "export", "capture": inp.capture, "fmt": fmt, "scale": scale, "loops": loops, "frames": len(uniq),
           "size": [int(uniq[0].shape[1]), int(uniq[0].shape[0])]}
    if fmt == "mp4":
        try:
            data = mp4_bytes(uniq, durations, float(index["fps"]), loops=max(1, loops), loop=index.get("loop"))
        except (Unsupported, RuntimeError, OSError, subprocess.SubprocessError) as e:
            return res | {"artifact": "unavailable", "reason": str(e)}
    elif fmt in ("gif", "webp", "apng"):
        data = preview_bytes(uniq, durations, fmt, loop=loops)
    else:
        raise ValueError("fmt is mp4 | gif | webp | apng")
    fname = f"{inp.capture}.{fmt}"
    ctx.artifact(fname, data, MEDIA.get("." + fmt, "application/octet-stream"), capture=inp.capture,
                 sprite=index.get("name"), clip=index.get("clip"), scale=scale, loops=loops)
    return res | {"artifact": sha256(data), "file": fname, "bytes": len(data)}


@tool("sprite_capture", VERSION, SpriteIn, SpriteOut, capabilities=["runtime", "video", "asset"],
      artifacts=["frame_0000.png", "sheet.png", "sheet.json", "preview.apng", "preview.webp", "clip.mp4", "frames.zip"],
      timeout_s=600, validate=_validate, validation="sheet.png PNG signature + hash",
      side_effects=["save=true adds a 2D 'sprites' entry (or a clip of one) to the character collection"])
def sprite_capture(inp: SpriteIn, ctx: Ctx):
    """Capture a sprite's animation from a running 2D game without pausing it: op=capture with session_id and the
    highlighted point (x, y) or box [x, y, w, h] (fractions of the picture or pixels), seconds (default 4, max 20),
    fps (default the game's rate or 30), name (the character) and clip (the animation). Tracks the sprite, cuts it out
    with a transparent background and returns a PNG sequence, a sprite sheet + JSON index (frame boxes, durations,
    loop), a looping APNG/WebP preview and an MP4 (ffmpeg; 'unavailable' without it) as artifacts, plus the loop and
    the tracked box per frame; save=true files it in the character collection as a 2D entry. op=list shows this
    worker's captures; op=export re-encodes one as mp4 | gif | webp | apng at a scale and loop count."""
    if inp.op == "capture":
        return {"result": capture(inp, ctx)}
    if inp.op == "list":
        return {"result": list_captures(ctx.config, inp.capture or inp.name)}
    if inp.op == "export":
        return {"result": export(inp, ctx)}
    raise ValueError(f"unknown op {inp.op!r} (capture | list | export)")
