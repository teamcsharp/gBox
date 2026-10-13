"""Universal Select+L2 rewind and Select+R2 fast-forward (#454, #1382), for every emulator gBox runs.

Every session reports `rewind` in its capabilities:

  native       RetroArch cores with rewind_enable: RetroArch's own rewind buffer answers Select+L2 (Select is the hotkey
               enabler in the session cfg). The worker only drives the Select+R2 ramp.
  checkpoint   everything else that saves and loads a state in place (RetroArch heavy cores where rewind_enable would
               stutter: Flycast, PCSX2, Citra, the Dolphin core; standalone Dolphin): the worker keeps a bounded ring
               of periodic save states and each Select+L2 press or hold-repeat loads the next older one. Select+R2
               ramps the adapter's fast_forward when it has one.
  unsupported  no in-place save state (Xenia, Yuzu) or one that reboots the emulator (RPCS3).
  off          checkpoints switched off (gbox.toml [rewind] checkpoints = false, or launch_game rewind=false).

The chord comes from the operator's own pad, which gBox only watches: on Windows the worker polls XInput slot 0 (the
pad itself goes straight to the emulator); for streamed sessions the pad events the browser sends through
/api/sessions/{sid}/input pass through the worker and are watched there (feed). A pad plugged into the Linux node
itself is not read (no evdev dependency; see docs/rewind.md).
"""
import contextlib
import os
import re
import shutil
import threading
import time
from pathlib import Path

from .config import HOST_OS
from .registry import Unsupported

MODES = ("native", "checkpoint", "unsupported", "off")
TRIGGER = 60            # an XInput trigger (0-255) counts as pressed above this, like the RetroArch ramp before it
BACK = 0x0020           # XINPUT_GAMEPAD_BACK = Select / View
STATE_SUFFIX = re.compile(r"\.state(-?\d+)?$")


class FastForwardRamp:
    """Hold Select+R2: 2x for the first 1.5 s, 4x until 3.5 s, then 16x. The emulator runs fast-forward at one fixed
    ratio (16x), so the lower speeds come from switching it on for part of the ticks: each 1/60 s tick earns
    (speed - 1) extra frames and a fast-forwarded tick spends 15 (2x / 4x advance in small bursts of 16 frames)."""
    STAGES = ((1.5, 2.0), (3.5, 4.0))
    TOP = 16.0

    def __init__(self):
        self.t0, self.credit = None, 0.0

    def speed(self, elapsed: float) -> float:
        for until, speed in self.STAGES:
            if elapsed < until:
                return speed
        return self.TOP

    def tick(self, held: bool, now: float) -> bool:
        """One tick: whether fast-forward should be on for this tick."""
        if not held:
            self.t0, self.credit = None, 0.0
            return False
        if self.t0 is None:
            self.t0 = now
        speed = self.speed(now - self.t0)
        if speed >= self.TOP:
            return True
        self.credit += speed - 1.0
        if self.credit >= self.TOP - 1.0:
            self.credit -= self.TOP - 1.0
            return True
        return False


class ChordDetector:
    """Select+L2 / Select+R2 from pad samples (select, l2, r2 held). update() returns the sample's actions:
    rewind_step (on the press, then every repeat_s while held), rewind_end, ff_start, ff_end.
    Select+L2 wins while both triggers are held. Pressing order does not matter."""

    def __init__(self, repeat_s: float = 0.6):
        self.repeat_s = float(repeat_s)
        self.select = self.l2 = self.r2 = False
        self.rewind_held = self.ff_held = False
        self._next = 0.0

    def feed(self, events, now: float) -> list[str]:
        """Pad events as the session input channel carries them ({key, down}); other keys are ignored."""
        for ev in events or []:
            key = str(ev.get("key") or "").lower() if isinstance(ev, dict) else ""
            if key in ("select", "l2", "r2"):
                setattr(self, key, bool(ev.get("down", True)))
        return self.update(self.select, self.l2, self.r2, now)

    def update(self, select: bool, l2: bool, r2: bool, now: float) -> list[str]:
        self.select, self.l2, self.r2 = bool(select), bool(l2), bool(r2)
        out = []
        rewind = self.select and self.l2
        ff = self.select and self.r2 and not rewind
        if rewind and not self.rewind_held:
            self.rewind_held, self._next = True, now + self.repeat_s
            out.append("rewind_step")
        elif rewind and now >= self._next:
            self._next = now + self.repeat_s
            out.append("rewind_step")
        elif not rewind and self.rewind_held:
            self.rewind_held = False
            out.append("rewind_end")
        if ff != self.ff_held:
            self.ff_held = ff
            out.append("ff_start" if ff else "ff_end")
        return out


def _identity(path: Path | None):
    try:
        st = path.stat() if path is not None else None
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns) if st else None


def supports(adapter) -> str | None:
    """Why this adapter cannot feed a checkpoint ring, or None when it can."""
    name = getattr(adapter, "name", None) or "this emulator"
    kind = getattr(adapter, "checkpoint_state", None)
    if kind is False:
        return getattr(adapter, "checkpoint_reason", None) or f"{name}'s save state does not work in place"
    sup = getattr(adapter, "supported", None) or ()
    if "save_state" not in sup or "load_state" not in sup:
        return f"{name} has no save state gBox can trigger"
    if kind not in ("path", "dir"):
        return f"{name} does not tell gBox where its save state file is"
    return None


class CheckpointRing:
    """A bounded ring of periodic save states for one session, taken through the adapter's own save-state mechanism.

    The emulator keeps writing its state where it always does (its slot file, `origin`); the ring copies each fresh
    file into its own folder and, to step back, copies an entry over the slot file and asks the emulator to load.
    "path" adapters (RetroArch: save_state reports the verified file) save in the operator's own slot, so the
    operator's file is stashed before the ring's first save and put back after every ring save and load: the slot
    file on disk stays the operator's. "dir" adapters (Dolphin) save the ring in a private slot through
    checkpoint_save / checkpoint_load; the fresh file is found under state_dir(), nothing to protect.
    Stepping back walks from the newest entry to the oldest; letting go of the chord drops the entries newer than the
    one loaded (that future was undone, like RetroArch's own rewind) and the ring resumes from there."""

    def __init__(self, adapter, directory: Path, interval_s: float = 2.0, depth: int = 60, max_mb: int = 2048,
                 content=None, settle_s: float = 4.0, load_settle_s: float = 0.75, clock=time.monotonic, sleep=time.sleep):
        self.adapter, self.dir = adapter, Path(directory)
        self.interval, self.depth = max(0.25, float(interval_s)), max(1, int(depth))
        self.max_bytes = max(0, int(max_mb)) * 2**20
        self.kind = getattr(adapter, "checkpoint_state", None)
        self.content = Path(content) if content else None
        self.settle_s, self.load_settle_s = settle_s, load_settle_s
        self.clock, self.sleep = clock, sleep
        self.entries: list[dict] = []           # oldest first: {"seq", "file", "ts", "bytes"}
        self.cursor: int | None = None          # index of the entry loaded while the chord is held
        self.busy = threading.Lock()            # held while any save or load (the ring's or the operator's) is in flight
        self.origin: Path | None = None         # the emulator's own slot file the ring copies from / writes to
        self._manual = self.dir / "manual.bin"  # the operator's slot file while the ring borrows the slot
        self._stash: dict | None = None         # before the first save: candidate slot files copied aside
        self._has_manual = False
        self._written = None                    # identity of origin after the ring last wrote it
        self.last_take = self.clock()           # the first checkpoint comes one interval after launch
        self.seq = self.failures = self.taken = 0
        self.error = None
        self.dir.mkdir(parents=True, exist_ok=True)

    # --- periodic checkpoints ---
    def due(self, now: float | None = None) -> bool:
        now = self.clock() if now is None else now
        wait = self.interval if not self.failures else min(30.0, self.interval * 2 ** min(self.failures, 4))
        return self.cursor is None and now - self.last_take >= wait

    def maybe_take(self, now: float | None = None) -> dict | None:
        """Take a checkpoint when one is due and nothing else is saving or loading; never stacks saves."""
        now = self.clock() if now is None else now
        if not self.due(now):
            return None
        if not self.busy.acquire(blocking=False):
            return None
        try:
            self.last_take = now
            try:
                entry = self._take()
            except Exception as exc:               # noqa: BLE001 - the game keeps running; the ring backs off and retries
                self.failures += 1
                self.error = f"{type(exc).__name__}: {exc}"
                return None
            self.failures, self.error = 0, None
            return entry
        finally:
            self.busy.release()

    def _adapter_lock(self):
        return getattr(self.adapter, "_state_lock", None) or contextlib.nullcontext()

    def _call(self, primary: str, fallback: str):
        fn = getattr(self.adapter, primary, None)
        if not callable(fn):
            fn = getattr(self.adapter, fallback)
        return fn()

    def _take(self) -> dict:
        with self._adapter_lock():
            self._follow_slot()
            self._protect_manual()
            protected = self.origin
            started = time.time_ns()
            res = self._call("checkpoint_save", "save_state")
            path = self._locate(res if isinstance(res, dict) else {}, started)
            if self.kind == "path" and protected is not None and path != protected:
                # The save went to a slot the ring had not protected (#1488): never copy another slot's backup onto it.
                self._has_manual, self._written = False, None
            self._adopt_stash()
            self.seq += 1
            dst = self.dir / f"ckpt-{self.seq:06d}.bin"
            shutil.copyfile(path, dst)
            self._written = _identity(path)
            self._restore_manual()
        entry = {"seq": self.seq, "file": dst, "ts": time.time(), "bytes": dst.stat().st_size}
        self.entries.append(entry)
        self.taken += 1
        self._trim()
        return entry

    def _state_folder(self) -> Path | None:
        fn = getattr(self.adapter, "state_dir", None)
        try:
            return Path(fn()) if callable(fn) else None
        except Exception:                          # noqa: BLE001 - adapter without an installed emulator
            return None

    def _locate(self, res: dict, started_ns: int) -> Path:
        """The file the emulator just wrote: reported by the adapter, or the fresh file under its state folder."""
        if self.kind == "path" or res.get("path"):
            path = Path(str(res.get("path") or ""))
            if not res.get("path") or not path.is_file():
                raise RuntimeError("the emulator did not report the save state file it wrote")
            self.origin = path
            return path
        folder = self._state_folder()
        if folder is None:
            raise RuntimeError("no state folder to watch for the save state")
        pattern = getattr(self.adapter, "state_glob", "*")
        deadline, seen = self.clock() + self.settle_s, None
        since = started_ns - 50_000_000                  # file times are coarser than the clock (Windows: ~16 ms ticks)
        while True:
            fresh = [(m, f) for f in folder.glob(pattern) if f.suffix.lower() != ".png"
                     and (m := (_identity(f) or (0, 0))[1]) >= since]
            if fresh:
                f = max(fresh)[1]
                ident = _identity(f)
                if ident and ident[0] > 0 and ident == seen:      # size stable across two polls: the writer is done
                    self.origin = f
                    return f
                seen = ident
            if self.clock() >= deadline:
                raise RuntimeError(f"no fresh save state appeared under {folder} within {self.settle_s:g} s")
            self.sleep(0.1)

    # --- the operator's own slot file ("path" adapters borrow the operator's slot) ---
    def _follow_slot(self) -> bool:
        """The operator (or a diagnostic save, #1488) switched the emulator to another slot since the ring last saved:
        give the old slot file back and protect the new one before the ring's next save lands in it. Without this the
        ring copied slot 0's backup over the freshly preserved slot-15 checkpoint of a frozen PSO session."""
        if self.kind != "path" or self.origin is None:
            return False
        fn = getattr(self.adapter, "checkpoint_target", None)
        try:
            target = fn() if callable(fn) else None
        except Exception:                          # noqa: BLE001 - adapter that cannot tell: keep the known slot
            target = None
        if not target or Path(target) == self.origin:
            return False
        if _identity(self.origin) == self._written:
            self._restore_manual()                 # the old slot is the operator's again
        # else the operator saved to the old slot since the ring last wrote it: that newer save stays, the backup is stale
        self._manual.unlink(missing_ok=True)
        self.origin, self._has_manual, self._written = Path(target), False, None
        return True

    def _protect_manual(self) -> None:
        if self.kind != "path":
            return
        if self.origin is None:                   # first save: the slot file is not known yet, keep every candidate
            if self._stash is None:
                self._stash = {}
                folder = self._state_folder()
                if folder is not None and self.content is not None and folder.is_dir():
                    prefix = self.content.stem + ".state"          # not glob: ROM names carry [ ] and ( )
                    for f in sorted(p for p in folder.iterdir() if p.name.startswith(prefix))[:8]:
                        if f.is_file() and f.suffix.lower() != ".png" and STATE_SUFFIX.search(f.name):
                            dst = self.dir / "stash" / f.name
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(f, dst)
                            self._stash[f.name] = dst
            return
        ident = _identity(self.origin)
        if ident is None:
            self._has_manual = False
        elif ident != self._written:              # the operator saved to this slot since the ring last wrote it
            shutil.copyfile(self.origin, self._manual)
            self._has_manual = True

    def _adopt_stash(self) -> None:
        if not self._stash:
            return
        mine = self._stash.pop(self.origin.name, None) if self.origin is not None else None
        if mine is not None:
            shutil.move(str(mine), str(self._manual))
            self._has_manual = True
        for f in self._stash.values():
            f.unlink(missing_ok=True)
        self._stash = {}

    def _restore_manual(self) -> None:
        if self.kind == "path" and self._has_manual and self.origin is not None:
            shutil.copyfile(self._manual, self.origin)
            self._written = _identity(self.origin)

    # --- ring bounds ---
    def _drop(self, entry: dict) -> None:
        try:
            Path(entry["file"]).unlink(missing_ok=True)
        except OSError:
            pass

    def size(self) -> int:
        return sum(e["bytes"] for e in self.entries)

    def _trim(self) -> None:
        while len(self.entries) > self.depth or (self.max_bytes and self.size() > self.max_bytes and len(self.entries) > 1):
            self._drop(self.entries.pop(0))
            if self.cursor is not None:
                self.cursor = max(0, self.cursor - 1)

    # --- stepping back ---
    def step_back(self) -> dict | None:
        """Load the next older checkpoint (the newest on the first step). None when there is nothing older."""
        with self.busy:
            if not self.entries:
                return None
            nxt = len(self.entries) - 1 if self.cursor is None else self.cursor - 1
            if nxt < 0:
                return None
            entry = self.entries[nxt]
            with self._adapter_lock():
                if self.origin is None:
                    raise RuntimeError("no save state file to load into yet")
                if self._follow_slot():            # load through the slot the emulator is on now, operator file kept
                    self._protect_manual()
                shutil.copyfile(entry["file"], self.origin)
                self._written = _identity(self.origin)
                self._call("checkpoint_load", "load_state")
                if self.kind == "path" and self._has_manual:
                    self.sleep(self.load_settle_s)   # the emulator reads the file on its next frame; then it is the operator's again
                    self._restore_manual()
            self.cursor = nxt
            return entry

    def release(self) -> int:
        """The chord was let go: the game continues from the loaded checkpoint; the undone future is dropped."""
        with self.busy:
            if self.cursor is None:
                return 0
            dropped = self.entries[self.cursor + 1:]
            del self.entries[self.cursor + 1:]
            for e in dropped:
                self._drop(e)
            self.cursor = None
            self.last_take = self.clock()
            return len(dropped)

    @contextlib.contextmanager
    def guard(self):
        """Around an operator save / load: the ring takes no checkpoint while it is in flight."""
        with self.busy:
            yield

    def close(self) -> None:
        with self.busy:
            try:
                self._restore_manual()
            except OSError:
                pass
            self.entries.clear()
            self.cursor = None
            shutil.rmtree(self.dir, ignore_errors=True)

    def status(self) -> dict:
        span = round(self.entries[-1]["ts"] - self.entries[0]["ts"], 1) if len(self.entries) > 1 else 0.0
        return {"entries": len(self.entries), "depth": self.depth, "interval_s": self.interval, "span_s": span,
                "bytes": self.size(), "taken": self.taken, "cursor": self.cursor, "error": self.error}


class XInputPad:
    """The operator's Xbox-layout pad on Windows (XInput slot 0): Select = Back / View, L2 / R2 = the triggers."""

    def __init__(self, slot: int = 0):
        self.slot, self.dll, self.state, self._byref = slot, None, None, None
        if os.name != "nt":
            return
        import ctypes

        class GP(ctypes.Structure):
            _fields_ = [("buttons", ctypes.c_ushort), ("lt", ctypes.c_ubyte), ("rt", ctypes.c_ubyte),
                        ("lx", ctypes.c_short), ("ly", ctypes.c_short), ("rx", ctypes.c_short), ("ry", ctypes.c_short)]

        class ST(ctypes.Structure):
            _fields_ = [("packet", ctypes.c_uint), ("gp", GP)]
        for name in ("xinput1_4", "xinput9_1_0"):
            try:
                dll = getattr(ctypes.windll, name)
            except OSError:
                continue
            dll.XInputGetState.argtypes = [ctypes.c_uint, ctypes.POINTER(ST)]
            dll.XInputGetState.restype = ctypes.c_uint
            self.dll, self.state, self._byref = dll, ST(), ctypes.byref
            break

    @property
    def ok(self) -> bool:
        return self.dll is not None

    def read(self) -> tuple[bool, bool, bool] | None:
        """(select, l2, r2) held, or None without a pad in the slot."""
        if self.dll is None or self.dll.XInputGetState(self.slot, self._byref(self.state)) != 0:
            return None
        g = self.state.gp
        return (bool(g.buttons & BACK), g.lt > TRIGGER, g.rt > TRIGGER)


class SessionRewind:
    """One live session's chord handling: the detector, the fast-forward ramp and (checkpoint sessions) the ring."""

    def __init__(self, sid: str, adapter, mode: str, ring: CheckpointRing | None = None, reason: str | None = None,
                 ramp: bool = True, repeat_s: float = 0.6, clock=time.monotonic, pad=None, native_steps: bool = False):
        self.sid, self.adapter, self.mode, self.ring, self.reason = sid, adapter, mode, ring, reason
        self.chord, self.ramp, self.clock = ChordDetector(repeat_s), FastForwardRamp(), clock
        self.use_ramp = bool(ramp) and "fast_forward" in (getattr(adapter, "supported", None) or ())
        self.native_steps = bool(native_steps)          # native rewind the pad cannot reach itself: the worker sends the steps
        self.pad = pad                                  # a local pad reader (XInputPad) or None
        self.fed = [False, False, False]                # select / l2 / r2 from streamed pad events
        self.ff_on, self.steps, self.ff_holds, self.last_step = False, 0, 0, None
        self._lock = threading.Lock()
        self.threads: list[threading.Thread] = []

    # --- pad sources ---
    def feed(self, events) -> None:
        """Pad events passing through the worker (streamed sessions): remembered, applied on the next poll."""
        for ev in events or []:
            key = str(ev.get("key") or "").lower() if isinstance(ev, dict) else ""
            if key in ("select", "l2", "r2"):
                self.fed[("select", "l2", "r2").index(key)] = bool(ev.get("down", True))

    def sample(self) -> tuple[bool, bool, bool]:
        local = self.pad.read() if self.pad is not None else None
        return tuple(bool(a or b) for a, b in zip(local or (False, False, False), self.fed))

    def poll(self, now: float | None = None, sample=None) -> list[str]:
        """One 60 Hz tick: the chord's actions go to the ring, the held fast-forward to the ramp."""
        now = self.clock() if now is None else now
        with self._lock:
            s = self.sample() if sample is None else sample
            acts = self.chord.update(*s, now)
            for a in acts:
                if a == "rewind_step" and self.ring is not None:
                    entry = self.ring.step_back()
                    if entry is not None:
                        self.steps, self.last_step = self.steps + 1, entry
                elif a == "rewind_step" and self.native_steps:
                    try:
                        self.adapter.rewind(self.chord.repeat_s)   # one repeat's worth through the emulator's own buffer
                        self.steps += 1
                    except Exception:                   # noqa: BLE001 - rewind off or the emulator between frames
                        pass
                elif a == "rewind_end" and self.ring is not None:
                    self.ring.release()
                elif a == "ff_start":
                    self.ff_holds += 1
            if self.use_ramp:
                self._set_ff(self.ramp.tick(self.chord.ff_held, now))
            return acts

    def _set_ff(self, want: bool) -> None:
        if want == self.ff_on:
            return
        try:
            try:
                self.adapter.fast_forward(on=want)
            except TypeError:                       # an adapter whose fast_forward is a plain toggle
                self.adapter.fast_forward()
            self.ff_on = want
        except Exception:                           # noqa: BLE001 - the emulator may be between frames or gone
            pass

    # --- threads (the real worker) ---
    def run(self, alive) -> None:
        def mine():
            return alive() and ACTIVE.get(self.sid) is self

        def pads():
            while mine():
                time.sleep(1 / 60)
                try:
                    self.poll()
                except Exception:                   # noqa: BLE001
                    time.sleep(0.25)
            if ACTIVE.get(self.sid) is self:        # the session ended without stop(): clean up anyway
                stop(self.sid)

        def ring():
            # Dolphin's hotkeys are keystrokes into the game window (focus goes there): only while the operator plays
            gate = bool(getattr(self.adapter, "checkpoint_when_playing", False))
            while mine():
                time.sleep(0.1)
                if gate and not _player_active(self.sid):
                    continue
                self.ring.maybe_take()
        self.threads = [threading.Thread(target=pads, daemon=True, name=f"rewind-pad-{self.sid}")]
        if self.ring is not None:
            self.threads.append(threading.Thread(target=ring, daemon=True, name=f"rewind-ring-{self.sid}"))
        for t in self.threads:
            t.start()

    def close(self) -> None:
        with self._lock:
            self._set_ff(False)
            if self.ring is not None:
                self.ring.close()

    def status(self) -> dict:
        d = {"rewind": self.mode, "fast_forward_ramp": self.use_ramp}
        if self.native_steps:
            d["native_steps"] = True
        if self.reason:
            d["reason"] = self.reason
        if self.ring is not None:
            d.update(self.ring.status())
        if self.last_step is not None:
            d["last_step_age_s"] = round(time.time() - self.last_step["ts"], 1)
        return d


def _player_active(sid: str, within: float = 3.0) -> bool:
    try:
        from .padstate import player_active
        return player_active(sid, within)
    except Exception:                                   # noqa: BLE001
        return True


# --- the worker's live sessions ---
ACTIVE: dict[str, SessionRewind] = {}


def ring_dir(config, sid: str) -> Path:
    return Path(config.runtime) / "rewind" / sid


def sweep(config) -> None:
    """Rings of sessions that are gone (a previous worker run): deleted."""
    root = Path(config.runtime) / "rewind"
    try:
        for d in root.iterdir() if root.is_dir() else ():
            if d.name not in ACTIVE:
                shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass


def start(sid: str, adapter, config, game: dict | None = None, enabled: bool | None = None, alive=None,
          threads: bool = True) -> dict:
    """Attach the chord handling to a session that just launched; returns its status (rewind kind, ring settings)."""
    rc = getattr(config, "rewind", None)
    checkpoints = bool(getattr(rc, "checkpoints", True)) if enabled is None else bool(enabled)
    interval, depth = getattr(rc, "interval_s", 2.0), getattr(rc, "depth", 60)
    max_mb, repeat = getattr(rc, "max_mb", 2048), getattr(rc, "repeat_s", 0.6)
    native = bool(getattr(adapter, "rewind_on", False))
    ring = reason = None
    if native:
        mode = "native"
    else:
        reason = supports(adapter)
        if reason:
            mode = "unsupported"
        elif not checkpoints:
            mode, reason = "off", "checkpoint rewind is switched off for this session"
        else:
            mode = "checkpoint"
            sweep(config)
            interval = max(float(interval), float(getattr(adapter, "checkpoint_min_interval_s", 0) or 0))
            ring = CheckpointRing(adapter, ring_dir(config, sid), interval, depth, max_mb,
                                  content=(game or {}).get("_rom_path"))
    # The pad reaches RetroArch's own hotkeys on Windows (XInput binds in the session cfg) and, streamed, where the
    # game leaves the triggers free (trigger_hotkeys); elsewhere the worker drives the native rewind and the ramp itself.
    hotkeys = HOST_OS == "windows" or bool(getattr(adapter, "trigger_hotkeys", False))
    native_steps = mode == "native" and not hotkeys
    ramp = mode != "native" or HOST_OS == "windows" or native_steps
    pad = XInputPad() if HOST_OS == "windows" and threads else None
    sr = SessionRewind(sid, adapter, mode, ring, reason, ramp=ramp, repeat_s=repeat, pad=pad if pad and pad.ok else None,
                       native_steps=native_steps)
    old = ACTIVE.pop(sid, None)
    if old is not None:
        old.close()
    ACTIVE[sid] = sr
    if threads and (ring is not None or sr.use_ramp or native_steps):
        sr.run(alive or (lambda: sid in ACTIVE))
    return sr.status()


def stop(sid: str) -> SessionRewind | None:
    """The session ended: fast-forward off, the ring's files deleted."""
    sr = ACTIVE.pop(sid, None)
    if sr is not None:
        sr.close()
    return sr


def feed(sid: str, events) -> None:
    sr = ACTIVE.get(sid)
    if sr is not None:
        sr.feed(events)


def mode(sid: str) -> str | None:
    sr = ACTIVE.get(sid)
    return sr.mode if sr is not None else None


def status(sid: str) -> dict | None:
    sr = ACTIVE.get(sid)
    return sr.status() if sr is not None else None


def capabilities(sid: str, caps: dict | None) -> dict:
    """The adapter's capabilities with `rewind` telling which kind this session has (native / checkpoint / unsupported / off)."""
    out = dict(caps or {})
    sr = ACTIVE.get(sid)
    if sr is not None:
        out["rewind"] = sr.mode
    return out


def step(sid: str, seconds: float = 5.0) -> dict:
    """The API / agent form of Select+L2 on a checkpoint session: back `seconds` through the ring."""
    sr = ACTIVE.get(sid)
    if sr is None or sr.ring is None:
        raise Unsupported((sr.reason if sr is not None else None) or "this session has no checkpoint rewind")
    n = max(1, round(float(seconds) / sr.ring.interval))
    loaded, done = None, 0
    for _ in range(n):
        entry = sr.ring.step_back()
        if entry is None:
            break
        loaded, done = entry, done + 1
    sr.ring.release()
    if loaded is None:
        raise RuntimeError("no checkpoint yet: the ring takes its first one a few seconds after launch")
    sr.steps, sr.last_step = sr.steps + done, loaded
    return {"kind": "checkpoint", "steps": done, "rewound_s": round(time.time() - loaded["ts"], 1),
            "requested_s": float(seconds)}


@contextlib.contextmanager
def guard(sid: str, op: str | None = None):
    """Around an operator save / load / transfer on a session: the ring takes no checkpoint meanwhile."""
    sr = ACTIVE.get(sid)
    if sr is None or sr.ring is None or op not in (None, "save_state", "load_state", "transfer"):
        yield
        return
    with sr.ring.guard():
        yield
