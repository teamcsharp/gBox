"""Instant rounds: the next Mercenaries round starts from a save state taken at a round's first in-round frame, not from
a walk through the results, the menus and the stage load (operator 2026-10-26: "get mercmode running ... consistently
playing without breaks in between rounds ... seamless and able to go from match to match to match without these loading
screens and waiting. Even if we have to use save states to get where we need").

A Library keeps those states per title build, one folder per (catalog game id, build / mod, disc id + revision), so a
state never reaches another disc or build: <runtime>/round_states/<key>/<room>-<character>-<stamp>.state + .json (its
receipt: room, stage, character, the clock at the frame, when, from which session, bytes, sha256, loads and failures).
At most MAX_PER_COMBO states per (stage, character), MAX_TOTAL and MAX_BYTES per folder: the oldest go first.

Dolphin (the only emulator here with an in-place state load): a capture goes through gBox's demo slot (adapter.jump_save:
slot 10, copied out, the slot file removed - never the operator's slot 1), on a thread, so the round goes on while the
file is written (Capture). A load copies the state over this game's slot-8 file (the checkpoint ring's private slot;
the file that was there is put back afterwards) and presses Dolphin's slot-8 load key, which every gBox Dolphin has
bound since launch (adapter.checkpoint_load: no new hotkey, no relaunch) - load(). The caller verifies the round in RAM
and then leaves the context; a failed check counts against the state (dropped after MAX_FAILS) and against the folder:
TRIP_FAILS failed loads in a row switch instant rounds off for TRIP_S (health.json), so a Dolphin that will not load
states costs at most a few menu walks. RPCS3 has no in-place load (every state load reboots the emulator): no RE5 here.

Which round comes next is Library.choose(): the DJ's pick when one is queued, else a random stage and character (never
the round just played, nor its character), from the library when it holds one and otherwise through the menus - so a
combination the library lacks is captured the first time the menus reach it, and while combinations are missing a
GROW_P share of the rounds walks the menus to one of them.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import random
import re
import shutil
import threading
import time
from pathlib import Path

MAX_PER_COMBO = 2               # states kept per (stage, character)
MAX_TOTAL = 40                  # states kept per library folder (RE4: 4 stages x 5 characters x 2)
MAX_BYTES = 768 * 2**20         # and their bytes (a Dolphin 2609 GameCube state is ~10 MB compressed)
MAX_FAILS = 2                   # a state whose load failed this many times is dropped
TRIP_FAILS, TRIP_S = 3, 6 * 3600.0   # this many failed loads in a row (any states): instant rounds off this long
GROW_P = 0.5                    # x the share of combinations the library lacks: the chance a round walks the menus to one
CAPTURE_WAIT_S = 2.5            # a capture's state must be serialized within this of the round's first frame
LOAD_SLOT = 8                   # the load key gBox binds in every Dolphin (checkpoint_load: F8); the slot file is borrowed
RESTORE_AFTER_FAIL_S = 1.0      # a load that never showed: wait this long before the borrowed slot file is put back
STALE_CAPTURE_S = 3600.0        # a capture-*.tmp this old was never filed (its run ended first): swept by prune()
_SLOT_LOCK = threading.Lock()   # one borrowed slot file at a time (every gBox Dolphin on a host shares its user folder)


def supported(ad) -> str | None:
    """Why this session's emulator cannot run instant rounds; None when it can: a Dolphin with gBox's demo save slot
    (jump_save), the slot-8 load key (checkpoint_load) and the state folder it writes (state_dir)."""
    if ad is None:
        return "no session adapter"
    name = getattr(ad, "name", None) or type(ad).__name__
    if name != "dolphin":
        return f"{name}: no in-place save state load (only Dolphin)"
    if "local_window" in (getattr(ad, "supported", None) or ()):
        return "Windows Dolphin's state hotkeys focus its window (the operator's PC): the Linux node only"
    missing = [a for a in ("jump_save", "checkpoint_load", "state_dir") if not callable(getattr(ad, a, None))]
    if missing:
        return f"{name} has no {', '.join(missing)}"
    return None


def _safe(text, limit: int) -> str:
    return re.sub(r"[^\w.-]", "_", str(text))[:limit] or "_"


def library_key(game: dict | None, disc: bytes, emulator: str | None = None) -> str:
    """<catalog game id>-<build>-<disc id>r<revision>[-dolphin<release>] (the disc header at 0x80000000: id, disc
    number, revision; the emulator's release when known: Dolphin refuses another release's states, so an update starts a
    fresh library instead of failing every stored state)."""
    g = game or {}
    disc = bytes(disc or b"")
    disc_id = disc[:6].decode("ascii", "replace") if len(disc) >= 6 else "nodisc"
    rev = disc[7] if len(disc) > 7 else 0
    key = f"{_safe(g.get('game_id') or 'unknown', 40)}-{_safe(g.get('mod') or 'stock', 60)}-{_safe(disc_id, 6)}r{rev}"
    return key + (f"-dolphin{_safe(emulator, 16)}" if emulator else "")


def emulator_release(ad) -> str | None:
    """The running Dolphin's release ("2609a"): the flatpak's metainfo inside the session's own process (its /app), else
    the installed flatpak's; None when neither can be read (the library key then goes without it)."""
    fp = getattr(ad, "flatpak", "") or "org.DolphinEmu.dolphin-emu"
    places = []
    tree = getattr(ad, "_tree", None)
    try:
        pids = tree() if callable(tree) else []
    except Exception:                                  # noqa: BLE001 - no process tree: the installed flatpak
        pids = []
    places += [Path(f"/proc/{pid}/root/app/share/metainfo/{fp}.metainfo.xml") for pid in pids[:8]]
    places += [Path(root) / "app" / fp / "current" / "active" / "files" / "share" / "metainfo" / f"{fp}.metainfo.xml"
               for root in ("/var/lib/flatpak", str(Path.home() / ".local" / "share" / "flatpak"))]
    for f in places:
        try:
            found = re.search(r'<release version="([^"]+)"', f.read_text(encoding="utf-8", errors="replace")[:20000])
        except OSError:
            continue
        if found:
            return found.group(1)
    return None


def state_release(path: Path) -> str | None:
    """The emulator release a Dolphin state names in its header ("Dolphin 2609a" at 0x20 in 2609's states)."""
    try:
        with open(path, "rb") as f:
            head = f.read(0x80)
    except OSError:
        return None
    found = re.search(rb"Dolphin ([0-9A-Za-z.\-]{2,24})", head)
    return found.group(1).decode("ascii") if found else None


def library_root(ad) -> Path:
    """The adapter's runtime folder (gbox-data/runtime-<os>-<arch>: the emulator build the states belong to)."""
    rt = getattr(getattr(ad, "config", None), "runtime", None)
    return (Path(rt) if rt else Path.home() / ".gbox") / "round_states"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Library:
    """One title build's round states (see the module doc). A combination is (room, character)."""

    def __init__(self, folder: Path, clock=time.time, rng=None):
        self.folder = Path(folder)
        self.clock = clock
        self.rng = rng or random.Random()

    # --- the states ---
    def entries(self) -> list[dict]:
        """Every state with its receipt (+ "file", "meta"), newest first; a receipt without its state is skipped."""
        out = []
        try:
            metas = list(self.folder.glob("*.json"))
        except OSError:
            return out
        for meta in metas:
            if meta.name == "health.json":
                continue
            state = meta.with_suffix(".state")
            try:
                d = json.loads(meta.read_text(encoding="utf-8"))
                if not isinstance(d, dict) or not state.is_file() or type(d.get("room")) is not int \
                        or not isinstance(d.get("character"), str):
                    continue
            except (OSError, ValueError):
                continue
            out.append(d | {"file": str(state), "meta": str(meta)})
        out.sort(key=lambda e: e.get("captured_at") or 0, reverse=True)
        return out

    def by_combo(self) -> dict:
        have: dict = {}
        for e in self.entries():
            have.setdefault((e["room"], e["character"]), []).append(e)
        return have

    def count(self, combo) -> int:
        return len(self.by_combo().get(tuple(combo), ()))

    def add(self, src: Path, meta: dict) -> dict:
        """File a captured state (moved in from src) with its receipt; prunes to the bounds. Returns the entry."""
        self.folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self.clock()))
        stem = f"r{int(meta['room']):03x}-{_safe(meta['character'], 24)}-{stamp}-{os.urandom(3).hex()}"
        state, receipt = self.folder / f"{stem}.state", self.folder / f"{stem}.json"
        shutil.move(str(src), str(state))
        row = dict(meta, captured_at=meta.get("captured_at") or self.clock(), bytes=state.stat().st_size,
                   sha256=_sha256(state), emulator=state_release(state), loads=0, fails=0)
        tmp = receipt.with_suffix(".tmp")
        tmp.write_text(json.dumps(row), encoding="utf-8")
        tmp.replace(receipt)
        self.prune()
        return row | {"file": str(state), "meta": str(receipt)}

    def drop(self, entry: dict) -> None:
        for key in ("file", "meta"):
            try:
                Path(entry[key]).unlink(missing_ok=True)
            except (OSError, KeyError):
                pass

    def prune(self) -> list[dict]:
        """The bounds: MAX_PER_COMBO per combination, then MAX_TOTAL and MAX_BYTES (the oldest go)."""
        dropped, seen, kept = [], {}, []
        for e in self.entries():                                # newest first
            k = (e["room"], e["character"])
            seen[k] = seen.get(k, 0) + 1
            (dropped if seen[k] > MAX_PER_COMBO else kept).append(e)
        total = 0
        for i, e in enumerate(kept):
            total += int(e.get("bytes") or 0)
            if i >= MAX_TOTAL or total > MAX_BYTES:
                dropped.append(e)
        for e in dropped:
            self.drop(e)
        try:                                                    # a capture its run never filed (paused, stopped)
            for f in self.folder.glob("capture-*.tmp"):
                if time.time() - f.stat().st_mtime > STALE_CAPTURE_S:
                    f.unlink(missing_ok=True)
        except OSError:
            pass
        return dropped

    def valid(self, entry: dict) -> str | None:
        """Why this state must not be loaded (None: it may): its bytes changed, or it is empty."""
        try:
            path = Path(entry["file"])
            if path.stat().st_size <= 0:
                return "empty state file"
            if entry.get("sha256") and _sha256(path) != entry["sha256"]:
                return "state file changed since it was captured (sha256)"
        except (OSError, KeyError) as exc:
            return f"state file unreadable: {type(exc).__name__}"
        return None

    def record(self, entry: dict, ok: bool, why: str = "") -> None:
        """A load's outcome: the state's loads / fails (dropped after MAX_FAILS) and the folder's health."""
        try:
            meta = Path(entry["meta"])
            d = json.loads(meta.read_text(encoding="utf-8"))
            if ok:
                d.update(loads=int(d.get("loads") or 0) + 1, fails=0, last_loaded=self.clock())
            else:
                d.update(fails=int(d.get("fails") or 0) + 1, last_failure=str(why)[:200], last_failed=self.clock())
            if not ok and d["fails"] >= MAX_FAILS:
                self.drop(entry)
            else:
                tmp = meta.with_suffix(".tmp")
                tmp.write_text(json.dumps(d), encoding="utf-8")
                tmp.replace(meta)
        except (OSError, ValueError, KeyError):
            pass
        h = self.health()
        if ok:
            h.update(fails_in_a_row=0, loads=int(h.get("loads") or 0) + 1, last_ok=self.clock())
        else:
            h.update(fails_in_a_row=int(h.get("fails_in_a_row") or 0) + 1, fails=int(h.get("fails") or 0) + 1,
                     last_error=str(why)[:200], last_failed=self.clock())
            if h["fails_in_a_row"] >= TRIP_FAILS:
                h["off_until"] = self.clock() + TRIP_S
        self._save_health(h)

    def trip(self, why: str) -> None:
        """Instant rounds off for TRIP_S at once (a load that froze the game)."""
        h = self.health()
        h.update(off_until=self.clock() + TRIP_S, last_error=str(why)[:200], last_failed=self.clock(),
                 fails_in_a_row=max(TRIP_FAILS, int(h.get("fails_in_a_row") or 0)))
        self._save_health(h)

    def health(self) -> dict:
        try:
            d = json.loads((self.folder / "health.json").read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_health(self, h: dict) -> None:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self.folder / "health.tmp"
            tmp.write_text(json.dumps(h), encoding="utf-8")
            tmp.replace(self.folder / "health.json")
        except OSError:
            pass

    def tripped(self) -> str | None:
        """Why instant rounds are off for this folder now (failed loads in a row), else None."""
        h = self.health()
        until = h.get("off_until")
        if isinstance(until, (int, float)) and self.clock() < until:
            left = (until - self.clock()) / 60.0
            return f"off for {left:.0f} more min after {h.get('fails_in_a_row')} failed loads ({h.get('last_error')})"
        return None

    # --- the next round ---
    def choose(self, combos, previous=None, request=None, grow_p: float | None = None):
        """("state", entry) or ("menus", combo) for the next round. combos: every (room, character) the title offers;
        previous: the combination just played; request: the DJ's pick {"room", "character"} (None = any of that part).
        A request is honoured from the library when it can be, else through the menus. Otherwise a random combination,
        never the previous one nor its character (when others exist): from the library, except that while some are
        missing a share grow_p x missing / all of the rounds goes through the menus to a missing one (it is captured)."""
        combos = [tuple(c) for c in combos]
        grow_p = GROW_P if grow_p is None else grow_p
        have = self.by_combo()
        if request:
            want = [c for c in combos if (request.get("room") is None or c[0] == request["room"])
                    and (request.get("character") is None or c[1] == request["character"])]
            stored = [c for c in want if c in have]
            if stored:
                return "state", self._pick(have[self.rng.choice(stored)])
            return "menus", (self.rng.choice(want) if want else None)
        previous = tuple(previous) if previous else None
        fresh = [c for c in combos if c != previous and (previous is None or c[1] != previous[1])] \
            or [c for c in combos if c != previous] or combos
        stored = [c for c in fresh if c in have]
        missing = [c for c in fresh if c not in have]
        lacking = sum(1 for c in combos if c not in have) / max(1, len(combos))
        if stored and not (missing and self.rng.random() < grow_p * lacking):
            return "state", self._pick(have[self.rng.choice(stored)])
        return "menus", self.rng.choice(missing or fresh)

    def _pick(self, entries: list[dict]) -> dict:
        least = min(int(e.get("fails") or 0) for e in entries)
        return self.rng.choice([e for e in entries if int(e.get("fails") or 0) == least])


class Capture:
    """A save state being taken at a round's first frame through Dolphin's demo slot (adapter.jump_save: slot 10, copied
    to dest, the slot file removed), on its own thread. serialized(): Dolphin has taken the snapshot (the slot file has
    appeared, or the save finished), so the round may go on while the file is written and copied."""

    def __init__(self, ad, dest: Path):
        self.ad, self.dest = ad, Path(dest)
        self.t0 = time.time()                          # file times are wall-clock times
        self.done = threading.Event()
        self.error: str | None = None
        self.bytes: int | None = None
        try:
            self.folder = Path(ad.state_dir())
        except Exception:                              # noqa: BLE001 - no folder to watch: wait for the save itself
            self.folder = None
        self.dest.parent.mkdir(parents=True, exist_ok=True)
        self.thread = threading.Thread(target=self._run, daemon=True, name="instant-round-capture")
        self.thread.start()

    def _run(self):
        try:
            self.bytes = int(self.ad.jump_save(self.dest))
        except Exception as exc:                       # noqa: BLE001 - no state this round: told in the receipt
            self.error = f"{type(exc).__name__}: {exc}"[:200]
        finally:
            self.done.set()

    def serialized(self) -> bool:
        if self.done.is_set():
            return self.error is None
        if self.folder is None:
            return False
        try:
            return any(f.stat().st_size > 0 and f.stat().st_mtime >= self.t0 - 1 for f in self.folder.glob("*.s10"))
        except OSError:
            return False

    def wait_serialized(self, wait_s: float = CAPTURE_WAIT_S, sleep=time.sleep, clock=time.monotonic) -> bool:
        end = clock() + wait_s
        while True:
            if self.serialized():
                return True
            if (self.done.is_set() and self.error) or clock() >= end:
                return False
            sleep(0.05)


@contextlib.contextmanager
def load(ad, src: Path, disc_id: str, sid: str | None = None, sleep=time.sleep):
    """Load a library state into the running Dolphin: the state is copied over this game's slot-8 file (what was there
    is kept aside), Dolphin's slot-8 load key is pressed (adapter.checkpoint_load), and the caller checks RAM inside the
    with-block; leaving it puts the borrowed file back. Yields {"verified": False}: the caller sets it True once RAM
    shows the state, else the borrowed file is put back only after RESTORE_AFTER_FAIL_S (a load still pending finds no
    file of ours and fails instead of loading the old one). One borrowed slot at a time; the session's checkpoint ring,
    if it has one, takes no checkpoint meanwhile (gbox.rewind.guard)."""
    from .. import rewind
    with _SLOT_LOCK, rewind.guard(sid or "", "load_state"):
        folder = Path(ad.state_dir())
        folder.mkdir(parents=True, exist_ok=True)
        slot = folder / f"{_safe(disc_id, 6)}.s{LOAD_SLOT:02d}"
        keep = slot.with_name(slot.name + ".instant-keep")
        if keep.is_file():                             # a load cut short before (a crash): the slot's own file first
            os.replace(keep, slot)
        kept = slot.is_file()
        if kept:
            shutil.copyfile(slot, keep)
        outcome = {"verified": False, "slot_file": str(slot)}
        try:
            tmp = slot.with_name(slot.name + ".instant-tmp")
            shutil.copyfile(src, tmp)
            os.replace(tmp, slot)
            ad.checkpoint_load()
            yield outcome
        finally:
            try:
                if not outcome.get("verified"):
                    slot.unlink(missing_ok=True)
                    sleep(RESTORE_AFTER_FAIL_S)
                if kept:
                    os.replace(keep, slot)
                else:
                    slot.unlink(missing_ok=True)
            except OSError:
                pass
