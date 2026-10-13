"""Examine in 3D: capture the frame on screen as a real 3D scene (glTF + textures) from any GPU-rendered emulator.

How it works (Windows node, portable RenderDoc in <runtime>/tools/RenderDoc_*):
  1. hook      RenderDoc can't attach to an existing D3D/Vulkan device, so emulators are started with renderdoc.dll
               already inside: the process is created suspended, renderdoc.dll is loaded through a remote LoadLibraryW,
               a few in-app API calls switch RenderDoc's on-screen overlay and capture hotkeys off, then the process runs.
               (`popen_hooked`, used by the RetroArch / Dolphin adapters when examine is enabled.)
               Vulkan backends need no injection: `popen_layer` sets RenderDoc's Vulkan layer for that process only
               (gbox/capture_backend.py), used by Yuzu / RPCS3 and by agent-owned capture sessions (#971: a GL
               RetroArch session is captured at the same moment in a Vulkan capture session, gbox/scene_relay.py).
  2. capture   pause the session, ask RenderDoc (target control, from qrenderdoc --python) for the next frame, step the
               emulator one frame (RetroArch FRAMEADVANCE) or let one frame through and suspend (Dolphin), so the game
               stays paused on exactly the captured frame.
  3. extract   replay the .rdc inside qrenderdoc and, for every draw call, read the vertex-shader output (clip position,
               texcoords, colour) and the bound texture (saved as PNG). View space is rebuilt from clip space:
                   x_view = x_clip / P00, y_view = y_clip / P11, z_view = w_clip
               PS2 (pcsx2) draws screen-space vertices (w = 1): view depth is 1/q of the perspective texcoord (STQ), and
               draws without a usable q get depth from the depth value (fitted z -> 1/q on the frame's textured draws).
               P00/P11 come from the aspect ratio and a nominal field of view unless the emulator exposes them.
               Draws whose depth is constant (2D HUD, sprites, full-screen passes) go to a separate screen-facing layer.
  4. glTF      one node per draw call (extras: draw index, event id, texture, vertex count, layer), textures embedded
               (.glb) so the viewer (clients/web Examine 3D tab) loads one artifact.

CLI (for testing against your own emulator):
    python -m gbox.scene_capture inject-launch -- <exe> <args...>       start a process with RenderDoc inside
    python -m gbox.scene_capture capture --pid N [--frames 2]           trigger a capture, print .rdc paths
    python -m gbox.scene_capture extract <file.rdc> --out dir [--fov 60] build dir/scene.glb + scene.json
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

from .scene_support import session_support, support  # noqa: F401  (capability matrix, #971)


def _cfg():
    from . import config
    return config.load(os.environ.get("GBOX_CONFIG") or Path(__file__).resolve().parents[1] / "gbox.toml")


RENDERDOC_VERSION = "1.46"                                             # portable build fetched when a PC has none
RENDERDOC_SHA256 = "9ca4d09ecaba2cc791168660d6fc2a7e3d70fe67146e87ec05c5f8dea70772f7"


def renderdoc_dir(provision: bool = False) -> Path:
    """The portable RenderDoc under <runtime>/tools (newest RenderDoc_* folder). (frame_rip has the same lookup but
    imports numpy, which the worker venv doesn't have: everything here is stdlib + qrenderdoc's own Python.)
    provision=True downloads the pinned portable build into <runtime>/tools when the PC has none (capture sessions on
    the test PC)."""
    roots = []
    try:
        roots.append(_cfg().runtime)
    except Exception:
        pass
    roots.append(Path("D:/gBox/runtime"))
    for r in roots:
        found = sorted((r / "tools").glob("RenderDoc_*/qrenderdoc.exe"))
        if found:
            return found[-1].parent
    if provision and roots:
        return ensure_renderdoc(roots[0])
    raise FileNotFoundError("RenderDoc not found under <runtime>/tools/RenderDoc_*")


def ensure_renderdoc(runtime: Path, version: str = RENDERDOC_VERSION, sha256_hex: str = RENDERDOC_SHA256,
                     fetch=None) -> Path:
    """Install the official portable RenderDoc (renderdoc.org zip, sha256-pinned) into <runtime>/tools/RenderDoc_<v>_64.
    `fetch(url) -> bytes` is injectable for tests."""
    import hashlib
    import io
    import zipfile
    dst = Path(runtime) / "tools" / f"RenderDoc_{version}_64"
    if (dst / "qrenderdoc.exe").is_file() and (dst / "renderdoc.json").is_file():
        return dst
    url = f"https://renderdoc.org/stable/{version}/RenderDoc_{version}_64.zip"
    if fetch is None:
        import urllib.request

        def fetch(u):
            with urllib.request.urlopen(u, timeout=1800) as r:
                return r.read()
    data = fetch(url)
    if hashlib.sha256(data).hexdigest() != sha256_hex:
        raise RuntimeError(f"RenderDoc {version} download failed its sha256 check")
    tmp = dst.with_name(dst.name + ".partial")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for m in z.infolist():
            name = m.filename.split("/", 1)[1] if "/" in m.filename else ""
            if not name or m.is_dir():
                continue
            out = (tmp / name).resolve()
            if not out.is_relative_to(tmp.resolve()):
                raise RuntimeError(f"unsafe path in the RenderDoc zip: {m.filename}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(m))
    shutil.rmtree(dst, ignore_errors=True)
    tmp.rename(dst)
    return dst


def _qrd(script: str, env: dict, timeout: float = 600) -> None:
    """Run a script inside qrenderdoc.exe (it hosts the renderdoc Python module); the script exits the process.
    Started minimized without focus so nothing pops over the game."""
    compile(script, "qrenderdoc-script", "exec")         # a script that doesn't compile leaves qrenderdoc's UI open: fail here
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(script)
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 7                                                  # SW_SHOWMINNOACTIVE
    job = _kill_job()                       # qrenderdoc + anything it spawns (crash handler, bug reporter) die with the job
    try:
        p = subprocess.Popen([str(renderdoc_dir() / "qrenderdoc.exe"), "--python", f.name], env={**os.environ, **env},
                             startupinfo=si, creationflags=CREATE_SUSPENDED)
        k = ctypes.WinDLL("kernel32")
        k.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(int(p._handle)))
        ctypes.WinDLL("ntdll").NtResumeProcess(wintypes.HANDLE(int(p._handle)))
        try:
            p.wait(timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            raise
    finally:
        ctypes.WinDLL("kernel32").CloseHandle(wintypes.HANDLE(job))
        os.unlink(f.name)


def _kill_job() -> int:
    """A Windows job object that kills every process in it when its handle closes."""
    class BASIC(ctypes.Structure):
        _fields_ = [("a", ctypes.c_int64), ("b", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                    ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("e", wintypes.DWORD), ("f", ctypes.c_size_t),
                    ("g", wintypes.DWORD), ("h", wintypes.DWORD)]

    class EXT(ctypes.Structure):
        _fields_ = [("basic", BASIC), ("io", ctypes.c_uint64 * 6), ("pm", ctypes.c_size_t), ("jm", ctypes.c_size_t),
                    ("ppm", ctypes.c_size_t), ("pjm", ctypes.c_size_t)]
    k = ctypes.WinDLL("kernel32")
    k.CreateJobObjectW.restype = wintypes.HANDLE
    job = k.CreateJobObjectW(None, None)
    info = EXT()
    info.basic.LimitFlags = 0x2000                                      # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    k.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))
    return job


def _kill_children(pid: int, name: str = "renderdoccmd.exe") -> int:
    """Terminate `name` processes whose parent is pid (RenderDoc's out-of-process crash handler: if the game crashed it
    would pop a RenderDoc bug-report window over the operator's desktop)."""
    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]
    k = ctypes.WinDLL("kernel32")
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.OpenProcess.restype = wintypes.HANDLE
    snap = k.CreateToolhelp32Snapshot(2, 0)
    pe, n = PE(), 0
    pe.dwSize = ctypes.sizeof(PE)
    ok = k.Process32FirstW(snap, ctypes.byref(pe))
    while ok:
        if pe.th32ParentProcessID == pid and pe.szExeFile.lower() == name:
            h = k.OpenProcess(0x0001, False, pe.th32ProcessID)            # PROCESS_TERMINATE
            if h:
                n += bool(k.TerminateProcess(wintypes.HANDLE(h), 0))
                k.CloseHandle(wintypes.HANDLE(h))
        ok = k.Process32NextW(snap, ctypes.byref(pe))
    k.CloseHandle(snap)
    return n


# ------------------------------------------------------------------------------------------------ 1. hook at launch

CREATE_SUSPENDED = 0x4


def _exports(dll: Path) -> dict[str, int]:
    """Export name -> RVA of a PE32+ DLL (no need to load renderdoc.dll into this process, which would hook it)."""
    b = Path(dll).read_bytes()
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    nsec = struct.unpack_from("<H", b, pe + 6)[0]
    opt = pe + 24
    exp_rva = struct.unpack_from("<I", b, opt + 112)[0]               # data directory 0 (PE32+)
    secs = [struct.unpack_from("<IIII", b, opt + struct.unpack_from("<H", b, pe + 20)[0] + 40 * i + 8)
            for i in range(nsec)]                                       # vsize, va, rawsize, rawptr

    def off(rva):
        for vs, va, rs, rp in secs:
            if va <= rva < va + max(vs, rs):
                return rva - va + rp
        raise ValueError(hex(rva))
    e = off(exp_rva)
    n_names, f_rva, n_rva, o_rva = struct.unpack_from("<I", b, e + 24)[0], *struct.unpack_from("<III", b, e + 28)
    out = {}
    for i in range(n_names):
        name_off = off(struct.unpack_from("<I", b, off(n_rva) + 4 * i)[0])
        name = b[name_off:b.index(b"\0", name_off)].decode()
        ordinal = struct.unpack_from("<H", b, off(o_rva) + 2 * i)[0]
        out[name] = struct.unpack_from("<I", b, off(f_rva) + 4 * ordinal)[0]
    return out


def _k32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.VirtualAllocEx.restype = ctypes.c_void_p
    k.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
    k.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
    k.CreateRemoteThread.restype = wintypes.HANDLE
    k.CreateRemoteThread.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p,
                                     wintypes.DWORD, ctypes.c_void_p]
    k.GetExitCodeThread.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k.GetModuleHandleW.restype = wintypes.HMODULE
    k.GetProcAddress.restype = ctypes.c_void_p
    k.GetProcAddress.argtypes = [wintypes.HMODULE, ctypes.c_char_p]
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


def _remote_call(k, h, start: int, arg: int, timeout_ms: int = 15000) -> int:
    th = k.CreateRemoteThread(h, None, 0, ctypes.c_void_p(start), ctypes.c_void_p(arg), 0, None)
    if not th:
        raise OSError(f"CreateRemoteThread failed ({ctypes.get_last_error()})")
    try:
        if k.WaitForSingleObject(th, timeout_ms) != 0:
            raise TimeoutError("remote thread did not finish")
        code = wintypes.DWORD()
        k.GetExitCodeThread(th, ctypes.byref(code))
        return code.value
    finally:
        k.CloseHandle(th)


def _modules(pid: int) -> dict[str, int]:
    """Loaded module name (lower) -> base address in another process (Toolhelp snapshot)."""
    class ME(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("GlblcntUsage", wintypes.DWORD), ("ProccntUsage", wintypes.DWORD), ("modBaseAddr", ctypes.c_void_p),
                    ("modBaseSize", wintypes.DWORD), ("hModule", wintypes.HMODULE), ("szModule", ctypes.c_wchar * 256),
                    ("szExePath", ctypes.c_wchar * 260)]
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k.CreateToolhelp32Snapshot(0x18, pid)                       # TH32CS_SNAPMODULE | SNAPMODULE32
    out, me = {}, ME()
    me.dwSize = ctypes.sizeof(ME)
    try:
        ok = k.Module32FirstW(snap, ctypes.byref(me))
        while ok:
            out[me.szModule.lower()] = me.modBaseAddr
            ok = k.Module32NextW(snap, ctypes.byref(me))
    finally:
        k.CloseHandle(snap)
    return out


def _api_stub(get_api: int, data: int, cap_template_ptr: int) -> bytes:
    """x64 thread routine: RENDERDOC_GetAPI(1.6.0) then MaskOverlayBits(0, 0) (no overlay over the game),
    SetCaptureKeys(NULL, 0) / SetFocusToggleKeys(NULL, 0) (F12/PrtScn stay the game's), UnloadCrashHandler(),
    SetCaptureFilePathTemplate(template). `data` = 8 bytes of scratch for the API pointer."""
    c = bytearray()
    c += b"\x48\x83\xEC\x38"                                    # sub rsp, 0x38
    c += b"\xB9" + struct.pack("<I", 10600)                     # mov ecx, eRENDERDOC_API_Version_1_6_0
    c += b"\x48\xBA" + struct.pack("<Q", data)                  # mov rdx, data
    c += b"\x48\xB8" + struct.pack("<Q", get_api)               # mov rax, RENDERDOC_GetAPI
    c += b"\xFF\xD0"                                            # call rax
    c += b"\x48\xB8" + struct.pack("<Q", data)                  # mov rax, data
    c += b"\x48\x8B\x00"                                        # mov rax, [rax]       (api table)
    c += b"\x48\x85\xC0"                                        # test rax, rax
    jz_at = len(c)
    c += b"\x0F\x84\0\0\0\0"                                    # jz end
    c += b"\x48\x89\x44\x24\x28"                                # mov [rsp+0x28], rax

    def call_slot(slot: int, rcx: int | None = 0, rdx: int | None = 0):
        nonlocal c
        c += b"\x48\x8B\x44\x24\x28"                            # mov rax, [rsp+0x28]
        c += b"\x48\x8B\x40" + bytes([slot * 8])                # mov rax, [rax+slot*8]
        c += b"\x48\xB9" + struct.pack("<Q", rcx or 0)          # mov rcx, imm64
        c += b"\x48\xBA" + struct.pack("<Q", rdx or 0)          # mov rdx, imm64
        c += b"\xFF\xD0"                                        # call rax
    call_slot(8)                                                # MaskOverlayBits(0, 0)
    call_slot(6)                                                # SetCaptureKeys(NULL, 0)
    call_slot(5)                                                # SetFocusToggleKeys(NULL, 0)
    call_slot(10)                                               # UnloadCrashHandler()
    if cap_template_ptr:
        call_slot(11, cap_template_ptr)                         # SetCaptureFilePathTemplate(utf8 path)
    end = len(c)
    c[jz_at + 2:jz_at + 6] = struct.pack("<i", end - (jz_at + 6))
    c += b"\x48\x83\xC4\x38"                                    # add rsp, 0x38
    c += b"\x31\xC0\xC3"                                        # xor eax, eax; ret
    return bytes(c)


def inject(pid: int, cap_dir: Path | None = None) -> dict:
    """Load renderdoc.dll into a (typically just created, still suspended) process and quiet its overlay/hotkeys."""
    rd = renderdoc_dir()
    dll = rd / "renderdoc.dll"
    k = _k32()
    h = k.OpenProcess(0x1F0FFF, False, pid)
    if not h:
        raise OSError(f"OpenProcess({pid}) failed ({ctypes.get_last_error()})")
    try:
        path = (str(dll) + "\0").encode("utf-16-le")
        tmpl = (str(Path(cap_dir) / "frame") + "\0").encode() if cap_dir else b""
        mem = k.VirtualAllocEx(h, None, 0x2000, 0x3000, 0x40)           # MEM_COMMIT|RESERVE, PAGE_EXECUTE_READWRITE
        if not mem:
            raise OSError("VirtualAllocEx failed")
        k.WriteProcessMemory(h, mem, path, len(path), None)
        ll = k.GetProcAddress(k.GetModuleHandleW("kernel32.dll"), b"LoadLibraryW")
        _remote_call(k, h, ll, mem)
        base = _modules(pid).get("renderdoc.dll")
        if not base:
            raise RuntimeError("renderdoc.dll did not load into the process")
        get_api = base + _exports(dll)["RENDERDOC_GetAPI"]
        data, tptr, code = mem + 0x800, (mem + 0x900 if tmpl else 0), mem + 0x1000
        if tmpl:
            Path(cap_dir).mkdir(parents=True, exist_ok=True)
            k.WriteProcessMemory(h, tptr, tmpl, len(tmpl), None)
        stub = _api_stub(get_api, data, tptr)
        k.WriteProcessMemory(h, code, stub, len(stub), None)
        _remote_call(k, h, code, 0)
        return {"renderdoc": str(dll), "base": hex(base)}
    finally:
        k.CloseHandle(h)


def popen_hooked(argv, cap_dir: Path | None = None, **kw) -> subprocess.Popen:
    """subprocess.Popen with RenderDoc loaded before the program's first instruction (so every D3D11/D3D12/GL/Vulkan
    device it creates is capturable). Falls back to a plain launch if injection fails."""
    kw["creationflags"] = kw.get("creationflags", 0) | CREATE_SUSPENDED
    p = subprocess.Popen(argv, **kw)
    nt = ctypes.WinDLL("ntdll")
    try:
        p.renderdoc = inject(p.pid, cap_dir)
    except Exception as e:                                              # never block a game launch on the examine hook
        p.renderdoc = {"error": f"{type(e).__name__}: {e}"}
    finally:
        nt.NtResumeProcess(wintypes.HANDLE(int(p._handle)))
    try:
        p.renderdoc["crash_handlers_closed"] = _kill_children(p.pid)
    except Exception:
        pass
    return p


def popen_layer(argv, cap_dir: Path | None = None, **kw) -> subprocess.Popen:
    """subprocess.Popen with RenderDoc's Vulkan layer enabled for this process only (gbox/capture_backend.layer_env):
    the Vulkan loader loads renderdoc.dll when the program creates its Vulkan instance. No injection, nothing
    registered system-wide. p.renderdoc["attach"] = "layer"; whether it loaded is checked later (renderdoc_loaded)."""
    from .capture_backend import layer_env
    try:
        rd = renderdoc_dir()
        kw["env"] = layer_env(rd, Path(cap_dir) / "frame" if cap_dir else None, base=kw.get("env"))
        info = {"attach": "layer", "renderdoc": str(rd / "renderdoc.dll"), "manifest": str(rd / "renderdoc.json"),
                "capfile": kw["env"].get("RENDERDOC_CAPFILE")}
    except Exception as e:                                              # never block a game launch on the examine hook
        info = {"attach": "layer", "error": f"{type(e).__name__}: {e}"}
    p = subprocess.Popen(argv, **kw)
    p.renderdoc = info
    return p


def renderdoc_loaded(pid: int) -> bool:
    """renderdoc.dll is mapped into the process (injected, or loaded by the Vulkan loader as a layer)."""
    try:
        return "renderdoc.dll" in _modules(pid)
    except Exception:
        return False


def layer_check(proc, wait_s: float = 0.0) -> bool | None:
    """For a layer-attached process: record whether the Vulkan loader loaded RenderDoc (p.renderdoc["loaded"]).
    Returns None for processes that weren't started with the layer."""
    info = getattr(proc, "renderdoc", None)
    if not isinstance(info, dict) or info.get("attach") != "layer" or "error" in info:
        return None
    t0 = time.time()
    while True:
        ok = proc.poll() is None and renderdoc_loaded(proc.pid)
        if ok or time.time() - t0 >= wait_s:
            info["loaded"] = ok
            if ok:
                try:
                    info["crash_handlers_closed"] = _kill_children(proc.pid)
                except Exception:
                    pass
            return ok
        time.sleep(0.25)


def hooked(proc) -> bool:
    """Whether a running emulator process has RenderDoc inside (popen_hooked, or popen_layer once Vulkan is up)."""
    if proc is None or proc.poll() is not None:
        return False
    info = getattr(proc, "renderdoc", None)
    if isinstance(info, dict) and info.get("attach") == "layer" and "error" not in info:
        return bool(layer_check(proc))
    if info and "error" not in info:
        return True
    return renderdoc_loaded(proc.pid)


# ------------------------------------------------------------------------------------------------ 2. capture

CAPTURE_PY = r'''
import os, socket, time
import renderdoc as rd
out = open(os.environ["RD_OUT"], "w")
def say(s):
    out.write(s + "\n"); out.flush()
try:
    pid = int(os.environ["RD_PID"])
    ident, tc = rd.EnumerateRemoteTargets("", 0), None
    while ident:
        t = rd.CreateTargetControl("", ident, "gbox-scene-capture", True)
        if t and t.GetPID() == pid:
            tc = t
            break
        if t:
            t.Shutdown()
        ident = rd.EnumerateRemoteTargets("", ident)
    if not tc:
        raise RuntimeError("no RenderDoc target for pid %d (was the game started with Examine 3D on?)" % pid)
    n = int(os.environ.get("RD_N", "1"))
    tc.TriggerCapture(n)
    say("TRIGGERED")
    step = os.environ.get("RD_STEP", "")            # "udp:<port>:<command>" - advance a paused emulator frame by frame
    t0, paths, last_step = time.time(), [], 0.0
    while time.time() - t0 < float(os.environ.get("RD_WAIT", "30")) and len(paths) < n:
        if step and time.time() - last_step > 0.25:
            _, port, cmd = step.split(":", 2)
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.sendto(cmd.encode(), ("127.0.0.1", int(port)))
            s.close()
            last_step = time.time()
        m = tc.ReceiveMessage(None)
        if m.type == rd.TargetControlMessageType.NewCapture:
            p = m.newCapture.path              # on connect the target also lists its older captures: skip those
            if os.path.exists(p) and os.path.getmtime(p) >= t0 - 1 and p not in paths:
                paths.append(p)
                say("CAPTURE %s" % p)
        elif m.type == rd.TargetControlMessageType.Disconnected:
            say("DISCONNECTED")
            break
    tc.Shutdown()
    say("DONE")
except BaseException:
    import traceback
    say("ERROR " + traceback.format_exc())
out.close()
os._exit(0)
'''


def capture_rdc(pid: int, frames: int = 1, step: str = "", wait: float = 30, on_triggered=None) -> list[Path]:
    """Ask the RenderDoc inside process `pid` for the next `frames` frames; returns the .rdc paths.
    step = "udp:<port>:FRAMEADVANCE" steps a paused RetroArch until the frames arrive. on_triggered() runs once the
    capture is armed (e.g. let a suspended emulator run)."""
    fd, name = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    out = Path(name)
    import threading
    th = threading.Thread(target=_qrd, args=(CAPTURE_PY, {"RD_OUT": str(out), "RD_PID": str(pid), "RD_N": str(frames),
                                                          "RD_STEP": step, "RD_WAIT": str(wait)}, wait + 60), daemon=True)
    th.start()
    armed = False
    while th.is_alive():
        th.join(0.05)
        if not armed and "TRIGGERED" in out.read_text(errors="replace"):
            armed = True
            if on_triggered:
                on_triggered()
    txt = out.read_text(errors="replace")
    out.unlink(missing_ok=True)
    paths = [Path(l[8:].strip()) for l in txt.splitlines() if l.startswith("CAPTURE ")]
    if not paths:
        raise RuntimeError("RenderDoc capture failed: " + (txt.strip()[-1500:] or "qrenderdoc produced no output"))
    return paths


# ------------------------------------------------------------------------------------------------ 3+4. extract -> glTF

EXTRACT_PY = r'''
import array, hashlib, json, math, os, struct, time, traceback, zlib
T0 = time.time()
TIMES = {}
import renderdoc as rd
OUT = os.environ["RD_OUT"]
os.makedirs(OUT, exist_ok=True)
log = open(os.path.join(OUT, "extract.log"), "w")


def png(w, h, rgba):
    raw = b"".join(b"\0" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def rid_of(x):
    x = getattr(x, "descriptor", x)
    for a in ("resource", "resourceId"):
        if hasattr(x, a):
            return getattr(x, a)
    return rd.ResourceId.Null()


def walk(a, acts):
    for x in a:
        if (x.flags & rd.ActionFlags.Drawcall) and x.numIndices >= 3:
            acts.append(x)
        walk(x.children, acts)
    return acts


NULL = rd.ResourceId.Null()
try:
    paths = os.environ["RD_CAP"].split("|")
    CAPFILE, ndraw = paths[0], -1                 # several consecutive frames: games at 30 fps leave every other one empty;
    if len(paths) > 1:                            # count draw chunks in each file (no replay) and use the busiest
        for path in paths:
            c_ = rd.OpenCaptureFile()
            if c_.OpenFile(path, "", None) == rd.ResultCode.Succeeded:
                n_ = sum(1 for ch in c_.GetStructuredData().chunks if "Draw" in ch.name)
                if n_ > ndraw:
                    CAPFILE, ndraw = path, n_
            c_.Shutdown()
    cap = rd.OpenCaptureFile()
    st = cap.OpenFile(CAPFILE, "", None)
    assert st == rd.ResultCode.Succeeded, str(st)
    st, ctl = cap.OpenCapture(rd.ReplayOptions(), None)
    assert st == rd.ResultCode.Succeeded, str(st)
    acts = walk(ctl.GetRootActions(), [])
    TIMES["open"] = round(time.time() - T0, 2)
    sf = ctl.GetStructuredFile()
    api = str(ctl.GetAPIProperties().pipelineType).split(".")[-1]
    texinfo = {t.resourceId: t for t in ctl.GetTextures()}
    mode = os.environ.get("RD_MODE", "auto")
    FOVY = float(os.environ.get("RD_FOVY", "0") or 0)
    ASPECT = float(os.environ.get("RD_ASPECT", "0") or 0)
    draws, tgt_count, projs, texfreq = [], {}, [], {}
    TOPO = {rd.Topology.TriangleList: "list", rd.Topology.TriangleStrip: "strip"}
    # ---------------------------------------------------------------- pass 1: post-VS vertices of every draw
    for di, a in enumerate(acts):
        ctl.SetFrameEvent(a.eventId, False)
        ps = ctl.GetPipelineState()
        try:
            rt = next((r for r in (rid_of(o) for o in ps.GetOutputTargets()) if r != NULL), NULL)
        except Exception:
            rt = NULL
        m = ctl.GetPostVSData(0, 0, rd.MeshDataStage.VSOut)
        topo = TOPO.get(m.topology)
        if topo is None or m.vertexResourceId == NULL or not m.numIndices:
            continue
        vs = ps.GetShaderReflection(rd.ShaderStage.Vertex)
        # RenderDoc's post-VS stream holds the position first, then the other outputs in signature order
        sig, off = [], 16
        for s in (vs.outputSignature if vs else []):
            if s.systemValue == rd.ShaderBuiltin.Position:
                continue
            sig.append(((s.semanticName or s.varName or "").upper(), s.semanticIndex, s.compCount, off // 4))
            off += 4 * s.compCount
        stride = m.vertexByteStride
        if stride < 16 or stride % 4:
            continue
        n = m.numIndices
        if m.indexResourceId != NULL:
            iw = m.indexByteStride or 4
            raw = ctl.GetBufferData(m.indexResourceId, m.indexByteOffset, n * iw)
            idx = array.array("H" if iw == 2 else "I", raw[:len(raw) // iw * iw]).tolist()
            if not idx:
                continue
            nv = max(idx) + 1
        else:
            idx, nv = list(range(n)), n
        vb = ctl.GetBufferData(m.vertexResourceId, m.vertexByteOffset, nv * stride)
        nv = len(vb) // stride
        if nv == 0:
            continue
        if topo == "strip":
            tri = []
            for k in range(len(idx) - 2):
                a0, a1, a2 = idx[k], idx[k + 1], idx[k + 2]
                if a0 == a1 or a1 == a2 or a0 == a2 or a0 >= nv or a1 >= nv or a2 >= nv:
                    continue
                tri += (a0, a1, a2) if k % 2 == 0 else (a1, a0, a2)
            idx = tri
        else:
            idx = [i if i < nv else 0 for i in idx[:len(idx) // 3 * 3]]
        if not idx:
            continue
        texs = []
        for ro in ps.GetReadOnlyResources(rd.ShaderStage.Pixel):
            r = rid_of(ro)
            t = texinfo.get(r)
            if t is not None and t.width > 1 and t.height > 1 and t.format.compByteWidth == 1 and t.format.compCount >= 3 \
                    and r not in texs:
                texs.append(r)
                texfreq[r] = texfreq.get(r, 0) + 1
        blend = False
        try:
            cb = ps.GetColorBlends()                # enabled with ONE/ZERO (Dolphin always enables it) is opaque
            if cb and cb[0].enabled:
                eq = cb[0].colorBlend
                if not (eq.source == rd.BlendMultiplier.One and eq.destination == rd.BlendMultiplier.Zero):
                    blend = [str(eq.source).split(".")[-1], str(eq.destination).split(".")[-1], str(eq.operation).split(".")[-1]]
        except Exception:
            pass
        zwrite = True                               # the draw's own depth-write state (blended draws often still write)
        try:
            if api == "D3D12":
                zwrite = bool(ctl.GetD3D12PipelineState().outputMerger.depthStencilState.depthWrites)
            elif api == "D3D11":
                zwrite = bool(ctl.GetD3D11PipelineState().outputMerger.depthStencilState.depthWrites)
            elif api == "Vulkan":
                zwrite = bool(ctl.GetVulkanPipelineState().depthStencil.depthWriteEnable)
            elif api == "OpenGL":
                zwrite = bool(ctl.GetGLPipelineState().depthState.depthWrites)
        except Exception:
            pass
        if blend and zwrite and blend[0] in ("SrcAlpha", "Src1Alpha") and blend[1] in ("InvSrcAlpha", "InvSrc1Alpha"):
            blend = False                           # plain alpha blend that writes depth (Dolphin blends everything): opaque + alpha test
        proj = None
        if vs and len(projs) < 400 and sum(1 for d_ in draws[-60:] if d_["proj"]) < 12:   # projection constants (Dolphin cproj), sampled
            try:
                for ci, cblk in enumerate(vs.constantBlocks):
                    hit = next((v.name for v in cblk.variables if v.name.lower().endswith(("cproj", "projection"))), None)
                    if not hit:
                        continue
                    bc = ps.GetConstantBlock(rd.ShaderStage.Vertex, ci, 0)
                    d_ = getattr(bc, "descriptor", bc)
                    vals = ctl.GetCBufferVariableContents(ps.GetGraphicsPipelineObject(), vs.resourceId, rd.ShaderStage.Vertex,
                                                          ps.GetShaderEntryPoint(rd.ShaderStage.Vertex), ci,
                                                          rid_of(d_), getattr(d_, "byteOffset", 0), getattr(d_, "byteSize", 0))
                    for v in vals:
                        if v.name == hit:
                            if v.members:
                                rows = [[v.members[r].value.f32v[c] for c in range(4)] for r in range(4)]
                            else:
                                rows = [[v.value.f32v[r * 4 + c] for c in range(4)] for r in range(4)]
                            proj = rows
            except Exception as e:
                projs.append({"error": str(e)})
        vp = ps.GetViewport(0)
        tgt = (rt, int(vp.width), int(vp.height))
        tgt_count[tgt] = tgt_count.get(tgt, 0) + len(idx)
        draws.append({"i": di, "eid": a.eventId, "name": a.GetName(sf), "tgt": tgt, "vb": vb, "s": stride // 4,
                      "nv": nv, "idx": idx, "sig": sig, "texs": texs, "blend": blend, "zwrite": zwrite, "proj": proj,
                      "vp": [vp.x, vp.y, vp.width, vp.height]})
    TIMES["vertices"] = round(time.time() - T0, 2)
    # the scene = draws into the busiest render target + viewport (drops shadow maps, render-to-texture, EFB copies)
    main = max(tgt_count, key=tgt_count.get) if tgt_count else None
    draws = [d for d in draws if d["tgt"] == main]
    main_rt = main[0] if main else None

    def el(d, sem, si=None, cc=None):
        for (nm, idx_, c_, o_) in d["sig"]:
            if nm.startswith(sem) and (si is None or idx_ == si) and (cc is None or c_ == cc):
                return o_, c_
        return None
    # ---------------------------------------------------------------- emulator layout
    if mode == "auto":
        if draws and any(d["proj"] for d in draws) and not any(nm.startswith("COLOR") for d in draws for (nm, _, _, _) in d["sig"]):
            mode = "dolphin"
        elif draws and all(el(d, "TEXCOORD", 0, 4) and el(d, "TEXCOORD", 2, 4) and el(d, "COLOR", 0, 4) for d in draws[:50]):
            ws = [w for d in draws[:200] for w in array.array("f", d["vb"])[3::d["s"]]]
            mode = "pcsx2" if ws and max(abs(x - 1.0) for x in ws) < 1e-4 else "generic"
        elif draws and all(el(d, "VTX_UV", 0, 3) and el(d, "VTX_BASE", 0, 4) for d in draws[:50]):
            ws = [w for d in draws[:200] for w in array.array("f", d["vb"])[3::d["s"]]]
            mode = "flycast" if ws and max(abs(x - 1.0) for x in ws) < 1e-4 else "generic"
        else:
            mode = "generic"
    flip = api == "Vulkan"
    for d in draws:                                 # texture: the most specific one bound (shared ones are ramps/env maps)
        if d["texs"]:
            low = min(texfreq[r] for r in d["texs"]) if mode == "dolphin" else None
            d["tex"] = next(r for r in d["texs"] if low is None or texfreq[r] == low)
        else:
            d["tex"] = None
    # ---------------------------------------------------------------- pass 2: view-space depth, uv, colour per vertex
    fitq = None
    if mode == "pcsx2":                     # PS2 GS vertices are screen space: w = 1/q (STQ); GS z is linear in q -> fit it
        zs, qs = [], []
        for d in draws:
            if d["tex"] is None:
                continue
            f, s, t = array.array("f", d["vb"]), d["s"], el(d, "TEXCOORD", 0, 4)[0]
            for k in range(0, d["nv"], max(1, d["nv"] // 64)):
                q = f[k * s + t + 3]
                if q > 1e-7 and abs(q - 1.0) > 1e-6 and (f[k * s + t] != 0 or f[k * s + t + 1] != 0):
                    zs.append(f[k * s + 2])
                    qs.append(q)
        if len(zs) > 8:
            mz, mq = sum(zs) / len(zs), sum(qs) / len(qs)
            szz = sum((z - mz) ** 2 for z in zs)
            szq = sum((z - mz) * (q - mq) for z, q in zip(zs, qs))
            sqq = sum((q - mq) ** 2 for q in qs)
            if szz > 0 and sqq > 0:
                b = szq / szz
                fitq = {"a": mq - b * mz, "b": b, "r": szq / math.sqrt(szz * sqq), "zmin": min(zs), "zmax": max(zs), "n": len(zs)}
        if fitq and fitq["r"] < 0.9:
            fitq = None
    allw = []
    for d in draws:
        f, s, nv = array.array("f", d["vb"]), d["s"], d["nv"]
        X, Y, Z, Wc = f[0::s], f[1::s], f[2::s], f[3::s]
        tex = d["tex"]
        tinfo = texinfo.get(tex) if tex is not None else None
        UV = None
        if mode == "pcsx2":
            t0 = el(d, "TEXCOORD", 0, 4)[0]
            t2 = el(d, "TEXCOORD", 2, 4)[0]
            c0 = el(d, "COLOR", 0, 4)[0]
            S, T, Q = f[t0::s], f[t0 + 1::s], f[t0 + 3::s]
            persp = tex is not None and any(q > 1e-7 and abs(q - 1.0) > 1e-6 for q in Q)
            W = []
            for z, q in zip(Z, Q):
                w = None
                if persp and q > 1e-7:
                    w = 1.0 / q
                elif fitq and fitq["zmin"] - 0.02 * abs(fitq["zmin"]) <= z <= fitq["zmax"] + 0.02 * abs(fitq["zmax"]):
                    qq = fitq["a"] + fitq["b"] * z
                    w = 1.0 / qq if qq > 1e-7 else None
                W.append(w)
            if tex is not None:
                U2, V2 = f[t2 + 2::s], f[t2 + 3::s]
                tw, th = 16.0 * tinfo.width, 16.0 * tinfo.height
                UV = [((u2 / tw, v2 / th) if (u == 0 and v == 0 and abs(q - 1) < 1e-6) else
                       ((u / q, v / q) if abs(q) > 1e-12 else (u, v))) for u, v, q, u2, v2 in zip(S, T, Q, U2, V2)]
            cs = 1.0 / (128.0 if tex is not None else 255.0)
            C = [(min(2.0, r * cs), min(2.0, g * cs), min(2.0, b * cs), min(1.0, a_ / 128.0))
                 for r, g, b, a_ in zip(f[c0::s], f[c0 + 1::s], f[c0 + 2::s], f[c0 + 3::s])]
            XY_CLIP = False
        elif mode == "flycast":
            # Flycast (Vulkan / GL4) draws the PVR's screen-space vertices: gl_Position = (x_ndc, y_ndc, 0, 1) and the
            # interpolants are pre-multiplied by q = 1/w for its own perspective correction: vtx_uv = (u*q, v*q, q),
            # vtx_base = colour*q. View depth w = 1/q; a draw with one q for every vertex is flat 2D (HUD, sprites).
            tu, cb_ = el(d, "VTX_UV", 0, 3)[0], el(d, "VTX_BASE", 0, 4)[0]
            Q = f[tu + 2::s]
            okq = [q for q in Q if q > 1e-9 and math.isfinite(q)]
            flat = not okq or len(okq) < len(Q) or max(okq) - min(okq) <= 1e-6 * max(okq)
            W = [None] * nv if flat else [1.0 / q for q in Q]
            iq = [(1.0 / q) if q > 1e-9 and math.isfinite(q) else 0.0 for q in Q]
            if tex is not None:
                UV = [((u * k, v * k) if math.isfinite(u) and math.isfinite(v) else (0.0, 0.0))
                      for u, v, k in zip(f[tu::s], f[tu + 1::s], iq)]
            C = [tuple(max(0.0, min(1.0, x * k)) if math.isfinite(x) else 1.0 for x in (r, g, b, a_))
                 for r, g, b, a_, k in zip(f[cb_::s], f[cb_ + 1::s], f[cb_ + 2::s], f[cb_ + 3::s], iq)]
            XY_CLIP = False
        else:
            W = [w if abs(w - 1.0) > 1e-5 else None for w in Wc]
            XY_CLIP = True
            if mode == "dolphin":                   # colors_0 = TEXCOORD1; uvs = 3-comp texcoords, first non-projective one
                ce = el(d, "TEXCOORD", 1, 4)
                t3 = [(o_, c_) for (nm, i_, c_, o_) in d["sig"] if nm.startswith("TEXCOORD") and c_ == 3]
                te = next((t for t in t3 if all(abs(q - 1.0) < 1e-3 for q in f[t[0] + 2::s])), t3[0] if t3 else None)
                if tex is not None:
                    ce = None                       # TEV lighting isn't reproduced: textured draws show the texture as is
            else:
                ce = el(d, "COLOR", 0, 4) or el(d, "COLOR", 0, 3)
                te = el(d, "TEXCOORD", 0, 3) or el(d, "TEXCOORD", 0, 2) or el(d, "TEXCOORD", 0, 4)
            if tex is not None and te:
                U, V = f[te[0]::s], f[te[0] + 1::s]
                if te[1] >= 3:
                    Q = f[te[0] + 2::s]
                    UV = [((u / q, v / q) if abs(q) > 1e-9 else (u, v)) for u, v, q in zip(U, V, Q)]
                else:
                    UV = list(zip(U, V))
            if ce:
                o_ = ce[0]
                A = f[o_ + 3::s] if ce[1] > 3 else [1.0] * nv
                C = [(max(0.0, min(1.0, r)), max(0.0, min(1.0, g)), max(0.0, min(1.0, b)), max(0.0, min(1.0, a_)))
                     for r, g, b, a_ in zip(f[o_::s], f[o_ + 1::s], f[o_ + 2::s], A)]
            else:
                C = [(1.0, 1.0, 1.0, 1.0)] * nv
        if flip:
            Y = [-y for y in Y]
        d.update(W=W, UV=UV, C=C, X=X, Y=Y, clip=XY_CLIP)
        ws = [w for w in W if w is not None]
        d["layer"] = "scene" if ws and len(ws) == len(W) else "hud"
        if d["layer"] == "hud" and ws and len(ws) >= 0.8 * len(W):
            med = sorted(ws)[len(ws) // 2]
            d["W"] = [w if w is not None else med for w in W]
            d["layer"] = "scene"
        if d["layer"] == "hud" and tex is not None and main_rt in texinfo and (
                tex == main_rt or (tinfo.width, tinfo.height) == (texinfo[main_rt].width, texinfo[main_rt].height)):
            d["layer"] = "post"                       # full-frame post-processing / frame-buffer feedback pass: not scene
        if d["layer"] == "hud":
            xn = [x / w if abs(w) > 1e-9 else x for x, w in zip(X, Wc)] if XY_CLIP else X
            yn = [y / w if abs(w) > 1e-9 else y for y, w in zip(Y, Wc)] if XY_CLIP else Y
            if max(xn) - min(xn) > 1.7 and max(yn) - min(yn) > 1.7:
                d["layer"] = "post"                   # full-screen 2D pass (clear, colour filter, fade, letterbox)
            d["X"], d["Y"], d["clip"] = xn, yn, False
        if d["layer"] == "scene":
            pos_w = [w for w in d["W"] if w > 0]
            if pos_w:
                allw.append(min(pos_w))
                allw.append(max(pos_w))
    draws = [d for d in draws if d["layer"] != "post"]
    # ---------------------------------------------------------------- projection: x_view = x_clip / P00 etc.
    P00 = P11 = None
    src = "fov"
    pr = [d["proj"] for d in draws if d["proj"] and d["layer"] == "scene"]
    if pr:
        best_ = max(set(json.dumps([round(pr_[0][0], 5), round(pr_[1][1], 5)]) for pr_ in pr),
                    key=lambda k: sum(1 for p_ in pr if json.dumps([round(p_[0][0], 5), round(p_[1][1], 5)]) == k))
        p00, p11 = json.loads(best_)
        if 0.05 < abs(p00) < 50 and 0.05 < abs(p11) < 50:
            P00, P11, src = abs(p00), abs(p11), "emulator projection constants"
    if P00 is None:
        if ASPECT <= 0:
            if mode == "pcsx2":
                ASPECT = 4.0 / 3.0                    # PS2 frame buffers are shown at 4:3 whatever their pixel size
            else:
                vp = main[1:] if main else (4, 3)
                ASPECT = (vp[0] / vp[1]) if vp[1] else 4.0 / 3.0
        P11 = 1.0 / math.tan(math.radians(FOVY or 55.0) / 2)
        P00 = P11 / ASPECT
    allw.sort()
    near = allw[0] if allw else 1.0
    far = allw[-1] if allw else 10.0
    near_robust = allw[len(allw) // 50] if allw else 1.0
    hud_d = max(near * 0.9, near_robust * 0.5)
    TIMES["depth"] = round(time.time() - T0, 2)
    # ---------------------------------------------------------------- textures (dedup by content, as seen at that draw)
    texfiles = {}
    doubled = bytes(min(255, i * 2) for i in range(256))
    for d in draws:
        r = d["tex"]
        if r is None:
            continue
        ctl.SetFrameEvent(d["eid"], False)
        t = texinfo[r]
        try:
            data = ctl.GetTextureData(r, rd.Subresource(0, 0, 0))
        except Exception:
            d["tex"] = None
            continue
        h = hashlib.md5(data).hexdigest()
        if h not in texfiles:
            fmt = t.format.Name()
            w_, h_ = t.width, t.height
            if len(data) < w_ * h_ * 4:
                d["tex"] = None
                continue
            px = bytearray(data[:w_ * h_ * 4])
            if fmt.startswith("B8G8R8"):
                px[0::4], px[2::4] = px[2::4], px[0::4]
            if "X8" in fmt:
                px[3::4] = b"\xff" * (w_ * h_)
            if mode == "pcsx2":                                   # GS alpha 0x80 = opaque
                px[3::4] = bytes(px[3::4]).translate(doubled)
            al = bytes(px[3::4])
            if sum(al.count(bytes([v])) for v in range(64)) > 0.9 * len(al):
                px[3::4] = b"\xff" * (w_ * h_)                  # alpha isn't coverage here (GC TEV uses it otherwise)
            name = "tex_%03d.png" % len(texfiles)
            open(os.path.join(OUT, name), "wb").write(png(w_, h_, bytes(px)))
            texfiles[h] = {"file": name, "w": w_, "h": h_, "fmt": fmt, "rid": str(r)}
        d["texf"] = h
    TIMES["textures"] = round(time.time() - T0, 2)
    # ---------------------------------------------------------------- glTF binary (.glb): one node per draw call
    B = bytearray()
    views, accs, meshes, nodes, mats, images, textures, matkey = [], [], [], [], [], [], [], {}

    def view(b, target=None):
        while len(B) % 4:
            B.append(0)
        views.append({"buffer": 0, "byteOffset": len(B), "byteLength": len(b), **({"target": target} if target else {})})
        B.extend(b)
        return len(views) - 1

    def acc(arr, comp, typ, n, mn=None, mx=None, target=34962):
        a_ = {"bufferView": view(arr.tobytes(), target), "componentType": comp, "count": n, "type": typ}
        if mn is not None:
            a_["min"], a_["max"] = mn, mx
        accs.append(a_)
        return len(accs) - 1
    imgidx = {}
    for h, tf in texfiles.items():
        imgidx[h] = len(images)
        images.append({"bufferView": view(open(os.path.join(OUT, tf["file"]), "rb").read()), "mimeType": "image/png", "name": tf["file"]})
        textures.append({"source": len(images) - 1, "sampler": 0, "name": tf["file"]})

    def material(d):
        key = (d.get("texf"), json.dumps(d["blend"]), d["zwrite"])
        if key not in matkey:
            mt = {"name": "untextured", "doubleSided": True, "extensions": {"KHR_materials_unlit": {}},
                  "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 1.0}}
            if d.get("texf"):
                mt["pbrMetallicRoughness"]["baseColorTexture"] = {"index": imgidx[d["texf"]]}
                mt["name"] = texfiles[d["texf"]]["file"]
                mt["alphaMode"], mt["alphaCutoff"] = "MASK", 0.25
            if d["blend"]:
                mt["alphaMode"] = "BLEND"
                mt.pop("alphaCutoff", None)
                mt["extras"] = {"blend": d["blend"], "zwrite": d["zwrite"]}   # the game's blend state (the viewer reproduces it)
            matkey[key] = len(mats)
            mats.append(mt)
        return matkey[key]
    layers = {"scene": [], "hud": []}
    summary = []
    i00, i11 = 1.0 / P00, 1.0 / P11
    for d in draws:
        nv = d["nv"]
        if d["layer"] == "hud":
            P = array.array("f", [c for x, y in zip(d["X"], d["Y"]) for c in (x * hud_d * i00, y * hud_d * i11, -hud_d)])
        elif d["clip"]:                         # clip space: x_view = x_clip / P00, y_view = y_clip / P11, z_view = w_clip
            P = array.array("f", [c for x, y, w in zip(d["X"], d["Y"], d["W"]) for c in (x * i00, y * i11, -w)])
        else:                                   # screen space + depth (PS2): x_view = x_ndc * w / P00
            P = array.array("f", [c for x, y, w in zip(d["X"], d["Y"], d["W"]) for c in (x * w * i00, y * w * i11, -w)])
        used = set(d["idx"])
        pts = [P[3 * v:3 * v + 3] for v in used]
        mn = [min(p_[c] for p_ in pts) for c in range(3)]
        mx = [max(p_[c] for p_ in pts) for c in range(3)]
        if not all(map(math.isfinite, mn + mx)):
            continue
        attrs = {"POSITION": acc(P, 5126, "VEC3", nv, mn, mx)}
        if d.get("texf") and d["UV"]:
            attrs["TEXCOORD_0"] = acc(array.array("f", [c for uv in d["UV"] for c in uv]), 5126, "VEC2", nv)
        attrs["COLOR_0"] = acc(array.array("f", [c for col in d["C"] for c in col]), 5126, "VEC4", nv)
        ix = array.array("I", d["idx"])
        prim = {"attributes": attrs, "indices": acc(ix, 5125, "SCALAR", len(ix), target=34963), "material": material(d)}
        tf = texfiles.get(d.get("texf")) if d.get("texf") else None
        extras = {"draw": d["i"], "eid": d["eid"], "call": d["name"], "vertices": len(used), "triangles": len(ix) // 3,
                  "layer": d["layer"], "texture": tf["file"] if tf else None,
                  "texture_size": [tf["w"], tf["h"]] if tf else None, "texture_format": tf["fmt"] if tf else None,
                  "blend": " ".join(d["blend"]) if d["blend"] else False, "depth": [round(-mx[2], 4), round(-mn[2], 4)]}
        meshes.append({"name": "draw_%04d" % d["i"], "primitives": [prim]})
        nodes.append({"name": "draw_%04d" % d["i"], "mesh": len(meshes) - 1, "extras": extras})
        layers[d["layer"]].append(len(nodes) - 1)
        summary.append(extras)
    nodes.append({"name": "scene", "children": layers["scene"], "extras": {"layer": "scene"}})
    nodes.append({"name": "hud", "children": layers["hud"], "extras": {"layer": "hud", "depth": hud_d}})
    fovy_out = 2 * math.atan(1.0 / P11)
    nodes.append({"name": "game_camera", "camera": 0})
    gl = {"asset": {"version": "2.0", "generator": "gbox scene_capture"}, "scene": 0,
          "scenes": [{"nodes": [len(nodes) - 3, len(nodes) - 2, len(nodes) - 1]}],
          "nodes": nodes, "meshes": meshes, "materials": mats, "accessors": accs, "bufferViews": views,
          "cameras": [{"type": "perspective", "perspective": {"yfov": fovy_out, "aspectRatio": P11 / P00,
                                                                 "znear": max(1e-4, near_robust * 0.2), "zfar": far * 4}}],
          "extensionsUsed": ["KHR_materials_unlit"],
          "extras": {"api": api, "mode": mode, "P00": P00, "P11": P11, "projection_source": src, "z_fit": fitq,
                     "near": near_robust, "far": far, "draws": len(summary)}}
    if images:
        gl.update(images=images, textures=textures, samplers=[{"magFilter": 9728, "minFilter": 9728, "wrapS": 10497, "wrapT": 10497}])
    while len(B) % 4:
        B.append(0)
    gl["buffers"] = [{"byteLength": len(B)}]
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    with open(os.path.join(OUT, "scene.glb"), "wb") as fo:
        fo.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(B)))
        fo.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        fo.write(struct.pack("<II", len(B), 0x004E4942) + bytes(B))
    json.dump({"capture": CAPFILE, "api": api, "mode": mode, "draws_total": len(acts),
               "draws_exported": len(summary), "scene_draws": len(layers["scene"]), "hud_draws": len(layers["hud"]),
               "textures": len(texfiles), "vertices": sum(s_["vertices"] for s_ in summary),
               "triangles": sum(s_["triangles"] for s_ in summary), "P00": P00, "P11": P11, "fovy_deg": math.degrees(fovy_out),
               "aspect": P11 / P00, "projection_source": src, "z_fit": fitq, "near": near_robust, "far": far,
               "target": [str(main[0]), main[1], main[2]] if main else None, "proj_errors": projs[:3],
               "times": dict(TIMES, glb=round(time.time() - T0, 2)), "draw_list": summary}, open(os.path.join(OUT, "scene.json"), "w"), indent=1)
    log.write("OK %d draws\n" % len(summary))
    ctl.Shutdown()
    cap.Shutdown()
except BaseException:
    log.write(traceback.format_exc())
log.close()
os._exit(0)
'''


def extract(rdc, out_dir: Path, fovy: float = 0, aspect: float = 0, mode: str = "auto", timeout: float = 600) -> dict:
    """Replay a .rdc (or the busiest of several) and write out_dir/scene.glb (+ scene.json summary, tex_*.png)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("tex_*.png"):
        f.unlink()
    (out_dir / "extract.log").unlink(missing_ok=True)
    rdcs = [str(r) for r in rdc] if isinstance(rdc, (list, tuple)) else [str(rdc)]
    _qrd(EXTRACT_PY, {"RD_CAP": "|".join(rdcs), "RD_OUT": str(out_dir), "RD_FOVY": str(fovy or ""), "RD_ASPECT": str(aspect or ""),
                      "RD_MODE": mode}, timeout)
    log = (out_dir / "extract.log").read_text(errors="replace") if (out_dir / "extract.log").exists() else "no log"
    if not log.startswith("OK"):
        raise RuntimeError("scene extract failed: " + log[-3000:])
    return json.loads((out_dir / "scene.json").read_text())


# ------------------------------------------------------------------------------------------------ session flow

def capture_session(ad, out_dir: Path, frames: int = 2, fovy: float = 0, aspect: float = 0, progress=None) -> dict:
    """Keep a successful scene paused; restore the original pause state if capture fails."""
    from .registry import Unsupported
    proc = getattr(ad, "proc", None)
    if proc is None or proc.poll() is not None:
        raise Unsupported("This game's emulator has stopped. Open the running game in Sessions.")
    runtime = ad.query_runtime()
    was_paused = runtime.get("paused", False) or runtime.get("state") == "PAUSED" or bool(getattr(ad, "paused_tids", None))
    try:
        result = _capture_session(ad, out_dir, frames, fovy, aspect, progress)
    except Exception:
        try:
            ad.pause() if was_paused else ad.resume()
        except Exception:
            pass
        raise
    return result | {"resume_on_leave": not was_paused}


def _capture_session(ad, out_dir: Path, frames: int = 2, fovy: float = 0, aspect: float = 0, progress=None) -> dict:
    """Pause a live local-window session on a frame and rebuild that frame as a 3D scene. The game stays paused.
    RetroArch: pause, arm the capture, FRAMEADVANCE until it lands (exactly the frames the game is paused on).
    Dolphin (and other emulators without a frame step): arm the capture, let the next frame through, then pause."""
    from .registry import Unsupported
    say = progress or (lambda p, m: None)
    proc = getattr(ad, "proc", None)
    if not hooked(proc):
        if reason := getattr(ad, "examine_unavailable_reason", None):
            raise Unsupported(reason)
        if getattr(ad, "name", None):                      # the capability matrix says why and what would work
            row = session_support(ad, "windows")
            if row["status"] == "unsupported" or row["driver"]:
                raise Unsupported(row["reason"])
        raise Unsupported("this session was started without Examine 3D (RenderDoc isn't inside the emulator): "
                          "relaunch the game with Examine 3D on (save state first)")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    times = {}
    if hasattr(ad, "cmd") and hasattr(ad, "addr"):                       # RetroArch
        say(5, "Pausing the game")
        ad.pause()
        say(10, "Capturing the frame on screen (RenderDoc)")
        rdcs = capture_rdc(proc.pid, frames, step=f"udp:{ad.addr[1]}:FRAMEADVANCE")
    else:
        if getattr(ad, "paused_tids", None):
            ad.resume()
        say(10, "Capturing the next frame (RenderDoc)")
        try:
            rdcs = capture_rdc(proc.pid, frames)
        finally:
            ad.pause()
    times["capture_s"] = round(time.time() - t0, 2)
    try:
        if getattr(ad, "capture_backend", None) and not hasattr(ad, "_screenshot"):
            raise RuntimeError("a capture session's window is parked off-screen: a desktop grab would be black")
        frame = ad.get_frame()
        (out_dir / "frame.png").write_bytes(frame)
    except Exception:
        frame = None
    say(35, f"Rebuilding the 3D scene from {len(rdcs)} captured frame(s)")
    t1 = time.time()
    summary = extract(rdcs, out_dir, fovy, aspect)
    times["extract_s"] = round(time.time() - t1, 2)
    keep = Path(summary["capture"])
    for r in rdcs:                                                       # keep only the frame used (open it in RenderDoc)
        try:
            if Path(r) != keep:
                Path(r).unlink()
        except OSError:
            pass
    try:
        dst = out_dir / "frame.rdc"
        dst.unlink(missing_ok=True)
        shutil.move(str(keep), str(dst))
        summary["capture"] = str(dst)
    except OSError:
        pass
    summary["timings"] = times
    summary["frame_png"] = frame is not None
    return summary


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="gbox.scene_capture", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("inject-launch")
    a.add_argument("argv", nargs=argparse.REMAINDER)
    a = sub.add_parser("capture")
    a.add_argument("--pid", type=int, required=True)
    a.add_argument("--frames", type=int, default=2)
    a.add_argument("--step", default="")
    a = sub.add_parser("extract")
    a.add_argument("rdc", nargs="+")
    a.add_argument("--out", required=True)
    a.add_argument("--fov", type=float, default=0)
    a.add_argument("--aspect", type=float, default=0)
    ns = ap.parse_args(argv)
    if ns.cmd == "inject-launch":
        p = popen_hooked([x for x in ns.argv if x != "--"])
        print(json.dumps({"pid": p.pid, "renderdoc": p.renderdoc}))
    elif ns.cmd == "capture":
        print("\n".join(map(str, capture_rdc(ns.pid, ns.frames, ns.step))))
    else:
        r = extract(ns.rdc, Path(ns.out), ns.fov, ns.aspect)
        r.pop("draw_list", None)
        print(json.dumps(r, indent=1))


# ------------------------------------------------------------------------------------------------ worker tool
from pydantic import BaseModel  # noqa: E402

from .registry import Ctx, tool  # noqa: E402
from .store import sha256  # noqa: E402


class SceneIn(BaseModel):
    session_id: str
    frames: int = 2                        # consecutive frames captured; the busiest is used (30 fps games)
    fovy: float = 0                        # vertical FOV (deg) when the emulator has no projection constants (PS2: 55)
    aspect: float = 0                      # display aspect override (0 = PS2 4:3 / viewport)
    relay: bool = False                    # server: capture this moment in a separate capture session (scene_relay)


class SceneOut(BaseModel):
    session_id: str
    glb: str                               # sha256 of the scene.glb artifact
    summary: dict
    paused: bool = True
    resume_on_leave: bool = True


def _scene_validate(out: SceneOut, arts):
    d = arts.get("scene.glb", b"")
    if d[:4] != b"glTF":
        return ["scene.glb is not a binary glTF"]
    return [] if sha256(d) == out.glb else ["scene.glb hash mismatch"]


@tool("scene_capture", "1.0", SceneIn, SceneOut, capabilities=["runtime", "video", "asset"],
      artifacts=["scene.glb", "scene.json"], timeout_s=900, validate=_scene_validate,
      validation="binary glTF magic + hash",
      side_effects=["pauses the session (resume with session_op resume)"],
      check=lambda c: None if sys.platform == "win32" else "RenderDoc capture runs on the Windows node")
def scene_capture(inp: SceneIn, ctx: Ctx):
    """Examine in 3D: pause a live session and rebuild the frame on screen as a 3D scene (glTF + textures, one node
    per draw call, HUD as its own layer). The game stays paused; resume with session_op resume."""
    from .tools import SESSIONS
    from .registry import Unsupported
    session = SESSIONS.get(inp.session_id)
    if session is None:
        raise Unsupported("This game session is no longer available on its worker. Open the running game in Sessions.")
    ad, g = session
    out = ctx.config.runtime / "scene_capture" / inp.session_id
    s = capture_session(ad, out, max(1, min(inp.frames, 4)), inp.fovy, inp.aspect, ctx.progress)
    try:
        ctx.progress(92, f"Uploading the scene ({s['draws_exported']} draws, {s['textures']} textures)")
        glb = (out / "scene.glb").read_bytes()
        meta = {"session": inp.session_id, "game": g.get("game_id"), "title": g.get("title")}
        ctx.artifact("scene.glb", glb, "model/gltf-binary", **meta)
        ctx.artifact("scene.json", json.dumps(s).encode(), "application/json", **meta)
        if (out / "frame.png").exists():
            ctx.artifact("frame.png", (out / "frame.png").read_bytes(), "image/png", **meta)
        small = {k: v for k, v in s.items() if k not in ("draw_list", "projection")}
        small["glb_bytes"] = len(glb)
        return {"session_id": inp.session_id, "glb": sha256(glb), "summary": small, "paused": True,
                "resume_on_leave": s["resume_on_leave"]}
    except Exception:
        if s["resume_on_leave"]:
            try:
                ad.resume()
            except Exception:
                pass
        raise


if __name__ == "__main__":
    main()
