"""shadPS4 native Windows sessions, with bounded process-memory inspection.

The upstream IPC protocol provides lifecycle control, not a guest RAM map or
debugger. Memory addresses here are native 64-bit process virtual addresses;
the map includes emulator allocations as well as the guest. Never translate
PS3/Xenia addresses into this space or infer game-specific offsets from it.
"""
from __future__ import annotations

import collections
import ctypes
import os
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .adapters import Adapter
from .config import Config, EmulatorConfig, HOST_OS
from .registry import ToolUnavailable, Unsupported

MAX_TRANSFER = 16 << 20
MAX_ADDRESS = 0x800000000000  # Windows x64 user virtual address limit (exclusive)
READABLE = {0x02, 0x04, 0x08, 0x20, 0x40, 0x80}
WRITABLE = {0x04, 0x08, 0x40, 0x80}
PAD_VK = {
    "cross": ord("N"), "circle": ord("B"), "square": ord("V"), "triangle": ord("C"),
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "l1": ord("Q"), "l2": ord("E"), "l3": ord("X"),
    "r1": ord("U"), "r2": ord("O"), "r3": ord("M"),
    "options": 0x0D, "touchpad": 0x20,
    "lup": ord("W"), "ldown": ord("S"), "lleft": ord("A"), "lright": ord("D"),
    "rup": ord("I"), "rdown": ord("K"), "rleft": ord("J"), "rright": ord("L"),
}
PAD_ALIASES = {"a": "circle", "b": "cross", "x": "triangle", "y": "square",
               "l": "l1", "r": "r1", "start": "options", "select": "touchpad"}


def executable(config: Config) -> Path:
    cfg = config.emulators.get("ps4")
    configured = cfg.executable if cfg else None
    candidates = [configured] if configured else [
        str(config.runtime / "shadps4" / "shadPS4.exe"), "shadPS4.exe", "shadPS4"]
    for candidate in candidates:
        if candidate:
            path = Path(shutil.which(candidate) or candidate)
            if path.is_file():
                return path.resolve()
    raise ToolUnavailable("shadPS4 is not installed on this worker. Set [emulators.ps4] "
                          "adapter='shadps4' and executable to the shadPS4 core executable, "
                          "or install it in runtime/shadps4 (see docs/shadps4.md).")


def boot_path(rom: str) -> Path:
    from .catalog import ps4_metadata
    path = Path(rom).resolve()
    if path.suffix.lower() == ".pkg":
        raise ToolUnavailable("This PS4 PKG needs installation/extraction first. shadPS4 boots an extracted "
                              "game folder with eboot.bin and sce_sys/param.sfo; a PKG is not a boot executable.")
    if path.is_dir():
        path = path / "eboot.bin"
    try:
        valid = path.is_file() and path.name.lower() == "eboot.bin" and bool(ps4_metadata(path))
    except (OSError, ValueError):
        valid = False
    if not valid:
        raise ToolUnavailable("Expected a PS4 game folder containing eboot.bin and a valid "
                              "sce_sys/param.sfo (CUSA title ID). PC and PS3 executables cannot use shadPS4.")
    return path


class ProcessMemory:
    """A handle to this session's process only. No page-permission changes."""

    def __init__(self, pid: int):
        from ctypes import wintypes as w
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            raise ToolUnavailable("shadPS4 memory inspection needs 64-bit Python")
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.k.OpenProcess.restype = w.HANDLE
        self.k.CloseHandle.argtypes = [w.HANDLE]
        self.k.CloseHandle.restype = w.BOOL
        for name in ("ReadProcessMemory", "WriteProcessMemory"):
            fn = getattr(self.k, name)
            fn.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                           ctypes.POINTER(ctypes.c_size_t)]
            fn.restype = w.BOOL
        self.k.VirtualQueryEx.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
        self.k.VirtualQueryEx.restype = ctypes.c_size_t
        self.k.FlushInstructionCache.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_size_t]
        self.k.FlushInstructionCache.restype = w.BOOL
        self.handle = self.k.OpenProcess(0x0400 | 0x0010 | 0x0020 | 0x0008, False, pid)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "Cannot open this shadPS4 session for memory inspection")

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None

    def query(self, address: int) -> dict | None:
        from ctypes import wintypes as w

        class MBI(ctypes.Structure):
            _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                        ("AllocationProtect", w.DWORD), ("PartitionId", w.WORD),
                        ("RegionSize", ctypes.c_size_t), ("State", w.DWORD),
                        ("Protect", w.DWORD), ("Type", w.DWORD)]
        m = MBI()
        if not self.k.VirtualQueryEx(self.handle, ctypes.c_void_p(address), ctypes.byref(m), ctypes.sizeof(m)):
            return None
        protection = int(m.Protect)
        accessible = m.State == 0x1000 and not (protection & 0x100)  # committed, not guard
        return {"start": int(m.BaseAddress or 0), "size": int(m.RegionSize),
                "readable": accessible and protection & 0xFF in READABLE,
                "writable": accessible and protection & 0xFF in WRITABLE,
                "executable": protection & 0xFF in {0x10, 0x20, 0x40, 0x80},
                "type": {0x20000: "private", 0x40000: "mapped", 0x1000000: "image"}.get(m.Type, "free"),
                "protection": protection}

    def read(self, address: int, length: int) -> bytes:
        buf, got = ctypes.create_string_buffer(length), ctypes.c_size_t()
        if not self.k.ReadProcessMemory(self.handle, ctypes.c_void_p(address), buf, length, ctypes.byref(got)) \
                or got.value != length:
            raise OSError(ctypes.get_last_error(), f"Incomplete shadPS4 read at {address:#x}")
        return buf.raw

    def write(self, address: int, data: bytes):
        buf, got = ctypes.create_string_buffer(data), ctypes.c_size_t()
        if not self.k.WriteProcessMemory(self.handle, ctypes.c_void_p(address), buf, len(data), ctypes.byref(got)) \
                or got.value != len(data):
            raise OSError(ctypes.get_last_error(), f"Incomplete shadPS4 write at {address:#x}")
        if not self.k.FlushInstructionCache(self.handle, ctypes.c_void_p(address), len(data)):
            raise OSError(ctypes.get_last_error(), "shadPS4 instruction-cache flush failed after memory write")


class ShadPS4Adapter(Adapter):
    name = "shadps4"
    supported = {"launch_game", "stop_game", "query_runtime", "get_frame", "send_input",
                 "read_memory", "write_memory", "query_memory_map"}
    checkpoint_state = False
    checkpoint_reason = "shadPS4 does not expose save states or deterministic frame stepping"

    def __init__(self, config: Config):
        if HOST_OS != "windows" or platform.machine().lower() not in {"amd64", "x86_64"}:
            raise ToolUnavailable("gBox's shadPS4 adapter currently requires a Windows x64 worker")
        self.config, self.cfg = config, config.emulators.get("ps4") or EmulatorConfig(adapter="shadps4")
        self.proc = self._memory = self.log_path = None
        self.supported = set(type(self).supported)
        self.paused, self.ipc, self.ipc_capabilities = False, False, set()
        self._ipc_ready, self._ipc_lock, self._memory_lock = threading.Event(), threading.Lock(), threading.RLock()
        self._tail = collections.deque(maxlen=120)
        self._held_keys: set[int] = set()
        self._readers = []

    def argv(self, exe: Path, eboot: Path) -> list[str]:
        if any("{rom}" in arg or arg in {"-g", "--game", "-b", "--big-picture"} for arg in self.cfg.args):
            raise ValueError("shadPS4 args must contain options only; gBox supplies the game path")
        return [str(exe), *self.cfg.args, "--fullscreen", "false", "-g", str(eboot)]

    def _ipc_command(self, command: str, *, proc=None):
        with self._ipc_lock:
            if proc is not None and proc is not self.proc:
                raise RuntimeError("shadPS4 launch changed before IPC command")
            if not self.proc or self.proc.poll() is not None or not self.proc.stdin:
                raise RuntimeError("shadPS4 process is not running")
            self.proc.stdin.write(command + "\n")
            self.proc.stdin.flush()

    def _consume_output(self, stream, *, ipc: bool, proc=None, log_path=None):
        collecting = False
        proc = proc or self.proc
        with (log_path or self.log_path).open("a", encoding="utf-8") as log:
            for line in stream:
                log.write(line)
                log.flush()
                if proc is not self.proc:
                    continue
                self._tail.append(line.rstrip())
                if not ipc:
                    continue
                token = line.strip()
                if token == ";#IPC_ENABLED":
                    collecting = True
                elif collecting and token == ";#IPC_END":
                    self.ipc = True
                    if "ENABLE_EMU_CONTROL" in self.ipc_capabilities:
                        self.supported |= {"pause", "resume"}
                    try:
                        self._ipc_command("RUN\nSTART", proc=proc)
                    except (OSError, RuntimeError):
                        return
                    self._ipc_ready.set()
                    collecting = False
                elif collecting and token.startswith(";"):
                    self.ipc_capabilities.add(token[1:])

    def _startup_window(self, user32=None):
        """Find this process's window even while hidden_start has it minimized.

        Capture/input retain the stricter non-minimized render-window selector.
        The desktop can only restore/dock a new game after launch returns its PID.
        """
        from ctypes import wintypes as w
        native = user32 is None
        if user32 is None:
            from .adapters import _pid_window
            window = _pid_window(self.proc.pid)
            if window:
                return window
            user32 = ctypes.WinDLL("user32", use_last_error=True)
        callback_type = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(w.BOOL, w.HWND, w.LPARAM)
        if native:
            user32.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
            user32.GetWindowThreadProcessId.restype = w.DWORD
            user32.IsWindowVisible.argtypes = [w.HWND]
            user32.IsWindowVisible.restype = w.BOOL
            user32.EnumWindows.argtypes = [callback_type, w.LPARAM]
            user32.EnumWindows.restype = w.BOOL
        found = []

        @callback_type
        def visit(window, _):
            owner = w.DWORD()
            user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
            if owner.value == self.proc.pid and user32.IsWindowVisible(window):
                found.append(window)
            return True

        user32.EnumWindows(visit, 0)
        return found[0] if found else None

    def launch_game(self, rom: str) -> dict:
        from .adapters import hidden_start
        if self.proc and self.proc.poll() is None:
            raise RuntimeError("This shadPS4 adapter already has a running game")
        if self.proc:
            self.stop_game()  # close the old memory handle and drain its output before reuse
        eboot, exe = boot_path(rom), executable(self.config)
        self._ipc_ready.clear()
        self.ipc, self.paused = False, False
        self.ipc_capabilities.clear()
        self.supported = set(type(self).supported)
        self._tail.clear()
        logs = self.config.runtime / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        self.log_path = logs / f"shadps4-{time.time_ns()}.log"
        env = dict(os.environ, SHADPS4_ENABLE_IPC="true")
        self.proc = subprocess.Popen(self.argv(exe, eboot), cwd=exe.parent, env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, encoding="utf-8", errors="replace", bufsize=1,
                                     startupinfo=hidden_start())
        try:
            for stream, ipc in ((self.proc.stdout, False), (self.proc.stderr, True)):
                reader = threading.Thread(target=self._consume_output, args=(stream,),
                                          kwargs={"ipc": ipc, "proc": self.proc, "log_path": self.log_path}, daemon=True)
                reader.start()
                self._readers.append(reader)
            deadline = time.monotonic() + float(getattr(self, "boot_timeout_s", 60))
            while time.monotonic() < deadline:
                if self.proc.poll() is not None:
                    raise RuntimeError(f"shadPS4 exited {self.proc.returncode}: {self.log_tail()}")
                if self._startup_window():
                    return {"pid": self.proc.pid, "local_window": True, "worker_name": platform.node(),
                            "emulator": self.name, "eboot": str(eboot), "log": str(self.log_path),
                            "ipc": self.ipc, "validation": "window_open; gameplay not yet verified",
                            "memory_scope": "process_virtual", "pad": "shadPS4 default keyboard bindings / controller"}
                time.sleep(0.1)
            raise RuntimeError(f"shadPS4 opened no game window before timeout: {self.log_tail()}")
        except Exception:
            self.stop_game()
            raise

    def log_tail(self, n: int = 1500) -> str:
        return "\n".join(self._tail)[-n:]

    def _running(self):
        if not self.proc or self.proc.poll() is not None:
            raise RuntimeError("This shadPS4 session is not running")

    def stop_game(self) -> dict:
        from .adapters import _kill_tree
        try:
            if self.ipc and self.proc and self.proc.poll() is None:
                try:
                    self._ipc_command("STOP")
                    self.proc.wait(3)
                except (subprocess.TimeoutExpired, OSError, RuntimeError, ValueError):
                    pass
        finally:
            _kill_tree(self.proc)
            with self._memory_lock:
                if self._memory:
                    self._memory.close()
                    self._memory = None
            if self.proc and self.proc.stdin:
                try:
                    self.proc.stdin.close()
                except OSError:
                    pass
            for reader in self._readers:
                reader.join(timeout=2)
            self._readers.clear()
            self._held_keys.clear()
            self.paused = False
        return {"returncode": self.proc.poll() if self.proc else None}

    def query_runtime(self) -> dict:
        return {"running": bool(self.proc and self.proc.poll() is None), "pid": self.proc.pid if self.proc else None,
                "paused": self.paused, "ipc": self.ipc, "memory_scope": "process_virtual",
                "log": str(self.log_path) if self.log_path else None,
                "note": "Process/window status does not verify gameplay compatibility"}

    def pause(self) -> dict:
        if "pause" not in self.supported:
            raise Unsupported("This shadPS4 build did not advertise IPC emulator control")
        self._ipc_command("PAUSE")
        self.paused = True
        return {"paused": True, "status": "requested", "via": "shadPS4 IPC (no acknowledgement)"}

    def resume(self) -> dict:
        if "resume" not in self.supported:
            raise Unsupported("This shadPS4 build did not advertise IPC emulator control")
        self._ipc_command("RESUME")
        self.paused = False
        return {"paused": False, "status": "requested", "via": "shadPS4 IPC (no acknowledgement)"}

    def get_frame(self) -> bytes:
        from .adapters import win_grab
        self._running()
        return win_grab(self.proc.pid)

    def _window(self):
        from .adapters import _pid_window
        self._running()
        window = _pid_window(self.proc.pid)
        if not window:
            raise RuntimeError("The shadPS4 window is not open")
        return window

    def send_input(self, events: list[dict]) -> dict:
        from .adapters import RPCS3Adapter
        rows = []
        for ev in events:
            key = str(ev.get("key", "")).lower()
            name = PAD_ALIASES.get(key, key)
            if int(ev.get("player", 1)) != 1 or name not in PAD_VK:
                raise Unsupported(f"shadPS4 keyboard input supports player 1 named buttons only: {key}")
            rows.append((PAD_VK[name], bool(ev.get("down", True))))
        window, pressed = self._window(), set()
        for vk, down in rows:
            if not down and vk in pressed:
                time.sleep(0.06)
            RPCS3Adapter._post_key(window, vk, down, vk in {0x25, 0x26, 0x27, 0x28})
            if down:
                pressed.add(vk)
                self._held_keys.add(vk)
            else:
                self._held_keys.discard(vk)
        return {"sent": len(rows), "via": "window keyboard events", "bindings": "shadPS4 defaults"}

    def _mem(self):
        self._running()
        if self._memory is None:
            self._memory = ProcessMemory(self.proc.pid)
        return self._memory

    def _check_range(self, address: int, length: int, *, write: bool = False):
        if isinstance(address, bool) or isinstance(length, bool) or not isinstance(address, int) \
                or not isinstance(length, int) or address < 0 or not 0 < length <= MAX_TRANSFER \
                or address + length > MAX_ADDRESS:
            raise ValueError("Memory requests need a valid 64-bit address and 1..16 MiB length")
        pos, end, mem = address, address + length, self._mem()
        while pos < end:
            region = mem.query(pos)
            if not region or not region["readable"] or (write and not region["writable"]) \
                    or not region["start"] <= pos < region["start"] + region["size"]:
                raise ValueError(f"shadPS4 process range at {pos:#x} is not {'writable' if write else 'readable'}")
            pos = min(end, region["start"] + region["size"])

    def read_memory(self, address: int, length: int) -> bytes:
        with self._memory_lock:
            self._check_range(address, length)
            return self._mem().read(address, length)

    def write_memory(self, address: int, data: bytes) -> dict:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("Memory replacement must be bytes")
        data = bytes(data)
        with self._memory_lock:
            self._check_range(address, len(data), write=True)
            mem = self._mem()
            before = mem.read(address, len(data))
            mem.write(address, data)
            if mem.read(address, len(data)) != data:
                raise RuntimeError("shadPS4 write could not be verified (the game may have changed these bytes)")
            return {"address": address, "written": len(data), "before_hex": before.hex(), "verified": True,
                    "scope": "process_virtual"}

    def query_memory_map(self) -> dict:
        with self._memory_lock:
            mem, address, regions = self._mem(), 0, []
            while address < MAX_ADDRESS:
                row = mem.query(address)
                if not row or row["start"] + row["size"] <= address:
                    break
                end = min(MAX_ADDRESS, row["start"] + row["size"])
                if row["readable"]:
                    regions.append({**row, "start": hex(row["start"]), "end": hex(end)})
                address = end
        return {"endianness": "little", "cpu": "x86-64", "pointer_size": 8, "scope": "process_virtual",
                "note": "Committed process mappings include host/emulator memory; not a verified guest-only RAM map",
                "regions": regions}

    def regions(self) -> list[tuple[int, int]]:
        return [(int(r["start"], 16), r["size"]) for r in self.query_memory_map()["regions"]]

    def debugger(self):
        from .debug import ShadPS4ProcMem
        return ShadPS4ProcMem(self)
