"""Xbox 360 on Windows nodes: Xenia Canary adapter with guest memory access and a keyboard virtual pad.

Xenia itself is NOT downloaded by gBox (operator decision pending). ensure_xenia(cfg) uses, in order:
  1. a Xenia Canary already placed in <runtime>/xenia/xenia-canary (xenia_canary.exe), e.g. installed by the operator;
  2. the library's own RocketLauncher build (<library>/emulators/xenia-canary), copied once to the local runtime
     (binaries are never run off the network share).
It checks prerequisites (64-bit Windows 10/11, MSVC 2015-2022 x64 runtime, a Direct3D 12 or Vulkan GPU) and writes a
portable setup (portable.txt + xenia-canary.config.toml next to the exe). Anything it can't fix becomes a clear error.

Memory: Xbox 360 guest virtual address A lives at host virtual_membase + A (+0x1000 for A >= 0xE0000000 on Windows);
virtual_membase is the first free 1<<n (n >= 32), normally 0x100000000 (xenia memory.cc). The guest is big-endian PPC.
"""
import ctypes
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .config import HOST_OS, Config
from .registry import ToolUnavailable, Unsupported

EXE = "xenia_canary.exe"


class XeniaSetupError(ToolUnavailable):
    """Something the operator has to fix (shown verbatim in the launch error)."""


def home(cfg: Config) -> Path:
    return cfg.runtime / "xenia"


def install_dir(cfg: Config) -> Path:
    return home(cfg) / "xenia-canary"


def _p(progress, pct, msg):
    if progress:
        progress(pct, msg)


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --- prerequisites ----------------------------------------------------------------------------

def check_os() -> dict:
    if HOST_OS != "windows":
        raise XeniaSetupError("Xbox 360 games run in Xenia on a Windows node")
    if platform.machine().lower() not in ("amd64", "x86_64") or sys.maxsize < 2**32:
        raise XeniaSetupError(f"Xenia needs 64-bit x86 Windows (this is {platform.machine()})")
    v = sys.getwindowsversion()
    if v.major < 10:
        raise XeniaSetupError(f"Xenia needs Windows 10 or 11 (this is Windows {platform.release()} build {v.build})")
    return {"windows": platform.release(), "build": v.build}


def vcredist_version() -> tuple[int, int] | None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            if winreg.QueryValueEx(k, "Installed")[0] != 1:
                return None
            return winreg.QueryValueEx(k, "Major")[0], winreg.QueryValueEx(k, "Minor")[0]
    except OSError:
        return None


def check_vcredist() -> str:
    v = vcredist_version()
    if not v or v < (14, 30):
        raise XeniaSetupError("Xenia needs the Microsoft Visual C++ 2015-2022 x64 runtime (14.30+): install "
                              "vc_redist.x64.exe from https://aka.ms/vs/17/release/vc_redist.x64.exe, then launch again")
    return f"{v[0]}.{v[1]}"


def d3d12_ok() -> bool:
    """D3D12CreateDevice(default adapter, feature level 11_0, ID3D12Device, NULL) returns S_FALSE when it would succeed."""
    try:
        d3d = ctypes.WinDLL("d3d12.dll")
    except OSError:
        return False

    class GUID(ctypes.Structure):
        _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]
    iid = GUID(0x189819F1, 0x1DB6, 0x4B57, (ctypes.c_ubyte * 8)(0xBE, 0x54, 0x18, 0x21, 0x33, 0x9B, 0x85, 0xF7))
    d3d.D3D12CreateDevice.restype = ctypes.c_long
    return d3d.D3D12CreateDevice(None, 0xB000, ctypes.byref(iid), None) in (0, 1)


def vulkan_devices() -> int:
    """Number of Vulkan physical devices (0 = no usable Vulkan driver)."""
    try:
        vk = ctypes.WinDLL("vulkan-1.dll")
    except OSError:
        return 0

    class AppInfo(ctypes.Structure):
        _fields_ = [("sType", ctypes.c_int), ("pNext", ctypes.c_void_p), ("pApplicationName", ctypes.c_char_p),
                    ("applicationVersion", ctypes.c_uint32), ("pEngineName", ctypes.c_char_p),
                    ("engineVersion", ctypes.c_uint32), ("apiVersion", ctypes.c_uint32)]

    class CreateInfo(ctypes.Structure):
        _fields_ = [("sType", ctypes.c_int), ("pNext", ctypes.c_void_p), ("flags", ctypes.c_uint32),
                    ("pApplicationInfo", ctypes.POINTER(AppInfo)), ("enabledLayerCount", ctypes.c_uint32),
                    ("ppEnabledLayerNames", ctypes.c_void_p), ("enabledExtensionCount", ctypes.c_uint32),
                    ("ppEnabledExtensionNames", ctypes.c_void_p)]
    app = AppInfo(0, None, b"gbox-probe", 1, b"gbox", 1, (1 << 22) | (1 << 12))      # VK_API_VERSION_1_1
    ci = CreateInfo(1, None, 0, ctypes.pointer(app), 0, None, 0, None)
    inst = ctypes.c_void_p()
    if vk.vkCreateInstance(ctypes.byref(ci), None, ctypes.byref(inst)) != 0:
        return 0
    n = ctypes.c_uint32()
    try:
        vk.vkEnumeratePhysicalDevices(inst, ctypes.byref(n), None)
    finally:
        vk.vkDestroyInstance(inst, None)
    return n.value


def pick_gpu_backend() -> str:
    if d3d12_ok():
        return "d3d12"
    if vulkan_devices():
        return "vulkan"
    raise XeniaSetupError("no Direct3D 12 or Vulkan capable GPU/driver found: Xenia needs one of them "
                          "(update the graphics driver, or use a PC with a DX12/Vulkan GPU)")


# --- locating Xenia -----------------------------------------------------------------------------

def receipt(cfg: Config) -> dict | None:
    try:
        return json.loads((home(cfg) / "installed.json").read_text())
    except (OSError, ValueError):
        return None


def installed_ok(cfg: Config) -> bool:
    """xenia_canary.exe is in the runtime and is a PE file (a 0-byte / truncated copy counts as broken)."""
    exe = install_dir(cfg) / EXE
    try:
        with open(exe, "rb") as f:
            return f.read(2) == b"MZ" and exe.stat().st_size > 1_000_000
    except OSError:
        return False


def _write_portable(d: Path):
    (d / "portable.txt").touch()
    cfg = d / "xenia-canary.config.toml"
    if not cfg.exists():                     # Xenia fills in every other option itself on first start
        cfg.write_text('[Display]\nfullscreen = false\n\n[HID]\nhid = "any"\nkeyboard_mode = 1\n\n'
                       '[General]\ndiscord = false\n', encoding="utf-8")


def library_copies(cfg: Config) -> list[Path]:
    """Xenia Canary folders shipped with the configured libraries (RocketLauncher's emulators/xenia-canary)."""
    out = []
    for lib in cfg.libraries:
        root = lib.root("windows")
        if root and (root / "emulators" / "xenia-canary" / EXE).exists():
            out.append(root / "emulators" / "xenia-canary")
    return out


def _copy_from_library(cfg: Config, src: Path) -> dict:
    dst = install_dir(cfg)
    dst.mkdir(parents=True, exist_ok=True)
    for n in (EXE, "gamecontrollerdb.txt", "LICENSE"):
        if (src / n).exists():
            shutil.copy2(src / n, dst / n)
    exe = dst / EXE
    rec = {"tag": "library-copy", "source": str(src), "exe_sha256": _sha256(exe), "exe_size": exe.stat().st_size,
           "exe_date": time.strftime("%Y-%m-%d", time.localtime(exe.stat().st_mtime)), "at": time.time()}
    (home(cfg) / "installed.json").write_text(json.dumps(rec, indent=1))
    return rec


def ensure_xenia(cfg: Config, progress=None) -> dict:
    """Return {exe, gpu, version, ...}. Raises XeniaSetupError with what the operator must do when it can't be fixed here."""
    info = {"os": check_os()}
    _p(progress, 8, "Checking Xbox 360 prerequisites (VC++ runtime, GPU)")
    info["vcredist"] = check_vcredist()
    info["gpu"] = pick_gpu_backend()
    if not installed_ok(cfg):
        srcs = library_copies(cfg)
        if not srcs:
            raise XeniaSetupError(f"Xenia Canary is not installed: put xenia_canary.exe (official build from "
                                  f"github.com/xenia-canary/xenia-canary-releases) into {install_dir(cfg)}")
        _p(progress, 20, f"Copying Xenia Canary from {srcs[0]} to the local runtime")
        info["installed"] = _copy_from_library(cfg, srcs[0])
    _write_portable(install_dir(cfg))
    r = receipt(cfg) or {}
    return info | {"exe": str(install_dir(cfg) / EXE), "version": r.get("tag") or "operator-installed",
                   "source": r.get("source")}


# --- adapter -------------------------------------------------------------------------------------

_cvars: dict[tuple, bytes] = {}


def cvar_known(exe: str, name: str) -> bool:
    """Does this Xenia build define option `name`? (cvar names are plain strings in the exe)"""
    st = Path(exe).stat()
    key = (exe, st.st_size, st.st_mtime)
    if key not in _cvars:
        _cvars.clear()
        _cvars[key] = Path(exe).read_bytes()
    return b"\0" + name.encode() + b"\0" in _cvars[key]


# gBox pad button -> Windows virtual key, bound in Xenia's keyboard driver (keyboard_mode=1, keybind_* flags at launch).
PAD_VK = {"a": 0x4A, "b": 0x4B, "x": 0x55, "y": 0x49,                                  # J K U I
          "l": 0x51, "r": 0x45, "l2": 0x31, "r2": 0x33,                               # Q E 1 3  (LB RB LT RT)
          "start": 0x0D, "back": 0x08, "select": 0x08, "guide": 0x48,                 # Enter Backspace H
          "l3": 0x46, "r3": 0x47,                                                     # F G
          "up": 0x54, "down": 0x42, "left": 0x56, "right": 0x4E,                      # T B V N  (d-pad)
          "lup": 0x57, "ldown": 0x53, "lleft": 0x41, "lright": 0x44,                  # W S A D  (left stick)
          "rup": 0x26, "rdown": 0x28, "rleft": 0x25, "rright": 0x27}                  # arrows   (right stick)
_KEYBIND = {"a": "keybind_a", "b": "keybind_b", "x": "keybind_x", "y": "keybind_y", "l": "keybind_left_shoulder",
            "r": "keybind_right_shoulder", "l2": "keybind_left_trigger", "r2": "keybind_right_trigger",
            "start": "keybind_start", "back": "keybind_back", "guide": "keybind_guide", "l3": "keybind_left_thumb",
            "r3": "keybind_right_thumb", "up": "keybind_dpad_up", "down": "keybind_dpad_down", "left": "keybind_dpad_left",
            "right": "keybind_dpad_right", "lup": "keybind_left_thumb_up", "ldown": "keybind_left_thumb_down",
            "lleft": "keybind_left_thumb_left", "lright": "keybind_left_thumb_right", "rup": "keybind_right_thumb_up",
            "rdown": "keybind_right_thumb_down", "rleft": "keybind_right_thumb_left", "rright": "keybind_right_thumb_right"}


def _xinput_connected() -> set[int]:
    """Slots that have a real XInput pad right now (the keyboard pad goes to the first free one)."""
    x = None
    for dll in ("xinput1_4.dll", "xinput9_1_0.dll"):
        try:
            x = ctypes.WinDLL(dll)
            break
        except OSError:
            pass
    if not x:
        return set()
    buf = (ctypes.c_ubyte * 16)()
    return {i for i in range(4) if x.XInputGetState(i, buf) == 0}


class XeniaAdapter:
    """Xbox 360 (Xenia Canary) on a Windows node. The game plays in Xenia's own window (docked into gBox)."""
    name = "xenia"
    supported = {"launch_game", "stop_game", "query_runtime", "get_frame", "send_input", "read_memory", "write_memory",
                 "query_memory_map", "pause", "resume"}

    def __init__(self, config: Config, platform: str = "xbox360"):
        self.config, self.platform = config, platform
        self.proc = self.stream = self.base = self._handle = self.log_path = None
        self.paused, self.info, self.pad_slot = False, {}, 0

    # Adapter protocol (same as adapters.Adapter; imported lazily so adapters.py can import this module)
    def get_capabilities(self) -> dict[str, str]:
        from .adapters import OPS
        return {op: ("supported" if op in self.supported else "unsupported") for op in OPS}

    def __getattr__(self, op):
        from .adapters import OPS
        if op in OPS:
            def unsupported(*a, **k):
                raise Unsupported(f"{self.name} does not support {op}")
            return unsupported
        raise AttributeError(op)

    def _p(self, pct, msg):
        cb = getattr(self, "progress", None)
        if cb:
            cb(pct, msg)

    def argv(self, rom: str) -> list[str]:
        exe = self.info["exe"]
        # Xenia quits silently on an unknown flag, and its options changed across builds: pass only what this build has.
        # New keyboard driver (keyboard_mode, ~2025+): key events from the window, any pad slot -> posted keys work.
        # Old "winkey" driver (2023): reads the physical keyboard (GetAsyncKeyState), pad slot 0 only.
        self.new_kbd = cvar_known(exe, "keyboard_mode")
        used = _xinput_connected()
        self.pad_slot = next((i for i in range(4) if i not in used), 3) if self.new_kbd else 0
        logs = self.config.runtime / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        self.log_path = logs / f"xenia-{int(time.time())}.log"
        flags = {"fullscreen": "false", "gpu": self.info["gpu"], "hid": "any", "keyboard_mode": "1",
                 "keyboard_user_index": str(self.pad_slot), "discord": "false", "log_file": str(self.log_path),
                 "mount_cache": "true"} | {_KEYBIND[k]: f"0x{vk:02X}" for k, vk in PAD_VK.items() if k in _KEYBIND}
        # sound (gbox/game_audio.py): no active output -> apu=nop (its xaudio2 init would wait on nothing)
        from . import game_audio
        from .adapters import _audio_selection
        self.audio_sel = _audio_selection(self, 1.0)
        if apu := game_audio.xenia_apu(self.audio_sel):
            flags["apu"] = apu
        self.audio_backend = flags.get("apu") or "default (xaudio2)"
        return [exe, rom, *[f"--{k}={v}" for k, v in flags.items() if cvar_known(exe, k)]]

    def prepare_audio(self):
        from .adapters import _audio_prefetch
        _audio_prefetch(self)

    def launch_game(self, rom: str) -> dict:
        from .adapters import _audio_release
        try:
            return self._launch_game(rom)
        finally:
            _audio_release(self)

    def _launch_game(self, rom: str) -> dict:
        self._p(6, "Checking Xenia")
        self.info = ensure_xenia(self.config, getattr(self, "progress", None))
        self._p(60, f"Xenia {self.info.get('version')} ready · GPU {self.info['gpu']}")
        __import__("gbox.graphics", fromlist=["x"]).prefer_gpu(self.info["exe"])     # the discrete GPU
        from .adapters import _pid_window, hidden_start, keep_offscreen
        self.proc = subprocess.Popen(self.argv(rom), cwd=Path(self.info["exe"]).parent, startupinfo=hidden_start(),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        keep_offscreen(self.proc.pid)                         # minimized / off-screen until gBox docks it
        for _ in range(120):                                  # window up within 60 s, process alive
            if self.proc.poll() is not None:
                raise RuntimeError(f"xenia exited {self.proc.returncode}: {self.log_tail()}")
            if _pid_window(self.proc.pid):
                break
            time.sleep(0.5)
        else:
            self.stop_game()
            raise RuntimeError(f"xenia started but opened no window in 60 s: {self.log_tail()}")
        self._p(90, "Xenia window open; title booting")
        return {"pid": self.proc.pid, "local_window": True, "worker_name": platform.node(), "emulator": "xenia_canary",
                "version": self.info.get("version"), "gpu": self.info["gpu"], "keyboard_pad_slot": self.pad_slot,
                "log": str(self.log_path),
                "audio": __import__("gbox.game_audio", fromlist=["x"]).session_detail(
                    getattr(self, "audio_sel", None) or {}, getattr(self, "audio_backend", None))}

    def log_tail(self, n: int = 1500) -> str:
        try:
            return self.log_path.read_text(errors="replace")[-n:]
        except (OSError, AttributeError):
            return ""

    def stop_game(self) -> dict:
        from .adapters import _kill_tree
        if self.paused:
            self.resume()
        if self._handle:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None
        _kill_tree(self.proc)
        return {"returncode": self.proc.poll() if self.proc else None}

    def query_runtime(self) -> dict:
        title = None
        try:
            from .adapters import _pid_window
            h = _pid_window(self.proc.pid) if self.proc else None
            if h:
                b = ctypes.create_unicode_buffer(256)
                ctypes.windll.user32.GetWindowTextW(h, b, 256)
                title = b.value
        except Exception:
            pass
        return {"running": bool(self.proc and self.proc.poll() is None), "paused": self.paused, "window_title": title,
                "guest_base": self.base and hex(self.base), "keyboard_pad_slot": self.pad_slot}

    def get_frame(self) -> bytes:
        from .adapters import win_grab
        return win_grab(self.proc.pid if self.proc else 0)

    # --- input: Xenia's keyboard pad. Key messages are posted straight to Xenia's window (WM_KEYDOWN/UP) after a
    # WM_SETFOCUS, so its "window has focus" gate is open without stealing the operator's foreground window.
    def _window(self):
        from .adapters import _pid_window
        h = _pid_window(self.proc.pid) if self.proc else None
        if not h:
            raise RuntimeError("the Xenia window isn't open")
        return h

    def send_input(self, events: list[dict]) -> dict:
        u = ctypes.windll.user32
        h = self._window()
        if not getattr(self, "new_kbd", True):
            return self._send_physical(events)
        u.PostMessageW(h, 0x0007, 0, 0)                       # WM_SETFOCUS
        sent, pressed = 0, set()
        for ev in events:
            k = str(ev["key"]).lower()
            vk = PAD_VK.get(k)
            if vk is None and len(k) == 1 and k.isalnum():
                vk = ord(k.upper())
            if vk is None:
                continue
            down = ev.get("down", True)
            if not down and k in pressed:
                time.sleep(0.06)                              # down+up in one batch: the game polls per frame
            pressed.add(k)
            sc = u.MapVirtualKeyW(vk, 0)
            ext = 1 << 24 if vk in (0x25, 0x26, 0x27, 0x28) else 0
            u.PostMessageW(h, 0x0100 if down else 0x0101, vk, 1 | sc << 16 | ext | (0 if down else 0xC0000000))
            sent += 1
        return {"sent": sent, "pad_slot": self.pad_slot}

    def _send_physical(self, events: list[dict]) -> dict:
        """Old winkey builds read the real keyboard state: SendInput, only while Xenia (or gBox docking it) is the
        foreground window, so keys never land in another app. Pad slot 0; a real XInput pad on slot 0 takes priority."""
        u = ctypes.windll.user32
        win = self._window()
        root = u.GetAncestor(win, 2)
        for _ in range(100):
            if u.GetForegroundWindow() in (root, win):     # docked in the gBox window, Xenia's own window reports as foreground
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Xenia isn't the active window: this Xenia build only reads the physical keyboard, so agent "
                               "input waits rather than typing into another app (a newer Xenia Canary removes this limit)")
        from ctypes import wintypes

        class KI(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        class INP(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("ki", KI), ("pad", ctypes.c_ubyte * 8)]
        sent, pressed = 0, set()
        for ev in events:
            k = str(ev["key"]).lower()
            vk = PAD_VK.get(k) or (ord(k.upper()) if len(k) == 1 and k.isalnum() else None)
            if vk is None:
                continue
            down = ev.get("down", True)
            if not down and k in pressed:
                time.sleep(0.06)
            pressed.add(k)
            flags = (0x0001 if vk in (0x25, 0x26, 0x27, 0x28) else 0) | (0 if down else 0x0002)
            if u.GetForegroundWindow() not in (root, win):    # the operator switched apps mid-batch: never type there
                return {"sent": sent, "pad_slot": 0, "via": "physical keyboard", "stopped": "another application came to the front"}
            inp = INP(type=1, ki=KI(vk, u.MapVirtualKeyW(vk, 0), flags, 0, 0))
            u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INP))
            sent += 1
        return {"sent": sent, "pad_slot": 0, "via": "physical keyboard"}

    def press(self, key: str, hold: float = 0.12):
        self.send_input([{"key": key, "down": True}])
        time.sleep(hold)
        self.send_input([{"key": key, "down": False}])

    # --- guest memory ---
    def _h(self):
        if not self._handle:
            self._handle = ctypes.windll.kernel32.OpenProcess(0x0010 | 0x0020 | 0x0008 | 0x0400 | 0x0800, False, self.proc.pid)
            if not self._handle:
                raise RuntimeError("cannot open the xenia process for memory access")
        return self._handle

    def _rpm(self, host: int, n: int) -> bytes | None:
        buf, got = ctypes.create_string_buffer(n), ctypes.c_size_t()
        ok = ctypes.windll.kernel32.ReadProcessMemory(self._h(), ctypes.c_void_p(host), buf, n, ctypes.byref(got))
        return buf.raw[:got.value] if ok else None

    def _base(self) -> int:
        """virtual_membase, found by the title's PE image ("MZ") at guest 0x82000000 (every XEX base image loads there)."""
        if self.base is None:
            for n in range(32, 44):
                if self._rpm((1 << n) + 0x82000000, 2) == b"MZ":
                    self.base = 1 << n
                    break
            else:
                raise RuntimeError("Xbox 360 guest memory not found in the xenia process (title still loading?)")
        return self.base

    def host(self, address: int) -> int:
        address &= 0xFFFFFFFF
        return self._base() + address + (0x1000 if address >= 0xE0000000 else 0)

    def read_memory(self, address: int, length: int) -> bytes:
        d = self._rpm(self.host(address), length)
        if d is None or len(d) != length:
            raise ValueError(f"Xbox 360 address {address:#x} (+{length}) is not mapped")
        return d

    def write_memory(self, address: int, data: bytes) -> dict:
        k, n = ctypes.windll.kernel32, ctypes.c_size_t()
        host = ctypes.c_void_p(self.host(address))
        ok = k.WriteProcessMemory(self._h(), host, bytes(data), len(data), ctypes.byref(n))
        if not ok:                                              # read-only guest page (code): lift, write, restore
            old = ctypes.c_ulong()
            if k.VirtualProtectEx(self._h(), host, len(data), 0x04, ctypes.byref(old)):
                ok = k.WriteProcessMemory(self._h(), host, bytes(data), len(data), ctypes.byref(n))
                k.VirtualProtectEx(self._h(), host, len(data), old.value, ctypes.byref(old))
        if not ok:
            raise ValueError(f"Xbox 360 address {address:#x} is not writable")
        return {"address": address, "written": n.value}

    def query_memory_map(self) -> dict:
        import ctypes.wintypes as w

        class MBI(ctypes.Structure):
            _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p), ("AllocationProtect", w.DWORD),
                        ("PartitionId", w.WORD), ("RegionSize", ctypes.c_size_t), ("State", w.DWORD), ("Protect", w.DWORD),
                        ("Type", w.DWORD)]
        base, out, m = self._base(), [], MBI()
        a = base
        while a < base + (1 << 32) and ctypes.windll.kernel32.VirtualQueryEx(self._h(), ctypes.c_void_p(a), ctypes.byref(m),
                                                                             ctypes.sizeof(m)):
            if m.State == 0x1000 and not (m.Protect & 0x101):          # MEM_COMMIT, not NOACCESS/GUARD
                g = a - base
                if out and out[-1][1] == g:
                    out[-1][1] = g + m.RegionSize
                else:
                    out.append([g, g + m.RegionSize])
            a = (m.BaseAddress or 0) + m.RegionSize
        return {"endianness": "big", "cpu": "PowerPC (Xenon)", "host_base": hex(base),
                "regions": [{"start": hex(s), "end": hex(e)} for s, e in out]}

    def debugger(self):
        from .debug import XeniaProcMem
        return XeniaProcMem(self)

    def regions(self) -> list[tuple[int, int]]:
        return [(int(r["start"], 16), int(r["end"], 16) - int(r["start"], 16)) for r in self.query_memory_map()["regions"]]

    def pause(self) -> dict:
        if not self.paused:
            ctypes.windll.ntdll.NtSuspendProcess(self._h())
            self.paused = True
        return {"paused": True}

    def resume(self) -> dict:
        if self.paused:
            ctypes.windll.ntdll.NtResumeProcess(self._h())
            self.paused = False
        return {"paused": False}
