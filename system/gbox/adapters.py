"""Runtime/emulator adapters behind one capability interface (plan §6). Unsupported ops raise Unsupported."""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import struct
import time
from pathlib import Path

from . import provision
from .config import HOST_OS, Config, EmulatorConfig
from .registry import ToolUnavailable, Unsupported

if HOST_OS == "linux" and "/usr/games" not in os.environ.get("PATH", ""):
    os.environ["PATH"] += ":/usr/games"                  # apt puts mame / mgba-qt there; systemd services don't have it

OPS = ["launch_game", "stop_game", "pause", "resume", "get_frame", "get_audio", "send_input", "read_memory",
       "write_memory", "query_memory_map", "save_state", "load_state", "step_frames", "set_breakpoint",
       "remove_breakpoint", "trace_execution", "query_runtime", "stream_session", "rewind", "fast_forward"]

# Rewind policy per platform.
# No rewind where snapshotting every few frames would cost frame rate (Dolphin/PCSX2/Citra cores).
NO_REWIND = {"gamecube", "wii", "ps2", "3ds", "wiiu", "switch",
             "dreamcast", "naomi", "atomiswave"}         # Flycast: 27 MB states every few frames stutter and break manual saves
# 3D / CD systems: snapshot every 15 frames (coarser steps, cheap); 8/16-bit: every 4 frames (smooth).
COARSE_REWIND = {"n64", "n64dd", "psx", "dreamcast", "naomi", "saturn", "psp", "segacd", "pcecd", "3do", "jaguar", "neocd", "cdi", "pcfx"}
# Pads whose games actually use L2/R2 (triggers): never steal those for rewind / fast-forward.
TRIGGERS_USED = {"psx", "ps2", "dreamcast", "naomi", "gamecube", "wii", "n64", "n64dd", "3ds", "wiiu", "switch"}


class Adapter:
    name = "base"
    supported: set[str] = set()

    def get_capabilities(self) -> dict[str, str]:
        return {op: ("supported" if op in self.supported else "unsupported") for op in OPS}

    def __getattr__(self, op):
        if op in OPS:
            def unsupported(*a, **k):
                raise Unsupported(f"{self.name} does not support {op}")
            return unsupported
        raise AttributeError(op)


def _kill_tree(proc: subprocess.Popen | None):
    if not proc or proc.poll() is not None:
        return
    if HOST_OS == "windows":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()


class CommandAdapter(Adapter):
    """Any emulator launched by a command template. Process lifetime only; no introspection."""
    name = "command"
    supported = {"launch_game", "stop_game", "query_runtime"}

    def __init__(self, cfg: EmulatorConfig):
        self.cfg, self.proc = cfg, None

    def _argv(self, rom: str) -> list[str]:
        return [self.cfg.executable] + [a.replace("{rom}", rom) for a in self.cfg.args]

    def launch_game(self, rom: str) -> dict:
        if not shutil.which(self.cfg.executable or "") and not Path(self.cfg.executable or "").exists():
            raise ToolUnavailable(f"emulator not found: {self.cfg.executable}")
        self.proc = subprocess.Popen(self._argv(rom))
        return {"pid": self.proc.pid}

    def stop_game(self) -> dict:
        _kill_tree(self.proc)
        return {"returncode": self.proc.poll() if self.proc else None}

    def query_runtime(self) -> dict:
        return {"running": bool(self.proc and self.proc.poll() is None), "pid": self.proc and self.proc.pid}


# --- virtual display (linux) ---------------------------------------------------------------

class Display:
    """A private Xvfb display per session so sessions never overlap and frames/input are isolated."""
    def __init__(self, w: int = 960, h: int = 720):          # = stream size: no rescale per frame
        self.w, self.h, self.proc = w, h, None
        for n in range(90, 140):
            if not Path(f"/tmp/.X11-unix/X{n}").exists() and not Path(f"/tmp/.X{n}-lock").exists():
                self.name = f":{n}"
                break
        else:
            raise RuntimeError("no free X display numbers")
        self.proc = subprocess.Popen(["Xvfb", self.name, "-screen", "0", f"{w}x{h}x24", "+extension", "GLX", "-nolisten", "tcp"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            if subprocess.run(["xdpyinfo", "-display", self.name], capture_output=True).returncode == 0:
                # synthetic holds must not auto-repeat (a held d-pad would step menus several times)
                subprocess.run(["xset", "-display", self.name, "r", "off"], capture_output=True)
                return
            time.sleep(0.1)
        raise RuntimeError(f"Xvfb {self.name} did not start")

    def close(self):
        _kill_tree(self.proc)


def grab_png(display: str | None, region: list[int] | None = None) -> bytes:
    """One frame: x11grab on linux (display), gdigrab desktop on windows."""
    out = Path(tempfile.mkdtemp()) / "frame.png"
    if HOST_OS == "windows":
        src = ["-f", "gdigrab"]
        if region:
            x, y, w, h = region
            src += ["-offset_x", str(x), "-offset_y", str(y), "-video_size", f"{w}x{h}"]
        src += ["-i", "desktop"]
    else:
        src = ["-f", "x11grab"]
        disp = display or os.environ.get("DISPLAY", ":0")
        if region:
            x, y, w, h = region
            src += ["-video_size", f"{w}x{h}", "-i", f"{disp}+{x},{y}"]
        else:
            src += ["-i", disp]
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *src, "-frames:v", "1", str(out)], check=True, timeout=30)
    data = out.read_bytes()
    shutil.rmtree(out.parent, ignore_errors=True)
    return data


class MjpegStream:
    """Persistent ffmpeg grab -> MJPEG pipe; `latest` always holds the newest complete JPEG.
    ponytail: MJPEG over HTTP (~60 fps on LAN, no audio); move to H.264/NVENC over WebRTC if bandwidth/latency bite."""
    def __init__(self, display: str | None, fps: int = 60, size: tuple[int, int] | None = None,
                 max_width: int = 960, draw_mouse: bool = False):
        if HOST_OS == "windows":
            src = ["-f", "gdigrab", "-draw_mouse", "1" if draw_mouse else "0", "-framerate", str(fps), "-i", "desktop"]
        else:
            src = ["-f", "x11grab", "-draw_mouse", "0", "-framerate", str(fps),
                   *(["-video_size", f"{size[0]}x{size[1]}"] if size else []), "-i", display or ":0"]
        self.proc = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-fflags", "nobuffer", *src,
                                      "-vf", f"scale='min({max_width},iw)':-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-pix_fmt", "yuvj420p",
                                      "-q:v", "7", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.latest, self.seq, self.cond = None, 0, threading.Condition()
        threading.Thread(target=self._read, daemon=True).start()

    def wait(self, seen: int, timeout: float) -> bool:
        """Block until a frame newer than `seen` exists."""
        with self.cond:
            return self.cond.wait_for(lambda: self.seq != seen and self.latest is not None, timeout)

    def _read(self):
        buf = b""
        while chunk := self.proc.stdout.read1(262144):
            buf += chunk
            while (s := buf.find(b"\xff\xd8")) >= 0 and (e := buf.find(b"\xff\xd9", s + 2)) >= 0:
                with self.cond:
                    self.latest, self.seq, buf = buf[s:e + 2], self.seq + 1, buf[e + 2:]
                    self.cond.notify_all()

    def close(self):
        _kill_tree(self.proc)


# RetroPad button -> X keysym per player. P1 = RetroArch defaults; P2 is bound in the session config (_write_cfg).
# Hotkeys are gated behind scroll_lock (never sent), so pad keys can't trigger pause/fast-forward/fullscreen etc.
PAD_KEYS = {
    1: {"up": "Up", "down": "Down", "left": "Left", "right": "Right", "a": "x", "b": "z", "x": "s", "y": "a",
        "l": "q", "r": "w", "start": "Return", "select": "Shift_R", "l2": "e", "r2": "r", "l3": "d", "r3": "f",
        # left analog stick as digital keys (3D games like PSO move with the stick, not the d-pad)
        "lup": "8", "ldown": "2", "lleft": "4", "lright": "6"},
    2: {"up": "i", "down": "k", "left": "j", "right": "l", "a": "n", "b": "b", "x": "h", "y": "u",
        "l": "y", "r": "o", "start": "p", "select": "t", "l2": "g", "r2": "v", "l3": "c", "r3": "m"},
}
_RA_KEYNAME = {"Up": "up", "Down": "down", "Left": "left", "Right": "right", "Return": "enter", "Shift_R": "rshift",
               "8": "num8", "2": "num2", "4": "num4", "6": "num6"}
_ANALOG = {"lup": "l_y_minus", "ldown": "l_y_plus", "lleft": "l_x_minus", "lright": "l_x_plus"}


# Windows: keyboard input into a local emulator window (autoplay on this PC). Scan codes, because RetroArch reads the
# keyboard through DirectInput. Only while gBox (or the emulator) is the active window: never types into another app.
# RETRO_DEVICE_ID_JOYPAD_* (libretro.h) and the left stick as RETRO_DEVICE_ANALOG (index 0: id 0 = x, 1 = y)
RETROPAD_ID = {"b": 0, "y": 1, "select": 2, "start": 3, "up": 4, "down": 5, "left": 6, "right": 7, "a": 8, "x": 9,
               "l": 10, "r": 11, "l2": 12, "r2": 13, "l3": 14, "r3": 15}
STICK = {"lleft": (0, -0x7FFF), "lright": (0, 0x7FFF), "lup": (1, -0x7FFF), "ldown": (1, 0x7FFF)}
_SCAN = {"Up": (0x48, 1), "Down": (0x50, 1), "Left": (0x4B, 1), "Right": (0x4D, 1), "Return": (0x1C, 0), "Shift_R": (0x36, 0),
         "8": (0x48, 0), "2": (0x50, 0), "4": (0x4B, 0), "6": (0x4D, 0),
         **{c: (sc, 0) for c, sc in zip("qwertyuiopasdfghjklzxcvbnm", [0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19,
                                                                     0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26,
                                                                     0x2C, 0x2D, 0x2E, 0x2F, 0x30, 0x31, 0x32])}}


def _pid_window(pid: int):
    """The visible window of a process, top-level or docked inside gBox as a child window."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    found = []
    PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def mine(h):
        p = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        return p.value == pid and u.IsWindowVisible(h)

    @PROC
    def child(h, _):
        if mine(h):
            found.append(h)
        return True

    @PROC
    def top(h, _):
        if mine(h):
            found.append(h)
        u.EnumChildWindows(h, child, 0)
        return True
    u.EnumWindows(top, 0)
    return found[0] if found else None


def win_send_keys(pid: int, events: list[dict]) -> dict:
    import ctypes
    from ctypes import wintypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    h = _pid_window(pid)
    if not h:
        raise RuntimeError("the game window isn't open")
    root = u.GetAncestor(h, 2)                                   # GA_ROOT: gBox when docked, else the emulator itself
    for _ in range(100):                                         # wait (up to 10 s) for the operator to bring gBox back
        if u.GetForegroundWindow() == root:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("gBox isn't the active window: autoplay waits rather than typing into another app")
    me, them = k.GetCurrentThreadId(), u.GetWindowThreadProcessId(h, None)
    u.AttachThreadInput(me, them, True)
    u.SetFocus(h)
    u.AttachThreadInput(me, them, False)

    class KI(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_size_t)]

    class INP(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("ki", KI), ("pad", ctypes.c_ubyte * 8)]
    seq, pressed = [], set()
    for ev in events:
        keys = PAD_KEYS.get(int(ev.get("player", 1)), PAD_KEYS[1])
        name = keys.get(ev["key"], ev["key"])
        sc, ext = _SCAN.get(name, _SCAN.get(str(name).lower(), (0, 0)))
        if not sc:
            continue
        down = ev.get("down", True)
        if not down and name in pressed:
            time.sleep(0.06)                                     # down+up in one batch: the game polls per frame
        pressed.add(name)
        flags = 0x0008 | (0x0001 if ext else 0) | (0 if down else 0x0002)   # SCANCODE | EXTENDED | KEYUP
        inp = INP(type=1, ki=KI(0, sc, flags, 0, 0))
        seq.append(name)
        u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INP))
    return {"sent": len(seq)}


def win_grab(pid: int) -> bytes:
    """PNG of a local emulator window (docked or not), as the screen shows it."""
    import ctypes
    import io
    from ctypes import wintypes
    from PIL import ImageGrab
    h = _pid_window(pid)
    if not h:
        raise RuntimeError("the game window isn't open")
    r = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(h, ctypes.byref(r))
    buf = io.BytesIO()
    ImageGrab.grab((r.left, r.top, r.right, r.bottom), all_screens=True).save(buf, "PNG")
    return buf.getvalue()


VGLRUN = "/opt/VirtualGL/bin/vglrun"


def _pad_binds() -> dict:
    """retroarch.cfg lines binding both players' RetroPad buttons to the keys above."""
    out = {"input_enable_hotkey": "scroll_lock"}
    for player, keys in PAD_KEYS.items():
        for btn, ks in keys.items():
            out[f"input_player{player}_{_ANALOG.get(btn, btn)}"] = _RA_KEYNAME.get(ks, ks)
    return out


def _examine_driver_ok(argv) -> bool:
    """RenderDoc injection only for Direct3D/Vulkan renderers: under it RetroArch's OpenGL driver can't create its window
    ("win32_set_video_mode failed", the game never starts: N64 parallel_n64 and the other GL cores)."""
    import re
    if "--config" not in argv:
        return True                                   # standalone emulators here (Dolphin D3D12) are Direct3D
    try:
        cfg = Path(argv[argv.index("--config") + 1]).read_text(errors="replace")
    except (OSError, IndexError):
        return False
    m = re.search(r'^video_driver\s*=\s*"([^"]*)"', cfg, re.M)
    return bool(m) and m.group(1) in ("d3d11", "d3d12", "vulkan")


def _popen(ad, argv, **kw) -> subprocess.Popen:
    """Start a local-window emulator; with Examine 3D on (ad.examine) RenderDoc is loaded into it from the first
    instruction, so the frame on screen can be captured as a 3D scene later (gbox.scene_capture)."""
    if HOST_OS == "windows":
        from .graphics import prefer_gpu
        prefer_gpu(argv[0])                                # the discrete GPU, never a virtual display / iGPU
        kw.setdefault("startupinfo", hidden_start())
    if HOST_OS == "windows" and getattr(ad, "examine", False) and _examine_driver_ok(argv):
        from . import scene_capture
        p = scene_capture.popen_hooked(argv, cap_dir=ad.config.runtime / "scene_capture" / "rdc" if ad.config else None, **kw)
    else:
        p = subprocess.Popen(argv, **kw)
    if HOST_OS == "windows":
        keep_offscreen(p.pid)
    return p


def hidden_start():
    """Windows: start the emulator minimized and without focus. Its first ShowWindow takes this instead of whatever the
    emulator asks for, so no big window flashes on the desktop before gBox docks it into the game area (winembed un-minimizes
    it while docking)."""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 7                                     # SW_SHOWMINNOACTIVE
    return si


def keep_offscreen(pid: int, limit_s: float = 90.0, give_up_s: float = 45.0):
    """Windows: every top-level window of this emulator is parked off-screen the moment it's created (a WinEvent hook on
    that process, so it's moved before it's ever shown), and stays there until gBox docks it (it becomes a child window).
    No big window flashing on the desktop while the game loads. If nothing docks it within give_up_s (the gBox app isn't
    running), it comes back on screen so the game isn't lost."""
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    H = wintypes.HWND
    u32.SetWindowPos.argtypes = [H, H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    u32.GetWindowRect.argtypes = [H, ctypes.POINTER(wintypes.RECT)]
    u32.GetWindowLongPtrW.argtypes, u32.GetWindowLongPtrW.restype = [H, ctypes.c_int], ctypes.c_ssize_t
    u32.GetAncestor.argtypes, u32.GetAncestor.restype = [H, wintypes.UINT], H
    for f in ("IsWindow", "IsWindowVisible", "IsIconic"):
        getattr(u32, f).argtypes = [H]
    u32.GetWindowThreadProcessId.argtypes = [H, ctypes.POINTER(wintypes.DWORD)]
    HOOK = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, H, ctypes.c_long, ctypes.c_long, wintypes.DWORD, wintypes.DWORD)
    u32.SetWinEventHook.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.HMODULE, HOOK, wintypes.DWORD, wintypes.DWORD, wintypes.UINT]
    u32.SetWinEventHook.restype = wintypes.HANDLE
    u32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
    u32.PeekMessageW.argtypes = [ctypes.c_void_p, H, wintypes.UINT, wintypes.UINT, wintypes.UINT]
    u32.MsgWaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD, wintypes.DWORD]
    u32.SetWindowLongPtrW.argtypes, u32.SetWindowLongPtrW.restype = [H, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t
    GWL_STYLE, GWL_EXSTYLE, WS_CHILD, WS_EX_LAYERED = -16, -20, 0x40000000, 0x00080000
    OFF, FLAGS = -32000, 0x0001 | 0x0004 | 0x0010          # NOSIZE | NOZORDER | NOACTIVATE
    parked: dict[int, tuple[int, int]] = {}                # hwnd -> where it wanted to be

    def opaque(h):                                         # RetroArch starts transparent (video_window_opacity 0)
        ex = u32.GetWindowLongPtrW(h, GWL_EXSTYLE)
        if ex & WS_EX_LAYERED:
            u32.SetWindowLongPtrW(h, GWL_EXSTYLE, ex & ~WS_EX_LAYERED)

    def windows(child: bool):
        out = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, H, wintypes.LPARAM)
        def cb(h, _):
            p = wintypes.DWORD()
            u32.GetWindowThreadProcessId(h, ctypes.byref(p))
            if p.value == pid and bool(u32.GetWindowLongPtrW(h, GWL_STYLE) & WS_CHILD) == child:
                out.append(h)
            return True
        if child:
            @ctypes.WINFUNCTYPE(wintypes.BOOL, H, wintypes.LPARAM)
            def top(h, _):
                u32.EnumChildWindows(h, cb, 0)
                return True
            u32.EnumWindows(top, 0)
        else:
            u32.EnumWindows(cb, 0)
        return out

    def park(h):
        if not h or not u32.IsWindow(h) or u32.GetAncestor(h, 2) != h or (u32.GetWindowLongPtrW(h, GWL_STYLE) & WS_CHILD):
            return                                         # GA_ROOT: top-level windows only; docked (child) = leave it
        r = wintypes.RECT()
        u32.GetWindowRect(h, ctypes.byref(r))
        if r.left > OFF + 1000:
            parked.setdefault(h, (r.left, r.top))
            u32.SetWindowPos(h, None, OFF, OFF, 0, 0, FLAGS)

    @HOOK
    def on_event(_hook, event, h, id_obj, id_child, _thread, _t):
        if id_obj == 0 and id_child == 0:                  # OBJID_WINDOW, the window itself
            park(h)

    def run():
        # EVENT_OBJECT_CREATE (0x8000) .. EVENT_OBJECT_LOCATIONCHANGE (0x800B), this process only, out of context
        hook = u32.SetWinEventHook(0x8000, 0x800B, None, on_event, pid, 0, 0x0000 | 0x0002)   # OUTOFCONTEXT | SKIPOWNPROCESS
        t0, msg = time.time(), wintypes.MSG()
        try:
            while time.time() - t0 < limit_s:
                u32.MsgWaitForMultipleObjects(0, None, False, 50, 0x04FF)   # QS_ALLINPUT: events arrive as messages
                while u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):   # PM_REMOVE
                    u32.TranslateMessage(ctypes.byref(msg))
                    u32.DispatchMessageW(ctypes.byref(msg))
                for h in [h for h in parked if not u32.IsWindow(h) or (u32.GetWindowLongPtrW(h, GWL_STYLE) & WS_CHILD)]:
                    parked.pop(h, None)                    # docked into gBox (or gone)
                docked = windows(True)
                if docked:                                 # docked into gBox: make sure it's opaque (older winembed), done
                    for h in docked:
                        opaque(h)
                    if not parked:
                        return
                if time.time() - t0 > give_up_s and not docked:   # nobody docked it (gBox app closed): show it normally
                    for h in windows(False):
                        opaque(h)
                    for h, (x, y) in parked.items():
                        u32.SetWindowPos(h, None, max(0, x), max(0, y), 0, 0, FLAGS)
                    return
        finally:
            if hook:
                u32.UnhookWinEvent(hook)
    threading.Thread(target=run, daemon=True, name=f"offscreen-{pid}").start()


def win_suspend_emulation(pid: int) -> list[int]:
    """Pause a Windows emulator without a pause command: suspend every thread of the process except the ones that own
    its windows. The window keeps answering messages, so docking/PiP resizes (SetWindowPos from the app) never block
    on a frozen thread, and the last frame stays on screen. Returns the suspended thread ids (for win_resume_threads)."""
    import ctypes
    from ctypes import wintypes
    k, u = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.windll.user32
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.OpenThread.restype = wintypes.HANDLE

    class TE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ThreadID", wintypes.DWORD),
                    ("th32OwnerProcessID", wintypes.DWORD), ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD)]
    ui = set()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        wpid = wintypes.DWORD()
        tid = u.GetWindowThreadProcessId(h, ctypes.byref(wpid))
        if wpid.value == pid:
            ui.add(tid)
        return True
    u.EnumWindows(cb, 0)
    snap = k.CreateToolhelp32Snapshot(0x4, 0)                       # TH32CS_SNAPTHREAD
    te, out = TE(), []
    te.dwSize = ctypes.sizeof(TE)
    ok = k.Thread32First(snap, ctypes.byref(te))
    while ok:
        if te.th32OwnerProcessID == pid and te.th32ThreadID not in ui:
            h = k.OpenThread(0x0002, False, te.th32ThreadID)           # THREAD_SUSPEND_RESUME
            if h:
                if k.SuspendThread(h) != 0xFFFFFFFF:
                    out.append(te.th32ThreadID)
                k.CloseHandle(h)
        ok = k.Thread32Next(snap, ctypes.byref(te))
    k.CloseHandle(snap)
    return out


def win_resume_threads(tids: list[int]) -> int:
    import ctypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenThread.restype = ctypes.c_void_p
    n = 0
    for tid in tids or []:
        h = k.OpenThread(0x0002, False, tid)
        if h:
            n += k.ResumeThread(ctypes.c_void_p(h)) != 0xFFFFFFFF
            k.CloseHandle(ctypes.c_void_p(h))
    return n


def _examine_ok(proc) -> bool:
    info = getattr(proc, "renderdoc", None)
    return bool(info) and "error" not in info


class RetroArchAdapter(CommandAdapter):
    """RetroArch + libretro core, controlled through RetroArch's UDP network command interface.

    Linux: each session runs on its own Xvfb display (frames via x11grab, input via xdotool).
    Cores, core assets and BIOS are resolved automatically (provision.ensure_platform).
    Memory ops depend on the core exposing a memory map; failures come back as explicit errors.
    """
    name = "retroarch"
    supported = {"launch_game", "stop_game", "pause", "resume", "read_memory", "write_memory", "save_state",
                 "load_state", "step_frames", "query_runtime", "get_frame", "send_input", "stream_session", "rewind", "fast_forward"}

    def __init__(self, cfg: EmulatorConfig, config: Config | None = None, platform: str | None = None,
                 port: int | None = None, host: str = "127.0.0.1"):
        super().__init__(cfg)
        self.config, self.platform = config, platform
        if port is None:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]
        self.addr, self.display, self.stream, self.log_path = (host, port), None, None, None
        self.rewind_on = (platform or "") not in NO_REWIND
        self.granularity = 15 if (platform or "") in COARSE_REWIND else 4
        self.trigger_hotkeys = self.rewind_on and (platform or "") not in TRIGGERS_USED   # L2 = rewind, R2 = fast-forward
        if HOST_OS == "windows":
            # local native play: the RetroArch window IS the display; real pads/keyboard go straight in, nothing to stream.
            # send_input (autoplay) types the bound keys into the docked window; get_frame captures that window.
            self.supported = self.supported - {"stream_session"}

    def _write_cfg(self) -> Path:
        rt = self.config.runtime
        d = {k: rt / k for k in ("system", "saves", "states", "screenshots", "logs", "retroarch", "extract")}
        for p in d.values():
            p.mkdir(parents=True, exist_ok=True)
        cfg = d["retroarch"] / f"session-{self.addr[1]}.cfg"
        opts = {"system_directory": d["system"], "savefile_directory": d["saves"], "savestate_directory": d["states"],
                # cores that need a real file (Citra, PPSSPP...) get .zip/.7z content extracted here first
                "cache_directory": d["extract"],
                "screenshot_directory": d["screenshots"], "network_cmd_enable": "true", "network_cmd_port": self.addr[1],
                "config_save_on_exit": "false", "pause_nonactive": "false",
                # network gamepad: gBox presses buttons over UDP, so input works whatever window has focus (docked on Windows,
                # DirectInput ignores injected keys because the emulator isn't the top-level foreground window)
                "network_remote_enable": "true", "network_remote_enable_user_p1": "true", "network_remote_base_port": self._remote_port(),
                # linux: fill the private Xvfb display exactly, so frames are never cropped; RetroArch letterboxes
                "video_fullscreen": "true" if HOST_OS == "linux" else "false", "video_windowed_fullscreen": "true",
                "video_driver": "gl", "audio_driver": "null" if HOST_OS == "linux" else "xaudio",
                "menu_driver": "rgui", "savestate_auto_index": "false", "video_vsync": "false",
                # no audio clock or vsync on a virtual display: pace emulation to the core's exact frame rate
                "vrr_runloop_enable": "true", "audio_sync": "false", "video_threaded": "false",
                "input_driver": "x" if HOST_OS == "linux" else "dinput", "libretro_log_level": "1",
                "core_options_path": d["retroarch"] / "core-options.cfg", "global_core_options": "true",
                "gamemode_enable": "false",          # GameMode needs a D-Bus session bus; services have none (abort -6)
                "suspend_screensaver_enable": "false", "video_font_enable": "false"}
        co = d["retroarch"] / "core-options.cfg"              # Flycast: threaded rendering lets the state grow between the size
        if (self.platform or "") == "n64" and HOST_OS == "windows":       # docked + resized windows: the GL plugins (Glide64)
            set_opt = {"parallel-n64-gfxplugin": "angrylion"}             # draw at launch size -> squeezed/cropped picture;
            lines = [l for l in (co.read_text().splitlines() if co.exists() else []) if l.split(" =")[0] not in set_opt]   # software
            co.write_text("\n".join(lines + [f'{k} = "{v}"' for k, v in set_opt.items()]) + "\n")                        # output scales
        if (self.platform or "") in ("dreamcast", "naomi", "atomiswave"):   # query and the write ("Serializer buffer overflow")
            lines = [l for l in (co.read_text().splitlines() if co.exists() else []) if not l.startswith("reicast_threaded_rendering")]
            co.write_text("\n".join(lines + ['reicast_threaded_rendering = "disabled"']) + "\n")
        if not self.rewind_on:
            opts["rewind_enable"] = "false"
        if self.rewind_on:
            opts.update({"rewind_enable": "true", "rewind_granularity": str(self.granularity),
                         "rewind_buffer_size": "1024" if self.granularity > 4 else "512", "rewind_buffer_size_step": "64"})
        if HOST_OS == "windows":
            # every game: hold Select + L2 = rewind (RetroArch's own hotkey). Select is the hotkey enabler, so L2/R2 keep
            # working in games that use them. SDL gamepad button 4 = View/Back (Select).
            # Select + R2 = fast-forward ramping 2x -> 4x -> 16x: driven by the worker (tools._ff_ramp), since RetroArch
            # has one fixed fast-forward ratio per run.
            opts.update({"input_enable_hotkey_btn": "4", "input_rewind_axis": "+4", "input_hold_fast_forward_axis": "nul"})
        elif self.trigger_hotkeys:         # streamed: the pad's L2/R2 keys, sent together with the hotkey-enable key
            opts.update({"input_rewind": "e", "input_hold_fast_forward": "r"})
        opts["fastforward_ratio"] = "16.0"                 # the ramp's top speed; lower speeds = fast-forward part of the time
        # cheats: the game's .cht is placed under <runtime>/cheats/<core library name>/ before launch (see install_cheats)
        opts.update({"cheat_database_path": rt / "cheats", "apply_cheats_after_load": "true", "apply_cheats_after_toggle": "true"})
        if HOST_OS == "windows":
            from .gamepads import retroarch_driver
            driver = retroarch_driver(self.cfg.executable or provision.retroarch_exe(self.config))
            # Native local play: SDL autoconfig + process-scoped SpaceMouse exclusions.
            opts.update({"video_fullscreen": "false", "video_windowed_fullscreen": "true", "video_vsync": "true",
                         "vrr_runloop_enable": "false", "audio_sync": "true", "audio_driver": "xaudio",
                         "input_driver": "dinput", "input_joypad_driver": driver, "input_autodetect_enable": "true",
                         # NOT video_window_opacity 0 to hide the window while loading: a GL context made on a layered window keeps
                         # presenting nothing after the window is made opaque (black game, 2026-10-08). keep_offscreen hides it.
                         "video_window_opacity": "100",
                         "video_window_save_positions": "false", "custom_viewport_width": "0",
                         "video_windowed_position_width": "1280", "video_windowed_position_height": "960",
                         # the window is embedded inside the gBox app: no menu bar, no decorations, no companion UI
                         "ui_menubar_enable": "false", "video_window_show_decorations": "false",
                         "ui_companion_enable": "false", "ui_companion_start_on_boot": "false", "video_window_auto_width_max": "0"})
            if (self.platform or "") == "ps2":       # pcsx2_libretro's GL path presents black frames on this PC; D3D11 works
                opts["video_driver"] = "d3d11"
        opts |= _pad_binds()                 # keyboard binds; native gamepads use SDL autoconfig
        if HOST_OS == "windows" and self.config is not None:   # per-game graphics settings (Sessions -> Graphics)
            from . import graphics
            opts |= graphics.retroarch_opts(graphics.get(self.config, getattr(self, "game_id", None)),
                                            Path(provision.retroarch_exe(self.config)).parent)
        if HOST_OS == "windows" and (self.platform or "") == "ps2":
            opts["video_shader_enable"] = "false"            # the .glslp post-AA presets don't load under d3d11
        cfg.write_text("".join(f'{k} = "{v}"\n' for k, v in opts.items()))
        return cfg

    def _argv(self, rom: str) -> list[str]:
        core = self.cfg.core
        if self.config is not None:
            self._p(10, f"Resolving core {core or self.platform} (downloads on first use)")
            core = str(provision.ensure_platform(self.config, self.platform, self.cfg.core)[0])
            self._p(25, f"Core ready: {Path(core).name}")
        elif not core:
            raise ToolUnavailable("retroarch adapter needs 'core' configured")
        exe = self.cfg.executable or (provision.retroarch_exe(self.config) if self.config else "retroarch")
        cfg = self._write_cfg() if self.config is not None else None
        return [exe, *(["--config", str(cfg)] if cfg else []), "-L", core, "--verbose", *self.cfg.args, rom]

    def install_cheats(self, core: str, rom: str) -> list[dict]:
        """Copy the libretro-database code list for this game where RetroArch auto-loads it (all codes off)."""
        from . import cheats
        self.cheats, self.cheat_index = [], 0
        if not self.config:
            return []
        db = self.config.data_dir / "cheatdb" / "libretro-database" / "cht"
        hits = cheats.find(db, self.platform or "", Path(rom).stem)
        lib = cheats.core_library_name(core) if hits else None
        if not hits or not lib:
            return []
        entries = cheats.parse_cht(hits[0].read_text(encoding="utf-8", errors="replace"))
        for e in entries:
            e["enable"] = False
        dst = self.config.runtime / "cheats" / lib / f"{Path(rom).stem}.cht"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(cheats.write_cht(entries), encoding="utf-8")
        self.cheats, self.cheat_source = entries, hits[0].name
        return entries

    def cheat_set(self, index: int, on: bool) -> dict:
        """Live toggle through RetroArch's cheat index (CHEAT_INDEX_PLUS/MINUS + CHEAT_TOGGLE; RetroArch re-applies)."""
        if not 0 <= index < len(self.cheats):
            raise ValueError(f"no cheat #{index} (this game has {len(self.cheats)})")
        if self.cheats[index]["enable"] == on:
            return {"index": index, "enabled": on, "changed": False}
        while self.cheat_index < index:
            self.cmd("CHEAT_INDEX_PLUS")
            self.cheat_index += 1
            time.sleep(0.12)                              # RetroArch handles ~1 command per frame
        while self.cheat_index > index:
            self.cmd("CHEAT_INDEX_MINUS")
            self.cheat_index -= 1
            time.sleep(0.12)                              # RetroArch handles ~1 command per frame
        time.sleep(0.12)
        self.cmd("CHEAT_TOGGLE")
        self.cheats[index]["enable"] = on
        return {"index": index, "enabled": on, "changed": True, "desc": self.cheats[index].get("desc")}

    def _from_7z(self, rom: str) -> str:
        """RetroArch's built-in 7z reader fails on some archives (e.g. large 3DS sets): extract with the system 7z once
        into the runtime's extract cache and launch the biggest file inside."""
        z = shutil.which("7z") or shutil.which("7za") or (r"C:\Program Files\7-Zip\7z.exe" if HOST_OS == "windows" else None)
        if not rom.lower().endswith(".7z") or not z or not Path(z).exists() and not shutil.which(z):
            return rom
        import hashlib
        out = self.config.runtime / "extract" / ("7z-" + hashlib.sha1(rom.encode()).hexdigest()[:16])
        if not out.exists() or not any(out.iterdir()):
            out.mkdir(parents=True, exist_ok=True)
            self._p(30, f"Extracting {Path(rom).name}")
            subprocess.run([z, "x", "-y", f"-o{out}", rom], check=True, capture_output=True, timeout=1800)
        files = [f for f in out.rglob("*") if f.is_file()]
        if (self.platform or "") in ("naomi", "naomi2", "atomiswave") and files:
            # arcade ROM sets: Flycast wants <shortname>.zip holding the chips, not one chip file
            import zipfile
            zp = out.parent / (out.name + "-zip") / (Path(rom).stem + ".zip")
            if not zp.exists():
                zp.parent.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(zp, "w", zipfile.ZIP_STORED) as z:
                    for f in files:
                        z.write(f, f.relative_to(out).as_posix())
            return str(zp)
        return str(max(files, key=lambda f: f.stat().st_size)) if files else rom

    def _from_lst_zip(self, rom: str) -> str:
        """NAOMI GD-ROM sets packed as <game>.zip holding <game>.lst + .bin (Demul-style list image): Flycast opens the
        .lst itself, not the zip. Extract once into the runtime's extract cache and launch the .lst."""
        if not rom.lower().endswith(".zip") or (self.platform or "") not in ("naomi", "naomi2", "atomiswave"):
            return rom
        import hashlib
        import zipfile
        try:
            with zipfile.ZipFile(rom) as z:
                names = z.namelist()
                lst = next((n for n in names if n.lower().endswith(".lst")), None)
                if not lst:
                    return rom                                   # a normal MAME-style ROM set: Flycast reads the zip
                out = self.config.runtime / "extract" / ("lst-" + hashlib.sha1(rom.encode()).hexdigest()[:16])
                if not (out / lst).exists():
                    out.mkdir(parents=True, exist_ok=True)
                    self._p(30, f"Unpacking {Path(rom).name}")
                    z.extractall(out)
                # the .lst may name its data file differently from what the set ships (capcomvssnk2.bin vs cvs2gd.bin):
                # link each missing name to the set's single data file
                import re
                bins = [f for f in out.iterdir() if f.suffix.lower() in (".bin", ".dat")]
                for want in re.findall(r'"?([\w\-. ]+\.(?:bin|dat))"?', (out / lst).read_text(errors="replace"), re.I):
                    if not (out / want).exists() and len(bins) == 1:
                        try:
                            os.link(bins[0], out / want)
                        except OSError:
                            shutil.copyfile(bins[0], out / want)
                return str(out / lst)
        except zipfile.BadZipFile:
            return rom

    def _from_old_chd(self, rom: str) -> str:
        """The neocd core only reads CHD v5; HyperSpin's Neo Geo CD set is v4: convert once to cue/bin with chdman."""
        if self.platform != "neocd" or not rom.lower().endswith(".chd") or not shutil.which("chdman"):
            return rom
        with open(rom, "rb") as f:
            head = f.read(16)
        if head[:8] != b"MComprHD" or int.from_bytes(head[12:16], "big") >= 5:
            return rom
        import hashlib
        out = self.config.runtime / "extract" / ("chd-" + hashlib.sha1(rom.encode()).hexdigest()[:16])
        cue = out / (Path(rom).stem + ".cue")
        if not cue.exists():
            out.mkdir(parents=True, exist_ok=True)
            self._p(30, f"Converting {Path(rom).name} (CHD v4) for the Neo Geo CD core")
            subprocess.run(["chdman", "extractcd", "-f", "-i", rom, "-o", str(cue)], check=True, capture_output=True, timeout=1800)
        return str(cue)

    def _from_gme(self, rom: str) -> str:
        """PocketStation: DexDrive .gme = 3904-byte header + 128 KiB card; the core reads the raw card (.min)."""
        if self.platform != "pocketstation" or not rom.lower().endswith(".gme"):
            return rom
        import hashlib
        out = self.config.runtime / "extract" / ("gme-" + hashlib.sha1(rom.encode()).hexdigest()[:16]) / (Path(rom).stem + ".min")
        if not out.exists():
            data = Path(rom).read_bytes()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data[3904:3904 + 131072] if len(data) >= 3904 + 131072 else data[-131072:])
        return str(out)

    def launch_game(self, rom: str) -> dict:
        if self.config is not None:
            rom = self._from_lst_zip(self._from_gme(self._from_old_chd(self._from_7z(rom))))
        argv = self._argv(rom)
        self.examine_unavailable_reason = None
        if HOST_OS == "windows" and getattr(self, "examine", False) and not _examine_driver_ok(argv):
            self.examine_unavailable_reason = (
                "3D draw-call capture is unavailable for this OpenGL RetroArch session. "
                "RenderDoc injection prevents this core from opening its game window; "
                "relaunching with Examine 3D would not fix it. The game remains playable and can be paused."
            )
        if "-L" in argv:
            try:
                n = len(self.install_cheats(argv[argv.index("-L") + 1], rom))
                if n:
                    self._p(76, f"{n} cheat codes available ({self.cheat_source})")
            except Exception:
                pass                                       # cheats are optional; never block a launch
        env = dict(os.environ)
        if HOST_OS == "windows":
            from .gamepads import emulator_environment
            env = emulator_environment(env)
        if HOST_OS == "linux":
            self.display = Display()
            env["DISPLAY"] = self.display.name
            # GPU: Xvfb alone renders on the CPU (Mesa llvmpipe). VirtualGL's EGL back end runs the core's OpenGL on
            # the NVIDIA GPU and hands finished frames to the private Xvfb display (verified: "NVIDIA GB10, GL 4.6").
            if Path(VGLRUN).exists():
                argv = [VGLRUN, "-d", "egl", *argv]
        logs = (self.config.runtime / "logs") if self.config else Path(tempfile.gettempdir())
        logs.mkdir(parents=True, exist_ok=True)
        self.log_path = logs / f"retroarch-{self.addr[1]}.log"
        work = (self.config.runtime / "work") if self.config else None       # cores drop scratch files in cwd
        if work:
            work.mkdir(parents=True, exist_ok=True)
        self.proc = _popen(self, argv, env=env, stdout=open(self.log_path, "wb"), stderr=subprocess.STDOUT, cwd=work)
        self._p(78, "Emulator process started" + (" on the GPU (VirtualGL)" if argv[0] == VGLRUN else "")
                + (" · Examine 3D ready" if _examine_ok(self.proc) else ""))
        for i in range(150):                                   # wait for the command interface to answer
            if i % 5 == 0:
                tail = [ln for ln in self.log_tail(4000).splitlines() if ln.strip()]
                try:
                    self._p(80 + 18 * i / 150, tail[-1][:160] if tail else "Waiting for content to start")
                except Exception:                              # cancelled: don't leave an emulator running
                    self.stop_game()
                    raise
            if self.proc.poll() is not None:
                if self.display:
                    self.display.close()
                raise RuntimeError(f"retroarch exited {self.proc.returncode}: {self.log_tail()}")
            try:
                st = self.query_runtime(timeout=0.3)
                if st.get("state") in ("PLAYING", "PAUSED"):
                    return {"pid": self.proc.pid, "display": self.display and self.display.name, "port": self.addr[1],
                            "local_window": HOST_OS == "windows", "worker_name": __import__("platform").node(),
                            "core": argv[argv.index("-L") + 1], "status": st, "log": str(self.log_path),
                            "renderer": self.renderer(), "examine": _examine_ok(self.proc)}
            except RuntimeError:
                pass
            time.sleep(0.2)
        tail = self.log_tail()
        self.stop_game()
        raise RuntimeError(f"retroarch started but content not running after 30s: {tail}")

    def _p(self, pct, msg):
        cb = getattr(self, "progress", None)
        if cb:
            cb(pct, msg)

    def renderer(self) -> str | None:
        """The GL renderer RetroArch actually got (evidence for GPU vs CPU rendering), from the session log."""
        for line in self.log_tail(200000).splitlines():
            if "[GL] Vendor:" in line or "Renderer:" in line:
                return line.split("]", 1)[-1].strip()[:120]
        return None

    def log_tail(self, n: int = 1500) -> str:
        try:
            return self.log_path.read_text(errors="replace")[-n:]
        except (OSError, AttributeError):
            return ""

    def stop_game(self) -> dict:
        if self.stream:
            self.stream.close()
        try:
            self.cmd("QUIT")
            self.proc and self.proc.wait(5)
        except Exception:
            pass
        _kill_tree(self.proc)
        if self.display:
            self.display.close()
        return {"returncode": self.proc.poll() if self.proc else None}

    def cmd(self, text: str, reply: bool = False, timeout: float = 2.0) -> str | None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            s.sendto(text.encode(), self.addr)
            if not reply:
                return None
            try:
                return s.recvfrom(65536)[0].decode().strip()
            except (TimeoutError, ConnectionResetError):
                raise RuntimeError(f"retroarch did not answer {text.split()[0]} on {self.addr}")

    def query_runtime(self, timeout: float = 2.0) -> dict:
        status = self.cmd("GET_STATUS", reply=True, timeout=timeout)     # "GET_STATUS PLAYING system,game,crc32=..."
        parts = status.split(" ", 2)
        return {"running": bool(self.proc and self.proc.poll() is None), "state": parts[1] if len(parts) > 1 else None,
                "content": parts[2] if len(parts) > 2 else None}

    def pause(self) -> dict:
        if self.query_runtime()["state"] != "PAUSED":
            self.cmd("PAUSE_TOGGLE")
        return self.query_runtime()

    def resume(self) -> dict:
        if self.query_runtime()["state"] == "PAUSED":
            self.cmd("PAUSE_TOGGLE")
        return self.query_runtime()

    def reset(self) -> dict:
        """Reset the emulated console (RetroArch RESET = the core's soft reset / power cycle); unpauses first."""
        self.resume()
        self.cmd("RESET")
        return {"reset": True} | self.query_runtime()

    def rewind(self, seconds: float = 5.0) -> dict:
        """Jump back in time through RetroArch's rewind buffer (one REWIND step per frame; each step = granularity frames)."""
        if not self.rewind_on:
            raise Unsupported(f"rewind is off for {self.platform} (snapshotting would cost frame rate)")
        steps = max(1, round(seconds * 60 / self.granularity))
        for _ in range(steps):
            self.cmd("REWIND")
            time.sleep(1 / 60)
        return {"rewound_s": seconds, "steps": steps}

    def fast_forward(self, on: bool | None = None) -> dict:
        """Toggle fast-forward (4x)."""
        self.cmd("FAST_FORWARD")
        return {"fast_forward": "toggled"}

    def step_frames(self, n: int = 1) -> dict:
        for _ in range(n):
            self.cmd("FRAMEADVANCE")
        return {"stepped": n}

    def _slot(self, slot):
        cur = getattr(self, "slot", 0)
        if slot is not None:                               # the network commands only step slots up/down
            for _ in range(abs(int(slot) - cur)):
                self.cmd("STATE_SLOT_PLUS" if slot > cur else "STATE_SLOT_MINUS")
                time.sleep(0.05)                           # one command per frame: back-to-back steps get dropped
            self.slot = cur = int(slot)
        return cur

    def save_state(self, slot: int | None = None) -> dict:
        slot = self._slot(slot)
        self.cmd("SAVE_STATE")
        return {"slot": slot}

    def load_state(self, slot: int | None = None) -> dict:
        slot = self._slot(slot)
        self.cmd("LOAD_STATE")
        return {"slot": slot}

    def debugger(self):
        from .debug import CPUS, MemoryDebugger
        if (self.platform or "") not in CPUS:
            raise Unsupported(f"no disassembler for {self.platform}")
        return MemoryDebugger(self, CPUS[self.platform])

    def get_frame(self) -> bytes:
        if HOST_OS == "windows":
            return win_grab(self.proc.pid if self.proc else 0)
        return grab_png(self.display.name if self.display else None)

    def stream_session(self) -> MjpegStream:
        if not self.stream:
            self.stream = MjpegStream(self.display.name if self.display else None,
                                      size=(self.display.w, self.display.h) if self.display else None)
        return self.stream

    def _remote_port(self) -> int:
        if not getattr(self, "remote_port", None):
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
                sk.bind(("127.0.0.1", 0))
                self.remote_port = sk.getsockname()[1]
        return self.remote_port

    def remote_input(self, events: list[dict]) -> tuple[int, list[dict]]:
        """Player-1 RetroPad buttons / left stick through RetroArch's network gamepad (focus-independent).
        Returns (sent, events it couldn't express)."""
        import socket
        if not getattr(self, "remote_port", None):
            return 0, events
        sent, rest = 0, []
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
            for ev in events:
                k, down = ev["key"], ev.get("down", True)
                if int(ev.get("player", 1)) != 1 or (k not in RETROPAD_ID and k not in STICK):
                    rest.append(ev)
                    continue
                if k in RETROPAD_ID:                                  # struct remote_message {int port, device, index, id; uint16 state}
                    msg = struct.pack("<iiiiH2x", 0, 1, 0, RETROPAD_ID[k], 1 if down else 0)
                else:
                    axis, val = STICK[k]
                    msg = struct.pack("<iiiiH2x", 0, 5, 0, axis, (val if down else 0) & 0xFFFF)
                if not down and sent:
                    time.sleep(0.05)                                  # down+up in one batch: let the game poll a frame
                sk.sendto(msg, ("127.0.0.1", self.remote_port))
                sent += 1
        return sent, rest

    def send_input(self, events: list[dict]) -> dict:
        """events: [{"key": "<pad button or X keysym>", "down": bool}] delivered to this session's display."""
        if HOST_OS == "windows":
            sent, rest = self.remote_input(events)
            if rest:
                win_send_keys(self.proc.pid if self.proc else 0, rest)
            return {"sent": len(events), "network_gamepad": sent}
        if HOST_OS != "linux" or not self.display:
            raise Unsupported("send_input needs a linux session display")
        args, pressed = [], set()
        for ev in events:
            keys = PAD_KEYS.get(int(ev.get("player", 1)), PAD_KEYS[1])
            key = keys.get(ev["key"], ev["key"])              # pad button name, or a raw X keysym from a keyboard
            down = ev.get("down", True)
            if self.trigger_hotkeys and ev["key"] in ("l2", "r2") and int(ev.get("player", 1)) == 1:
                # L2 = rewind, R2 = fast-forward (held): hotkeys need the hotkey-enable key held with them
                args += (["keydown", "Scroll_Lock", "keydown", key] if down else ["keyup", key, "keyup", "Scroll_Lock"])
                continue
            if not down and key in pressed:
                args += ["sleep", "0.06"]                     # down+up in one batch: games poll per frame and would miss it
            pressed.add(key) if down else None
            args += ["keydown" if down else "keyup", key]
        if args:
            subprocess.run(["xdotool", *args], env={**os.environ, "DISPLAY": self.display.name}, timeout=5)
        return {"sent": len(events)}

    # Native address -> RetroAchievements RAM offset, for cores without a libretro memory map (Flycast, Dolphin):
    # (segment mask, segment value, offset mask): Dreamcast main RAM 0x0C000000 with P1/P2 mirrors 0x8C/0xAC000000
    # (verified with Flycast: rcheevos registers 16MB SYSTEM RAM at $0); GameCube/Wii MEM1 at 0x80000000/0xC0000000.
    RAM_WINDOWS = {"dreamcast": (0x1F000000, 0x0C000000, 0x00FFFFFF), "naomi": (0x1F000000, 0x0C000000, 0x00FFFFFF),
                   "gamecube": (0x3E000000, 0x00000000, 0x01FFFFFF), "wii": (0x3E000000, 0x00000000, 0x01FFFFFF),
                   "n64": (0x1F800000, 0x00000000, 0x007FFFFF)}

    def _ram_offset(self, address: int) -> int:
        w = self.RAM_WINDOWS.get(self.platform or "")
        if w and address > w[2] and (address & w[0]) == w[1]:   # native address -> offset into RAM
            return address & w[2]
        return address                                          # already a RAM offset

    def _read(self, verb: str, address: int, length: int) -> bytes | str:
        out = bytearray()
        step = 16384 if length > 256 else 256                     # 16 KB request = ~49 KB hex reply, under the 64 KB datagram limit
        for off in range(0, length, step):
            n = min(step, length - off)
            r = self.cmd(f"{verb} {address + off:x} {n}", reply=True).split()
            if len(r) < 3 or r[2] == "-1":
                return " ".join(r)
            out += bytes(int(b, 16) for b in r[2:])
        return bytes(out)

    def read_memory(self, address: int, length: int) -> bytes:
        """Core memory map first (native addresses); else the RAM view RetroArch exposes for achievements."""
        r = self._read("READ_CORE_MEMORY", address, length)
        if isinstance(r, bytes):
            return r
        r2 = self._read("READ_CORE_RAM", self._ram_offset(address), length)
        if isinstance(r2, bytes):
            return r2
        raise RuntimeError(f"memory read failed: {r} | {r2}")

    def write_memory(self, address: int, data: bytes) -> dict:
        if len(data) > 512:                                     # RetroArch parses a command from a 2 KB buffer: one
            n, via = 0, None                                    # WRITE_CORE_MEMORY carries at most 674 bytes
            for k in range(0, len(data), 512):
                r = self.write_memory(address + k, data[k:k + 512])
                n, via = n + r["written"], r["via"]
            return {"written": n, "via": via, "chunks": (len(data) + 511) // 512}
        hexs = " ".join(f"{b:02x}" for b in data)
        r = self.cmd(f"WRITE_CORE_MEMORY {address:x} {hexs}", reply=True).split()
        if len(r) >= 3 and r[2] != "-1":
            if int(r[2]) != len(data):
                raise RuntimeError(f"retroarch wrote {r[2]} of {len(data)} bytes at {address:#x}")
            return {"written": int(r[2]), "via": "core_memory_map"}
        self.cmd(f"WRITE_CORE_RAM {self._ram_offset(address):x} {hexs}")    # no reply in RetroArch's protocol
        if self.read_memory(address, len(data)) != data:
            raise RuntimeError(f"memory write not confirmed by read-back ({' '.join(r)})")
        return {"written": len(data), "via": "core_ram", "verified": True}


# --- standalone emulators with built-in debug servers (linux, flatpak) ------------------------------------------

def _free_tcp_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class StandaloneAdapter(Adapter):
    """A standalone emulator on a private Xvfb display: streamed like RetroArch sessions, driven by synthetic keys,
    and debugged through its own debug server (registers, breakpoints, stepping, memory).
    Subclasses give the flatpak id, argv/config, the pad->key map and the debugger."""
    name = "standalone"
    flatpak = ""
    supported = {"launch_game", "stop_game", "pause", "resume", "read_memory", "write_memory", "query_runtime", "get_frame",
                 "send_input", "stream_session", "set_breakpoint", "remove_breakpoint", "save_state", "load_state"}
    keys: dict[str, str] = {}                     # pad button -> X keysym the emulator is configured for
    hotkeys = {"save_state": "shift+F1", "load_state": "F1"}
    screen = (960, 720)
    env: dict[str, str] = {}

    def __init__(self, config: Config, platform: str):
        self.config, self.platform = config, platform
        self.proc = self.display = self.stream = self.dbg = self.log_path = None
        self.port = _free_tcp_port()

    def _p(self, pct, msg):
        cb = getattr(self, "progress", None)
        if cb:
            cb(pct, msg)

    def _argv(self, rom: str) -> list[str]:
        raise NotImplementedError

    def _debugger(self):
        raise NotImplementedError

    def _ensure(self):
        provision.ensure_flatpak(self.flatpak)

    def _unpacked(self, rom: str) -> str:
        """Emulators built without archive support get the largest file of a .zip extracted to the local cache."""
        if not rom.lower().endswith(".zip"):
            return rom
        import zipfile
        out = self.config.runtime / "extract" / Path(rom).stem
        with zipfile.ZipFile(rom) as z:
            m = max(z.infolist(), key=lambda i: i.file_size)
            dst = out / Path(m.filename).name
            if not dst.exists() or dst.stat().st_size != m.file_size:
                out.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(z.read(m))
        return str(dst)

    def launch_game(self, rom: str) -> dict:
        if HOST_OS != "linux":
            raise ToolUnavailable(f"{self.name} sessions run on the linux node")
        self._p(10, f"Checking {self.name} (installs on first use)")
        self._ensure()
        self.display = Display(*self.screen)
        argv = self._argv(rom)
        logs = self.config.runtime / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        self.log_path = logs / f"{self.name}-{self.port}.log"
        env = {**os.environ, "DISPLAY": self.display.name, "QT_QPA_PLATFORM": "xcb", **self.env}
        self.proc = subprocess.Popen(argv, env=env, stdout=open(self.log_path, "wb"), stderr=subprocess.STDOUT)
        self._p(80, f"{self.name} started; attaching the debugger")
        try:
            self.dbg = self._debugger()
        except Exception as e:
            if self.proc.poll() is not None:
                self.display.close()
                raise RuntimeError(f"{self.name} exited {self.proc.returncode}: {self.log_tail()}")
            self.dbg = None
            self._p(95, f"running without debugger: {e}")
        return {"pid": self.proc.pid, "display": self.display.name, "debug_port": self.port, "debugger": bool(self.dbg),
                "worker_name": __import__("platform").node(), "emulator": self.name, "log": str(self.log_path)}

    def log_tail(self, n: int = 1500) -> str:
        try:
            return self.log_path.read_text(errors="replace")[-n:]
        except (OSError, AttributeError):
            return ""

    def stop_game(self) -> dict:
        if self.stream:
            self.stream.close()
        if self.dbg:
            self.dbg.close()
        _kill_tree(self.proc)                   # flatpak run --die-with-parent takes the sandbox down with it
        if self.display:
            self.display.close()
        return {"returncode": self.proc.poll() if self.proc else None}

    def query_runtime(self) -> dict:
        d = {"running": bool(self.proc and self.proc.poll() is None), "emulator": self.name}
        if self.dbg:
            try:
                d["state"] = "PAUSED" if self.dbg.info()["halted"] else "PLAYING"
            except Exception as e:
                d["debugger_error"] = str(e)
        return d

    def debugger(self):
        if not self.dbg:
            raise Unsupported(f"{self.name}: debugger not attached")
        return self.dbg

    def pause(self) -> dict:
        return self.debugger().halt()

    def resume(self) -> dict:
        return self.debugger().resume()

    def read_memory(self, address: int, length: int) -> bytes:
        return self.debugger().read(address, length)

    def write_memory(self, address: int, data: bytes) -> dict:
        r = self.debugger().write(address, data)
        if self.dbg.read(address, len(data)) != data:
            raise RuntimeError("memory write not confirmed by read-back")
        return r | {"verified": True}

    def set_breakpoint(self, address: int, kind: str = "exec", length: int = 4) -> dict:
        return self.debugger().set_breakpoint(address, kind, length)

    def remove_breakpoint(self, address: int, kind: str = "exec", length: int = 4) -> dict:
        return self.debugger().remove_breakpoint(address, kind, length)

    def _xdo(self, *args):
        subprocess.run(["xdotool", *args], env={**os.environ, "DISPLAY": self.display.name}, timeout=5)

    def save_state(self) -> dict:
        self._xdo("key", self.hotkeys["save_state"])
        return {"slot": 1}

    def load_state(self) -> dict:
        self._xdo("key", self.hotkeys["load_state"])
        return {"slot": 1}

    def get_frame(self) -> bytes:
        return grab_png(self.display.name)

    def stream_session(self) -> MjpegStream:
        if not self.stream:
            self.stream = MjpegStream(self.display.name, size=(self.display.w, self.display.h))
        return self.stream

    def send_input(self, events: list[dict]) -> dict:
        args, pressed = [], set()
        for ev in events:
            if int(ev.get("player", 1)) != 1:
                continue                         # ponytail: player 1 only for standalone emulators
            key = self.keys.get(ev["key"], ev["key"])
            down = ev.get("down", True)
            if not down and key in pressed:
                args += ["sleep", "0.06"]
            pressed.add(key) if down else None
            args += ["keydown" if down else "keyup", key]
        if args:
            self._xdo(*args)
        return {"sent": len(events)}


class DolphinAdapter(StandaloneAdapter):
    """GameCube / Wii on standalone Dolphin (flatpak), Vulkan on the GPU, GDB stub for CPU debugging."""
    name = "dolphin"
    flatpak = "org.DolphinEmu.dolphin-emu"
    screen = (640, 480)                          # GameCube output size; Dolphin's window opens at exactly this
    # gBox pad -> keys; GCPadNew.ini binds the same keys to the GameCube pad (Dolphin names letter keys in upper case)
    keys = {"up": "Up", "down": "Down", "left": "Left", "right": "Right", "a": "x", "b": "z", "x": "s", "y": "a",
            "l": "q", "r": "w", "l2": "q", "r2": "w", "select": "e", "z": "e", "start": "Return",
            "cup": "i", "cdown": "k", "cleft": "j", "cright": "l", "dup": "t", "ddown": "g", "dleft": "f", "dright": "h"}
    PAD_INI = """[GCPad1]
Device = XInput2/0/Virtual core pointer
Buttons/A = `X`
Buttons/B = `Z`
Buttons/X = `S`
Buttons/Y = `A`
Buttons/Z = `E`
Buttons/Start = `Return`
Main Stick/Up = `Up`
Main Stick/Down = `Down`
Main Stick/Left = `Left`
Main Stick/Right = `Right`
C-Stick/Up = `I`
C-Stick/Down = `K`
C-Stick/Left = `J`
C-Stick/Right = `L`
Triggers/L = `Q`
Triggers/R = `W`
Triggers/L-Analog = `Q`
Triggers/R-Analog = `W`
D-Pad/Up = `T`
D-Pad/Down = `G`
D-Pad/Left = `F`
D-Pad/Right = `H`
"""

    # ---- Gecko codes run by Dolphin itself (incl. C2 ASM hooks gBox's memory-write engine can't do) ----
    @staticmethod
    def _disc_id(rom: str) -> str | None:
        """Disc id (e.g. GMSE01) from a plain image or a GCZ (Dolphin's zlib format: first block holds the disc header).
        ponytail: rvz/wbfs not read; those games simply get no Gecko list."""
        import struct
        import zlib
        low = rom.lower()
        with open(rom, "rb") as f:
            if low.endswith((".iso", ".gcm")):
                head = f.read(6)
            elif low.endswith(".gcz"):
                magic, _sub, _csize, _dsize, _bsize, nblocks = struct.unpack("<IIQQII", f.read(32))
                if magic != 0xB10BC001:
                    return None
                p0, p1 = struct.unpack("<QQ", f.read(16))
                base = 32 + 12 * nblocks
                f.seek(base + (p0 & ~(1 << 63)))
                blob = f.read(((p1 & ~(1 << 63)) - (p0 & ~(1 << 63))) if nblocks > 1 else 0x8000)
                head = blob[:6] if p0 >> 63 else zlib.decompressobj().decompress(blob)[:6]
            else:
                return None
        gid = head.decode("ascii", "replace")
        return gid if gid.isalnum() else None

    def _gecko_setup(self, user: Path, rom: str):
        from . import cheats
        self.cheats, self.gecko_id = [], self._disc_id(rom)
        if not self.gecko_id:
            return
        try:
            codes = cheats.gecko_codes(self.gecko_id, self.config.data_dir / "cheatdb" / "gecko")
        except Exception:
            codes = []
        on_f = user / "GameSettings" / f"{self.gecko_id}.gbox-enabled.json"
        on = set(json.loads(on_f.read_text())) if on_f.exists() else set()
        self.cheats = [{"desc": c["desc"], "code": "\n".join(c["lines"]), "lines": c["lines"], "enable": c["desc"] in on} for c in codes]
        self._gecko_write(user)

    def _gecko_write(self, user: Path):
        gs = user / "GameSettings"
        gs.mkdir(parents=True, exist_ok=True)
        body = ["[Gecko]"] + [ln for c in self.cheats for ln in (f"${c['desc']}", *c["lines"])]
        body += ["[Gecko_Enabled]"] + [f"${c['desc']}" for c in self.cheats if c["enable"]]
        (gs / f"{self.gecko_id}.ini").write_text("\n".join(body) + "\n", encoding="utf-8")
        (gs / f"{self.gecko_id}.gbox-enabled.json").write_text(json.dumps([c["desc"] for c in self.cheats if c["enable"]]))

    def cheat_set(self, index: int, on: bool) -> dict:
        """Dolphin applies Gecko codes when the game boots: the choice is saved now and takes effect on the next start."""
        if not 0 <= index < len(self.cheats):
            raise ValueError(f"no cheat #{index} (this game has {len(self.cheats)})")
        self.cheats[index]["enable"] = on
        self._gecko_write(self.config.runtime / "dolphin-user")
        return {"index": index, "enabled": on, "desc": self.cheats[index]["desc"], "restart_needed": True,
                "note": "Dolphin runs this Gecko code from the next game start (load state / restart the game)"}

    def _argv(self, rom: str) -> list[str]:
        user = self.config.runtime / "dolphin-user"            # shared: memory cards, shader cache, settings
        (user / "Config").mkdir(parents=True, exist_ok=True)
        (user / "Config" / "GCPadNew.ini").write_text(self.PAD_INI)
        self._gecko_setup(user, rom)
        opts = {"Dolphin.General.GDBPort": self.port, "Dolphin.Core.GFXBackend": "Vulkan", "Dolphin.Core.EnableCheats": "True",
                "Dolphin.Display.Fullscreen": "True", "Dolphin.Interface.ConfirmStop": "False",
                "Dolphin.Analytics.PermissionAsked": "True", "Dolphin.Analytics.Enabled": "False",
                "Dolphin.Input.BackgroundInput": "True", "Dolphin.Core.SIDevice0": "6",   # 6 = standard controller
                # JIT emits breakpoint/watchpoint checks only in debug mode (verified: breakpoints fire, steps work;
                # ponytail: JIT steps can cover a few instructions; Core.CPUCore=0 (interpreter) steps exactly but is slow)
                "Dolphin.Interface.DebugModeEnabled": "True"}
        return ["flatpak", "run", "--die-with-parent", f"--filesystem={user}", self.flatpak, "-b", "-u", str(user),
                *[a for k, v in opts.items() for a in ("-C", f"{k}={v}")], "-e", rom]

    def _debugger(self):
        from .debug import GdbDebugger
        return GdbDebugger("127.0.0.1", self.port, "ppc", connect_timeout=60)


class DolphinWinAdapter(DolphinAdapter):
    """GameCube / Wii on standalone Dolphin on Windows (portable copy in the runtime folder, same release as the Spark's
    flatpak so save states move between them). Docked in the app like RetroArch; the operator's Xbox pad drives the
    GameCube pad; memory + breakpoints through Dolphin's GDB stub, exactly like on the Spark."""
    name = "dolphin"
    supported = (DolphinAdapter.supported - {"stream_session"}) | {"local_window"}   # native window, frames via get_frame
    # XInput pad (positional, like RetroArch's autoconfig) with the keyboard keys gBox sends as an alternative
    PAD_INI_WIN = """[GCPad1]
Device = XInput/0/Gamepad
Buttons/A = `Button A` | `DInput/0/Keyboard Mouse:X`
Buttons/B = `Button B` | `DInput/0/Keyboard Mouse:Z`
Buttons/X = `Button X` | `DInput/0/Keyboard Mouse:S`
Buttons/Y = `Button Y` | `DInput/0/Keyboard Mouse:A`
Buttons/Z = `Shoulder R` | `DInput/0/Keyboard Mouse:E`
Buttons/Start = `Start` | `DInput/0/Keyboard Mouse:RETURN`
Main Stick/Up = `Left Y+` | `DInput/0/Keyboard Mouse:UP`
Main Stick/Down = `Left Y-` | `DInput/0/Keyboard Mouse:DOWN`
Main Stick/Left = `Left X-` | `DInput/0/Keyboard Mouse:LEFT`
Main Stick/Right = `Left X+` | `DInput/0/Keyboard Mouse:RIGHT`
C-Stick/Up = `Right Y+` | `DInput/0/Keyboard Mouse:K`
C-Stick/Down = `Right Y-` | `DInput/0/Keyboard Mouse:I`
C-Stick/Left = `Right X-` | `DInput/0/Keyboard Mouse:J`
C-Stick/Right = `Right X+` | `DInput/0/Keyboard Mouse:L`
Triggers/L = `Trigger L` | `DInput/0/Keyboard Mouse:Q`
Triggers/R = `Trigger R` | `DInput/0/Keyboard Mouse:W`
Triggers/L-Analog = `Trigger L`
Triggers/R-Analog = `Trigger R`
D-Pad/Up = `Pad N`
D-Pad/Down = `Pad S`
D-Pad/Left = `Pad W`
D-Pad/Right = `Pad E`
"""

    def _exe(self) -> Path:
        for c in (self.config.runtime / "dolphin" / "Dolphin-x64" / "Dolphin.exe", Path("D:/gBox/runtime/dolphin/Dolphin-x64/Dolphin.exe")):
            if c.is_file():
                named = c.with_name("gBox Dolphin.exe")              # so Task Manager says which games are gBox's
                if not named.exists() or named.stat().st_size != c.stat().st_size:
                    shutil.copy2(c, named)
                return named
        raise ToolUnavailable("standalone Dolphin isn't installed on this PC (runtime/dolphin/Dolphin-x64/Dolphin.exe)")

    def _argv(self, rom: str) -> list[str]:
        exe = self._exe()
        user = exe.parent / "User"                                  # portable mode (portable.txt next to the exe)
        (exe.parent / "portable.txt").touch()
        (user / "Config").mkdir(parents=True, exist_ok=True)
        (user / "Config" / "GCPadNew.ini").write_text(self.PAD_INI_WIN)
        self._gecko_setup(user, rom)
        opts = {"Dolphin.General.GDBPort": self.port, "Dolphin.Core.GFXBackend": "D3D12", "Dolphin.Core.EnableCheats": "True",
                "Dolphin.Display.Fullscreen": "False", "Dolphin.Display.RenderToMain": "False",   # batch mode hides the main window
                "Dolphin.Interface.ConfirmStop": "False", "Dolphin.Interface.ShowToolbar": "False", "Dolphin.Interface.ShowStatusbar": "False",
                "Dolphin.Analytics.PermissionAsked": "True", "Dolphin.Analytics.Enabled": "False",
                "Dolphin.Input.BackgroundInput": "True", "Dolphin.Core.SIDevice0": "6",
                "Dolphin.AutoUpdate.UpdateTrack": "",
                # play speed: the debugging UI makes the JIT check breakpoints on every block (the GDB stub's memory
                # reads/writes don't need it); async ubershaders = no shader-compile stutter on the RTX
                "Dolphin.Interface.DebugModeEnabled": "False", "Dolphin.General.EnableDebugging": "False",
                "Dolphin.Core.CPUThread": "True", "Dolphin.Core.Fastmem": "True", "Dolphin.Core.SyncGPU": "False",
                "GFX.Settings.ShaderCompilationMode": "2", "GFX.Settings.WaitForShadersBeforeStarting": "True",
                "GFX.Hardware.VSync": "True",                    # off tore the picture (rolling-shutter look); the RTX has headroom
                # a raw memory card file keeps its serial between boots; the GCI-folder card's changes, and games that
                # bind saves to the card (RE4) then call every save "corrupted" on the next boot
                "Dolphin.Core.SlotA": "1", "Dolphin.Core.MemcardAPath": str(user / "GC" / "MemoryCardA.USA.raw")}
        return [str(exe), "-b", "-u", str(user), *[a for k, v in opts.items() for a in ("-C", f"{k}={v}")], "-e", rom]

    def cheat_set(self, index: int, on: bool) -> dict:
        if not 0 <= index < len(self.cheats):
            raise ValueError(f"no cheat #{index} (this game has {len(self.cheats)})")
        self.cheats[index]["enable"] = on
        self._gecko_write(self._exe().parent / "User")
        return {"index": index, "enabled": on, "desc": self.cheats[index]["desc"], "restart_needed": True}

    def launch_game(self, rom: str) -> dict:
        self._p(10, "Starting Dolphin")
        argv = self._argv(rom)
        logs = self.config.runtime / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        self.log_path = logs / f"dolphin-win-{self.port}.log"
        si = subprocess.STARTUPINFO()                                # minimized, no focus: no boot window on screen;
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW                # the app docks (and restores) the game window
        si.wShowWindow = 7                                           # SW_SHOWMINNOACTIVE
        self.proc = _popen(self, argv, stdout=open(self.log_path, "wb"), stderr=subprocess.STDOUT, cwd=str(Path(argv[0]).parent),
                           startupinfo=si)
        self._p(70, "Dolphin started; releasing the boot hold")
        try:
            gdb = self._debugger()                                 # with a GDB port set, Dolphin waits for a client to boot
            try:
                gdb.sock.sendall(b"$D#44")                          # detach: a client left attached costs ~70x speed here
                time.sleep(0.2)
                gdb.sock.close()
            except OSError:
                pass
            from .debug import DolphinProcMem
            self.dbg = DolphinProcMem(self.proc.pid)                # memory mods: straight into Dolphin's RAM mapping
        except Exception as e:
            if self.proc.poll() is not None:
                raise RuntimeError(f"Dolphin exited {self.proc.returncode}: {self.log_tail()}")
            self.dbg = None
            self._p(95, f"running without memory access (no memory mods): {e}")
        return {"pid": self.proc.pid, "local_window": True, "debug_port": self.port, "debugger": bool(self.dbg),
                "worker_name": __import__("platform").node(), "emulator": "dolphin (Windows)", "log": str(self.log_path),
                "examine": _examine_ok(self.proc)}

    def stop_game(self) -> dict:
        if self.paused_tids:
            self.resume()
        if self.dbg:
            try:
                self.dbg.close()
            except Exception:
                pass
        _kill_tree(self.proc)
        return {"returncode": self.proc.poll() if self.proc else None}

    def get_frame(self) -> bytes:
        return win_grab(self.proc.pid)

    paused_tids: list | None = None

    def pause(self) -> dict:
        """Dolphin has no pause command gBox can send; its emulation threads are suspended instead (window stays live)."""
        if not self.paused_tids:
            self.paused_tids = win_suspend_emulation(self.proc.pid)
        return {"state": "PAUSED", "threads": len(self.paused_tids)}

    def resume(self) -> dict:
        n = win_resume_threads(self.paused_tids or [])
        self.paused_tids = None
        return {"state": "PLAYING", "threads": n}

    def query_runtime(self) -> dict:
        return {"running": bool(self.proc and self.proc.poll() is None), "emulator": self.name,
                "state": "PAUSED" if self.paused_tids else "PLAYING"}

    def send_input(self, events: list[dict]) -> dict:
        # win_send_keys already maps standard pad names to keyboard keys. Translating
        # them here as well makes A -> x -> s (Dolphin X), so menus ignore A.
        keymap = {"z": "e", "cup": "k", "cdown": "i", "cleft": "j", "cright": "l"}
        return win_send_keys(self.proc.pid, [{**e, "key": keymap.get(e["key"], e["key"])} for e in events])

    def save_state(self, slot: int | None = None) -> dict:
        win_send_keys(self.proc.pid, [{"key": "Shift_R", "down": True}, {"key": "F1", "down": True},
                                      {"key": "F1", "down": False}, {"key": "Shift_R", "down": False}])
        return {"slot": 1}

    def load_state(self, slot: int | None = None) -> dict:
        win_send_keys(self.proc.pid, [{"key": "F1", "down": True}, {"key": "F1", "down": False}])
        return {"slot": 1}


class MgbaAdapter(StandaloneAdapter):
    """Game Boy Advance on standalone mGBA (apt) with its GDB stub: ARM7 registers (named, from target.xml), Thumb-aware
    disassembly, breakpoints, watchpoints, stepping. ponytail: mGBA's stub port is fixed (2345) -> one debug GBA session at a time."""
    name = "mgba"
    screen = (720, 480)
    # the service has no audio session; mGBA paces itself on audio and crawls (0.4 fps) without a device
    env = {"SDL_AUDIODRIVER": "dummy"}
    keys = {"up": "Up", "down": "Down", "left": "Left", "right": "Right", "a": "x", "b": "z", "l": "a", "r": "s",
            "start": "Return", "select": "BackSpace"}               # mGBA's default keyboard map

    def __init__(self, config: Config, platform: str):
        super().__init__(config, platform)
        self.port = 2345

    def _ensure(self):
        if not shutil.which("mgba-qt"):
            provision.apt_packages(["mgba-qt"])
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", self.port)) == 0:
                raise ToolUnavailable("another mGBA debug session is running (its GDB port 2345 is fixed); stop it first")

    def _argv(self, rom: str) -> list[str]:
        return ["mgba-qt", "-g", "-f", self._unpacked(rom)]

    def _debugger(self):
        from .debug import GdbDebugger
        time.sleep(3)          # mGBA opens its GDB port before the ROM is loaded; a 'continue' sent that early is lost
        return GdbDebugger("127.0.0.1", self.port, "arm", connect_timeout=30)


class DuckStationAdapter(StandaloneAdapter):
    """PlayStation on standalone DuckStation (flatpak) with its GDB server: R3000A registers, breakpoints, stepping.
    DuckStation reads one fixed settings.ini, so it's patched in place before each launch (ponytail: concurrent launches race)."""
    name = "duckstation"
    flatpak = "org.duckstation.DuckStation"
    screen = (640, 480)
    keys = {"up": "Up", "down": "Down", "left": "Left", "right": "Right", "a": "x", "b": "z", "x": "s", "y": "a",
            "l": "q", "r": "w", "l2": "e", "r2": "r", "start": "Return", "select": "BackSpace"}
    SETTINGS = Path.home() / ".var/app/org.duckstation.DuckStation/config/duckstation/settings.ini"

    def _settings(self):
        import configparser
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        cp.optionxform = str
        cp.read(self.SETTINGS)
        if not cp.has_option("Main", "SettingsVersion"):
            cp.read_dict({"Main": {"SettingsVersion": "3"}})   # without it DuckStation discards the file
        pad = {"Type": "AnalogController", "Up": "Keyboard/Up", "Down": "Keyboard/Down", "Left": "Keyboard/Left",
               "Right": "Keyboard/Right", "Cross": "Keyboard/X", "Circle": "Keyboard/Z", "Square": "Keyboard/S",
               "Triangle": "Keyboard/A", "L1": "Keyboard/Q", "R1": "Keyboard/W", "L2": "Keyboard/E", "R2": "Keyboard/R",
               "Start": "Keyboard/Return", "Select": "Keyboard/Backspace"}
        cp.read_dict({"Main": {"SetupWizardIncomplete": "false", "ConfirmPowerOff": "false", "StartFullscreen": "true",
                               "PauseOnFocusLoss": "false"},
                      "AutoUpdater": {"CheckAtStartup": "false"},
                      "BIOS": {"SearchDirectory": self.config.retroarch_bios.get("linux", "")},
                      "Debug": {"EnableGDBServer": "true", "GDBServerPort": str(self.port)}, "Pad1": pad})
        self.SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        with open(self.SETTINGS, "w") as f:
            cp.write(f)

    def _argv(self, rom: str) -> list[str]:
        self._settings()
        dirs = {str(Path(rom).parent), self.config.retroarch_bios.get("linux", "")} - {""}
        return ["dbus-run-session", "--", "flatpak", "run", "--die-with-parent", *[f"--filesystem={d}:ro" for d in dirs],
                self.flatpak, "-batch", "-fullscreen", "--", rom]

    def _debugger(self):
        from .debug import GdbDebugger
        return GdbDebugger("127.0.0.1", self.port, "mips_le", connect_timeout=60)


class MameAdapter(StandaloneAdapter):
    """Arcade on standalone MAME (apt) with its gdbstub debugger: registers/breakpoints/stepping for the CPUs MAME's
    gdbstub supports (68000 family, Z80, x86, ARM, PPC, MIPS, SH...). Register layout + CPU come from MAME's target.xml.
    ponytail: the NAS romset is MAME 0.228 and apt MAME is newer, so a few sets may not boot here."""
    name = "mame"
    screen = (800, 600)
    keys = {"up": "Up", "down": "Down", "left": "Left", "right": "Right", "a": "Control_L", "b": "Alt_L", "x": "space",
            "y": "Shift_L", "l": "z", "r": "x", "l2": "c", "r2": "v", "start": "1", "select": "5"}   # MAME defaults (5 = coin)

    def _ensure(self):
        if not shutil.which("mame"):
            provision.apt_packages(["mame"])

    def _argv(self, rom: str) -> list[str]:
        home = self.config.runtime / "mame"
        for d in ("cfg", "nvram", "sta"):
            (home / d).mkdir(parents=True, exist_ok=True)
        p = Path(rom)
        return ["mame", p.stem, "-rompath", str(p.parent), "-debug", "-debugger", "gdbstub", "-debugger_port", str(self.port),
                "-window", "-nomaximize", "-resolution", f"{self.screen[0]}x{self.screen[1]}", "-skip_gameinfo",
                "-sound", "none", "-homepath", str(home), "-cfg_directory", str(home / "cfg"),
                "-nvram_directory", str(home / "nvram"), "-state_directory", str(home / "sta")]

    def _debugger(self):
        from .debug import GdbDebugger
        return GdbDebugger("127.0.0.1", self.port, "m68k", connect_timeout=60)


# platforms whose "debug" launch uses a standalone emulator with a full debug server
DEBUG_ADAPTERS = {"gamecube": DolphinAdapter, "wii": DolphinAdapter, "gba": MgbaAdapter, "psx": DuckStationAdapter, "arcade": MameAdapter}


class YuzuAdapter(Adapter):
    """Launch the operator's portable Yuzu and Switch ROM directly on the Windows worker."""
    name = "yuzu"
    supported = {"launch_game", "stop_game", "query_runtime", "get_frame", "pause", "resume"}

    def __init__(self, config: Config):
        self.config = config
        self.proc = None
        self.bridge_proc = None
        self.paused_tids = []
        self.examine_unavailable_reason = "3D draw-call capture is not integrated with the Yuzu window yet."

    def launch_game(self, rom: str) -> dict:
        exe = self.config.library("hyperspin").root() / "emulators" / "yuzu" / "yuzu.exe"
        if HOST_OS != "windows" or not exe.is_file():
            raise ToolUnavailable(f"portable Yuzu is unavailable on this Windows worker: {exe}")
        from . import gamepads
        guid = gamepads.sdl2_xbox_guid(exe.parent / "SDL2.dll")
        controller_config = exe.parent / "user" / "config" / "qt-config.ini"
        bridge = bool(guid and controller_config.is_file())
        if controller_config.is_file():
            gamepads.enable_yuzu_mouse_touch(controller_config)
        if bridge:
            gamepads.bind_yuzu_xinput_bridge(controller_config)
        self.proc = subprocess.Popen([str(exe), "-g", rom], cwd=exe.parent, startupinfo=hidden_start(),
                                     env=gamepads.emulator_environment(os.environ))
        keep_offscreen(self.proc.pid)
        for _ in range(60):
            if self.proc.poll() is not None:
                raise RuntimeError(f"Yuzu exited before opening the game (code {self.proc.returncode})")
            if _pid_window(self.proc.pid):
                break
            time.sleep(1)
        else:
            self.stop_game()
            raise RuntimeError("Yuzu did not open a game window within 60 seconds")
        if bridge:
            self.bridge_proc = subprocess.Popen([sys.executable, "-u", "-P", "-m", "gbox.yuzu_input", str(self.proc.pid)],
                                                stdin=subprocess.PIPE, startupinfo=hidden_start())
        return {"pid": self.proc.pid, "rom": rom, "local_window": True, "controller_guid": guid,
                "controller_mode": "xinput_keyboard_bridge" if bridge else "sdl",
                "worker_name": __import__("platform").node(), "emulator": "yuzu"}

    def stop_game(self) -> dict:
        if self.paused_tids:
            self.resume()
        if self.bridge_proc and self.bridge_proc.poll() is None:
            try:
                self.bridge_proc.stdin.write(b"stop\n")
                self.bridge_proc.stdin.flush()
                self.bridge_proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                _kill_tree(self.bridge_proc)
        self.bridge_proc = None
        _kill_tree(self.proc)
        return {"returncode": self.proc.poll() if self.proc else None}

    def query_runtime(self) -> dict:
        return {"running": bool(self.proc and self.proc.poll() is None), "paused": bool(self.paused_tids)}

    def get_frame(self) -> bytes:
        return win_grab(self.proc.pid)

    def pause(self) -> dict:
        if not self.paused_tids:
            self.paused_tids = win_suspend_emulation(self.proc.pid)
        return {"paused": bool(self.paused_tids)}

    def resume(self) -> dict:
        if self.paused_tids:
            win_resume_threads(self.paused_tids)
            self.paused_tids = []
        return {"paused": False}


class RocketLauncherAdapter(Adapter):
    """Windows node: launch any HyperSpin game through the drive's own RocketLauncher + bundled emulators."""
    name = "rocketlauncher"
    supported = {"launch_game", "stop_game", "query_runtime", "get_frame"}     # native window; see RPCS3Adapter

    def __init__(self, root: Path):
        self.root, self.proc, self.stream = Path(root), None, None

    def launch_game(self, emulator: str, name: str) -> dict:
        exe = self.root / "RocketLauncher" / "RocketLauncher.exe"
        if HOST_OS != "windows" or not exe.exists():
            raise ToolUnavailable(f"RocketLauncher needs a Windows node with {exe}")
        self.proc = subprocess.Popen([str(exe), "-s", emulator, "-r", name, "-p", "AttractMode"], cwd=exe.parent)
        return {"pid": self.proc.pid, "emulator": emulator, "rom": name}

    def stop_game(self) -> dict:
        if self.stream:
            self.stream.close()
        _kill_tree(self.proc)
        return {"returncode": self.proc.poll() if self.proc else None}

    def query_runtime(self) -> dict:
        return {"running": bool(self.proc and self.proc.poll() is None)}

    def get_frame(self) -> bytes:
        return grab_png(None)

    def stream_session(self) -> MjpegStream:
        self.stream = self.stream or MjpegStream(None)
        return self.stream


RPCS3_XINPUT = """Player 1 Input:
  Handler: XInput
  Device: "XInput Pad #1"
  Config:
    Left Stick Left: LS X-
    Left Stick Down: LS Y-
    Left Stick Right: LS X+
    Left Stick Up: LS Y+
    Right Stick Left: RS X-
    Right Stick Down: RS Y-
    Right Stick Right: RS X+
    Right Stick Up: RS Y+
    Start: Start
    Select: Back
    PS Button: Guide
    Square: X
    Cross: A
    Circle: B
    Triangle: Y
    Left: Left
    Down: Down
    Right: Right
    Up: Up
    R1: RB
    R2: RT
    R3: RS
    L1: LB
    L2: LT
    L3: LS
    Enable Vibration Motor Large: true
    Enable Vibration Motor Small: true
"""


class RPCS3Adapter(Adapter):
    """Windows node: PS3 games (extracted disc folders) in RPCS3. Guest memory is read/written straight from the
    emulator process (PS3 addresses map 1:1 onto a 4 GiB-aligned host reservation); pause/resume freeze the whole
    emulator, which is how a mechanic can be held mid-flight while something else decides its outcome."""
    name = "rpcs3"
    # no stream_session: the game plays in its own native window, and a 60 fps gdigrab desktop capture next to a
    # GPU-rendered game made it stutter (same reason RetroArch native windows aren't streamed)
    supported = {"launch_game", "stop_game", "query_runtime", "get_frame", "read_memory", "write_memory", "pause", "resume",
                 "save_state", "load_state"}

    def __init__(self, config: Config):
        self.config, self.proc, self.stream, self.base, self.paused = config, None, None, None, False

    def launch_game(self, rom: str) -> dict:
        prog = getattr(self, "progress", None)
        provision.ensure_rpcs3(self.config, prog)
        home = provision.rpcs3_free_home(self.config)      # a second PS3 game gets its own RPCS3 folder (one per lock)
        pad = home / "config" / "input_configs" / "global" / "Default.yml"
        if not pad.exists():                               # fresh install has no pad: Xbox controller as player 1
            pad.parent.mkdir(parents=True, exist_ok=True)
            pad.write_text(RPCS3_XINPUT, encoding="utf-8")
        if getattr(self, "serial", None):                  # per-game graphics settings (Sessions -> Graphics)
            from . import graphics
            cc = home / "config" / "custom_configs" / f"config_{self.serial}.yml"
            cc.parent.mkdir(parents=True, exist_ok=True)
            cc.write_text(graphics.rpcs3_yaml(graphics.get(self.config, getattr(self, "game_id", None))), encoding="utf-8")
        # F2 = RPCS3's own "save state and continue" (works in place). Its restart-from-state shortcut crashes in --no-gui
        # mode, so it is moved off F4; gBox owns F4 and relaunches RPCS3 straight into the newest state (load_state).
        gui = home / "GuiConfigs" / "CurrentSettings.ini"
        ini = gui.read_text(encoding="utf-8") if gui.exists() else ""
        if "game_window_savestate=" not in ini:
            ini = ini.rstrip("\n") + "\n\n[Shortcuts]\ngame_window_savestate=F2\ngame_window_restart=Ctrl+Alt+Shift+F11\n"
        ini = ini.replace("game_window_restart=F4", "game_window_restart=Ctrl+Alt+Shift+F11")
        gui.parent.mkdir(parents=True, exist_ok=True)
        gui.write_text(ini, encoding="utf-8")
        self.home = home
        __import__("gbox.graphics", fromlist=["x"]).prefer_gpu(home / "rpcs3.exe")   # the discrete GPU
        self.proc = subprocess.Popen([str(home / "rpcs3.exe"), "--no-gui", rom], cwd=home, startupinfo=hidden_start())
        keep_offscreen(self.proc.pid)
        return {"pid": self.proc.pid, "eboot": rom, "local_window": True, "worker_name": __import__("platform").node()}

    def stop_game(self) -> dict:
        if self.stream:
            self.stream.close()
        _kill_tree(self.proc)
        return {"returncode": self.proc.poll() if self.proc else None}

    def query_runtime(self) -> dict:
        return {"running": bool(self.proc and self.proc.poll() is None), "paused": self.paused, "guest_base": self.base and hex(self.base)}

    def get_frame(self) -> bytes:
        return grab_png(None)

    def stream_session(self) -> MjpegStream:
        self.stream = self.stream or MjpegStream(None)
        return self.stream

    # --- process memory ---
    def _h(self):
        import ctypes
        if not getattr(self, "_handle", None):
            self._handle = ctypes.windll.kernel32.OpenProcess(0x0010 | 0x0020 | 0x0008 | 0x0400 | 0x0800, False, self.proc.pid)
        return self._handle

    def _rpm(self, host: int, n: int) -> bytes | None:
        import ctypes
        buf, got = ctypes.create_string_buffer(n), ctypes.c_size_t()
        ok = ctypes.windll.kernel32.ReadProcessMemory(self._h(), ctypes.c_void_p(host), buf, n, ctypes.byref(got))
        return buf.raw[:got.value] if ok else None

    def _base(self) -> int:
        # ponytail: probe the usual RPCS3 reservations and take the first where the game's code at 0x10000 is mapped;
        # a full VirtualQueryEx walk if a future build moves it
        if self.base is None:
            for b in (0x300000000, 0x200000000, 0x100000000, 0x10000000000):
                d = self._rpm(b + 0x10000, 16)
                if d and any(d):
                    self.base = b
                    break
            else:
                raise RuntimeError("PS3 guest memory not found in the RPCS3 process (game still booting?)")
        return self.base

    def read_memory(self, address: int, length: int) -> bytes:
        d = self._rpm(self._base() + address, length)
        if d is None:
            raise ValueError(f"PS3 address {address:#x} is not mapped")
        return d

    def regions(self) -> list[tuple[int, int]]:
        """Committed guest ranges [(address, size)] (VirtualQueryEx over the 4 GiB guest window)."""
        import ctypes
        import ctypes.wintypes as w

        class MBI(ctypes.Structure):
            _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p), ("AllocationProtect", w.DWORD),
                        ("PartitionId", w.WORD), ("RegionSize", ctypes.c_size_t), ("State", w.DWORD), ("Protect", w.DWORD), ("Type", w.DWORD)]
        base, out, a, m = self._base(), [], self._base(), MBI()
        while a < base + (1 << 32) and ctypes.windll.kernel32.VirtualQueryEx(self._h(), ctypes.c_void_p(a), ctypes.byref(m), ctypes.sizeof(m)):
            if m.State == 0x1000 and not (m.Protect & 0x101):          # MEM_COMMIT, not NOACCESS/GUARD
                out.append((a - base, m.RegionSize))
            a = (m.BaseAddress or 0) + m.RegionSize
        return out

    def write_memory(self, address: int, data: bytes) -> dict:
        import ctypes
        n = ctypes.c_size_t()
        k, host = ctypes.windll.kernel32, ctypes.c_void_p(self._base() + address)
        ok = k.WriteProcessMemory(self._h(), host, data, len(data), ctypes.byref(n))
        if not ok:                                         # read-only guest page (e.g. the executable): lift, write, restore
            old = ctypes.c_ulong()
            if k.VirtualProtectEx(self._h(), host, len(data), 0x04, ctypes.byref(old)):     # PAGE_READWRITE
                ok = k.WriteProcessMemory(self._h(), host, data, len(data), ctypes.byref(n))
                k.VirtualProtectEx(self._h(), host, len(data), old.value, ctypes.byref(old))
        if not ok:
            raise ValueError(f"PS3 address {address:#x} is not writable")
        return {"address": address, "written": n.value}

    # --- save states: RPCS3 game-window hotkeys set at launch to F2 = save (then continue from it) and F4 = restart from
    # the newest save state. Both reload the game, so live memory patches must be re-applied: `generation` counts
    # reloads for tools that cache addresses (script_patch). ---
    generation = 0

    def _hotkey(self, vk: int):
        import ctypes
        import ctypes.wintypes as w
        u = ctypes.windll.user32
        found = []

        @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        def cb(h, _):
            p = w.DWORD()
            u.GetWindowThreadProcessId(h, ctypes.byref(p))
            if p.value == self.proc.pid and u.IsWindowVisible(h):
                t = ctypes.create_unicode_buffer(256)
                u.GetWindowTextW(h, t, 256)
                if "FPS" in t.value:                       # the game window ("FPS: 30 | Vulkan | ... | TITLE [ID]")
                    found.append(h)
            return True
        u.EnumChildWindows(u.GetDesktopWindow(), cb, 0)    # top-level or docked inside the gBox app (child window)
        if not found:
            raise RuntimeError("RPCS3 game window not found")
        # posted straight to the game window: no focus needed, works while embedded (plain F-keys need no modifiers)
        sc = u.MapVirtualKeyW(vk, 0)
        u.PostMessageW(found[0], 0x0100, vk, 1 | sc << 16)                # WM_KEYDOWN
        time.sleep(0.08)
        u.PostMessageW(found[0], 0x0101, vk, 1 | sc << 16 | 0xC0 << 24)   # WM_KEYUP

    def save_state(self, slot: int | None = None) -> dict:
        self.resume()
        self._hotkey(0x71)                                 # F2
        self.generation += 1
        return {"saved": True, "note": "RPCS3 saves, then continues from the save state after a short reload"}

    def load_state(self, slot: int | None = None) -> dict:
        """Relaunch RPCS3 booting the newest save state of this game (verified stable; the in-process restart is not).
        The new process replaces the old one in this session; the worker reports the new pid so the app re-docks it."""
        home = getattr(self, "home", None) or provision.rpcs3_home(self.config)
        states = sorted((home / "savestates").glob(f"{getattr(self, 'serial', '') or '*'}/*.SAVESTAT*"), key=lambda f: f.stat().st_mtime)
        if not states:
            raise RuntimeError("no save state for this game yet: press F2 in the game first")
        old = self.proc
        _kill_tree(old)                                    # free this folder's lock first (one RPCS3 per folder)
        for _ in range(40):
            if not provision._rpcs3_busy(home):
                break
            time.sleep(0.25)
        __import__("gbox.graphics", fromlist=["x"]).prefer_gpu(home / "rpcs3.exe")   # the discrete GPU
        self.proc = subprocess.Popen([str(home / "rpcs3.exe"), "--no-gui", str(states[-1])], cwd=home, startupinfo=hidden_start())
        keep_offscreen(self.proc.pid)
        self._handle, self.base, self.paused = None, None, False
        self.generation += 1
        return {"loaded": states[-1].name, "pid": self.proc.pid}

    def slowmo(self, rate: float = 0.1, period_ms: int = 40) -> dict:
        """Slow the whole game to `rate` of real speed by alternating short runs and pauses of the process
        (e.g. Stranglehold's bullet keeps flying in slow motion behind a Tetris overlay). rate >= 1 stops it."""
        import ctypes
        self._slow = rate
        if rate >= 1:
            return {"slowmo": False}
        if getattr(self, "_slow_t", None) and self._slow_t.is_alive():
            return {"slowmo": rate}

        def loop():
            h, nt = self._h(), ctypes.windll.ntdll
            while self.proc and self.proc.poll() is None and getattr(self, "_slow", 1) < 1:
                run = max(1, period_ms * self._slow) / 1000
                nt.NtResumeProcess(h); time.sleep(run)
                nt.NtSuspendProcess(h); time.sleep(period_ms / 1000 - run)
            nt.NtResumeProcess(h)
        self._slow_t = threading.Thread(target=loop, daemon=True, name="slowmo")
        self._slow_t.start()
        return {"slowmo": rate}

    def pause(self) -> dict:
        import ctypes
        if not self.paused:
            ctypes.windll.ntdll.NtSuspendProcess(self._h())
            self.paused = True
        return {"paused": True}

    def resume(self) -> dict:
        import ctypes
        if self.paused:
            ctypes.windll.ntdll.NtResumeProcess(self._h())
            self.paused = False
        return {"paused": False}


class SteamAdapter(Adapter):
    """Launch installed Steam apps through the Steam client (Steam's own launch path: DRM, overlay and EULA untouched).
    With the install folder known, the game's process is found by its exe living there: the session then knows when
    the game ends, stop_game closes it (WM_CLOSE, then kill) and get_frame grabs its window."""
    name = "steam"
    supported = {"launch_game"}
    GRACE_S = 240                                          # Steam update/EULA/splash before the game process exists

    def __init__(self):
        self.install_dir, self.started, self.seen = None, 0.0, False

    def launch_game(self, appid: str, install_dir: str | None = None) -> dict:
        url = f"steam://rungameid/{int(appid)}"
        if sys.platform == "win32":
            os.startfile(url)  # noqa: S606 — url built from an int
        else:
            subprocess.Popen(["xdg-open", url])
        self.started = time.time()
        if install_dir and Path(install_dir).is_dir():
            self.install_dir = Path(install_dir)
            self.supported = {"launch_game", "stop_game", "query_runtime", "get_frame"}
        return {"url": url, "install_dir": install_dir, "local_window": True}

    def _proc(self):
        if not self.install_dir:
            return None
        import psutil
        root = str(self.install_dir.resolve()).lower()
        for p in psutil.process_iter(["exe", "name"]):
            exe = (p.info["exe"] or "").lower()
            if exe.startswith(root) and not any(k in (p.info["name"] or "").lower() for k in ("crash", "installer", "unins")):
                return p
        return None

    def query_runtime(self) -> dict:
        p = self._proc()
        self.seen = self.seen or p is not None
        waiting = not self.seen and time.time() - self.started < self.GRACE_S
        return {"running": bool(p) or waiting, "pid": p.pid if p else None, "starting": waiting and not p}

    def stop_game(self) -> dict:
        p = self._proc()
        if not p:
            return {"stopped": False, "running": False}
        if sys.platform == "win32":
            import ctypes
            import ctypes.wintypes as w
            u = ctypes.windll.user32

            @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
            def cb(h, _):
                pid = w.DWORD()
                u.GetWindowThreadProcessId(h, ctypes.byref(pid))
                if pid.value == p.pid and u.IsWindowVisible(h):
                    u.PostMessageW(h, 0x0010, 0, 0)        # WM_CLOSE: the game's own quit path
                return True
            u.EnumWindows(cb, 0)
        try:
            p.wait(15)
            how = "closed"
        except Exception:                                  # noqa: BLE001 - psutil.TimeoutExpired
            p.kill()
            how = "killed"
        return {"stopped": True, "how": how, "pid": p.pid}

    def get_frame(self) -> bytes:
        """The game window as it is on screen (desktop grab of its rectangle)."""
        p = self._proc()
        if not p or sys.platform != "win32":
            raise RuntimeError("the game window is not open")
        import ctypes
        import ctypes.wintypes as w
        u = ctypes.windll.user32
        rects = []

        @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        def cb(h, _):
            pid = w.DWORD()
            u.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value == p.pid and u.IsWindowVisible(h):
                r = w.RECT()
                u.GetWindowRect(h, ctypes.byref(r))
                if r.right - r.left > 64 and r.bottom - r.top > 64:
                    rects.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
            return True
        u.EnumWindows(cb, 0)
        if not rects:
            raise RuntimeError("the game window is not visible")
        x, y, ww, hh = max(rects, key=lambda r: r[2] * r[3])
        return grab_png(None, [max(0, x), max(0, y), ww - ww % 2, hh - hh % 2])


def for_game(game: dict, config: Config, debug: bool = False) -> Adapter:
    """Pick the adapter for a catalog entry on THIS node. debug=True prefers an emulator with a full CPU debugger."""
    plat = game["platform"]
    if debug and HOST_OS == "linux" and plat in DEBUG_ADAPTERS:
        return DEBUG_ADAPTERS[plat](config, plat)
    if plat == "pc_steam":
        return SteamAdapter()
    from . import systems
    if game.get("core") and plat != "arcade" and systems.core_for(plat)[0] is None:
        game = game | {"core": None}                       # catalog still has a core the platform rule has since dropped
    override = config.emulators.get(plat)
    if override and override.adapter == "command":
        return CommandAdapter(override)
    if plat == "ps3" and game.get("launch", {}).get("kind") != "attract":
        if HOST_OS != "windows":
            raise ToolUnavailable("PS3 games run in RPCS3 on a Windows node")
        return RPCS3Adapter(config)
    if HOST_OS == "windows" and plat in ("gamecube", "wii") and not (override and override.core) \
            and (config.runtime / "dolphin" / "Dolphin-x64" / "Dolphin.exe").is_file():
        return DolphinWinAdapter(config, plat)              # same Dolphin release as the Spark: full speed + memory mods
    if plat == "xbox360" and HOST_OS == "windows":
        from .xenia import XeniaAdapter
        return XeniaAdapter(config, plat)
    if plat == "switch" and HOST_OS == "windows":
        return YuzuAdapter(config)
    if HOST_OS == "windows" and game.get("launch", {}).get("kind") == "attract" and not game.get("core"):
        return RocketLauncherAdapter(config.library(game["library"]).root("windows"))   # no libretro core: drive's own emulators
    if HOST_OS == "linux" and plat in ("gamecube", "wii") and not (override and override.core) \
            and provision.flatpak_ok(DolphinAdapter.flatpak):
        return DolphinAdapter(config, plat)                # current Dolphin + GDB stub (the libretro core is years older)
    core = (override.core if override else None) or game.get("core")
    if not core:
        hint = " (runs on a Windows node via RocketLauncher)" if HOST_OS != "windows" else ""
        raise ToolUnavailable(f"no runtime for platform '{plat}' on {HOST_OS}: no libretro core mapped{hint}")
    return RetroArchAdapter(override or EmulatorConfig(core=core), config=config, platform=plat)


def for_platform(platform: str, config: Config) -> Adapter:
    """Back-compat: adapter by platform only (requires an explicit [emulators.<platform>] entry)."""
    if platform != "pc_steam" and platform not in config.emulators:
        raise ToolUnavailable(f"no emulator configured for platform '{platform}' (set [emulators.{platform}] in gbox.toml)")
    return for_game({"platform": platform, "launch": {}}, config)
