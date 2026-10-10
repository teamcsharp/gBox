"""A covered emulator window must not be reported as a game screenshot."""

import ctypes
from ctypes import wintypes
from types import SimpleNamespace

import pytest
from PIL import Image, ImageGrab

from gbox import adapters


@pytest.mark.parametrize("foreign_points,allowed", [(0, True), (2, True), (3, False), (9, False)])
def test_win_grab_rejects_covered_game(monkeypatch, foreign_points, allowed):
    seen = []

    def window_from_point(point):
        seen.append((point.x, point.y))
        return 2 if len(seen) <= foreign_points else 1

    window_from_point.argtypes = None
    window_from_point.restype = None

    def get_window_rect(_hwnd, address):
        rect = ctypes.cast(address, ctypes.POINTER(wintypes.RECT)).contents
        rect.left, rect.top, rect.right, rect.bottom = 0, 0, 900, 900
        return 1

    def get_window_pid(hwnd, address):
        ctypes.cast(address, ctypes.POINTER(wintypes.DWORD)).contents.value = 999 if hwnd == 2 else 123
        return 1

    user = SimpleNamespace(GetWindowRect=get_window_rect, WindowFromPoint=window_from_point,
                           GetWindowThreadProcessId=get_window_pid)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user), raising=False)
    monkeypatch.setattr(adapters, "_pid_window", lambda pid: 1)
    monkeypatch.setattr(ImageGrab, "grab", lambda *args, **kwargs: Image.new("RGB", (10, 10)))

    if allowed:
        assert adapters.win_grab(123).startswith(b"\x89PNG")
    else:
        with pytest.raises(RuntimeError, match="covered by another app"):
            adapters.win_grab(123)
    assert len(seen) == 9
