"""Frame a remote Windows desktop stream around the visible gBox window, or around a game's own window (#2858)."""
from __future__ import annotations

import io
import re
import time
from typing import Callable, Iterator

from PIL import Image

FRESH_S = 5.0            # a desktop frame older than this is never streamed (the other PC stopped sending)
GAME_RECTS_MAX = 16      # game windows reported per frame; more live games than this on one PC is not real
SAMPLES = ((.25, .25), (.5, .25), (.75, .25), (.25, .5), (.5, .5), (.75, .5), (.25, .75), (.5, .75), (.75, .75))


def _screen(user) -> tuple[int, int, int, int]:
    """The virtual desktop (every monitor): x, y, width, height."""
    return tuple(user.GetSystemMetrics(n) for n in (76, 77, 78, 79))


def window_fraction(box, screen) -> tuple[float, float, float, float] | None:
    """A window's screen box (left, top, right, bottom) clipped to the virtual desktop (x, y, w, h), as fractions of it;
    None when less than 200 x 150 pixels of it are on the screen."""
    sx, sy, sw, sh = screen
    if sw <= 0 or sh <= 0:
        return None
    x0, y0 = max(box[0], sx), max(box[1], sy)
    x1, y1 = min(box[2], sx + sw), min(box[3], sy + sh)
    if x1 - x0 < 200 or y1 - y0 < 150:
        return None
    return ((x0 - sx) / sw, (y0 - sy) / sh, (x1 - x0) / sw, (y1 - y0) / sh)


def gbox_window_rect() -> tuple[float, float, float, float] | None:
    """Return the gBox top-level window as fractions of the virtual desktop."""
    import ctypes
    from ctypes import wintypes

    user = ctypes.windll.user32
    screen = _screen(user)
    windows = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(hwnd, _):
        if not user.IsWindowVisible(hwnd) or user.IsIconic(hwnd):
            return True
        title = ctypes.create_unicode_buffer(256)
        user.GetWindowTextW(hwnd, title, len(title))
        if title.value.strip().casefold() != "gbox":
            return True
        rect = wintypes.RECT()
        if user.GetWindowRect(hwnd, ctypes.byref(rect)):
            fraction = window_fraction((rect.left, rect.top, rect.right, rect.bottom), screen)
            if fraction:
                windows.append(fraction)
        return True

    user.EnumWindows(visit, 0)
    return max(windows, key=lambda r: r[2] * r[3]) if windows else None


def shown_on_screen(box, pid: int, owner_at: Callable[[int, int], int]) -> bool:
    """Whether the screen shows a window's own pixels: at least 5 of 9 points across its box belong to its process
    (owner_at(x, y) -> the pid of the window the screen shows at that point, 0 for none)."""
    left, top, right, bottom = box
    if right <= left or bottom <= top:
        return False
    hits = sum(owner_at(round(left + (right - left) * fx), round(top + (bottom - top) * fy)) == pid for fx, fy in SAMPLES)
    return hits >= 5


def _shown_box(user, pid: int) -> tuple[int, int, int, int] | None:
    """A game's window (docked in gBox or its own) as a screen box, when the screen shows it; else None."""
    import ctypes
    from ctypes import wintypes

    from .adapters import _pid_window

    user.WindowFromPoint.argtypes = [wintypes.POINT]
    user.WindowFromPoint.restype = wintypes.HWND

    def owner_at(x, y):
        hwnd = user.WindowFromPoint(wintypes.POINT(x, y))
        owner = wintypes.DWORD()
        return owner.value if hwnd and user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner)) else 0

    hwnd, rect = _pid_window(pid), wintypes.RECT()
    if not hwnd or not user.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    box = (rect.left, rect.top, rect.right, rect.bottom)
    return box if shown_on_screen(box, pid, owner_at) else None


def game_window_rects(pids: dict[str, int]) -> dict[str, tuple[float, float, float, float]]:
    """Each live game's window (session id -> emulator pid) as fractions of the virtual desktop, while the screen shows
    it, so a crop there is the game. A GPU-captured source parked off-screen or behind gBox, a minimised game or one
    another window covers is left out: a crop there would show some other app."""
    if not pids:
        return {}
    import ctypes

    user = ctypes.windll.user32
    screen = _screen(user)
    out = {}
    for sid, pid in pids.items():
        box = _shown_box(user, pid)
        fraction = window_fraction(box, screen) if box else None
        if fraction:
            out[sid] = fraction
    return out


STILL_MAX_W = 960        # a still shows the game in a header icon, a preview or a list: small and cheap to send


def still_jpeg(image, max_width: int = STILL_MAX_W) -> bytes | None:
    """A screen grab of a game window as a small JPEG; None when it is black (a sleeping display, a window that draws
    nothing): no picture says more than a black one."""
    image = image.convert("RGB")
    if image.convert("L").getextrema()[1] < 16:
        return None
    if image.width > max_width:
        image = image.resize((max_width, max(1, round(image.height * max_width / image.width))))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=78)
    return output.getvalue()


def window_still(pid: int) -> bytes | None:
    """A still of a native game's window as the screen shows it now (#2858), or None when the screen doesn't show it
    (minimised, covered, parked off-screen, black). It only reads the screen: the emulator is never asked to draw
    itself (PrintWindow, its own screenshot), which could hitch the game or put a message over it."""
    import ctypes

    from PIL import ImageGrab

    box = _shown_box(ctypes.windll.user32, pid)
    if not box or box[2] - box[0] < 64 or box[3] - box[1] < 48:
        return None
    return still_jpeg(ImageGrab.grab(box, all_screens=True))


def game_rects_header(rects: dict) -> str:
    """The x-gbox-game-rects header a worker sends with a desktop frame: "<session id>=x,y,w,h;..." (fractions)."""
    return ";".join(f"{sid}=" + ",".join(f"{v:.6f}" for v in r) for sid, r in list(rects.items())[:GAME_RECTS_MAX])


def parse_game_rects(text: str) -> dict[str, tuple[float, float, float, float]]:
    """The control plane's reading of that header; a malformed entry is dropped, never an error."""
    out = {}
    for item in (text or "").split(";")[:GAME_RECTS_MAX]:
        sid, _, values = item.strip().partition("=")
        try:
            rect = tuple(float(v) for v in values.split(","))
        except ValueError:
            continue
        if re.fullmatch(r"[\w-]{1,80}", sid) and len(rect) == 4 and all(0 <= v <= 1 for v in rect) and rect[2] > 0 and rect[3] > 0:
            out[sid] = rect
    return out


def crop_jpeg(image: bytes, rect: tuple[float, float, float, float] | None) -> bytes | None:
    """Crop an already captured desktop JPEG to a normalized window rectangle."""
    if rect is None or len(rect) != 4:
        return None
    x, y, w, h = rect
    if not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in rect) or w <= 0 or h <= 0:
        return None
    with Image.open(io.BytesIO(image)) as source:
        width, height = source.size
        box = (max(0, round(x * width)), max(0, round(y * height)),
               min(width, round((x + w) * width)), min(height, round((y + h) * height)))
        if box[2] - box[0] < 100 or box[3] - box[1] < 75:
            return None
        output = io.BytesIO()
        source.crop(box).save(output, format="JPEG", quality=82)
        return output.getvalue()


def frame_for_view(image: bytes, view: str, rect: tuple[float, float, float, float] | None) -> bytes | None:
    """Never substitute the whole desktop for a window-only stream (the gBox window, or a game's window)."""
    return image if view == "desktop" else crop_jpeg(image, rect)


def stream_parts(next_frame: Callable[[int], dict], view: str, session: str = "", renew: Callable[[], None] = lambda: None,
                 clock: Callable[[], float] = time.time) -> Iterator[bytes]:
    """The /api/workers/{wid}/desktop/stream body: one multipart part per new desktop frame, cropped to the view (app:
    the gBox window, game: that session's game window, desktop: all of it). next_frame(seen) waits up to a couple of
    seconds for a frame newer than `seen` and returns the newest one ({} for none).

    Whenever there is nothing to send (no new frame, an old one, no window to crop to) it yields b"": the server gets
    control back between frames, so a viewer that left ends the response and stops renewing the watch, and the other PC
    stops capturing its screen. An old frame counts as seen, so waiting for the next one never spins."""
    seen = 0
    while True:
        renew()
        frame = next_frame(seen)
        seq = frame.get("seq", 0)
        if seq == seen:
            yield b""
            continue
        seen, image = seq, None
        if clock() - frame.get("ts", 0) <= FRESH_S:
            rect = (frame.get("game_rects") or {}).get(session) if view == "game" else frame.get("app_rect")
            image = frame_for_view(frame["image"], view, rect)
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + image + b"\r\n" if image else b""
