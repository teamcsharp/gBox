"""Runtime/emulator adapters behind one capability interface (plan §6). Unsupported ops raise Unsupported."""
import collections
import json
import os
import re
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
FLYCAST_PLATFORMS = {"dreamcast", "naomi", "atomiswave"}
# Keep rendered textures in emulated VRAM, so future states can include them.
# Unthreaded rendering also keeps serialization size stable between query/write.
FLYCAST_STATE_OPTS = {"reicast_threaded_rendering": "disabled", "reicast_enable_rttb": "enabled"}
# Flycast save states are ~27 MB and stall the game while they serialize: gBox's checkpoint ring takes one at most every
# 20 s there (#1489, 2 fps in PSO with a checkpoint every 2 s); the ring's frame-rate budget can stretch it further.
FLYCAST_CHECKPOINT_MIN_S = 20.0
# Windows N64 (docked, resizable window) uses parallel_n64's software angrylion RDP, whose output scales with the window.
# angrylion is an LLE RDP: it needs the LLE cxd4 RSP. With rspplugin "auto"/"hle" the core runs HLE graphics tasks that
# angrylion never draws, so every 3D/textured layer stays black while CPU-drawn text still updates (#1322, MK4).
N64_WINDOWS_OPTS = {"parallel-n64-gfxplugin": "angrylion", "parallel-n64-rspplugin": "cxd4"}


def _set_core_opts(path: Path, values: dict[str, str]) -> None:
    """Replace exact option keys while preserving every unrelated setting."""
    lines = [line for line in (path.read_text().splitlines() if path.exists() else [])
             if line.split("=", 1)[0].strip() not in values]
    path.write_text("\n".join(lines + [f'{key} = "{value}"' for key, value in values.items()]) + "\n")


class Adapter:
    name = "base"
    supported: set[str] = set()
    # gBox's checkpoint rewind (gbox/rewind.py): "path" = save_state reports the file it wrote (the operator's slot,
    # borrowed and given back), "dir" = checkpoint_save writes a private slot found under state_dir() / state_glob,
    # False = the save state does not work in place (checkpoint_reason says why), None = no save state file to copy.
    checkpoint_state: str | bool | None = None

    def prepare_audio(self):
        """Called at the top of a launch: Windows emulators choose their output device (and wake it) while the launch
        stages files and checks BIOS (gbox/game_audio.py). Nothing to do elsewhere."""
        return None

    def get_capabilities(self) -> dict[str, str]:
        return {op: ("supported" if op in self.supported else "unsupported") for op in OPS}

    def __getattr__(self, op):
        if op in OPS:
            def unsupported(*a, **k):
                raise Unsupported(f"{self.name} does not support {op}")
            return unsupported
        raise AttributeError(op)


def _win_descendants(pid: int) -> list[int]:
    """PIDs started (transitively) by `pid`, from one Toolhelp snapshot: what taskkill /T walks, without its startup."""
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)                     # TH32CS_SNAPPROCESS
    if snap in (None, wintypes.HANDLE(-1).value):
        raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")
    children: dict[int, list[int]] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            children.setdefault(entry.th32ParentProcessID, []).append(entry.th32ProcessID)
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    out, todo = [], [pid]
    while todo:
        for child in children.get(todo.pop(), []):
            if child not in out and child != pid:
                out.append(child)
                todo.append(child)
    return out


def _win_terminate_tree(proc: subprocess.Popen) -> None:
    """TerminateProcess on the emulator (gBox started it: its own handle) and every process it started; nothing else."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p

    def created(handle) -> int | None:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not k32.GetProcessTimes(ctypes.c_void_p(handle), *(ctypes.byref(t) for t in times)):
            return None
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    root = created(int(proc._handle))
    if root is None:
        raise OSError(ctypes.get_last_error(), "GetProcessTimes failed")
    kids = _win_descendants(proc.pid)                                # before the parent goes (its children re-parent)
    proc.kill()                                                      # Popen.kill = TerminateProcess on our handle
    for pid in kids:
        h = k32.OpenProcess(0x0001 | 0x1000, False, pid)             # PROCESS_TERMINATE | QUERY_LIMITED_INFORMATION
        if not h:
            continue
        try:
            born = created(h)
            if born is not None and born >= root:                    # a reused parent PID: older, not ours, untouched
                k32.TerminateProcess(ctypes.c_void_p(h), 1)
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))


def _kill_tree(proc: subprocess.Popen | None):
    """Kill the emulator's own process tree now (#1504): TerminateProcess on the emulator gBox started and on the
    processes it started (taskkill /T /F on its PID as the fallback), SIGTERM on Linux; nothing else is touched."""
    if not proc or proc.poll() is not None:
        return
    if HOST_OS == "windows":
        try:
            _win_terminate_tree(proc)          # ~10 ms; taskkill itself took 1-1.3 s here, ~5 s on a busy PC
        except Exception:                      # noqa: BLE001 - no Toolhelp / access: the system tool does the same
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=10)
    else:
        proc.terminate()
    try:
        proc.wait(3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(5)  # No successful stop until the native process has actually exited.


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


def _wall(ts: float | None = None) -> str:
    """Local wall-clock time with the UTC offset, so a stall line matches the operator's "it went black at 4:52"."""
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() if ts is None else ts))


class MjpegStream:
    """Persistent ffmpeg grab -> MJPEG pipe; `latest` always holds the newest complete JPEG.
    ponytail: MJPEG over HTTP (~60 fps on LAN, no audio); move to H.264/NVENC over WebRTC if bandwidth/latency bite.

    The encoder is supervised (docs/stream-stability.md): x11grab/gdigrab grabs at a fixed rate whether or not the
    picture changes, so a pipe that stays silent for STALL_S while ffmpeg is alive is a hung grab, and an exited
    ffmpeg is a dead one. Either way only the encoder is restarted (with backoff); the emulator is never touched and
    `latest` keeps the last good frame meanwhile. Gaps of SLOW_S or more are logged with wall-clock timestamps."""
    STALL_S = 8.0          # generous: an overloaded host (load 30+, swap full) can starve ffmpeg for a few seconds
    SLOW_S = 2.0           # a frame gap this long is logged (no action)
    BACKOFF = (0.5, 10.0)  # restart delay: doubles per restart without a frame in between, capped
    CHECK_S = 0.5

    def __init__(self, display: str | None, fps: int = 60, size: tuple[int, int] | None = None,
                 max_width: int = 960, draw_mouse: bool = False, *, label: str = "", popen=None, kill=None,
                 clock=time.monotonic, supervise: bool = True, stall_s: float | None = None):
        if HOST_OS == "windows":
            src = ["-f", "gdigrab", "-draw_mouse", "1" if draw_mouse else "0", "-framerate", str(fps), "-i", "desktop"]
        else:
            src = ["-f", "x11grab", "-draw_mouse", "0", "-framerate", str(fps),
                   *(["-video_size", f"{size[0]}x{size[1]}"] if size else []), "-i", display or ":0"]
        self.argv = ["ffmpeg", "-loglevel", "error", "-fflags", "nobuffer", *src,
                     "-vf", f"scale='min({max_width},iw)':-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-pix_fmt", "yuvj420p",
                     "-q:v", "7", "-"]
        self.label, self.clock = label or (display or "desktop"), clock
        self.stall_s = float(stall_s or self.STALL_S)
        self._popen = popen or (lambda argv: subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL))
        self._kill = kill or _kill_tree
        self.latest, self.seq, self.cond = None, 0, threading.Condition()
        self.closed, self.restarts, self._fails, self._next_spawn = False, 0, 0, 0.0
        self.events = collections.deque(maxlen=50)    # stalls / restarts, newest last (served by stats())
        self.on_event = None                          # callable(dict): the worker forwards events to the control plane
        self.last_frame = self.spawned = clock()
        self.proc = None
        self._spawn()
        if supervise:
            threading.Thread(target=self._supervise, daemon=True, name=f"mjpeg-supervisor-{self.label}").start()

    def wait(self, seen: int, timeout: float) -> bool:
        """Block until a frame newer than `seen` exists."""
        with self.cond:
            return self.cond.wait_for(lambda: self.seq != seen and self.latest is not None, timeout)

    def _spawn(self):
        self.spawned = self.clock()
        self.proc = proc = self._popen(self.argv)
        threading.Thread(target=self._read, args=(proc,), daemon=True, name=f"mjpeg-reader-{self.label}").start()

    def _event(self, kind: str, **detail):
        ev = {"kind": kind, "at": _wall(), "stream": self.label, **detail}
        self.events.append(ev)
        print("gBox stream: " + " ".join(f"{k}={v}" for k, v in ev.items()), flush=True)
        if self.on_event:
            try:
                self.on_event(ev)
            except Exception:                         # noqa: BLE001 - reporting must never stop the video
                pass

    def _read(self, proc):
        buf = b""
        while chunk := proc.stdout.read1(262144):
            buf += chunk
            while (s := buf.find(b"\xff\xd8")) >= 0 and (e := buf.find(b"\xff\xd9", s + 2)) >= 0:
                now = self.clock()
                gap = now - self.last_frame
                with self.cond:
                    if proc is not self.proc or self.closed:  # a replaced encoder's late output is dropped
                        return
                    self.latest, self.seq, buf = buf[s:e + 2], self.seq + 1, buf[e + 2:]
                    self.last_frame, self._fails = now, 0
                    self.cond.notify_all()
                if gap >= self.SLOW_S and self.seq > 1:
                    self._event("slow_frames", gap_s=round(gap, 2))

    def check(self, now: float | None = None) -> str | None:
        """One supervision step (the supervisor thread calls it every CHECK_S): restart a dead or hung encoder."""
        now = self.clock() if now is None else now
        if self.closed:
            return None
        proc = self.proc
        if proc is None:
            if now >= self._next_spawn:
                self.restarts += 1
                self._event("encoder_restart", restart=self.restarts)
                self._spawn()
                return "restarted"
            return None
        silent = now - max(self.last_frame, self.spawned)
        if proc.poll() is not None:
            self._event("encoder_exit", returncode=proc.poll(), silent_s=round(now - self.last_frame, 2))
        elif silent >= self.stall_s:
            self._event("encoder_stall", silent_s=round(silent, 2))
            try:
                self._kill(proc)
            except Exception:                         # noqa: BLE001 - an unkillable grab is replaced anyway
                pass
        else:
            return None
        with self.cond:
            self.proc = None
        first, cap = self.BACKOFF
        self._next_spawn = now + min(cap, first * 2 ** min(self._fails, 6))
        self._fails += 1
        return "scheduled"

    def _supervise(self):
        while not self.closed:
            time.sleep(self.CHECK_S)
            try:
                self.check()
            except Exception as e:                    # noqa: BLE001 - keep supervising
                print(f"gBox stream: supervisor error {type(e).__name__}: {e}", flush=True)

    def stats(self) -> dict:
        now = self.clock()
        return {"seq": self.seq, "frame_age_s": round(now - self.last_frame, 2), "restarts": self.restarts,
                "encoder_alive": bool(self.proc and self.proc.poll() is None), "events": list(self.events)[-10:]}

    def close(self):
        self.closed = True
        proc, self.proc = self.proc, None
        self._kill(proc)


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
# function keys and Tab: emulator hotkeys (Dolphin's save / load state slots and its speed limit); they were dropped before
_SCAN.update({f"F{i + 1}": (sc, 0) for i, sc in enumerate([0x3B, 0x3C, 0x3D, 0x3E, 0x3F, 0x40, 0x41, 0x42, 0x43, 0x44, 0x57, 0x58])})
_SCAN["Tab"] = (0x0F, 0)
# F13-F15 (DirectInput DIK_F13..F15 = these scan codes): keys no keyboard in use here has, so gBox's emulator hotkeys bound
# to them never collide with what the operator types (Dolphin's gBox Hotkeys.ini, DolphinWinAdapter.HOTKEYS_INI)
_SCAN.update({"F13": (0x64, 0), "F14": (0x65, 0), "F15": (0x66, 0),
              "Control_L": (0x1D, 0), "Control_R": (0x1D, 1), "Shift_L": (0x2A, 0)})


def _pid_window(pid: int):
    """The game's visible render window, including one docked inside gBox.

    Enumeration order is not a render-window identity: an owned Warning dialog
    can come first, even minimized, and would receive input and black captures.
    """
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    found = []
    PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def consider(h):
        p = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value != pid or not u.IsWindowVisible(h) or u.IsIconic(h):
            return
        title = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(h, title, len(title))
        if title.value.startswith(('DIEmWin', '__wgl', 'NVOGL', 'Default IME', 'MSCTFIME')):
            return
        rect = wintypes.RECT()
        u.GetWindowRect(h, ctypes.byref(rect))
        area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
        if area:
            render = title.value.startswith('Dolphin ') and ' | ' in title.value
            found.append((render, area, h))

    @PROC
    def child(h, _):
        consider(h)
        return True

    @PROC
    def top(h, _):
        consider(h)
        u.EnumChildWindows(h, child, 0)
        return True
    u.EnumWindows(top, 0)
    return max(found)[2] if found else None


def _win_input_in_front(user32, root, hidden_ok: bool) -> bool:
    foreground = user32.GetForegroundWindow()
    if not foreground:                                      # locked screen / secure desktop: never send there
        return False
    if root and foreground == root:
        return True
    if not hidden_ok:
        return False                                        # pad input must never type into another app
    # hidden_ok: Dolphin's global focus-free hotkeys (F13-F15 lane chords plus Ctrl/Shift). Dolphin reads them
    # without focus (HotkeysRequireFocus=False, BackgroundInput=True) and nothing else binds F13-F15, so they
    # are safe to send while another app is in front. Requiring gBox.exe to be the foreground window here blocked
    # every save-before-switch when the operator was in another app or a remote launch ran while gBox was not
    # focused ("The previous game could not be saved: gBox or the emulator must be active to send emulator input").
    return True


def win_send_keys(pid: int, events: list[dict], hidden_ok: bool = False) -> dict:
    """hidden_ok: the keys are emulator hotkeys that need no focus (Dolphin's gBox F13-F15 chords): sent even while the
    game window is hidden (the app hides it the moment Stop is pressed, before the last-played moment is saved)."""
    import ctypes
    from ctypes import wintypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    if hidden_ok and any(e.get('key') not in {'F13', 'F14', 'F15', 'Control_L', 'Control_R', 'Shift_R'} for e in events):
        raise ValueError('Background emulator input accepts only gBox Dolphin hotkeys')
    h = _pid_window(pid)
    if not h and not hidden_ok:
        raise RuntimeError("the game window isn't open")
    root = u.GetAncestor(h, 2) if h else None
    for _ in range(100):                                         # wait (up to 10 s) for the operator to bring gBox back
        if _win_input_in_front(u, root, hidden_ok):
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("gBox or the emulator must be active to send emulator input safely")
    if h and not hidden_ok:                                     # global Dolphin hotkeys need no native-window focus
        me, them = k.GetCurrentThreadId(), u.GetWindowThreadProcessId(h, None)
        u.AttachThreadInput(me, them, True)
        u.SetFocus(h)
        u.AttachThreadInput(me, them, False)

    class KI(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_size_t)]

    class INP(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("ki", KI), ("pad", ctypes.c_ubyte * 8)]
    seq, pressed, held = [], set(), {}
    def release_injected():
        for sc, ext in held.values():
            release = INP(type=1, ki=KI(0, sc, 0x0008 | 0x0002 | (0x0001 if ext else 0), 0, 0))
            u.SendInput(1, ctypes.byref(release), ctypes.sizeof(INP))
        held.clear()
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
        if not _win_input_in_front(u, root, hidden_ok):          # the operator switched apps mid-batch: never type there
            release_injected()                                # don't leave Ctrl/Shift held in the next application
            return {"sent": len(seq), "stopped": "another application came to the front"}
        inp = INP(type=1, ki=KI(0, sc, flags, 0, 0))
        if u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INP)) != 1:
            release_injected()
            raise RuntimeError('Windows rejected emulator input; the hotkey was not completed')
        seq.append(name)
        if down:
            held[name] = (sc, ext)
        else:
            held.pop(name, None)
    return {"sent": len(seq)}


_last_grab = {}


def win_grab_state() -> dict:
    """Capture origin/occlusion for diagnostics; never substitute another app's pixels."""
    return dict(_last_grab)


def _win_title(hwnd):
    import ctypes
    title = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetWindowTextW(hwnd, title, 256)
    return title.value


WINDOW_SURFACE = "window-surface"   # PrintWindow of the emulator's own HWND (#1057)


def _print_window_png(hwnd, width: int, height: int) -> bytes | None:
    """PNG of one window's own surface via PrintWindow(PW_RENDERFULLCONTENT), or None.

    Works while other windows cover it. Returns None when the API is missing,
    refuses, or produces a uniformly empty bitmap (some GPU swap chains do)."""
    if width <= 0 or height <= 0 or width * height > 16384 * 16384:
        return None
    try:
        import ctypes
        user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
        from ctypes import wintypes as wt
        for function, args, result in (
                (user.GetWindowDC, [wt.HWND], wt.HDC),
                (user.ReleaseDC, [wt.HWND, wt.HDC], ctypes.c_int),
                (user.PrintWindow, [wt.HWND, wt.HDC, wt.UINT], wt.BOOL),
                (gdi.CreateCompatibleDC, [wt.HDC], wt.HDC),
                (gdi.CreateCompatibleBitmap, [wt.HDC, ctypes.c_int, ctypes.c_int], wt.HBITMAP),
                (gdi.SelectObject, [wt.HDC, wt.HANDLE], wt.HANDLE),
                (gdi.DeleteObject, [wt.HANDLE], wt.BOOL),
                (gdi.DeleteDC, [wt.HDC], wt.BOOL),
                (gdi.GetDIBits, [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT,
                                ctypes.c_void_p, ctypes.c_void_p, wt.UINT], ctypes.c_int)):
            function.argtypes, function.restype = args, result
        src = user.GetWindowDC(hwnd)
        if not src:
            return None
        mem = bmp = None
        try:
            mem = gdi.CreateCompatibleDC(src)
            bmp = gdi.CreateCompatibleBitmap(src, width, height)
            old = gdi.SelectObject(mem, bmp)
            ok = user.PrintWindow(hwnd, mem, 2)              # PW_RENDERFULLCONTENT
            gdi.SelectObject(mem, old)
            if not ok:
                return None

            class BIH(ctypes.Structure):
                _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                            ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16),
                            ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32),
                            ("biXPelsPerMeter", ctypes.c_int32), ("biYPelsPerMeter", ctypes.c_int32),
                            ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]
            info = BIH(ctypes.sizeof(BIH), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
            buf = ctypes.create_string_buffer(width * height * 4)
            if gdi.GetDIBits(mem, bmp, 0, height, buf, ctypes.byref(info), 0) != height:
                return None
        finally:
            if bmp:
                gdi.DeleteObject(bmp)
            if mem:
                gdi.DeleteDC(mem)
            user.ReleaseDC(hwnd, src)
        return print_window_bitmap_png(buf.raw, width, height)
    except Exception:
        return None


def print_window_bitmap_png(bgra: bytes, width: int, height: int) -> bytes | None:
    """Encode a top-down BGRA PrintWindow bitmap; None for an empty (one-colour) result."""
    import io
    from PIL import Image
    if len(bgra) != width * height * 4:
        return None
    image = Image.frombuffer("RGB", (width, height), bgra, "raw", "BGRX", 0, 1)
    lo, hi = zip(*image.getextrema())
    if lo == hi:                                             # nothing rendered: let the caller report occlusion
        return None
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def win_grab(pid: int) -> bytes:
    """PNG of a local emulator window (docked or not), as the screen shows it."""
    global _last_grab
    _last_grab = {}  # A failed capture must not retain metadata from the previous PNG.
    import ctypes
    import io
    from hashlib import sha256
    from ctypes import wintypes
    from PIL import ImageGrab
    # Chromium captures a composited game's GPU window even when its source is
    # off-screen. Never return a stale image or a desktop screenshot of other apps.
    frame_dir = Path(os.environ.get("GBOX_GAME_FRAME_DIR") or Path(os.environ.get("APPDATA", "")) / "gbox-desktop" / "game-frames")
    frame = frame_dir / f"{int(pid)}.png"
    if frame.is_file() and 0 <= time.time() - frame.stat().st_mtime < 5:
        data = frame.read_bytes()
        if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) < 8 * 1024 * 1024:
            _last_grab = dict(pid=pid, covered=0, source="chromium-gpu-surface", sha256=sha256(data).hexdigest(),
                             frame_age_s=round(time.time() - frame.stat().st_mtime, 3))
            return data
    h = _pid_window(pid)
    if not h:
        raise RuntimeError("the game window isn't open")
    r = wintypes.RECT()
    user = ctypes.windll.user32
    user.GetWindowRect(h, ctypes.byref(r))
    # ImageGrab reads the compositor, not the emulator's back buffer. When a
    # browser covers the game, an unguarded capture looks like that browser and
    # a vision model can mistake it for gameplay. Check the visible window at
    # several points inside the game before accepting the frame.
    user.WindowFromPoint.argtypes = [wintypes.POINT]
    user.WindowFromPoint.restype = wintypes.HWND
    foreign = 0
    for fx, fy in ((.25, .25), (.5, .25), (.75, .25), (.25, .5), (.5, .5), (.75, .5), (.25, .75), (.5, .75), (.75, .75)):
        point = wintypes.POINT(round(r.left + (r.right - r.left) * fx), round(r.top + (r.bottom - r.top) * fy))
        top = user.WindowFromPoint(point)
        owner = wintypes.DWORD()
        if not top or not user.GetWindowThreadProcessId(top, ctypes.byref(owner)) or owner.value != pid:
            foreign += 1
    if foreign >= 3:
        # The compositor would return the covering app. Ask the emulator's own
        # window to render itself instead; its pixels are never another app's.
        data = _print_window_png(h, r.right - r.left, r.bottom - r.top)
        if not data:
            raise RuntimeError("the game window is covered by another app; bring gBox or the emulator forward before capturing")
        _last_grab = dict(pid=pid, covered=foreign, source=WINDOW_SURFACE, frame_age_s=0,
                         sha256=sha256(data).hexdigest())
        return data
    buf = io.BytesIO()
    ImageGrab.grab((r.left, r.top, r.right, r.bottom), all_screens=True).save(buf, "PNG")
    data = buf.getvalue()
    _last_grab = dict(pid=pid, covered=foreign, source="desktop-compositor", frame_age_s=0,
                     sha256=sha256(data).hexdigest())
    return data


VGLRUN = "/opt/VirtualGL/bin/vglrun"


def _pad_binds() -> dict:
    """retroarch.cfg lines binding both players' RetroPad buttons to the keys above."""
    out = {"input_enable_hotkey": "scroll_lock"}
    for player, keys in PAD_KEYS.items():
        for btn, ks in keys.items():
            out[f"input_player{player}_{_ANALOG.get(btn, btn)}"] = _RA_KEYNAME.get(ks, ks)
    return out


def _examine_driver_ok(argv, also: tuple = ()) -> bool:
    """RenderDoc injection only for Direct3D/Vulkan renderers: under it RetroArch's OpenGL driver can't create its window
    ("win32_set_video_mode failed", the game never starts: N64 parallel_n64 and the other GL cores). `also` adds
    drivers a capture session may inject into (core-profile "glcore", #971)."""
    import re
    if "--config" not in argv:
        return True                                   # standalone emulators here (Dolphin on Vulkan) are RenderDoc-capturable
    try:
        cfg = Path(argv[argv.index("--config") + 1]).read_text(errors="replace")
    except (OSError, IndexError):
        return False
    m = re.search(r'^video_driver\s*=\s*"([^"]*)"', cfg, re.M)
    return bool(m) and m.group(1) in ("d3d11", "d3d12", "vulkan", *also)


def _popen(ad, argv, **kw) -> subprocess.Popen:
    """Start a local-window emulator; with Examine 3D on (ad.examine) RenderDoc is loaded into it from the first
    instruction, so the frame on screen can be captured as a 3D scene later (gbox.scene_capture).
    An agent-owned capture session (ad.capture_backend, #971) with a Vulkan backend gets RenderDoc through its Vulkan
    layer instead (environment only, no injection), and its window stays parked off-screen for its whole life."""
    cap = getattr(ad, "capture_backend", None)
    if HOST_OS == "windows":
        from .graphics import prefer_gpu
        prefer_gpu(argv[0])                                # the discrete GPU, never a virtual display / iGPU
        kw.setdefault("startupinfo", capture_start() if cap else hidden_start())
    cap_dir = ad.config.runtime / "scene_capture" / "rdc" if getattr(ad, "config", None) else None
    if HOST_OS == "windows" and getattr(ad, "examine", False) and (cap or {}).get("attach") == "layer":
        from . import scene_capture
        p = scene_capture.popen_layer(argv, cap_dir, **kw)
    elif HOST_OS == "windows" and getattr(ad, "examine", False) and _examine_driver_ok(argv, ("glcore",) if cap else ()):
        from . import scene_capture
        p = scene_capture.popen_hooked(argv, cap_dir=cap_dir, **kw)
    else:
        p = subprocess.Popen(argv, **kw)
    if HOST_OS == "windows":
        keep_offscreen(p.pid, **({"limit_s": 1800.0, "give_up_s": float("inf")} if cap else {}))
    return p


def capture_start():
    """Windows: a capture session's window is shown normally but never activated (a minimized Vulkan/GL window has
    no swapchain to present, so RenderDoc would never see a frame); keep_offscreen parks it off-screen as it opens."""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 4                                     # SW_SHOWNOACTIVATE
    return si


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
    u32.GetPropW.argtypes, u32.GetPropW.restype = [H, wintypes.LPCWSTR], wintypes.HANDLE
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
        if h and u32.GetPropW(h, "GBoxCompositedSurface"):
            return                                         # the GPU capture helper owns this off-screen window
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
                if any(u32.GetPropW(h, "GBoxCompositedSurface") for h in windows(False)):
                    return                                 # never restore a captured source onto the desktop at 45 s
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


def _audio_prefetch(ad):
    """Start (once) the output-device choice + warm-up for a Windows launch (game_audio.Prefetch)."""
    if HOST_OS != "windows" or getattr(ad, "config", None) is None:
        return None
    pre = ad.__dict__.get("_audio_pre")
    if pre is None:
        from . import game_audio
        pre = ad._audio_pre = game_audio.Prefetch(ad.config)
    return pre


def _audio_selection(ad, wait_s: float = 1.0) -> dict:
    """The device choice for this launch: the prefetched one when ready within wait_s, else 'unknown' (the
    emulator's own default device). Never blocks a launch for long."""
    from . import game_audio
    pre = _audio_prefetch(ad)
    return pre.result(wait_s) if pre else dict(game_audio.NOT_READY, error="not windows")


def _audio_release(ad):
    pre = ad.__dict__.get("_audio_pre")
    if pre is not None:
        pre.release()


def _examine_ok(proc, wait_s: float = 0.0) -> bool:
    """RenderDoc is inside the emulator: injected at launch, or (Vulkan layer) loaded once the game made its Vulkan
    device; wait_s gives the layer that long to show up."""
    info = getattr(proc, "renderdoc", None)
    if isinstance(info, dict) and info.get("attach") == "layer" and "error" not in info:
        from .scene_capture import layer_check
        return bool(layer_check(proc, wait_s))
    return bool(info) and "error" not in info


def _state_file_identity(stat) -> tuple:
    # Windows Python 3.12 path.stat/fstat expose different legacy ctime
    # semantics. Device/inode bind the file; size/mtime bind its write state.
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _validate_completed_state_file(path: Path, expected_stat) -> None:
    """Require a stable, complete recognized container without inspecting a core layout.

    Raw core snapshots keep their existing handling. A temporarily stable file
    may still contain an unfinished RZIP header/chunk, so its envelope must be
    complete before capture reports verified success.
    """
    expected = _state_file_identity(expected_stat)
    with path.open('rb') as stream:
        if _state_file_identity(os.fstat(stream.fileno())) != expected:
            raise ValueError('saved checkpoint changed before validation')
        header = stream.read(8)
        if not header:
            raise ValueError('saved checkpoint is empty')
        if header.startswith((b'#RZIPv', b'RASTATE')):
            from .flycast_state import MAX_RZIP_CHUNK, MAX_STATE_BYTES, unpack
            # Bound the encoded read as well as unpack's decoded/chunk budgets.
            limit = MAX_STATE_BYTES + MAX_RZIP_CHUNK
            if expected_stat.st_size > limit:
                raise ValueError('saved checkpoint container exceeds inspection budget')
            # Read only the observed file plus one growth-detection byte; using
            # the full global budget here would allocate hundreds of MiB even
            # for a tiny unfinished checkpoint on every polling attempt.
            data = header + stream.read(expected_stat.st_size + 1 - len(header))
            if len(data) != expected_stat.st_size or len(data) > limit:
                raise ValueError('saved checkpoint changed or exceeded budget during read')
            if not unpack(data):
                raise ValueError('saved checkpoint contains no core state')
        if (_state_file_identity(os.fstat(stream.fileno())) != expected
                or _state_file_identity(path.stat()) != expected):
            raise ValueError('saved checkpoint changed during validation')


def _link_lst_names(lst: Path) -> list[str]:
    """A GD-ROM .lst may name its data file differently from what the set ships
    (capcomvssnk2.bin vs cvs2gd.bin): hard-link each missing referenced name to the
    set's single data file, next to the .lst. Returns the names that were linked.
    A set with more than one data file is left alone (ambiguous)."""
    text = lst.read_text(errors="replace")
    wants = [m[4].strip('"') for m in (re.findall(r'"[^"]+"|\S+', ln) for ln in text.splitlines())
             if len(m) >= 5 and m[4].strip('"').lower().endswith((".bin", ".dat"))]
    bins = [f for f in lst.parent.iterdir() if f.suffix.lower() in (".bin", ".dat")]
    linked = []
    for want in wants:
        if Path(want).name != want or '/' in want or '\\' in want or ':' in want or want in ('.', '..'):
            raise ValueError('GD list reference must be a sibling filename')
        if len(bins) != 1 or (lst.parent / want).exists():
            continue
        try:
            os.link(bins[0], lst.parent / want)
        except OSError:
            shutil.copyfile(bins[0], lst.parent / want)
        linked.append(want)
    return linked


class RetroArchAdapter(CommandAdapter):
    """RetroArch + libretro core, controlled through RetroArch's UDP network command interface.

    Linux: each session runs on its own Xvfb display (frames via x11grab, input via xdotool).
    Cores, core assets and BIOS are resolved automatically (provision.ensure_platform).
    Memory ops depend on the core exposing a memory map; failures come back as explicit errors.
    """
    name = "retroarch"
    supported = {"launch_game", "stop_game", "pause", "resume", "read_memory", "write_memory", "save_state",
                 "load_state", "step_frames", "query_runtime", "get_frame", "send_input", "stream_session", "rewind", "fast_forward"}
    checkpoint_state = "path"                            # NO_REWIND cores: gBox's checkpoint ring behind Select+L2
    ff_on = False                                        # gBox's view of RetroArch's fast-forward toggle

    def __init__(self, cfg: EmulatorConfig, config: Config | None = None, platform: str | None = None,
                 port: int | None = None, host: str = "127.0.0.1"):
        super().__init__(cfg)
        self.config, self.platform = config, platform
        if port is None:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]
        self.addr, self.display, self.stream, self.log_path = (host, port), None, None, None
        self._state_lock = threading.RLock()
        self.rewind_on = (platform or "") not in NO_REWIND
        self.checkpoint_min_interval_s = FLYCAST_CHECKPOINT_MIN_S if (platform or "") in FLYCAST_PLATFORMS else 0.0
        self.granularity = 15 if (platform or "") in COARSE_REWIND else 4
        self.trigger_hotkeys = False                  # the worker owns Select+trigger and D-pad time controls
        # sound (gbox/game_audio.py): the driver of the current attempt and the device it opens ("" = Windows' default)
        self.audio_driver, self.audio_device = ("null" if HOST_OS == "linux" else "xaudio"), ""
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
                # in-game saves (SRAM) reach the disk every 5 s while playing, so Stop can kill RetroArch at once (#1504)
                "autosave_interval": "5",
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
        cap = getattr(self, "capture_backend", None)          # agent-owned capture session (#971): its own files only,
        if cap:                                               # the operator's retroarch/core options are only read
            from . import capture_backend
            work = rt / "capture_sessions" / f"ra-{self.addr[1]}"
            for sub in ("states", "saves", "shots"):
                (work / sub).mkdir(parents=True, exist_ok=True)
            co = capture_backend.core_options_file(co, {}, work)
        if (self.platform or "") == "n64" and HOST_OS == "windows":       # docked + resized windows: the GL plugins (Glide64)
            _set_core_opts(co, N64_WINDOWS_OPTS)                          # draw at launch size -> squeezed/cropped picture
        if (self.platform or "") in FLYCAST_PLATFORMS:
            _set_core_opts(co, FLYCAST_STATE_OPTS)
        if not self.rewind_on:
            opts["rewind_enable"] = "false"
        if self.rewind_on:
            opts.update({"rewind_enable": "true", "rewind_granularity": str(self.granularity),
                         "rewind_buffer_size": "1024" if self.granularity > 4 else "512", "rewind_buffer_size_step": "64"})
        # One worker handles both D-pad aliases and triggers on every emulator. Disable inherited RetroArch time
        # bindings so a native pad never rewinds twice, and L2/R2 without Select remain ordinary game controls.
        opts.update({"input_rewind": "nul", "input_rewind_btn": "nul", "input_rewind_axis": "nul",
                     "input_hold_fast_forward": "nul", "input_hold_fast_forward_btn": "nul",
                     "input_hold_fast_forward_axis": "nul", "input_toggle_fast_forward": "nul",
                     "input_toggle_fast_forward_btn": "nul", "input_toggle_fast_forward_axis": "nul"})
        if HOST_OS == "windows":
            opts["input_enable_hotkey_btn"] = "4"       # Select still gates the emulator's other hotkeys
        opts["fastforward_ratio"] = "16.0"                 # the ramp's top speed; lower speeds = fast-forward part of the time
        # cheats: the game's .cht is placed under <runtime>/cheats/<core library name>/ before launch (see install_cheats)
        opts.update({"cheat_database_path": rt / "cheats", "apply_cheats_after_load": "true", "apply_cheats_after_toggle": "true"})
        if HOST_OS == "windows":
            from .gamepads import retroarch_driver
            driver = retroarch_driver(self.cfg.executable or provision.retroarch_exe(self.config))
            # Native local play: SDL autoconfig + process-scoped SpaceMouse exclusions.
            opts.update({"video_fullscreen": "false", "video_windowed_fullscreen": "true", "video_vsync": "true",
                         "vrr_runloop_enable": "false", "audio_sync": "true",
                         # a named, active output (never a stale default); the next driver when this one stalls
                         "audio_driver": getattr(self, "audio_driver", "xaudio") or "xaudio",
                         "audio_device": getattr(self, "audio_device", "") or "",
                         "audio_wasapi_exclusive_mode": "false",   # shared: other apps + gBox's volume slider keep working
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
        if cap:                                              # the capture backend: vulkan (layer) or glcore (injected)
            _set_core_opts(co, cap.get("core_options") or {})
            opts = capture_backend.retroarch_cfg(opts, cap, work)
            self.states_override = work / "states"
            cfg = work / "retroarch.cfg"
        playback = getattr(self, 'tas_playback', None)
        if playback:
            work = Path(playback['folder'])
            for sub in ('saves', 'states', 'screenshots', 'system'):
                (work/sub).mkdir(parents=True, exist_ok=True)
            co = work/'core-options.cfg'
            co.write_text(playback.get('core_options', ''))
            opts.update(system_directory=work/'system', savefile_directory=work/'saves',
                        savestate_directory=work/'states', screenshot_directory=work/'screenshots',
                        core_options_path=co, rewind_enable='false', run_ahead_enabled='false',
                        preemptive_frames_enable='false', savestate_auto_load='false',
                        savestate_auto_save='false', apply_cheats_after_load='false',
                        input_autodetect_enable='false', input_joypad_driver='null',
                        audio_volume='-34', pause_nonactive='false')
            cfg = work/'retroarch.cfg'
            self.states_override = work/'states'
        from . import memory_card_emulators
        opts=memory_card_emulators.retroarch_options(self,opts,co)
        if getattr(self,'memory_card_context',None):
            from . import memory_card_sessions
            memory_card_sessions.journal(self.memory_card_context)
        cfg.write_text("".join(f'{k} = "{v}"\n' for k, v in opts.items()))
        return cfg

    def _argv(self, rom: str) -> list[str]:
        core = self.cfg.core
        exe = self.cfg.executable or (provision.retroarch_exe(self.config) if self.config else "retroarch")
        if self.config is not None:
            self._p(10, f"Resolving core {core or self.platform} (downloads on first use)")
            rc = self.runtime_check = provision.runtime_check(self.config, self.platform, self.cfg.core, exe)
            core = str(rc["core"])
            self._p(25, f"Core ready: {Path(core).name}" + (" (checked on an earlier launch)" if rc["cached"] else ""))
        elif not core:
            raise ToolUnavailable("retroarch adapter needs 'core' configured")
        cfg = self._write_cfg() if self.config is not None else None
        playback = getattr(self, 'tas_playback', None)
        if playback:
            from . import tas
            if tas.fingerprint(core) != playback['core_sha256']:
                raise Unsupported('This replay requires the exact recorded Mesen core binary')
            self.tas_real_core = core
            self.tas_environment = {'GBOX_TAS_CORE': core, 'GBOX_TAS_PLAY': playback['tape'],
                                    'GBOX_TAS_STATUS': playback['status'],
                                    'GBOX_TAS_FROM': str(playback['start_frame']),
                                    'GBOX_TAS_TO': str(playback['end_frame']),
                                    'GBOX_TAS_LOOP': '1' if playback['loop'] else '0'}
            return [exe, '--config', str(cfg), '-L', str(tas.compile_proxy(self.config.runtime,
                    getattr(self, 'tas_server', ''), getattr(self, 'tas_headers', {}))), '--verbose', rom]
        # SMB1 capture wraps native callbacks and state restores, preserving rewind branches.
        # A capture failure is reported without preventing the operator's game from loading.
        if self.config is not None:
            try:
                from . import tas
                proxy = tas.prepare(self, core, rom)
                if proxy is not None:
                    return [exe, *(["--config", str(cfg)] if cfg else []), "-L", str(proxy), "--verbose", *self.cfg.args, rom]
            except Exception as exc:
                self.tas_capture = {'state': 'unavailable', 'reason': str(exc)[:240]}
        from .gameplay_replay import prepare
        try:
            movie = prepare(self,exe,core,rom) if self.config is not None else []
        except Exception as exc:
            # A full recording disk must never prevent the operator's game from loading.
            self.gameplay_replay = {'state':'failed','reason':type(exc).__name__}
            movie = []
        return [exe, *(["--config", str(cfg)] if cfg else []), "-L", core, "--verbose", *self.cfg.args, *movie, rom]

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
                _link_lst_names(out / lst)
                return str(out / lst)
        except zipfile.BadZipFile:
            return rom

    def _from_lst(self, rom: str) -> str:
        """Unpacked NAOMI/Atomiswave GD-ROM list sets (<game>.lst + data files next to it): Flycast opens
        the .lst itself. When its referenced names all exist next to it, launch in place (the library stays
        read-only). When the set's data file has a different name than the .lst expects, stage a linked copy
        in the runtime extract cache and launch that instead."""
        if not rom.lower().endswith(".lst") or (self.platform or "") not in ("naomi", "naomi2", "atomiswave"):
            return rom
        path = Path(rom)
        try:
            wants = [m[4].strip('"') for m in (re.findall(r'"[^"]+"|\S+', ln)
                     for ln in path.read_text(errors="replace").splitlines()) if len(m) >= 5]
        except OSError:
            return rom
        if not wants or all((path.parent / w).exists() for w in wants):
            return rom                                     # names match: flycast reads the set in place
        if self.config is None or any(Path(w).suffix.lower() not in (".bin", ".dat") for w in wants):
            return rom                                     # ambiguous or nowhere to stage: let flycast report it
        bins = [f for f in path.parent.iterdir() if f.suffix.lower() in (".bin", ".dat")]
        if len(bins) != 1:
            return rom
        import hashlib
        out = self.config.runtime / "extract" / ("lst-" + hashlib.sha1(rom.encode()).hexdigest()[:16])
        staged = out / path.name
        if not staged.exists():
            out.mkdir(parents=True, exist_ok=True)
            self._p(30, f"Staging {Path(rom).name}")
            shutil.copyfile(path, staged)
            shutil.copyfile(bins[0], out / bins[0].name)
        _link_lst_names(staged)
        return str(staged)

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

    def prepare_audio(self):
        if not getattr(self, "capture_backend", None):
            _audio_prefetch(self)

    def _audio_plan(self) -> dict:
        """Drivers to try in order, the device, and the reasoning. Linux / capture sessions: no sound, nothing to try."""
        from . import game_audio
        from .config import GameAudioConfig
        ga = getattr(self.config, "game_audio", None) or GameAudioConfig()
        if HOST_OS != "windows" or getattr(self, "capture_backend", None) or self.config is None:
            return {"ga": ga, "chain": [self.audio_driver], "sel": None}
        sel = _audio_selection(self, 1.0)
        dev = (sel.get("chosen") or {}).get("id")
        first = game_audio.first_driver(self.config.runtime, dev, ga.remember_driver_h)
        chain = game_audio.driver_chain(ga.retroarch_drivers, first)
        self.audio_device = sel.get("retroarch_device") or ""
        self.audio_driver = chain[0]
        return {"ga": ga, "chain": chain, "sel": sel, "remembered": first}

    def _rebind_port(self, failed_ports=()) -> None:
        """Choose an ephemeral UDP port without touching the conflicting listener.
        The probe cannot reserve a port for RetroArch; another collision is handled
        by the launch's bounded retry count. Never reuse a failed attempt's port.
        """
        excluded = {*failed_ports, self.addr[1]}
        for _ in range(8):
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.bind((self.addr[0], 0))
                port = sock.getsockname()[1]
            if port not in excluded:
                self.addr = (self.addr[0], port)
                return
        raise RuntimeError("Could not allocate a fresh network command interface port")

    def launch_game(self, rom: str) -> dict:
        try:
            return self._launch_game(rom)
        finally:
            _audio_release(self)                       # the warm-up stream ends once the emulator has its own

    def _launch_game(self, rom: str) -> dict:
        started = time.monotonic()
        if self.config is not None:
            rom = self._from_lst_zip(self._from_lst(self._from_gme(self._from_old_chd(self._from_7z(rom)))))
        prepared = time.monotonic()
        plan = self._audio_plan()                          # before _argv: the session cfg names driver + device
        argv = self._argv(rom)
        configured = time.monotonic()
        from .scene_support import video_driver
        self.video_driver = video_driver(argv)             # Examine 3D capability matrix (gbox/scene_support.py)
        self.core_path = argv[argv.index("-L") + 1] if "-L" in argv else None
        self.core_path = getattr(self, 'tas_real_core', self.core_path)
        # an OpenGL session can't hold RenderDoc; the capability matrix (scene_support) names the capture session that
        # captures its moment instead (#971), so there is no blanket "unavailable" reason here any more
        self.examine_unavailable_reason = None
        if "-L" in argv and not getattr(self, 'tas_playback', None):
            try:
                n = len(self.install_cheats(self.core_path, rom))
                if n:
                    self._p(76, f"{n} cheat codes available ({self.cheat_source})")
            except Exception:
                pass                                       # cheats are optional; never block a launch
        env = dict(os.environ)
        env.update(getattr(self, 'tas_environment', {}))
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
        from . import game_audio
        ga, chain, attempts, st, watch = plan["ga"], plan["chain"], [], None, None
        # the base boot wait: launch_game boot_timeout_s (#318, the "content not running in time" remedy) or
        # [game_audio] boot_wait_s; content loaded with audio still opening extends past it (extended_wait_s)
        boot_s = float(getattr(self, "boot_timeout_s", None) or ga.boot_wait_s)
        boot_started = time.monotonic()
        n = 0
        netcmd_retries = 0
        failed_ports = set()
        verdict = None
        while n < len(chain):
            driver = chain[n]
            if n and attempts[-1]["outcome"] == "fallback":   # only an audio stall changes drivers
                self.audio_driver = driver
                self._write_cfg()
            self.proc = _popen(self, argv, env=env, stdout=open(self.log_path, "wb"), stderr=subprocess.STDOUT, cwd=work)
            from . import memory_card_sessions
            memory_card_sessions.launched(self)
            if not attempts or attempts[-1]["outcome"] == "netcmd":
                self._p(78, "Emulator process started" + (" on the GPU (VirtualGL)" if argv[0] == VGLRUN else "")
                        + (" · Examine 3D ready" if _examine_ok(self.proc) else ""))
            else:
                self._p(80, f"Audio device slow ({attempts[-1]['reason']}): restarted with the {driver} audio driver")
            watch = game_audio.BootWatch(time.monotonic(), boot_s, max(ga.extended_wait_s, boot_s), ga.init_grace_s,
                                         ga.stall_s, can_fallback=n + 1 < len(chain))
            t0 = time.monotonic()
            verdict, st = self._wait_boot(watch)
            attempts.append({"driver": driver, "outcome": verdict, "port": self.addr[1], "log": str(self.log_path),
                             "s": round(time.monotonic() - t0, 2),
                             "audio_init_s": watch.audio_init_s(time.monotonic()), "reason": watch.reason})
            if verdict == "ready":
                break
            if verdict == "netcmd":
                # Retry only this failed launch. A peer occupying the port stays
                # untouched; the same audio driver, ROM, core and input port remain.
                if netcmd_retries >= 2 or self.config is None or "--config" not in argv:
                    tail = self.log_tail()
                    self.stop_game()
                    raise RuntimeError("retroarch network command interface failed to bind "
                                       f"after {netcmd_retries} port retries: {tail}")
                _kill_tree(self.proc)
                failed_ports.add(self.addr[1])
                netcmd_retries += 1
                try:
                    self._rebind_port(failed_ports)
                    cfg = self._write_cfg()
                    argv[argv.index("--config") + 1] = str(cfg)
                    self.log_path = logs / f"retroarch-{self.addr[1]}.log"
                    self._p(80, "Network command interface could not bind; restarting on a fresh port "
                                f"(attempt {netcmd_retries})")
                except Exception:
                    self.stop_game()
                    raise
                continue                                  # keep the current audio-chain position
            _kill_tree(self.proc)                              # stuck in its audio init: nothing to save yet
            try:                                               # keep the stalled attempt's log as evidence
                shutil.copyfile(self.log_path, self.log_path.with_name(f"{self.log_path.stem}-{driver}.log"))
            except OSError:
                pass
            n += 1
        if verdict != "ready":
            tail = self.log_tail()
            self.stop_game()
            raise RuntimeError(f"retroarch started but {getattr(watch, 'reason', None) or 'boot did not become ready'}: {tail}")
        boot_finished = time.monotonic()
        if any(a["outcome"] == "fallback" for a in attempts) and self.config is not None:
            game_audio.remember(self.config.runtime, ((plan["sel"] or {}).get("chosen") or {}).get("id"),
                                self.audio_driver, attempts[0]["driver"])
        warning = next((a["reason"] for a in attempts if a["outcome"] == "fallback"), None) or \
            (game_audio.AUDIO_WARNING if watch and watch.warning else None)
        audio = game_audio.session_detail(plan["sel"] or {}, self.audio_driver, attempts=attempts,
                                          remembered=plan.get("remembered"),
                                          warning=f"{game_audio.AUDIO_WARNING}: {warning}" if warning else None)
        out = {"pid": self.proc.pid, "display": self.display and self.display.name, "port": self.addr[1],
               "local_window": HOST_OS == "windows", "worker_name": __import__("platform").node(),
               "core": argv[argv.index("-L") + 1], "status": st, "log": str(self.log_path),
               "renderer": self.renderer(), "examine": _examine_ok(self.proc, 5.0), "audio": audio}
        if audio.get("warning"):
            out["warnings"] = [audio["warning"]]
        out["startup_timings"] = {"prepare_s": round(prepared - started, 3),
                                 "configure_s": round(configured - prepared, 3),
                                 "cheats_and_environment_s": round(boot_started - configured, 3),
                                 "boot_s": round(boot_finished - boot_started, 3),
                                 "report_s": round(time.monotonic() - boot_finished, 3)}
        return out

    def _owns_command_port(self) -> bool:
        """Windows launches own their direct Popen PID, not a UDP reply's sender.
        Windows bootstrap installs psutil>=5.9; support both its old and new API
        names. Missing permissions/process/API evidence never confirms ownership.
        """
        try:
            import psutil
        except ImportError:
            return False
        try:
            process = psutil.Process(self.proc.pid)
            connections = getattr(process, "net_connections", None) or process.connections
            return self.proc.poll() is None and any(
                c.laddr and c.laddr.port == self.addr[1] and c.laddr.ip in (self.addr[0], "0.0.0.0")
                for c in connections(kind="udp4"))
        except (psutil.Error, OSError, AttributeError):
            return False

    def _wait_boot(self, watch) -> tuple[str, dict | None]:
        """Poll until ready, audio fallback, a command-port bind failure, or a terminal failure.
        The deadline is the watch's: content loaded with audio still opening waits longer instead of failing."""
        i = 0
        while True:
            try:
                log = self.log_path.read_text(errors="replace")
            except OSError:
                log = ""
            watch.observe(log, time.monotonic())
            if i % 5 == 0:                                     # also how an operator's cancel reaches this loop
                tail = [ln for ln in log[-4000:].splitlines() if ln.strip()]
                try:
                    self._p(80 + min(18.0, 18 * (time.monotonic() - watch.t0) / max(watch.boot_wait_s, 1)),
                            tail[-1][:160] if tail else "Waiting for content to start")
                except Exception:                              # cancelled: don't leave an emulator running
                    self.stop_game()
                    raise
            if self.proc.poll() is not None:
                if self.display:
                    self.display.close()
                raise RuntimeError(f"retroarch exited {self.proc.returncode}: {self.log_tail()}")
            if watch.phase.get("netcmd_down"):
                # Do not query the colliding listener: it is not this process.
                return watch.decide(time.monotonic(), False), None
            st, running = None, False
            try:
                st = self.query_runtime(timeout=0.3)
                running = st.get("state") in ("PLAYING", "PAUSED")
            except RuntimeError:
                pass
            unowned_reply = running and HOST_OS == "windows" and not self._owns_command_port()
            if unowned_reply:
                running = False
            verdict = watch.decide(time.monotonic(), running)
            if verdict in ("ready", "fallback", "netcmd"):
                return verdict, st
            if verdict == "fail":
                if unowned_reply:
                    watch.reason = "the network command interface binding could not be verified for the owned process"
                tail = self.log_tail()
                self.stop_game()
                raise RuntimeError(f"retroarch started but {watch.reason}: {tail}")
            time.sleep(0.2)
            i += 1

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
            with self.log_path.open('rb') as stream:
                stream.seek(max(0, self.log_path.stat().st_size - n))
                return stream.read(n).decode('utf-8', 'replace')
        except (OSError, AttributeError):
            return ""

    def stop_game(self) -> dict:
        # Killed at once (#1504). The old QUIT + wait(5) never ended a Windows session by itself (exit code 1 = the kill
        # that followed, median stop 5.5 s) and left the checkpoint ring time to start a save into a quitting RetroArch.
        # In-game saves are not lost: the session cfg flushes SRAM every few seconds (autosave_interval).
        if getattr(self, 'tas_capture', None):
            from . import tas
            tas.finalize(self)
        if self.stream:
            self.stream.close()
        _kill_tree(self.proc)
        if self.display:
            self.display.close()
        return {"returncode": self.proc.poll() if self.proc else None}

    def _exited(self) -> bool:
        proc = self.__dict__.get("proc")                 # __getattr__ answers op names only; no proc = not ours to judge
        return bool(proc is not None and proc.poll() is not None)

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
        return self._set_paused(True)

    def resume(self) -> dict:
        return self._set_paused(False)

    def _set_paused(self, wanted: bool) -> dict:
        """Send at most one toggle and return only an observed requested state.
        RetroArch may report stale status in the command poll receiving the hotkey.
        Bound the follow-up reads; an unconfirmed transition remains a failure."""
        before = self.query_runtime()
        if before.get("state") in ("PLAYING", "PAUSED") and (before["state"] == "PAUSED") == wanted:
            return before
        self.cmd("PAUSE_TOGGLE")
        for _ in range(12):
            after = self.query_runtime()
            if (after.get("state") == "PAUSED") == wanted and after.get("state") in ("PLAYING", "PAUSED"):
                return after
            time.sleep(0.05)
        raise RuntimeError("Emulator did not confirm " + ("pause" if wanted else "resume"))

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
        """Fast-forward (fastforward_ratio, 16x in the session cfg): a toggle, or on / off as gBox last set it."""
        if on is not None and bool(on) == self.ff_on:
            return {"fast_forward": "on" if self.ff_on else "off"}
        self.cmd("FAST_FORWARD")
        self.ff_on = (not self.ff_on) if on is None else bool(on)
        return {"fast_forward": "toggled", "on": self.ff_on}

    def fast_forward_status(self) -> dict:
        # New RetroArch versions expose the actual toggle, including native hotkeys.
        # Older versions have no such query: retain a clearly labelled tracked state.
        if self.__dict__.get('_ff_option') is not False:
            try:
                reply = self.cmd('GET_OPTION fast_forward', reply=True, timeout=0.25)
                words = (reply or '').split()
                if words == ['fast_forward', 'on'] or words == ['fast_forward', 'off']:
                    self._ff_option = True
                    return {"supported": True, "on": words[-1] == 'on', "source": "emulator"}
            except RuntimeError:
                if self.__dict__.get('_ff_option') is True:
                    raise
            self._ff_option = False
        return {"supported": True, "on": self.ff_on, "source": "tracked"}

    def normal_speed(self) -> dict:
        state = self.fast_forward_status()
        if state['source'] == 'emulator':
            self.cmd('SET_OPTION fast_forward off', reply=True)
            after = self.fast_forward_status()
            if after['on']:
                raise RuntimeError('RetroArch did not clear fast-forward; release the fast-forward hotkey and retry')
        else:
            # Legacy runloop.c clears fastmotion on a fast-forward input edge WHILE
            # PAUSED. A hold pulse while playing just toggles twice and cannot repair
            # a stale toggle. Preserve pause state and never restart the content.
            before = self.query_runtime()
            if before.get('state') not in ('PLAYING', 'PAUSED'):
                raise RuntimeError('RetroArch is not ready to restore normal speed')
            was_paused = before['state'] == 'PAUSED'
            try:
                if not was_paused:
                    self.pause()
                self.cmd('FAST_FORWARD_HOLD\nGET_STATUS', reply=True)
                time.sleep(0.05)
                self.query_runtime()  # a subsequent poll: the hold pulse has been released
            finally:
                if not was_paused:
                    self.resume()
            after = {"supported": True, "on": False, "source": "tracked"}
        self.ff_on = False
        return after

    def state_dir(self) -> Path:
        return getattr(self, "states_override", None) or self.config.runtime / "states"

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
        with self._state_lock:
            requested = self._slot(slot)
            offset = self.log_path.stat().st_size
            started = time.time_ns()
            self.cmd("SAVE_STATE")
            deadline = time.monotonic() + 12
            previous = None
            validation_error = None
            while time.monotonic() < deadline:
                if self._exited():                         # stopped meanwhile: no file is coming, don't hold the stop
                    raise RuntimeError('RetroArch exited before the save state was written')
                with self.log_path.open('rb') as stream:
                    stream.seek(max(offset, self.log_path.stat().st_size - 65536))
                    text = stream.read(65536).decode('utf-8', 'replace')
                matches = re.findall(r'\[State\] Saving state "([^"]+)"', text)
                if matches:
                    path = Path(matches[-1])
                    match = re.search(r'\.state(-?\d+)?$', path.name)
                    if match:
                        try:
                            stat = path.stat()
                        except OSError:
                            stat = None
                        current = (str(path), *_state_file_identity(stat)) if stat else None
                        if (stat and stat.st_size > 0 and stat.st_mtime_ns >= started
                                and current == previous):
                            try:
                                _validate_completed_state_file(path, stat)
                            except (OSError, ValueError) as error:
                                validation_error = str(error)
                                time.sleep(.1)
                                continue
                            actual = int(match[1] or 0)
                            self.slot, self._last_state_path = actual, path
                            result = {'slot': actual, 'requested_slot': requested,
                                      'path': str(path), 'bytes': stat.st_size,
                                      'verified': True, 'slot_verified': actual == requested}
                            if actual != requested:
                                result['warning'] = ('RetroArch dropped relative slot commands; '
                                    'this result identifies the actual saved file, and the slot counter was reconciled.')
                            return result
                        previous = current
                time.sleep(.1)
            detail = f'; last container validation: {validation_error}' if validation_error else ''
            raise RuntimeError('RetroArch did not produce a verified save file; capture was not completed' + detail)

    def checkpoint_target(self) -> Path | None:
        """The file the next SAVE_STATE writes (the current slot), named after the last verified save: the checkpoint
        ring protects that slot before saving into it (#1488). None until a save has shown RetroArch's state folder."""
        last, slot = getattr(self, "_last_state_path", None), int(getattr(self, "slot", 0) or 0)
        if last is None or slot < 0:
            return None
        return last.with_name(re.sub(r'\.state(-?\d+)?$', '.state' + (str(slot) if slot else ''), last.name))

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
        if getattr(self, "capture_backend", None) and getattr(self, "states_override", None):
            return self._screenshot(Path(self.states_override).parent / "shots")
        if HOST_OS == "windows":
            return win_grab(self.proc.pid if self.proc else 0)
        return grab_png(self.display.name if self.display else None)

    def _screenshot(self, shots: Path, timeout: float = 6.0) -> bytes:
        """A capture session's window is parked off-screen (a desktop grab is black): RetroArch's own SCREENSHOT reads
        the frame from the GPU into the session's shots folder."""
        before = set(shots.glob("*.png")) if shots.exists() else set()
        self.cmd("SCREENSHOT")
        t0 = time.time()
        while time.time() - t0 < timeout:
            new = (set(shots.glob("*.png")) if shots.exists() else set()) - before
            if new:
                f = max(new, key=lambda p: p.stat().st_mtime)
                size = -1
                while size != f.stat().st_size:                  # written asynchronously
                    size = f.stat().st_size
                    time.sleep(0.2)
                return f.read_bytes()
            time.sleep(0.1)
        raise RuntimeError("RetroArch did not write a screenshot")

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
        total, gamepad = len(events), 0
        if getattr(self, "remote_port", None):
            # Pad buttons go through RetroArch's network gamepad here too: on lilspark's Xvfb sessions Flycast never
            # saw xdotool keys although its window held focus (#1153), while the UDP pad reached the game at once.
            # L2/R2 stay keyboard hotkeys (rewind / fast-forward) when trigger_hotkeys is on.
            hot = [self.trigger_hotkeys and ev["key"] in ("l2", "r2") and int(ev.get("player", 1)) == 1 for ev in events]
            gamepad, rest = self.remote_input([ev for ev, h in zip(events, hot) if not h])
            events = [ev for ev, h in zip(events, hot) if h] + rest
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
        return {"sent": total, "network_gamepad": gamepad} if gamepad else {"sent": total}

    # Native address -> RetroAchievements RAM offset, for cores without a libretro memory map (Flycast, Dolphin):
    # (segment mask, segment value, offset mask): Dreamcast main RAM 0x0C000000 with P1/P2 mirrors 0x8C/0xAC000000
    # (verified with Flycast: rcheevos registers 16MB SYSTEM RAM at $0); GameCube/Wii MEM1 at 0x80000000/0xC0000000.
    RAM_WINDOWS = {"dreamcast": (0x1F000000, 0x0C000000, 0x00FFFFFF), "naomi": (0x1F000000, 0x0C000000, 0x00FFFFFF),
                   "gamecube": (0x3E000000, 0x00000000, 0x01FFFFFF), "wii": (0x3E000000, 0x00000000, 0x01FFFFFF),
                   "n64": (0x1F800000, 0x00000000, 0x007FFFFF),
                   # NDS main RAM: 4 MiB at 0x02000000 (mirrored to 0x02FFFFFF); melonDS registers it as SYSTEM_RAM at $0
                   "nds": (0xFF000000, 0x02000000, 0x003FFFFF)}

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
        from . import memory_card_sessions
        memory_card_sessions.launched(self)
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
        subprocess.run(["xdotool", *args], env={**os.environ, "DISPLAY": self.display.name}, timeout=5, check=True)

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
    supported = StandaloneAdapter.supported | {'fast_forward'}
    flatpak = "org.DolphinEmu.dolphin-emu"
    screen = (640, 480)                          # GameCube output size; Dolphin's window opens at exactly this
    checkpoint_state, state_glob = "dir", "*.s08"   # gBox's checkpoint ring lives in Dolphin's slot 8 (Shift+F8 / F8)
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

    def _title_options(self) -> dict:
        # SC2 USA (#1922, #1973): the original GRSEAF disc hit Dolphin's
        # "GFX FIFO: Unknown Opcode" CPU/GPU desync warning. Windows' speed
        # defaults below force dual core on, so override it for this exact
        # header identity. The command-line layer leaves saved profiles intact.
        if getattr(self, 'gecko_id', None) == 'GRSEAF':
            return {'Dolphin.Core.CPUThread': 'False'}
        return {}

    def cheat_set(self, index: int, on: bool) -> dict:
        """Dolphin applies Gecko codes when the game boots: the choice is saved now and takes effect on the next start."""
        if not 0 <= index < len(self.cheats):
            raise ValueError(f"no cheat #{index} (this game has {len(self.cheats)})")
        self.cheats[index]["enable"] = on
        self._gecko_write(self.config.runtime / "dolphin-user")
        return {"index": index, "enabled": on, "desc": self.cheats[index]["desc"], "restart_needed": True,
                "note": "Dolphin runs this Gecko code from the next game start (load state / restart the game)"}

    def _argv(self, rom: str) -> list[str]:
        user = Path(getattr(self, 'gameplay_demo_user', self.config.runtime / "dolphin-user"))
        (user / "Config").mkdir(parents=True, exist_ok=True)
        (user / "Config" / "GCPadNew.ini").write_text(self.PAD_INI)
        (user / "Config" / "Hotkeys.ini").write_text('[Hotkeys]\nDevice = XInput2/0/Virtual core pointer\n'
            'Emulation Speed/Disable Emulation Speed Limit = `Tab`\n'
            'Save State/Save State Slot 8 = `Shift_L` & `F8`\n'
            'Load State/Load State Slot 8 = !`Shift_L` & `F8`\n'
            'Save State/Save State Slot 1 = `Shift_L` & `F1`\n'
            'Load State/Load State Slot 1 = !`Shift_L` & `F1`\n')
        self._gecko_setup(user, rom)
        opts = {"Dolphin.General.GDBPort": self.port, "Dolphin.Core.GFXBackend": "Vulkan", "Dolphin.Core.EnableCheats": "True",
                "Dolphin.General.HotkeysRequireFocus": "False",  # private Xvfb has no window manager to give Qt focus
                "Dolphin.Display.Fullscreen": "True", "Dolphin.Interface.ConfirmStop": "False",
                "Dolphin.Analytics.PermissionAsked": "True", "Dolphin.Analytics.Enabled": "False",
                "Dolphin.Input.BackgroundInput": "True", "Dolphin.Core.SIDevice0": "6",   # 6 = standard controller
                # JIT emits breakpoint/watchpoint checks only in debug mode (verified: breakpoints fire, steps work;
                # ponytail: JIT steps can cover a few instructions; Core.CPUCore=0 (interpreter) steps exactly but is slow)
                "Dolphin.Interface.DebugModeEnabled": "True"}
        if str(getattr(self, 'gecko_id', '') or '').startswith('GPO'):
            opts['GFX.Settings.SafeTextureCacheColorSamples'] = '0'  # hash every byte for small live PSO face edits
        from . import memory_card_emulators
        opts.update(memory_card_emulators.dolphin_options(self,rom))
        if getattr(self,'memory_card_context',None):
            from . import memory_card_sessions
            memory_card_sessions.journal(self.memory_card_context)
        extra=[f'--filesystem={getattr(self,"memory_card_context",{}).get("work_dir")}'] if getattr(self,'memory_card_context',None) else []
        opts.update(self._title_options())
        return ["flatpak", "run", "--die-with-parent", f"--filesystem={user}", *extra, self.flatpak, "-b", "-u", str(user),
                *[a for k, v in opts.items() for a in ("-C", f"{k}={v}")], "-e", rom]

    def _debugger(self):
        from .debug import GdbDebugger
        return GdbDebugger("127.0.0.1", self.port, "ppc", connect_timeout=60)

    # gBox's checkpoint ring (Select+L2 on the streamed pad, gbox/rewind.py): Dolphin's slot 8, the operator keeps slot 1
    def state_dir(self) -> Path:
        return Path(getattr(self, 'gameplay_demo_user', self.config.runtime / 'dolphin-user')) / 'StateSaves'

    ff_on = False

    def normal_speed(self) -> dict:
        self._xdo('keyup', 'Tab')
        self.ff_on = False
        return {'supported': True, 'on': False, 'source': 'tracked'}

    def fast_forward(self, on: bool | None = None) -> dict:
        want = not self.ff_on if on is None else bool(on)
        if want != self.ff_on:
            self._xdo('keydown' if want else 'keyup', 'Tab')
            self.ff_on = want
        return {'fast_forward': 'on' if self.ff_on else 'off'}

    def checkpoint_save(self) -> dict:
        self._xdo('keydown', 'Shift_L', 'keydown', 'F8', 'sleep', '0.1', 'keyup', 'F8', 'keyup', 'Shift_L')
        return {"slot": 8}

    def checkpoint_load(self) -> dict:
        self._xdo('keydown', 'F8', 'sleep', '0.1', 'keyup', 'F8')
        return {"slot": 8}


class DolphinWinAdapter(DolphinAdapter):
    """GameCube / Wii on standalone Dolphin on Windows (portable copy in the runtime folder, same release as the Spark's
    flatpak so save states move between them). Docked in the app like RetroArch; the operator's Xbox pad drives the
    GameCube pad; memory + breakpoints through Dolphin's GDB stub, exactly like on the Spark."""
    name = "dolphin"
    supported = (DolphinAdapter.supported - {"stream_session"}) | {"local_window", "fast_forward"}   # native window, frames via get_frame
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
    # gBox's Dolphin hotkeys (Hotkeys.ini, written at every launch): one base key per running Dolphin ("lane": F13, F14 or
    # F15; Dolphin reads Hotkeys.ini only when it starts, so two Dolphins on this PC - a reset's replacement, an Examine 3D
    # capture session - never answer each other's keys) plus right/left Ctrl and right Shift. Hotkeys work without focus
    # (HotkeysRequireFocus False), so nothing else is bound: Esc, F1-F12, Tab... stay the game's / the operator's.
    LANES = ("F13", "F14", "F15")
    HOTKEY_MODS = ("RCONTROL", "RSHIFT", "LCONTROL")
    HOTKEYS = {                                 # Dolphin hotkey -> modifiers held with the lane key (exactly these)
        "Emulation Speed/Disable Emulation Speed Limit": (),          # held while gBox fast-forwards
        "General/Reset": ("RSHIFT",),
        "Load State/Load State Slot 1": ("RCONTROL",),
        "Save State/Save State Slot 1": ("RCONTROL", "RSHIFT"),
        "Load State/Load State Slot 8": ("LCONTROL",),                 # gBox's checkpoint ring (gbox/rewind.py)
        "Save State/Save State Slot 8": ("LCONTROL", "RSHIFT"),
    }
    _MOD_KEY = {"RCONTROL": "Control_R", "RSHIFT": "Shift_R", "LCONTROL": "Control_L"}   # win_send_keys names
    _lanes: dict[str, object] = {}              # lane key -> the adapter holding it (this worker process)
    _lanes_lock = threading.Lock()
    lane = "F13"
    STATE_WAIT_S = 20.0                         # Dolphin compresses and writes a state on its own thread

    @classmethod
    def hotkeys_ini(cls, lane: str) -> str:
        dev = "DInput/0/Keyboard Mouse"
        key = lambda k: f"`{dev}:{k}`"
        lines = ["[Hotkeys]", f"Device = {dev}"]
        for name, mods in cls.HOTKEYS.items():
            expr = " & ".join([key(lane), *[key(m) for m in mods], *[f"!{key(m)}" for m in cls.HOTKEY_MODS if m not in mods]])
            lines.append(f"{name} = {expr}")
        return "\n".join(lines) + "\n"

    def _claim_lane(self) -> str:
        with self._lanes_lock:
            for k, holder in list(self._lanes.items()):     # launches are serialised (tools._LAUNCH_LOCK): another
                proc = getattr(holder, "proc", None)          # holder without a process is a launch that failed
                if holder is self or proc is None or proc.poll() is not None:
                    self._lanes.pop(k, None)
            free = [k for k in self.LANES if k not in self._lanes]
            lane = free[0] if free else self.LANES[0]       # a 4th Dolphin on one PC shares the first lane
            self._lanes[lane] = self
            return lane

    def _release_lane(self):
        with self._lanes_lock:
            if self._lanes.get(self.lane) is self:
                self._lanes.pop(self.lane, None)

    def _hotkey(self, name: str) -> list[dict]:
        """The key presses for one gBox Dolphin hotkey on this Dolphin's lane (fast-forward held stays held)."""
        mods = [self._MOD_KEY[m] for m in self.HOTKEYS[name]]
        seq = [*({"key": m, "down": True} for m in mods), {"key": self.lane, "down": True}, {"key": self.lane, "down": False},
               *({"key": m, "down": False} for m in reversed(mods))]
        if self.ff_on:                                     # the lane key alone = no speed limit: press it again
            seq.append({"key": self.lane, "down": True})
        result = win_send_keys(self.proc.pid, seq, hidden_ok=True)
        if result.get('stopped') or result.get('sent') != len(seq):
            raise RuntimeError('Dolphin hotkey was interrupted before completion; the game was kept running')
        return result

    def _wait_state(self, slot: int, t0: float, timeout: float | None = None) -> Path:
        """The state file Dolphin wrote for this hotkey: <game id>.sNN in StateSaves, newer than t0, size settled."""
        folder, pattern = self.state_dir(), f"*.s{slot:02d}"
        deadline = time.time() + (self.STATE_WAIT_S if timeout is None else timeout)
        last = None
        while time.time() < deadline:
            try:
                fresh = [f for f in folder.glob(pattern) if f.is_file() and f.stat().st_mtime >= t0 - 1]
            except OSError:
                fresh = []
            f = max(fresh, key=lambda p: p.stat().st_mtime) if fresh else None
            size = f.stat().st_size if f else 0
            if f and size > 0 and last == (f, size):
                return f
            last = (f, size) if f else None
            time.sleep(0.3)
        raise RuntimeError(f"Dolphin did not write a save state (slot {slot}) within "
                           f"{self.STATE_WAIT_S if timeout is None else timeout:g} s in {folder}")

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
        user = Path(getattr(self, 'gameplay_demo_user', exe.parent / 'User'))
        if not getattr(self, 'gameplay_demo_user', None):
            (exe.parent / "portable.txt").touch()
        (user / "Config").mkdir(parents=True, exist_ok=True)
        (user / "Config" / "GCPadNew.ini").write_text(self.PAD_INI_WIN)
        self.lane = self._claim_lane()
        (user / "Config" / "Hotkeys.ini").write_text(self.hotkeys_ini(self.lane))   # read once, when this Dolphin starts
        self._gecko_setup(user, rom)
        # Vulkan, not D3D12: Dolphin's D3D12 renderer can hang and stop presenting frames while the CPU core keeps
        # "playing" (gpu_pct 0.0, black frame - Soul Calibur II #1806/#1933). Vulkan matches the Linux adapter and the
        # capture-session backend; RenderDoc still enters through popen_hooked (which covers Vulkan) or the capture
        # session's Vulkan layer, so Examine 3D keeps working.
        opts = {"Dolphin.General.GDBPort": self.port, "Dolphin.Core.GFXBackend": "Vulkan", "Dolphin.Core.EnableCheats": "True",
                # Docked in gBox, Dolphin's render window is a child window: on Windows Dolphin counts it focused only
                # when it is the foreground window, which a child never is, so every hotkey (save / load state, speed
                # limit) was dropped and StateSaves stayed empty. Hotkeys.ini binds only F13-F15 chords, so no key a
                # person presses reaches them (state_transfer "the emulator didn't write a save state", 2026-10-13).
                "Dolphin.General.HotkeysRequireFocus": "False",
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
        # sound (gbox/game_audio.py): Cubeb = WASAPI shared, which follows the default device as it comes and goes;
        # no active output at all = "No Audio Output" (Dolphin's XAudio2 / OpenAL would wait on a missing device)
        from . import game_audio
        self.audio_sel = _audio_selection(self, 1.0)
        opts["Dolphin.DSP.Backend"] = game_audio.dolphin_backend(self.audio_sel)
        if getattr(self, "capture_backend", None):                  # agent-owned capture session (#971): Vulkan via -C,
            opts["Dolphin.Core.GFXBackend"] = "Vulkan"              # Dolphin's command-line layer is never saved
            opts["Dolphin.DSP.Backend"] = "No Audio Output"
        self.audio_backend = opts["Dolphin.DSP.Backend"]
        if str(getattr(self, 'gecko_id', '') or '').startswith('GPO'):
            opts['GFX.Settings.SafeTextureCacheColorSamples'] = '0'
        from . import memory_card_emulators
        opts.update(memory_card_emulators.dolphin_options(self,rom))
        if getattr(self,'memory_card_context',None):
            from . import memory_card_sessions
            memory_card_sessions.journal(self.memory_card_context)
        opts.update(self._title_options())
        return [str(exe), "-b", "-u", str(user), *[a for k, v in opts.items() for a in ("-C", f"{k}={v}")], "-e", rom]

    def cheat_set(self, index: int, on: bool) -> dict:
        if not 0 <= index < len(self.cheats):
            raise ValueError(f"no cheat #{index} (this game has {len(self.cheats)})")
        self.cheats[index]["enable"] = on
        self._gecko_write(self._exe().parent / "User")
        return {"index": index, "enabled": on, "desc": self.cheats[index]["desc"], "restart_needed": True}

    def prepare_audio(self):
        if not getattr(self, "capture_backend", None):
            _audio_prefetch(self)

    def launch_game(self, rom: str) -> dict:
        try:
            return self._launch_game(rom)
        finally:
            _audio_release(self)

    def _launch_game(self, rom: str) -> dict:
        self._p(10, "Starting Dolphin")
        started = time.monotonic()
        argv = self._argv(rom)
        configured = time.monotonic()
        logs = self.config.runtime / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        self.log_path = logs / f"dolphin-win-{self.port}.log"
        si = subprocess.STARTUPINFO()                                # minimized, no focus: no boot window on screen;
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW                # the app docks (and restores) the game window
        si.wShowWindow = 4 if getattr(self, 'gameplay_demo_user', None) else 7  # idle demo visible without activation
        if getattr(self, "capture_backend", None):
            si = capture_start()                                     # a minimized window presents no frames to capture
        self.proc = _popen(self, argv, stdout=open(self.log_path, "wb"), stderr=subprocess.STDOUT, cwd=str(Path(argv[0]).parent),
                           startupinfo=si)
        from . import memory_card_sessions
        memory_card_sessions.launched(self)
        self._p(70, "Dolphin started; releasing the boot hold")
        spawned = time.monotonic()
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
        released = time.monotonic()
        from . import game_audio
        out = {"pid": self.proc.pid, "local_window": True, "debug_port": self.port, "debugger": bool(self.dbg),
                "worker_name": __import__("platform").node(), "emulator": "dolphin (Windows)", "log": str(self.log_path),
                "examine": _examine_ok(self.proc, 10.0),
                "audio": game_audio.session_detail(getattr(self, "audio_sel", None) or {}, getattr(self, "audio_backend", None))}
        out["startup_timings"] = {"configure_s": round(configured - started, 3), "spawn_s": round(spawned - configured, 3),
                                 "boot_hold_s": round(released - spawned, 3), "report_s": round(time.monotonic() - released, 3)}
        return out

    def stop_game(self) -> dict:
        if self.paused_tids:
            self.resume()
        if self.ff_on:                                     # never leave the lane key held down after the game is gone
            try:
                win_send_keys(self.proc.pid, [{"key": self.lane, "down": False}])
            except Exception:
                pass
            self.ff_on = False
        if self.dbg:
            try:
                self.dbg.close()
            except Exception:
                pass
        _kill_tree(self.proc)
        self._release_lane()
        return {"returncode": self.proc.poll() if self.proc else None}

    def get_frame(self) -> bytes:
        return win_grab(self.proc.pid)

    paused_tids: list | None = None

    def _memory_control_lock(self):
        # DolphinProcMem is the cached debugger() object used by all memory
        # reads and writes, including generic tools and cheat freezes.
        from contextlib import nullcontext
        return getattr(getattr(self, 'dbg', None), 'lock', None) or nullcontext()

    def pause(self) -> dict:
        """Dolphin has no pause command gBox can send; its emulation threads are suspended instead (window stays live)."""
        with self._memory_control_lock():
            if not self.paused_tids:
                self.paused_tids = win_suspend_emulation(self.proc.pid)
            return {"state": "PAUSED", "threads": len(self.paused_tids)}

    def resume(self) -> dict:
        with self._memory_control_lock():
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
        """Dolphin's slot 1 (gBox's Save state / state_transfer). Confirmed by the file Dolphin writes, or it raises."""
        t0 = time.time()
        self._hotkey("Save State/Save State Slot 1")
        f = self._wait_state(1, t0)
        return {"slot": 1, "path": str(f), "bytes": f.stat().st_size, "verified": True}

    def load_state(self, slot: int | None = None) -> dict:
        self._hotkey("Load State/Load State Slot 1")
        return {"slot": 1}

    def reset(self) -> dict:
        """The console's reset button (Dolphin's Reset hotkey on this Dolphin's lane): the game restarts in place, same
        disc, same mod, same window; the session and its view stay."""
        if self.ff_on:                                     # a reset leaves fast-forward off
            win_send_keys(self.proc.pid, [{"key": self.lane, "down": False}])
            self.ff_on = False
        self._hotkey("General/Reset")
        return {"reset": True, "via": f"Dolphin hotkey ({self.lane} lane)"}

    # gBox's checkpoint ring (Select+L2 rewind, gbox/rewind.py) uses Dolphin's slot 8: the operator's slot 1 is untouched.
    # Its hotkeys are keystrokes into the game window (win_send_keys focuses it): checkpoints only while the pad is in use.
    checkpoint_when_playing = True
    # The ring's hotkeys never reached a docked Dolphin before HotkeysRequireFocus=False, so it never saved. Now that they
    # land, a save state (which stalls the game while Dolphin serialises it) is taken at most every 20 s, like Flycast.
    checkpoint_min_interval_s = FLYCAST_CHECKPOINT_MIN_S

    def state_dir(self) -> Path:
        user = getattr(self, 'gameplay_demo_user', None)
        return (Path(user) if user else self._exe().parent / 'User') / 'StateSaves'

    def checkpoint_save(self) -> dict:
        self._hotkey("Save State/Save State Slot 8")
        return {"slot": 8}

    def checkpoint_load(self) -> dict:
        self._hotkey("Load State/Load State Slot 8")
        return {"slot": 8}

    ff_on = False

    def normal_speed(self) -> dict:
        # Release even if our cached toggle says off: a missed release is recoverable.
        result = win_send_keys(self.proc.pid, [{"key": self.lane, "down": False}], hidden_ok=True)
        if result.get('sent') != 1 or result.get('stopped'):
            raise RuntimeError('Dolphin did not receive the speed-limit key release')
        self.ff_on = False
        return {"supported": True, "on": False, "source": "tracked"}

    def fast_forward(self, on: bool | None = None) -> dict:
        """Hold Dolphin's "Disable Emulation Speed Limit" hotkey (this Dolphin's lane key alone) while gBox fast-forwards."""
        want = (not self.ff_on) if on is None else bool(on)
        if want != self.ff_on:
            result = win_send_keys(self.proc.pid, [{"key": self.lane, "down": want}], hidden_ok=True)
            if result.get('sent') != 1 or result.get('stopped'):
                raise RuntimeError('Dolphin did not receive the speed-limit hotkey')
            self.ff_on = want
        return {"fast_forward": "on" if self.ff_on else "off"}


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

    def reset(self) -> dict:
        """mGBA's own Reset (Ctrl+R in its window on the session's private display): the session and its stream stay."""
        self._xdo("key", "ctrl+r")
        return {"reset": True, "via": "mGBA Ctrl+R"}


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

    def reset(self) -> dict:
        """MAME's soft reset (F3, its default UI key) on the session's private display: the session and its stream stay."""
        self._xdo("key", "F3")
        return {"reset": True, "via": "MAME soft reset (F3)"}


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
        self.video_driver = None                       # Yuzu's renderer (qt-config.ini), for the Examine 3D matrix

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
        from .capture_backend import yuzu_backend
        self.video_driver = yuzu_backend(exe.parent / "user" / "config" / "qt-config.ini")
        env = gamepads.emulator_environment(os.environ)
        if getattr(self, "examine", False) and self.video_driver == "vulkan":
            # Examine 3D (#971): RenderDoc's Vulkan layer for this process only (no injection, Yuzu's config untouched)
            from . import scene_capture
            self.proc = scene_capture.popen_layer([str(exe), "-g", rom], self.config.runtime / "scene_capture" / "rdc",
                                                  cwd=exe.parent, startupinfo=hidden_start(), env=env)
        else:
            self.proc = subprocess.Popen([str(exe), "-g", rom], cwd=exe.parent, startupinfo=hidden_start(), env=env)
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
                "worker_name": __import__("platform").node(), "emulator": "yuzu", "renderer": self.video_driver,
                "examine": _examine_ok(self.proc, 10.0)}

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


class SaveMGOAdapter(Adapter):
    """The owned MGO2PC portable runner; never provision or configure generic RPCS3."""
    name = 'savemgo'
    supported = {'launch_game', 'stop_game', 'query_runtime'}
    checkpoint_state = False
    checkpoint_reason = 'SaveMGO has no verified in-place checkpoint interface'

    def __init__(self, config: Config, game: dict):
        self.config, self.game, self.proc, self._lease = config, game, None, None

    def prepare_bundle(self, archive: Path) -> Path:
        from . import savemgo
        self.bundle = savemgo.prepare(archive, self.config, getattr(self, 'progress', None),
            expected_fingerprint=self.game['launch'].get('source_fingerprint'))
        return self.bundle['eboot']

    def _release_lease(self):
        if self._lease is not None:
            lease, self._lease = self._lease, None
            lease.__exit__(None, None, None)

    def launch_game(self, rom: str) -> dict:
        from . import savemgo
        if not getattr(self, 'bundle', None) or Path(rom) != self.bundle['eboot']:
            raise ValueError('SaveMGO must be prepared from its complete verified package')
        if getattr(self, 'capture_backend', None):
            raise Unsupported('The bundled SaveMGO emulator has no verified RenderDoc capture path')
        self.home = self.bundle['home']
        lease = savemgo.runtime_lease(self.home)
        lease.__enter__()
        self._lease = lease
        try:
            # Keep the vendor runtime and account/graphics configuration. Bind
            # only its stock DualSense selection to a connected local XInput pad.
            from . import gamepads
            gamepads.bind_savemgo_xinput(self.home, gamepads.xinput_devices())
            self.proc = subprocess.Popen([str(self.bundle['executable']), '--no-gui', rom],
                                         cwd=self.home, startupinfo=hidden_start())
            keep_offscreen(self.proc.pid)
            self.proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass  # Alive; window creation and shader compilation may continue.
        except BaseException:
            _kill_tree(self.proc)
            self._release_lease()
            raise
        else:
            self._release_lease()
            raise RuntimeError(f'SaveMGO bundled emulator exited during startup (code {self.proc.returncode})')
        return {'pid': self.proc.pid, 'eboot': rom, 'local_window': True,
                'worker_name': __import__('platform').node(), 'examine': False,
                'bundled_runtime': {'kind': 'savemgo_bundle', 'verified': True,
                    'source_fingerprint': self.bundle['source_fingerprint'],
                    'archive_sha256': self.bundle['archive_sha256'],
                    'reused': self.bundle['reused'], 'settings': 'bundled, per-PC',
                    'healed_files': self.bundle.get('healed_files', [])},
                'startup': 'process running; awaiting game window'}

    def stop_game(self) -> dict:
        _kill_tree(self.proc)
        running = bool(self.proc and self.proc.poll() is None)
        if not running:
            self._release_lease()
        return {'returncode': self.proc.poll() if self.proc else None, 'ended': not running}

    def query_runtime(self) -> dict:
        running = bool(self.proc and self.proc.poll() is None)
        if not running:
            self._release_lease()
        return {'running': running, 'paused': False}


class RPCS3Adapter(Adapter):
    """Windows node: PS3 games (extracted disc folders) in RPCS3. Guest memory is read/written straight from the
    emulator process (PS3 addresses map 1:1 onto a 4 GiB-aligned host reservation); pause/resume freeze the whole
    emulator, which is how a mechanic can be held mid-flight while something else decides its outcome."""
    name = "rpcs3"
    # no stream_session: the game plays in its own native window, and a 60 fps gdigrab desktop capture next to a
    # GPU-rendered game made it stutter (same reason RetroArch native windows aren't streamed)
    supported = {"launch_game", "stop_game", "query_runtime", "get_frame", "read_memory", "write_memory", "pause", "resume",
                 "save_state", "load_state"}
    # save state = F2 "save and continue" (RPCS3 reloads the game from it), load = a relaunch: no in-place checkpoint
    # every two seconds; Select+L2 reports itself unsupported here (gbox/rewind.py)
    checkpoint_state, checkpoint_reason = False, "RPCS3 reloads the game on every save state (no in-place rewind)"

    def __init__(self, config: Config):
        self.config, self.proc, self.stream, self.base, self.paused = config, None, None, None, False

    def prepare_audio(self):
        if not getattr(self, "capture_backend", None):
            _audio_prefetch(self)

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
            # sound (gbox/game_audio.py): Cubeb = WASAPI shared, follows device changes; Null with no active output
            from . import game_audio
            self.audio_sel = _audio_selection(self, 1.0)
            cc.write_text(graphics.rpcs3_yaml(graphics.get(self.config, getattr(self, "game_id", None)))
                          + game_audio.rpcs3_audio_yaml(self.audio_sel), encoding="utf-8")
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
        argv = [str(home / "rpcs3.exe"), "--no-gui"]
        cap = getattr(self, "capture_backend", None)
        if cap:                                            # agent-owned capture session (#971): Vulkan in a config file of
            from .capture_backend import rpcs3_renderer_yaml      # its own, passed with --config (never the shared one)
            own = self.config.runtime / "capture_sessions" / f"rpcs3-{int(time.time() * 1000)}.yml"
            own.parent.mkdir(parents=True, exist_ok=True)
            base = cc.read_text(encoding="utf-8") if getattr(self, "serial", None) and cc.exists() else ""
            own.write_text(rpcs3_renderer_yaml(base, "Vulkan"), encoding="utf-8")
            argv += ["--config", str(own)]
        if getattr(self, "examine", False):
            # Examine 3D (#971): RPCS3 renders with Vulkan by default; RenderDoc's Vulkan layer for this process only
            from . import scene_capture
            self.proc = scene_capture.popen_layer([*argv, rom], self.config.runtime / "scene_capture" / "rdc", cwd=home,
                                                  startupinfo=capture_start() if cap else hidden_start())
        else:
            self.proc = subprocess.Popen([*argv, rom], cwd=home, startupinfo=hidden_start())
        keep_offscreen(self.proc.pid, **({"limit_s": 1800.0, "give_up_s": float("inf")} if cap else {}))
        _audio_release(self)
        from . import game_audio
        sel = getattr(self, "audio_sel", None)
        backend = game_audio.rpcs3_audio_yaml(sel).split("Renderer: ")[1].strip() if sel else "RPCS3 global setting"
        return {"pid": self.proc.pid, "eboot": rom, "local_window": True, "worker_name": __import__("platform").node(),
                "examine": _examine_ok(self.proc, 15.0) if getattr(self, "examine", False) else False,
                "audio": game_audio.session_detail(sel or {}, backend)}

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


def for_game(game: dict, config: Config, debug: bool = False, *, mod: str | None = None) -> Adapter:
    """Pick the adapter for a catalog entry on THIS node. debug=True prefers an emulator with a full CPU debugger."""
    plat = game["platform"]
    if debug and HOST_OS == "linux" and plat in DEBUG_ADAPTERS:
        return DEBUG_ADAPTERS[plat](config, plat)
    if plat == "pc_steam":
        return SteamAdapter()
    if (game.get('launch') or {}).get('kind') == 'savemgo_bundle':
        if plat != 'ps3':
            raise ToolUnavailable('The SaveMGO bundle must be catalogued as PS3')
        if HOST_OS != 'windows':
            raise ToolUnavailable('The bundled SaveMGO emulator runs on a Windows PC')
        if mod or game.get('mod'):
            raise Unsupported('SaveMGO file-mod builds need a verified package writer')
        return SaveMGOAdapter(config, game)
    # Older catalog rows called original Xbox games windows_native. Match their
    # physical collection too, before the broken RocketLauncher wrapper path.
    from .xbox import XboxAdapter, is_xbox_game
    if is_xbox_game(game):
        xbox_override = config.emulators.get("xbox") or config.emulators.get(plat)
        if xbox_override and xbox_override.adapter == "command":
            return CommandAdapter(xbox_override)
        if HOST_OS != "windows":
            raise ToolUnavailable("Original Xbox games run in Cxbx-Reloaded on a Windows worker")
        from .doa3_native import Doa3NativeAdapter, supports_game
        if supports_game(game):
            # Asset-only variants keep the exact pinned guest executable. The
            # native adapter verifies that hash before it creates a play disc.
            return Doa3NativeAdapter(config, game | {"mod": mod or game.get("mod") or ""})
        return XboxAdapter(config)
    from . import systems
    if game.get("core") and plat != "arcade" and systems.core_for(plat)[0] is None:
        game = game | {"core": None}                       # catalog still has a core the platform rule has since dropped
    override = config.emulators.get(plat)
    if override and override.adapter == "command":
        return CommandAdapter(override)
    launch = game.get("launch") or {}
    # A HyperSpin PS3 entry is an empty "<name>.txt" stub beside its disc folder. RocketLauncher's RPCS3.ahk only
    # resolves that folder's EBOOT.BIN, and on the test PCs every RocketLauncher run throws "RLDLL.Start - Exception
    # thrown: -2" and exits 0 within ~15 s: a black screen with no save state (#1093). Boot the stub's EBOOT in
    # gBox's own RPCS3 instead (tools._launch_game resolves it), which keeps save/load state for recovery.
    if plat == "ps3" and (launch.get("kind") != "attract"
                          or str(launch.get("rel_path") or game.get("rel_path") or "").lower().endswith(".txt")):
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
