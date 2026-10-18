"""Bounded Cxbx window screenshots, with observations rather than gameplay claims.

PrintWindow may include clipped/embedded host UI. Nine hit tests can detect some
occlusion, never prove the entire rectangle is unobscured. Both capture methods
are diagnostic only; no screenshot establishes guest execution or gameplay.
"""
from __future__ import annotations

import hashlib
import io


_MAX_PIXELS = 16_777_216
_POINTS = ((.1, .1), (.5, .1), (.9, .1), (.1, .5), (.5, .5), (.9, .5), (.1, .9), (.5, .9), (.9, .9))


def capture_window(hwnd: int, pid: int, *, render_class="CxbxRender", source_prefix="cxbx") -> tuple[bytes, dict]:
    import ctypes
    from ctypes import wintypes as w
    from PIL import Image, ImageGrab
    from .adapters import _print_window_png

    user = ctypes.windll.user32
    user.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    user.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    user.ClientToScreen.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
    user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    user.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    user.WindowFromPoint.argtypes = [w.POINT]
    user.WindowFromPoint.restype = w.HWND
    user.IsChild.argtypes = [w.HWND, w.HWND]

    def geometry():
        owner, name = w.DWORD(), ctypes.create_unicode_buffer(64)
        if (not user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner)) or owner.value != pid
                or not user.GetClassNameW(hwnd, name, len(name)) or name.value != render_class):
            raise RuntimeError("The owned Cxbx render window identity is unavailable")
        rect, outer, origin = w.RECT(), w.RECT(), w.POINT(0, 0)
        if (not user.GetClientRect(hwnd, ctypes.byref(rect))
                or not user.ClientToScreen(hwnd, ctypes.byref(origin))
                or not user.GetWindowRect(hwnd, ctypes.byref(outer))):
            raise RuntimeError("The Xbox render window geometry is unavailable")
        width, height = rect.right - rect.left, rect.bottom - rect.top
        ow, oh = outer.right - outer.left, outer.bottom - outer.top
        if min(width, height, ow, oh) < 2 or max(width * height, ow * oh) > _MAX_PIXELS:
            raise RuntimeError("The Xbox render window is minimized or exceeds the capture limit")
        x, y = origin.x - outer.left, origin.y - outer.top
        if x < 0 or y < 0 or x + width > ow or y + height > oh:
            raise RuntimeError("The Xbox client rectangle is outside its owned window")
        return origin.x, origin.y, width, height, outer.left, outer.top, ow, oh

    def coverage(box):
        ox, oy, width, height, *_ = box
        covered, known = 0, True
        for fx, fy in _POINTS:
            try:
                top = user.WindowFromPoint(w.POINT(round(ox + width * fx), round(oy + height * fy)))
                owner = w.DWORD()
                if not top or not user.GetWindowThreadProcessId(top, ctypes.byref(owner)):
                    known = False
                elif owner.value != pid or (top != hwnd and not user.IsChild(hwnd, top)):
                    # Same-process dialogs are not the render surface either.
                    covered += 1
            except (OSError, ValueError):
                known = False
        return covered, known

    before = geometry()
    first_covered, first_known = coverage(before)
    ox, oy, width, height, left, top, ow, oh = before
    data = _print_window_png(hwnd, ow, oh)
    source = source_prefix + "-print-window"
    if data:
        with Image.open(io.BytesIO(data)) as image:
            if image.size != (ow, oh):
                raise RuntimeError("Cxbx PrintWindow returned unexpected image dimensions")
            frame = image.crop((ox - left, oy - top, ox - left + width, oy - top + height))
    else:
        # Keep the existing restriction on compositor fallback. Sampling is a
        # necessary guard here, not proof against a small overlay between points.
        if first_covered or not first_known:
            raise RuntimeError("The Xbox render window is covered or its coverage is unknown; no screen capture is available")
        source = source_prefix + "-desktop-compositor"
        frame = ImageGrab.grab((ox, oy, ox + width, oy + height), all_screens=True)
        if frame.size != (width, height):
            raise RuntimeError("Cxbx screen capture returned unexpected image dimensions")
    if geometry() != before:
        raise RuntimeError("The Xbox render window moved or changed during capture")
    last_covered, last_known = coverage(before)
    if source == source_prefix + "-desktop-compositor" and (last_covered or not last_known):
        raise RuntimeError("The Xbox render window became covered or coverage unknown during screen capture")
    covered = max(first_covered, last_covered)
    status = "occluded" if covered else "sampled-clear" if first_known and last_known else "unknown"
    output = io.BytesIO()
    frame.save(output, "PNG")
    png = output.getvalue()
    return png, {"pid": pid, "hwnd": hwnd, "sha256": hashlib.sha256(png).hexdigest(),
                 "source": source, "covered": covered, "occlusion": status}
