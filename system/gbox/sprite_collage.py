"""Sprite collage: tile chosen 2D animation clips onto one canvas along a timeline (the basis of the operator's
animation collage system).

A clip is any collection ``sprites`` clip: ``<entry>/clips/<clip>/sheet.json`` + ``sheet.png`` as written by
gbox.sonic2d_sprites (per-frame ``duration_frames`` at ``fps``, an ``origin`` hotspot, a ``loop``) or by
gbox.sprite_capture (``duration_ms``, an ``anchor``). Each frame's picture is cut from ``sheet.png`` by its ``sheet``
cell, so the same reader serves both.

Layout (JSON)::

  {"canvas": [320, 224], "fps": 60, "frames": 240, "background": "#262830" | [r, g, b, a] | "transparent",
   "scale": 2,
   "items": [{"clip": "sonic2_sonic/spindash_charge", "x": 80, "y": 160, "start": 0, "end": null,
              "loops": 0, "hold": "last", "flip": false, "scale": 1, "z": 0, "speed": 1.0, "offset": 0}, ...]}

* ``clip``: ``<entry>/<clip>`` (or ``<entry>:<clip>``) under the collection root, or a path to a clip folder or its
  sheet.json.
* ``x``/``y``: where the clip's origin (the sprite's x_pos/y_pos) lands, in canvas pixels; ``flip`` mirrors around it.
* ``start``/``end``: output frames the item is on screen (end exclusive; default: to the end of the collage).
* ``loops``: how many times the clip's loop section plays (0 = until ``end``); afterwards ``hold`` "last" keeps the
  final frame, "hide" removes it. Clips without a loop play once.
* ``speed`` scales clip time; ``offset`` starts that many clip frames in; ``z`` orders items (higher on top).
* ``frames``: the collage length (default: the latest finite item end, else 4 s); ``scale`` upscales the whole output
  (nearest neighbour).

``export`` writes ``frames/collage_NNNN.png`` (RGBA), ``collage.json`` (the resolved layout + per-item clip info),
``preview.apng`` and ``collage.mp4`` (ffmpeg; over the background, or the collection grey when it is transparent).

CLI: ``python -m gbox.sprite_collage LAYOUT.json --out DIR [--root COLLECTION_ROOT] [--no-mp4]``
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

VERSION = "1.0"
DEFAULT_SECONDS = 4.0
MAX_FRAMES = 60 * 120


class CollageError(ValueError):
    pass


@dataclass
class Clip:
    name: str
    images: list               # RGBA arrays, one per clip frame
    durations: list            # in clip ticks
    fps: float                 # ticks per second
    origins: list              # (x, y) per frame
    loop: dict | None          # {start, length} in frames
    source: str

    @property
    def total(self) -> int:
        return int(sum(self.durations))

    def play_ticks(self, loops: int = 0) -> int | None:
        """Ticks a play lasts: the whole clip without a loop, intro + ``loops`` loop passes, None when it loops on."""
        if not self.loop:
            return self.total
        if not loops:
            return None
        starts = np.cumsum([0] + list(self.durations))
        intro = int(starts[self.loop["start"]])
        return intro + loops * int(starts[self.loop["start"] + self.loop["length"]] - intro)

    def frame_at(self, tick: int, loops: int = 0) -> int | None:
        """The frame shown ``tick`` ticks in; None once a finite play is over."""
        starts = np.cumsum([0] + list(self.durations))
        total = int(starts[-1])
        if tick < 0:
            return None
        if self.loop:
            intro = int(starts[self.loop["start"]])
            length = int(starts[self.loop["start"] + self.loop["length"]] - intro)
            if tick >= intro and length > 0:
                k = (tick - intro) // length
                if loops and k >= loops:
                    return None
                tick = intro + (tick - intro) % length
        elif tick >= total:
            return None
        return int(np.searchsorted(starts, tick, side="right") - 1)


def _resolve(ref: str, root: Path | None) -> Path:
    p = Path(ref)
    for cand in (p, p / "sheet.json"):
        if cand.is_file() and cand.suffix == ".json":
            return cand
    if root is not None:
        entry, _, clip = ref.replace(":", "/").partition("/")
        cand = Path(root) / entry / "clips" / clip / "sheet.json"
        if cand.is_file():
            return cand
        meta = Path(root) / entry / "meta.json"
        if meta.is_file():                                  # a clip listed in meta.animations under another folder
            for a in json.loads(meta.read_text()).get("animations") or []:
                if clip in (a.get("clip"), a.get("name")) and a.get("index"):
                    cand = Path(root) / entry / a["index"]
                    if cand.is_file():
                        return cand
    raise CollageError(f"clip {ref!r} not found" + (f" under {root}" if root else ""))


def load_clip(ref: str, root: Path | None = None) -> Clip:
    from PIL import Image
    idx_path = _resolve(ref, root)
    index = json.loads(idx_path.read_text())
    sheet = np.asarray(Image.open(idx_path.parent / "sheet.png").convert("RGBA"))
    frames = index.get("frames") or []
    if not frames:
        raise CollageError(f"{idx_path} lists no frames")
    images, durations, origins = [], [], []
    by_frames = all("duration_frames" in f for f in frames)
    fps = float(index.get("fps") or 60) if by_frames else 1000.0
    default_origin = index.get("origin") or index.get("anchor")
    for f in frames:
        x, y, w, h = f["sheet"]
        images.append(sheet[y:y + h, x:x + w].copy())
        durations.append(int(f["duration_frames"]) if by_frames else max(1, int(round(f.get("duration_ms", 16)))))
        o = f.get("origin") or default_origin or [w // 2, h]
        origins.append((int(o[0]), int(o[1])))
    loop = index.get("loop")
    if loop and ("start" not in loop or "length" not in loop):
        loop = None
    return Clip(index.get("clip") or idx_path.parent.name, images, durations, fps, origins, loop, str(idx_path))


def _color(v) -> tuple[int, int, int, int]:
    if v in (None, "transparent"):
        return (0, 0, 0, 0)
    if isinstance(v, str):
        s = v.lstrip("#")
        if len(s) in (6, 8):
            c = [int(s[i:i + 2], 16) for i in range(0, len(s), 2)]
            return tuple(c + [255] * (4 - len(c)))
        raise CollageError(f"bad colour {v!r}")
    c = list(v)
    return tuple((c + [255])[:4]) if len(c) in (3, 4) else (0, 0, 0, 0)


def _paste(canvas: np.ndarray, img: np.ndarray, x0: int, y0: int) -> None:
    """Alpha-over ``img`` at (x0, y0), clipped to the canvas."""
    H, W = canvas.shape[:2]
    h, w = img.shape[:2]
    cx0, cy0, cx1, cy1 = max(0, x0), max(0, y0), min(W, x0 + w), min(H, y0 + h)
    if cx0 >= cx1 or cy0 >= cy1:
        return
    src = img[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0].astype(np.float32)
    dst = canvas[cy0:cy1, cx0:cx1].astype(np.float32)
    a = src[..., 3:4] / 255.0
    out_a = a + dst[..., 3:4] / 255.0 * (1 - a)
    rgb = (src[..., :3] * a + dst[..., :3] * (dst[..., 3:4] / 255.0) * (1 - a)) / np.maximum(out_a, 1e-6)
    canvas[cy0:cy1, cx0:cx1, :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    canvas[cy0:cy1, cx0:cx1, 3:4] = np.clip(out_a * 255, 0, 255).astype(np.uint8)


def render(layout: dict, root: Path | None = None, clips: dict | None = None) -> dict:
    """The collage as RGBA frames: {'frames': [...], 'fps', 'size', 'items': [...]}. ``clips`` may pre-supply Clip
    objects by their ``clip`` reference (tests, or callers that built clips in memory)."""
    cw, ch = (int(v) for v in layout.get("canvas") or (320, 224))
    if cw <= 0 or ch <= 0 or cw * ch > 4096 * 4096:
        raise CollageError("canvas must be a positive size up to 4096x4096")
    fps = float(layout.get("fps") or 60)
    bg = _color(layout.get("background", "transparent"))
    scale = max(1, int(layout.get("scale") or 1))
    items = []
    for k, it in enumerate(layout.get("items") or []):
        ref = it["clip"]
        clip = (clips or {}).get(ref) or load_clip(ref, root)
        items.append({**it, "_clip": clip, "_order": k})
    if not items:
        raise CollageError("the layout has no items")
    n = layout.get("frames")
    if n is None:
        ends = [int(it["end"]) for it in items if it.get("end") is not None]
        finite = []
        for it in items:
            c = it["_clip"]
            ticks = c.play_ticks(int(it.get("loops", 0)))
            if ticks is not None:
                finite.append(int(it.get("start", 0))
                              + int(np.ceil((ticks - int(it.get("offset", 0))) / c.fps * fps / float(it.get("speed", 1)))))
        n = max(ends + finite) if (ends or finite) else int(DEFAULT_SECONDS * fps)
    n = int(min(max(1, n), MAX_FRAMES))
    order = sorted(items, key=lambda it: (it.get("z", 0), it["_order"]))
    frames = []
    for t in range(n):
        canvas = np.zeros((ch, cw, 4), np.uint8)
        canvas[:] = bg
        for it in order:
            start, end = int(it.get("start", 0)), it.get("end")
            if t < start or (end is not None and t >= int(end)):
                continue
            c = it["_clip"]
            tick = int(np.floor((t - start) / fps * float(it.get("speed", 1)) * c.fps)) + int(it.get("offset", 0))
            k = c.frame_at(tick, int(it.get("loops", 0)))
            if k is None:
                if it.get("hold", "last") == "hide":
                    continue
                k = len(c.images) - 1
            img, (ox, oy) = c.images[k], c.origins[k]
            s = max(1, int(it.get("scale", 1)))
            if it.get("flip"):
                img, ox = img[:, ::-1], img.shape[1] - ox
            if s > 1:
                img, ox, oy = img.repeat(s, 0).repeat(s, 1), ox * s, oy * s
            _paste(canvas, img, int(it.get("x", 0)) - ox, int(it.get("y", 0)) - oy)
        if scale > 1:
            canvas = canvas.repeat(scale, 0).repeat(scale, 1)
        frames.append(canvas)
    info = [{"clip": it["clip"], "source": it["_clip"].source, "frames": len(it["_clip"].images),
             "clip_fps": it["_clip"].fps, "loop": it["_clip"].loop,
             **{k: v for k, v in it.items() if not k.startswith("_") and k != "clip"}} for it in items]
    return {"frames": frames, "fps": fps, "size": [cw * scale, ch * scale], "items": info}


def export(layout: dict, out: Path, root: Path | None = None, mp4: bool = True, clips: dict | None = None) -> dict:
    """Write the collage: frames/collage_NNNN.png, collage.json, preview.apng, collage.mp4 (ffmpeg when present)."""
    from . import sprite_capture as SC
    r = render(layout, root, clips)
    out = Path(out)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    for k, f in enumerate(r["frames"]):
        (out / "frames" / f"collage_{k:04d}.png").write_bytes(SC.png_bytes(f))
    # consecutive identical frames -> one preview frame with the summed duration
    uniq, durs = [], []
    for f in r["frames"]:
        if uniq and np.array_equal(uniq[-1], f):
            durs[-1] += 1
        else:
            uniq.append(f)
            durs.append(1)
    ms = [d * 1000.0 / r["fps"] for d in durs]
    (out / "preview.apng").write_bytes(SC.preview_bytes(uniq, [max(1, int(round(m))) for m in ms], "apng"))
    reason = None
    if mp4:
        try:
            bg = _color(layout.get("background", "transparent"))
            (out / "collage.mp4").write_bytes(SC.mp4_bytes(uniq, ms, r["fps"],
                                                           background=bg[:3] if bg[3] else (38, 40, 48)))
        except Exception as e:                                 # noqa: BLE001 - no ffmpeg is reported, not fatal
            reason = str(e)
    else:
        reason = "not requested"
    summary = {"tool": f"gbox.sprite_collage {VERSION}", "layout": {k: v for k, v in layout.items() if k != "items"},
               "frames": len(r["frames"]), "fps": r["fps"], "size": r["size"], "items": r["items"],
               "files": {"frames": "frames/collage_NNNN.png", "preview": "preview.apng",
                         "mp4": None if reason else "collage.mp4"}, "mp4_unavailable": reason}
    (out / "collage.json").write_text(json.dumps(summary, indent=1, default=str))
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Tile sprite clips onto a canvas timeline")
    ap.add_argument("layout")
    ap.add_argument("--out", required=True)
    ap.add_argument("--root", help="collection root holding <entry>/clips/<clip>/ (default: the configured library)")
    ap.add_argument("--no-mp4", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root) if a.root else None
    if root is None:
        try:
            from . import characters as C
            from .config import load
            root = C.library_root(load())
        except Exception:                                      # noqa: BLE001 - paths work without a config
            root = None
    s = export(json.loads(Path(a.layout).read_text()), Path(a.out), root, not a.no_mp4)
    print(f"{s['frames']} frames {s['size']} -> {a.out} (mp4: {s['mp4_unavailable'] or 'yes'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
