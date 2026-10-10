"""Frame a remote Windows desktop stream around the visible gBox window."""
from __future__ import annotations

import io

from PIL import Image


def gbox_window_rect() -> tuple[float, float, float, float] | None:
    """Return the gBox top-level window as fractions of the virtual desktop."""
    import ctypes
    from ctypes import wintypes

    user = ctypes.windll.user32
    screen = tuple(user.GetSystemMetrics(n) for n in (76, 77, 78, 79))
    sx, sy, sw, sh = screen
    if sw <= 0 or sh <= 0:
        return None
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
            x0, y0 = max(rect.left, sx), max(rect.top, sy)
            x1, y1 = min(rect.right, sx + sw), min(rect.bottom, sy + sh)
            if x1 - x0 >= 200 and y1 - y0 >= 150:
                windows.append((x0, y0, x1, y1))
        return True

    user.EnumWindows(visit, 0)
    if not windows:
        return None
    x0, y0, x1, y1 = max(windows, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
    return ((x0 - sx) / sw, (y0 - sy) / sh, (x1 - x0) / sw, (y1 - y0) / sh)


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


def frame_for_view(image: bytes, view: str, app_rect: tuple[float, float, float, float] | None) -> bytes | None:
    """Never substitute the whole desktop for an app-only stream."""
    return image if view == "desktop" else crop_jpeg(image, app_rect)
