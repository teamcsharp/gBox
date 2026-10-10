"""Forward the physical Xbox pad to Yuzu's keyboard bindings when its SDL pad path is silent."""
import ctypes
import sys
import threading
import time
from ctypes import wintypes

from .gamepads import xinput_snapshot


# Virtual-key codes match the player-one bindings in gamepads.bind_yuzu_xinput_bridge.
BUTTON_KEYS = {
    0x1000: 0x43,  # Xbox A -> Switch A (C)
    0x2000: 0x58,  # Xbox B -> Switch B (X)
    0x4000: 0x56,  # X -> X (V)
    0x8000: 0x5A,  # Y -> Y (Z)
    0x0100: 0x51,  # LB -> L (Q)
    0x0200: 0x45,  # RB -> R (E)
    0x0010: 0x4D,  # Menu -> + (M)
    0x0020: 0x4E,  # View -> - (N)
    0x0040: 0x46,  # left stick click (F)
    0x0080: 0x47,  # right stick click (G)
    0x0001: 0x26,  # dpad up
    0x0002: 0x28,  # dpad down
    0x0004: 0x25,  # dpad left
    0x0008: 0x27,  # dpad right
}
ARROWS = {0x25, 0x26, 0x27, 0x28}
DEADZONE = 10000


class GuiThreadInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT)]


def yuzu_has_focus(pid: int) -> bool:
    user32 = ctypes.windll.user32
    info = GuiThreadInfo()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetGUIThreadInfo(0, ctypes.byref(info)) or not info.hwndFocus:
        return False
    owner = wintypes.DWORD()
    user32.GetWindowThreadProcessId(info.hwndFocus, ctypes.byref(owner))
    return owner.value == pid


def keys_for_pad(pad: dict) -> set[int]:
    buttons = pad["buttons"]
    keys = {key for bit, key in BUTTON_KEYS.items() if buttons & bit}
    if pad["lt"] > 127:
        keys.add(0x52)  # R -> ZL
    if pad["rt"] > 127:
        keys.add(0x54)  # T -> ZR
    if pad["lx"] < -DEADZONE:
        keys.add(0x41)
    if pad["lx"] > DEADZONE:
        keys.add(0x44)
    if pad["ly"] > DEADZONE:
        keys.add(0x57)
    if pad["ly"] < -DEADZONE:
        keys.add(0x53)
    if pad["rx"] < -DEADZONE:
        keys.add(0x4A)
    if pad["rx"] > DEADZONE:
        keys.add(0x4C)
    if pad["ry"] > DEADZONE:
        keys.add(0x49)
    if pad["ry"] < -DEADZONE:
        keys.add(0x4B)
    return keys


def send_key(key: int, down: bool) -> None:
    user32 = ctypes.windll.user32
    flags = (0 if down else 0x0002) | (0x0001 if key in ARROWS else 0)
    user32.keybd_event(key, user32.MapVirtualKeyW(key, 0), flags, 0)


def run(pid: int) -> None:
    held = set()
    stop = threading.Event()
    threading.Thread(target=lambda: (sys.stdin.readline(), stop.set()), daemon=True).start()
    try:
        while not stop.is_set():
            pads = xinput_snapshot()
            pad = next((p for p in pads if p["slot"] == 0), pads[0] if pads else None)
            now = keys_for_pad(pad) if pad and yuzu_has_focus(pid) else set()
            for key in sorted(held - now):
                send_key(key, False)
            for key in sorted(now - held):
                send_key(key, True)
            held = now
            time.sleep(0.02)
    finally:
        for key in held:
            send_key(key, False)


if __name__ == "__main__":
    run(int(sys.argv[1]))
