"""Capture the PSO Dolphin window's own pixels (PrintWindow, so it works even when other windows are on top).

Writes PNGs into D:\\gBox\\pso-ds\\demo\\ and prints what it captured. Used to show the operator the game as it plays.
"""
import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

OUT = Path(r"D:\gBox\pso-ds\demo")

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
user32.SetProcessDPIAware()


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def find_window(needle: str):
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _l):
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        if needle.lower() in buf.value.lower() and user32.IsWindowVisible(hwnd):
            found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    return found


def capture(hwnd, path: Path) -> tuple[int, int]:
    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise RuntimeError(f"window has no size ({width}x{height})")
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, width, height)
    gdi32.SelectObject(mem, bmp)
    # 2 = PW_RENDERFULLCONTENT: capture Direct3D/Vulkan output too
    user32.PrintWindow(hwnd, mem, 2)
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]
    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth, bi.biHeight = width, -height
    bi.biPlanes, bi.biBitCount, bi.biCompression = 1, 32, 0
    buf = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(mem, bmp, 0, height, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    from PIL import Image
    Image.frombuffer("RGBA", (width, height), buf, "raw", "BGRA", 0, 1).convert("RGB").save(path)
    return width, height


def main():
    windows = find_window("Phantasy Star Online")
    if not windows:
        print("no PSO window")
        return 1
    hwnd, title = windows[0]
    user32.ShowWindow(hwnd, 9)                       # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.7)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{time.strftime('%H%M%S')}-pso-window.png"
    w, h = capture(hwnd, path)
    print(f"captured {title!r} {w}x{h} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
