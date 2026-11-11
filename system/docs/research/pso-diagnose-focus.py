"""Diagnose why keys do not reach the docked game: is the app window raised, and does the focus check pass?"""
import ctypes
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import game_input as G
from gbox import adapters

user32 = ctypes.windll.user32

hwnd = G.app_window()
print("app window:", hwnd)
root = user32.GetAncestor(hwnd, 2) if hwnd else None
print("root:", root)
print("IsWindowVisible:", bool(user32.IsWindowVisible(hwnd)) if hwnd else None)
print("raised:", G.raise_window())
time.sleep(0.4)
print("in_front:", adapters._win_input_in_front(user32, root, False))
fg = user32.GetForegroundWindow()
buf = ctypes.create_unicode_buffer(256)
user32.GetWindowTextW(fg, buf, 256)
print("foreground hwnd:", fg, "title:", buf.value.strip()[:60])
pid = ctypes.wintypes.DWORD()
user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
print("foreground pid:", pid.value, "| emulator pid:", G._pid())
print("session pid:", G._session.pid())
