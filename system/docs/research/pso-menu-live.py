"""Drive PSO's menus from the keyboard, learning the transitions and speeding up on every run.

`observe` is a fast perceptual fingerprint of the game window (64x48 grey, sha1) so a look costs a capture, not a full menu
analysis; `press` uses GCPad1's keyboard fallback from Dolphin's INI (Start=RETURN, A=X, B=Z, D-pad=T/G/F/H). The learner from
`gbox.pso_menu_learn` then records `(screen, key) -> screen`, learns each edge's delay and shrinks it while the screens still change.
"""
import argparse
import ctypes
import json
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")
sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")

import pso_window_shot as SHOT                                    # noqa: E402
from gbox.pso_menu_learn import MenuLearner, TransitionGraph      # noqa: E402

KEYS = {"start": "{ENTER}", "a": "x", "b": "z", "ddown": "g", "dup": "t", "dleft": "f", "dright": "h",
        "up": "{UP}", "down": "{DOWN}"}
OUT = Path(r"D:\gBox\pso-ds\demo\menus")
STATE = Path(r"D:\gBox\pso-ds\menus-learned.json")

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()


def pso_window(pid: int | None):
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _l):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(owner))
        if (pid is None or owner.value == pid) and user32.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(h, buf, 256)
            if "Phantasy Star Online" in buf.value:
                found.append(h)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def fingerprint(hwnd) -> str:
    """A cheap screen id: 64x48 grey of the window, sha1. The PNG is kept for evidence."""
    rect = SHOT.wintypes.RECT() if hasattr(SHOT, "wintypes") else None
    from ctypes import wintypes as W
    r = W.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    width, height = r.right - r.left, r.bottom - r.top
    if width <= 0 or height <= 0:
        return "no-window"
    hdc = user32.GetWindowDC(hwnd)
    gdi32 = ctypes.windll.gdi32
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, width, height)
    gdi32.SelectObject(mem, bmp)
    user32.PrintWindow(hwnd, mem, 2)

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", W.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", W.WORD), ("biBitCount", W.WORD), ("biCompression", W.DWORD),
                    ("biSizeImage", W.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", W.DWORD), ("biClrImportant", W.DWORD)]

    bi = BIH()
    bi.biSize, bi.biWidth, bi.biHeight = ctypes.sizeof(BIH), width, -height
    bi.biPlanes, bi.biBitCount, bi.biCompression = 1, 32, 0
    buf = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(mem, bmp, 0, height, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    from PIL import Image
    import hashlib
    image = Image.frombuffer("RGBA", (width, height), buf, "raw", "BGRA", 0, 1).convert("L").resize((16, 12))
    # quantise to four levels per cell: menus keep their layout, the attract movie's motion does not survive this
    quantised = bytes((pixel // 64) * 64 for pixel in image.tobytes())
    digest = hashlib.sha1(quantised).hexdigest()[:12]
    OUT.mkdir(parents=True, exist_ok=True)
    image.save(OUT / f"{digest}.png")
    return digest


class KeySender:
    """One persistent PowerShell sender: each press is a pipe write, not a process spawn."""

    def __init__(self, hwnd):
        self.proc = subprocess.Popen([
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(Path(__file__).with_name("pso_key_sender.ps1")), "-Hwnd", str(hwnd)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.proc.stdout.readline()                          # 'ready'

    def send(self, combo: str) -> None:
        self.proc.stdin.write(combo + "\n")
        self.proc.stdin.flush()
        self.proc.stdout.readline()                          # 'ok'

    def close(self) -> None:
        try:
            self.proc.stdin.write("QUIT\n")
            self.proc.stdin.flush()
        except Exception:                                    # noqa: BLE001
            pass
        self.proc.terminate()


def wait_stable(hwnd, timeout: float = 3.0, step: float = 0.12) -> tuple[str, bool]:
    """A real menu holds still; the attract movie does not. Returns (screen id, stable)."""
    previous = fingerprint(hwnd)
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(step)
        current = fingerprint(hwnd)
        if current == previous:
            return current, True
        previous = current
    return previous, False


def make_press(sender):
    def press(key: str):
        combo = KEYS.get(key)
        if combo is None:
            raise ValueError(f"no keyboard mapping for {key!r}")
        sender.send(combo)
    return press


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, default=52376)
    ap.add_argument("--rounds", type=int, default=12)
    ap.add_argument("--verify", default="")
    args = ap.parse_args()
    hwnd = pso_window(args.pid)
    if not hwnd:
        print("no PSO window for pid", args.pid)
        return 1
    print("window", hex(hwnd))
    graph = TransitionGraph.load(STATE) if STATE.is_file() else TransitionGraph()
    sender = KeySender(hwnd)
    learner = MenuLearner(lambda: wait_stable(hwnd)[0], make_press(sender), graph, keys=("start", "a", "ddown", "dup"), settle=0.7)
    screen, stable = wait_stable(hwnd)
    print("start screen:", screen, "stable:", stable)
    if not stable:
        print("the screen is animating (attract loop): pressing START once to reach the stable menu")
        sender.send(KEYS["start"])
        time.sleep(1.5)
        screen, stable = wait_stable(hwnd)
        print("after START:", screen, "stable:", stable)
    if stable:
        result = learner.explore(rounds=args.rounds)
        print("explored:", result, "screens:", learner.graph.known_screens())
    else:
        print("still animating; not learning from the movie")
        result = {"presses": 0, "screens": 0, "goal_reached": False}
    learner.graph.save(STATE)
    sender.close()
    print("edges:", json.dumps(learner.graph.as_dict()["edges"], indent=0)[:600])
    return 0


if __name__ == "__main__":
    sys.exit(main())
