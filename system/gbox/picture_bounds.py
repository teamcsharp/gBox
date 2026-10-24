"""Where the game's picture is inside a session frame: the black letterbox / pillarbox bars measured off the
latest JPEG, so a picture-in-picture viewer can scale the picture itself to its window (operator 2026-10-24: "the
game needs to fit the window ... scale 1:1 to fit the vertical bounds of the PiP window"). RE4 on GameCube draws
its 16:9 picture letterboxed inside the 4:3 frame; a 16:9 window then showed bars on every side.

Pure black only (max luminance <= BLACK per row / column after a small downscale): a dark scene has noise above
that. A frame that is black almost everywhere (a load, a fade) reports no content; the viewer keeps its last fit.
"""
from __future__ import annotations

import io
import threading
import time

BLACK = 12                      # 0..255: a row / column whose brightest sample is at or below this is a bar
SAMPLE_W = 192                  # measure on a thumbnail this wide (bars are big; sub-pixel accuracy is not needed)
MIN_CONTENT = 0.25              # a picture smaller than this share of the frame is a black frame, not a bar layout
TTL_S = 2.0

_CACHE: dict[str, tuple[float, int, dict]] = {}
_LOCK = threading.Lock()


def measure(jpeg: bytes) -> dict:
    """{"w", "h", "content": {"x", "y", "w", "h"} | None, "bars": {"top", "bottom", "left", "right"} (fractions)}."""
    from PIL import Image
    im = Image.open(io.BytesIO(jpeg))
    w, h = im.size
    k = max(1, w // SAMPLE_W)
    small = im.convert("L").resize((max(1, w // k), max(1, h // k)))
    sw, sh = small.size
    px = small.load()
    row_max = [max(px[x, y] for x in range(sw)) for y in range(sh)]
    col_max = [max(px[x, y] for y in range(sh)) for x in range(sw)]
    top = next((y for y, v in enumerate(row_max) if v > BLACK), sh)
    bottom = next((y for y, v in enumerate(reversed(row_max)) if v > BLACK), sh)
    left = next((x for x, v in enumerate(col_max) if v > BLACK), sw)
    right = next((x for x, v in enumerate(reversed(col_max)) if v > BLACK), sw)
    out = {"w": w, "h": h, "content": None,
           "bars": {"top": round(top / sh, 4), "bottom": round(bottom / sh, 4),
                    "left": round(left / sw, 4), "right": round(right / sw, 4)}}
    cw, ch = sw - left - right, sh - top - bottom
    if cw > 0 and ch > 0 and cw * ch >= MIN_CONTENT * sw * sh:
        out["content"] = {"x": left * k, "y": top * k, "w": (w - right * k) - left * k, "h": (h - bottom * k) - top * k}
    return out


def cached(sid: str, jpeg: bytes, now: float | None = None) -> dict:
    """measure() at most once per TTL_S per session for the same frame bytes."""
    now = time.time() if now is None else now
    key = len(jpeg) ^ (hash(jpeg[:512]) & 0xFFFFFFFF)
    with _LOCK:
        hit = _CACHE.get(sid)
        if hit and hit[1] == key and now - hit[0] <= TTL_S:
            return dict(hit[2])
    try:
        value = measure(jpeg)
    except Exception as exc:                                    # noqa: BLE001 - a truncated frame: no fit this time
        value = {"w": None, "h": None, "content": None, "bars": None, "error": type(exc).__name__}
    with _LOCK:
        _CACHE[sid] = (now, key, value)
        for old in [k for k, v in _CACHE.items() if now - v[0] > 60]:
            _CACHE.pop(old, None)
    return dict(value)
