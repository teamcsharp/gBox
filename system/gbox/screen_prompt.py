"""On-screen action-button prompts: see what the game asks for ("A JUMP OVER", "A TAKE", "A KICK", a grab's mash
prompt) and say which button (operator 2026-10-20: "I need the system able to detect that a press A dialogue is being
required of them and to be able to press it").

detect(rgb) looks for the button icon the game draws where its prompts sit (PROFILES: per game, the box as fractions
of the picture and each button's colour range) and returns {"button", "px", "box"} or None. Measured on RE4 GC
(G4BE08, Dolphin on the Spark, 640x480 frames): the A icon is a teal-green disc (mean RGB 40, 134, 104) at
x 247-271, y 377-396 - 206 pixels; frames without a prompt have none in the box (the green ammo dial sits outside it).

Watcher runs detection on a frame source in a thread (MjpegFrames: the session's /api/sessions/{sid}/mjpeg stream,
or any grab() -> image bytes) and keeps the latest result: visible(max_age) is the button on screen right now.
"""
from __future__ import annotations

import io
import threading
import time

import numpy as np

# box: (x0, y0, x1, y1) as fractions of the frame; colours: button -> test on int RGB arrays
PROFILES = {
    "G4BE08": {"box": (0.30, 0.72, 0.60, 0.88), "min_px": 60, "max_px": 1500,
               "buttons": {"a": lambda r, g, b: (g > 100) & (g > r + 50) & (g > b + 10) & (r < 90),
                           "b": lambda r, g, b: (r > 140) & (r > g + 70) & (r > b + 50)}},
}
DEFAULT = "G4BE08"


def detect(rgb, profile: str = DEFAULT) -> dict | None:
    """The prompt button visible in rgb (H x W x 3 uint8 / int array), or None."""
    p = PROFILES.get(profile) or PROFILES[DEFAULT]
    a = np.asarray(rgb)
    if a.ndim != 3 or a.shape[2] < 3:
        return None
    h, w = a.shape[:2]
    x0, y0, x1, y1 = (int(p["box"][0] * w), int(p["box"][1] * h), int(p["box"][2] * w), int(p["box"][3] * h))
    reg = a[y0:y1, x0:x1, :3].astype(np.int16)
    r, g, b = reg[..., 0], reg[..., 1], reg[..., 2]
    best = None
    for button, test in p["buttons"].items():
        m = test(r, g, b)
        n = int(m.sum())
        if n < p["min_px"] * (w * h) / (640 * 480) or n > p["max_px"] * (w * h) / (640 * 480):
            continue
        ys, xs = np.nonzero(m)
        bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
        if not (0.5 < bw / bh < 2.0) or n < 0.35 * bw * bh:                   # a disc, not a strip of grass
            continue
        if best is None or n > best["px"]:
            best = {"button": button, "px": n, "box": (x0 + int(xs.min()), y0 + int(ys.min()),
                                                       x0 + int(xs.max()), y0 + int(ys.max()))}
    return best


def decode(image: bytes):
    from PIL import Image
    return np.asarray(Image.open(io.BytesIO(image)).convert("RGB"))


class MjpegFrames:
    """The newest JPEG of an MJPEG HTTP stream (multipart): a reader thread keeps only the latest frame."""

    def __init__(self, url: str, headers: dict | None = None):
        self.url, self.headers = url, headers or {}
        self.latest, self.at = None, 0.0
        self.stop = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="mjpeg-frames").start()

    def _run(self):
        import urllib.request
        while not self.stop.is_set():
            try:
                with urllib.request.urlopen(urllib.request.Request(self.url, headers=self.headers), timeout=10) as r:
                    buf = b""
                    while not self.stop.is_set():
                        chunk = r.read(32768)
                        if not chunk:
                            break
                        buf += chunk
                        end = buf.rfind(b"\xff\xd9")
                        start = buf.rfind(b"\xff\xd8", 0, end) if end > 0 else -1
                        if start >= 0:
                            self.latest, self.at = buf[start:end + 2], time.time()
                            buf = buf[end + 2:]
                        elif len(buf) > 4 << 20:
                            buf = buf[-(1 << 20):]
            except Exception:                         # noqa: BLE001 - the stream restarts: reconnect
                time.sleep(1.0)

    def grab(self) -> bytes | None:
        return self.latest


class Watcher:
    """detect() on grab() at up to hz; visible(max_age) -> the prompt button on screen now, or None."""

    def __init__(self, grab, profile: str = DEFAULT, hz: float = 10.0, clock=time.time):
        self.grab, self.profile, self.period, self.clock = grab, profile, 1.0 / hz, clock
        self.last, self.last_at, self.frames = None, 0.0, 0
        self.stop = threading.Event()

    def start(self) -> "Watcher":
        threading.Thread(target=self._run, daemon=True, name="screen-prompt").start()
        return self

    def step(self) -> dict | None:
        img = self.grab()
        if not img:
            return None
        try:
            found = detect(decode(img) if isinstance(img, (bytes, bytearray)) else img, self.profile)
        except Exception:                             # noqa: BLE001 - a torn frame
            return None
        self.frames += 1
        self.last, self.last_at = found, self.clock()
        return found

    def _run(self):
        while not self.stop.is_set():
            self.step()
            time.sleep(self.period)

    def visible(self, max_age: float = 0.5) -> str | None:
        if self.last and self.clock() - self.last_at <= max_age:
            return self.last["button"]
        return None
