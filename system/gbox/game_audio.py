"""Emulator sound on a Windows node: a ready output device, and a launch that a slow one cannot hold up.

JAYBUILTFINALE, 2026-10-13: every RetroArch log carried
    [WARN] [Audio] Driver "xaudio" has not returned from init after 2 seconds; the device is not opening.
RetroArch opens its audio driver on the main thread, and the network command interface gBox polls (GET_STATUS) is
served by that same loop. While the playback device wakes (the default output is a wireless headset whose base station
powers the link down when idle; XAudio2's mastering voice took 0.1-1.4 s here even with the headset in use, a cold
endpoint's shared-mode init up to 1.8 s), the core has loaded the disc but gBox hears nothing, and a 30 s budget ran out:
"retroarch started but content not running after 30s" (job 19cff4fd02724017).

Here:
- render_endpoints / pick_output: the playback endpoints Windows reports ACTIVE (Core Audio, no extra packages); the
  default one when it is active, else the first active one, so an emulator never opens a stale or unplugged default.
- warm: a silent shared-mode stream on that device while the launch prepares, so a sleeping device is awake by the
  time the emulator opens it.
- BootWatch: reads the RetroArch log while gBox waits. Content loaded + audio still opening extends the wait instead of
  failing; audio init past init_grace_s (or opened late with the loop still silent past stall_s) asks for the next
  driver in [game_audio] retroarch_drivers (xaudio -> wasapi -> null). Never a failure because audio is slow.
- remember / first_driver: a driver that took over from a stalled one starts first on that device for a while, so the
  next launch does not pay for the stall again. null is never remembered (sound comes back on the next launch).
- dolphin / xenia / rpcs3 settings: the same choice for the standalone Windows emulators that have an audio knob.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

from .config import HOST_OS

AUDIO_WARNING = "audio device slow/unavailable"
DRIVERS = ("xaudio", "wasapi", "null")
STATE_FILE = "game-audio.json"                     # <runtime>/: device id -> driver that worked after a stall

# --- RetroArch boot log ---------------------------------------------------------------------------------------------

CONTENT = re.compile(r"\[BOOT\] Game ID|\[Core\] Geometry:|\[Core\] Version of libretro API|\[Content\] Loaded content")
AUDIO_START = re.compile(r"\[Audio\] (?:Starting threaded audio driver|Set audio input rate)")
AUDIO_SLOW = re.compile(r'\[Audio\] Driver "([^"]+)" has not returned from init')
# anything RetroArch logs once the audio driver's init has returned (the driver's own report, or the next subsystems)
AUDIO_DONE = re.compile(r'\[Audio\] Driver "[^"]+" reports a|\[Microphone\]|\[Display\] Found display driver|'
                        r'\[NetCMD\]|\[Audio\] Failed to initialize|\[WASAPI\] .*(?:[Ii]nitialized|Using)')
AUDIO_FAILED = re.compile(r"\[Audio\] Failed to initialize audio driver|[Aa]udio driver.*failed")
AUDIO_FLOWING = re.compile(r"\[Audio\] sinc resampler active path")
# parallel_n64 / mupen64plus: the core has loaded the ROM and started the emulated CPU (the EmuThread running the
# R4300 dynarec). The first rendered frame (and so GET_STATUS "PLAYING") can lag behind this, most of all on Windows
# with the LLE angrylion+cxd4 plugins and a modded ROM whose file table was relocated to Expansion Pak RAM (#1707).
CORE_EXEC = re.compile(r"M64CMD_EXECUTE|Starting R4300 emulator|Init new dynarec")


def boot_phase(log: str) -> dict:
    """What a RetroArch log says about the boot so far (pure: the tests feed it real log text)."""
    start = AUDIO_START.search(log)
    tail = log[start.start():] if start else ""
    slow = AUDIO_SLOW.search(tail)
    return {"content": bool(CONTENT.search(log)), "audio_started": bool(start), "audio_slow": bool(slow),
            "audio_driver": slow.group(1) if slow else None,
            "audio_done": bool(start and AUDIO_DONE.search(tail)), "audio_failed": bool(AUDIO_FAILED.search(tail)),
            "audio_flowing": bool(AUDIO_FLOWING.search(log)), "netcmd": "[NetCMD]" in log,
            "core_exec": bool(CORE_EXEC.search(log))}


class BootWatch:
    """The launch's patience while a RetroArch session boots. observe() each poll with the log so far; decide() says
    'ready' | 'wait' | 'fallback' (relaunch with the next audio driver) | 'fail' (gave up: not an audio problem, or
    audio still not open after extended_wait_s)."""

    def __init__(self, t0: float, boot_wait_s: float = 30.0, extended_wait_s: float = 120.0, init_grace_s: float = 3.0,
                 stall_s: float = 6.0, can_fallback: bool = True):
        self.t0, self.boot_wait_s, self.extended_wait_s = t0, boot_wait_s, extended_wait_s
        self.init_grace_s, self.stall_s, self.can_fallback = init_grace_s, stall_s, can_fallback
        self.seen: dict[str, float] = {}               # phase -> first time it was in the log
        self.phase: dict = boot_phase("")
        self.warning: str | None = None
        self.reason: str | None = None                 # why decide() said fallback / fail

    def observe(self, log: str, now: float) -> dict:
        self.phase = boot_phase(log)
        for k in ("content", "audio_started", "audio_slow", "audio_done", "audio_flowing"):
            if self.phase[k]:
                self.seen.setdefault(k, now)
        if self.phase["audio_slow"]:
            self.warning = AUDIO_WARNING
            if "audio_started" in self.seen:                   # RetroArch warns 2 s after it began: the start was earlier
                self.seen["audio_started"] = min(self.seen["audio_started"], self.seen["audio_slow"] - 2.0)
        return self.phase

    def audio_init_s(self, now: float) -> float | None:
        if "audio_started" not in self.seen:
            return None
        return round(self.seen.get("audio_done", now) - self.seen["audio_started"], 2)

    def deadline(self) -> float:
        """Content loaded and something still in progress (audio opening, or a core that has started executing but not
        yet reported its first frame): the long wait. Otherwise the normal one."""
        p = self.phase
        audio_busy = p["audio_started"] and not p["audio_done"] or p["audio_slow"]
        core_busy = p["core_exec"]                       # parallel_n64 running the R4300, first frame still pending
        return self.t0 + (self.extended_wait_s if p["content"] and (audio_busy or core_busy) else self.boot_wait_s)

    def decide(self, now: float, running: bool) -> str:
        p, seen = self.phase, self.seen
        if running:
            return "ready"
        pending = p["audio_started"] and not p["audio_done"]
        if pending and now - seen["audio_started"] >= self.init_grace_s or p["audio_slow"]:
            self.warning = AUDIO_WARNING
        if self.can_fallback and pending and now - seen["audio_started"] >= self.init_grace_s:
            self.reason = f"audio init not returned after {now - seen['audio_started']:.1f} s"
            return "fallback"
        if self.can_fallback and p["audio_slow"] and p["audio_done"] and now - seen["audio_done"] >= self.stall_s:
            self.reason = f"audio opened late and the core's loop still not answering {now - seen['audio_done']:.1f} s on"
            return "fallback"
        if now >= self.deadline():
            # "content not running after Ns" is what launch_failures classifies as content_timeout (#318)
            elapsed = now - self.t0
            if self.warning:
                self.reason = f"content not running after {elapsed:.0f}s (content loaded, audio still opening)"
            elif p["core_exec"]:
                self.reason = f"content not running after {elapsed:.0f}s (content loaded, core executing)"
            else:
                self.reason = f"content not running after {self.boot_wait_s:.0f}s"
            return "fail"
        return "wait"


def next_driver(driver: str, chain=DRIVERS) -> str | None:
    """The audio driver to try after `driver` stalled (None: nothing left)."""
    chain = list(chain)
    if driver not in chain:
        return chain[0] if chain else None
    i = chain.index(driver)
    return chain[i + 1] if i + 1 < len(chain) else None


def driver_chain(chain, first: str | None = None) -> list[str]:
    """The drivers a launch will try, `first` (a remembered one) moved to the front."""
    out = [d for d in chain if d in DRIVERS] or list(DRIVERS)
    if first in out:
        out = [first] + [d for d in out if d != first]
    if "null" not in out:
        out.append("null")                      # the last resort is always there: a silent game beats no game
    return out


# --- remembered driver per device ------------------------------------------------------------------------------------

_STATE_LOCK = threading.Lock()


def _state_path(runtime: Path) -> Path:
    return Path(runtime) / STATE_FILE


def _load_state(runtime: Path) -> dict:
    try:
        return json.loads(_state_path(runtime).read_text())
    except (OSError, ValueError):
        return {}


def remember(runtime: Path, device_id: str | None, driver: str, stalled: str) -> None:
    """`driver` worked after `stalled` stalled on this device: start with it next time. null is never remembered."""
    if driver == "null" or not driver:
        return
    with _STATE_LOCK:
        st = _load_state(runtime)
        st[device_id or "default"] = {"driver": driver, "stalled": stalled, "at": time.time()}
        p = _state_path(runtime)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(st))
        tmp.replace(p)


def first_driver(runtime: Path, device_id: str | None, hours: float, now: float | None = None) -> str | None:
    rec = _load_state(runtime).get(device_id or "default") or {}
    if rec.get("driver") in DRIVERS and rec["driver"] != "null" and (now or time.time()) - rec.get("at", 0) < hours * 3600:
        return rec["driver"]
    return None


# --- Windows playback endpoints (Core Audio over ctypes) -------------------------------------------------------------

E_RENDER, E_CONSOLE, DEVICE_STATE_ACTIVE, CLSCTX_ALL = 0, 0, 1, 23
CLSID_ENUMERATOR = "BCDE0395-E52F-467C-8E3D-C4579291692E"
IID_ENUMERATOR = "A95664D2-9614-4F35-A746-DE8DB63617E6"
IID_AUDIO_CLIENT = "1CB9AD4C-DBFA-4C32-B178-C2F568A703B2"
IID_RENDER_CLIENT = "F294ACFC-3146-4483-A7BF-ADDCA7C260E2"
PKEY_FRIENDLY_NAME = ("A45C254E-DF1C-4EFD-8020-67D146A850E0", 14)


def _com():
    """ctypes plumbing for the few Core Audio calls used here (vtable index calls, no comtypes/pycaw needed)."""
    import ctypes
    from ctypes import wintypes as W

    class GUID(ctypes.Structure):
        _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16), ("d3", ctypes.c_uint16), ("d4", ctypes.c_ubyte * 8)]

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", W.DWORD)]

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                    ("p", ctypes.c_void_p), ("p2", ctypes.c_void_p)]

    def guid(s):
        g = GUID()
        ctypes.memmove(ctypes.byref(g), uuid.UUID(s).bytes_le, 16)
        return g

    def call(obj, idx, *args, argtypes=()):
        vt = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vt[idx])(obj, *args)

    def release(obj):
        if obj:
            vt = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vt[2])(obj)
    return ctypes, W, guid, call, release, PROPERTYKEY, PROPVARIANT


class _Com:
    """CoInitializeEx for this thread (MTA) and the device enumerator; released on exit."""

    def __enter__(self):
        self.ctypes, self.W, self.guid, self.call, self.release, self.PK, self.PV = _com()
        ole = self.ctypes.windll.ole32
        hr = ole.CoInitializeEx(None, 0) & 0xFFFFFFFF
        self.uninit = hr in (0, 1)                      # S_OK / S_FALSE; RPC_E_CHANGED_MODE: someone else's apartment
        self.enum = self.ctypes.c_void_p()
        hr = ole.CoCreateInstance(self.ctypes.byref(self.guid(CLSID_ENUMERATOR)), None, CLSCTX_ALL,
                                  self.ctypes.byref(self.guid(IID_ENUMERATOR)), self.ctypes.byref(self.enum))
        if hr != 0:
            self.__exit__()
            raise OSError(f"MMDeviceEnumerator unavailable (0x{hr & 0xFFFFFFFF:08x})")
        return self

    def __exit__(self, *exc):
        self.release(getattr(self, "enum", None))
        if self.uninit:
            self.ctypes.windll.ole32.CoUninitialize()

    def dev_id(self, dev) -> str:
        c = self.ctypes
        s = c.c_wchar_p()
        self.call(dev, 5, c.byref(s), argtypes=(c.POINTER(c.c_wchar_p),))
        try:
            return s.value
        finally:
            c.windll.ole32.CoTaskMemFree(s)

    def dev_state(self, dev) -> int:
        c = self.ctypes
        st = self.W.DWORD()
        self.call(dev, 6, c.byref(st), argtypes=(c.POINTER(self.W.DWORD),))
        return st.value

    def dev_name(self, dev) -> str | None:
        c = self.ctypes
        store = c.c_void_p()
        self.call(dev, 4, 0, c.byref(store), argtypes=(self.W.DWORD, c.POINTER(c.c_void_p)))
        try:
            key, pv = self.PK(self.guid(PKEY_FRIENDLY_NAME[0]), PKEY_FRIENDLY_NAME[1]), self.PV()
            self.call(store, 5, c.byref(key), c.byref(pv), argtypes=(c.POINTER(self.PK), c.POINTER(self.PV)))
            name = c.wstring_at(pv.p) if pv.vt == 31 and pv.p else None          # VT_LPWSTR
            c.windll.ole32.PropVariantClear(c.byref(pv))
            return name
        finally:
            self.release(store)

    def device(self, endpoint_id: str):
        c = self.ctypes
        dev = c.c_void_p()
        self.call(self.enum, 5, endpoint_id, c.byref(dev), argtypes=(c.c_wchar_p, c.POINTER(c.c_void_p)))
        return dev


def _enumerate() -> dict:
    with _Com() as com:
        c = com.ctypes
        default_id = None
        dev = c.c_void_p()
        try:
            com.call(com.enum, 4, E_RENDER, E_CONSOLE, c.byref(dev), argtypes=(c.c_int, c.c_int, c.POINTER(c.c_void_p)))
            default_id = com.dev_id(dev)
        except OSError:                                      # E_NOTFOUND: no default playback device at all
            pass
        finally:
            com.release(dev)
        col, n = c.c_void_p(), c.c_uint()
        com.call(com.enum, 3, E_RENDER, DEVICE_STATE_ACTIVE, c.byref(col),
                 argtypes=(c.c_int, com.W.DWORD, c.POINTER(c.c_void_p)))
        out = []
        try:
            com.call(col, 3, c.byref(n), argtypes=(c.POINTER(c.c_uint),))
            for i in range(n.value):
                d = c.c_void_p()
                com.call(col, 4, i, c.byref(d), argtypes=(c.c_uint, c.POINTER(c.c_void_p)))
                try:
                    out.append({"index": i, "id": com.dev_id(d), "name": com.dev_name(d), "state": com.dev_state(d)})
                finally:
                    com.release(d)
        finally:
            com.release(col)
        return {"default_id": default_id, "endpoints": out}


_LAST: dict = {}                                     # the newest listing and when it was taken (one per process)
LISTING_FRESH_S = 10.0


def render_endpoints(timeout_s: float = 2.0) -> dict:
    """{"default_id", "endpoints": [{"index", "id", "name", "state"}]}: the ACTIVE playback endpoints in Windows'
    enumeration order (the order RetroArch's device list uses). Empty off Windows or when Core Audio does not answer
    within timeout_s (never blocks a launch). The first COM activation in a Python process that has called
    platform.system() (its WMI query) took 4-7 s on JAYBUILTFINALE; later ones take milliseconds, so launches start
    this early (Prefetch) and a listing is reused for LISTING_FRESH_S."""
    if HOST_OS != "windows":
        return {"default_id": None, "endpoints": [], "error": "not windows"}
    if _LAST and time.monotonic() - _LAST["t"] < LISTING_FRESH_S:
        return _LAST["r"]
    box: dict = {}

    def run():
        try:
            box["r"] = _enumerate()
            _LAST.update(t=time.monotonic(), r=box["r"])
        except Exception as e:                               # noqa: BLE001 - no device list = the emulator's own default
            box["r"] = {"default_id": None, "endpoints": [], "error": f"{type(e).__name__}: {e}"}
    t = threading.Thread(target=run, daemon=True, name="audio-endpoints")
    t.start()
    t.join(timeout_s)
    return box.get("r") or {"default_id": None, "endpoints": [], "error": f"Core Audio did not answer in {timeout_s:g} s"}


def pick_output(listing: dict, wanted: str = "") -> dict:
    """The device an emulator should open (pure): the configured name when it is active, else the default playback
    device when it is active, else the first active one. {"id", "name", "index", "default", "why"} or {"why"} alone
    / {"none": True, "why"} (no active output) / {"unknown": True, "why"} (no device list: the emulator's default)."""
    eps = [e for e in listing.get("endpoints") or [] if e.get("state", DEVICE_STATE_ACTIVE) == DEVICE_STATE_ACTIVE]
    default_id = listing.get("default_id")
    if wanted:
        hit = next((e for e in eps if (e.get("name") or "").lower() == wanted.lower()), None) \
            or next((e for e in eps if wanted.lower() in (e.get("name") or "").lower()), None)
        if hit:
            return hit | {"default": hit["id"] == default_id, "why": "configured device"}
    d = next((e for e in eps if e["id"] == default_id), None)
    if d:
        return d | {"default": True, "why": "default playback device is active"}
    if eps:
        why = "default playback device is not active" if default_id else "no default playback device"
        return eps[0] | {"default": False, "why": f"{why}: first active device"}
    if listing.get("error"):                         # no list (Core Audio slow / not Windows): the emulator's own default
        return {"unknown": True, "why": listing["error"]}
    return {"none": True, "why": "no active playback device"}


def retroarch_device(listing: dict, chosen: dict) -> str:
    """audio_device for RetroArch's xaudio / wasapi drivers: both match it against their list of active endpoints'
    names first, then read a number as an index into that list. A unique name is stable; a shared one gets the index."""
    if not chosen or chosen.get("none") or "index" not in chosen:
        return ""
    names = [e.get("name") for e in listing.get("endpoints") or [] if e.get("state", 1) == DEVICE_STATE_ACTIVE]
    name = chosen.get("name")
    if name and names.count(name) == 1:
        return name
    return str(chosen["index"])


def selection(config, timeout_s: float = 2.0) -> dict:
    """The device a launch on this node should use, with the reasoning (session detail)."""
    listing = render_endpoints(timeout_s)
    want = getattr(getattr(config, "game_audio", None), "device", "") or ""
    chosen = pick_output(listing, want)
    return {"listing": listing, "chosen": chosen, "retroarch_device": retroarch_device(listing, chosen),
            "active": len(listing.get("endpoints") or []), "error": listing.get("error")}


NOT_READY = {"listing": {}, "chosen": {"unknown": True, "why": "device list not ready in time"}, "retroarch_device": "",
             "active": None, "error": "device list not ready in time"}


class Prefetch:
    """Device choice started at the top of a launch (while it stages, checks BIOS...), then a silent warm-up stream
    on the chosen device until the emulator has its audio open (release()). result() never waits long."""

    def __init__(self, config, warm_device: bool | None = None, hold_s: float = 45.0, timeout_s: float = 10.0):
        ga = getattr(config, "game_audio", None)
        self.config, self.hold_s, self.timeout_s = config, hold_s, timeout_s
        self.warm_device = getattr(ga, "warm_device", True) if warm_device is None else warm_device
        self.sel: dict | None = None
        self.done, self.stop = threading.Event(), threading.Event()
        self.warming: str | None = None
        threading.Thread(target=self._run, daemon=True, name="audio-prefetch").start()

    def _run(self):
        try:
            self.sel = selection(self.config, self.timeout_s)
        except Exception as e:                               # noqa: BLE001
            self.sel = NOT_READY | {"error": f"{type(e).__name__}: {e}"}
        finally:
            self.done.set()
        dev = (self.sel or {}).get("chosen", {}).get("id")
        if self.warm_device and dev and not self.stop.is_set():
            self.warming = dev
            warm(dev, self.hold_s, self.stop)

    def result(self, wait_s: float = 1.0) -> dict:
        self.done.wait(wait_s)
        return self.sel or NOT_READY

    def release(self):
        self.stop.set()


def warm(endpoint_id: str | None, hold_s: float = 20.0, stop: threading.Event | None = None) -> threading.Thread | None:
    """A silent shared-mode stream on the endpoint for up to hold_s (or until `stop`), on its own thread: a device that
    sleeps when idle is awake when the emulator opens it. Never raises; does nothing off Windows."""
    if HOST_OS != "windows" or not endpoint_id:
        return None
    stop = stop or threading.Event()

    def run():
        try:
            with _Com() as com:
                c, W = com.ctypes, com.W
                dev, client, render, fmt = com.device(endpoint_id), c.c_void_p(), c.c_void_p(), c.c_void_p()
                try:
                    com.call(dev, 3, c.byref(com.guid(IID_AUDIO_CLIENT)), CLSCTX_ALL, None, c.byref(client),
                             argtypes=(c.POINTER(type(com.guid(IID_AUDIO_CLIENT))), W.DWORD, c.c_void_p, c.POINTER(c.c_void_p)))
                    com.call(client, 8, c.byref(fmt), argtypes=(c.POINTER(c.c_void_p),))           # GetMixFormat
                    com.call(client, 3, 0, 0, 10_000_000, 0, fmt, None,                            # Initialize: shared, 1 s
                             argtypes=(c.c_int, W.DWORD, c.c_longlong, c.c_longlong, c.c_void_p, c.c_void_p))
                    frames = c.c_uint()
                    com.call(client, 4, c.byref(frames), argtypes=(c.POINTER(c.c_uint),))          # GetBufferSize
                    com.call(client, 14, c.byref(com.guid(IID_RENDER_CLIENT)), c.byref(render),    # GetService
                             argtypes=(c.POINTER(type(com.guid(IID_RENDER_CLIENT))), c.POINTER(c.c_void_p)))
                    buf = c.c_void_p()
                    com.call(render, 3, frames.value, c.byref(buf), argtypes=(c.c_uint, c.POINTER(c.c_void_p)))
                    com.call(render, 4, frames.value, 2, argtypes=(c.c_uint, W.DWORD))             # AUDCLNT_BUFFERFLAGS_SILENT
                    com.call(client, 10)                                                           # Start
                    stop.wait(hold_s)
                    com.call(client, 11)                                                           # Stop
                finally:
                    if fmt:
                        c.windll.ole32.CoTaskMemFree(fmt)
                    com.release(render)
                    com.release(client)
                    com.release(dev)
        except Exception:                                    # noqa: BLE001 - best effort, the launch never waits on it
            pass
    t = threading.Thread(target=run, daemon=True, name="audio-warm")
    t.stop = stop
    t.start()
    return t


# --- standalone emulators ---------------------------------------------------------------------------------------------

def dolphin_backend(sel: dict) -> str:
    """Dolphin.DSP.Backend: Cubeb (WASAPI shared; follows the default device when it comes and goes) with an output to
    open, "No Audio Output" when there is none (Dolphin's XAudio2/OpenAL would wait on a missing device)."""
    return "No Audio Output" if (sel.get("chosen") or {}).get("none") else "Cubeb"


def xenia_apu(sel: dict) -> str | None:
    """Xenia's --apu: nop with no active output (its xaudio2 init would wait on nothing); else Xenia's own default."""
    return "nop" if (sel.get("chosen") or {}).get("none") else None


def rpcs3_audio_yaml(sel: dict) -> str:
    """RPCS3 per-game config Audio section: Cubeb (WASAPI shared, survives device changes) or Null with no output."""
    return f"Audio:\n  Renderer: {'Null' if (sel.get('chosen') or {}).get('none') else 'Cubeb'}\n"


def session_detail(sel: dict, driver: str | None = None, **extra) -> dict:
    """What the session detail records about its sound: driver, device, why, and any warning."""
    ch = sel.get("chosen") or {}
    out = {"driver": driver, "device": ch.get("name"), "device_id": ch.get("id"), "default_device": ch.get("default"),
           "why": ch.get("why"), "active_devices": sel.get("active")}
    if sel.get("error"):
        out["device_error"] = sel["error"]
    return out | {k: v for k, v in extra.items() if v is not None}
