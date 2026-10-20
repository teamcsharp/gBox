"""The RAM inspector (docs/ram_maps.md): a live session's memory by name, its state changes as events, a hex view and
a search that finds new addresses, on the control plane.

Operator 2026-10-20: "some sort of RAM inspector that lets us see in real time what's happening in the game and to
identify the hex codes associated with QTE events and door opening events and map navigation ... Vision analysis to me
should be the last level that we have to fall back to".

One Inspector per running session, made on first use:
  * its reader (gbox/ram_reader.py): the session's own adapter when its worker runs in this process (the Spark's serve
    --worker: Dolphin's shared RAM views, read-only, no halt), else its worker over the session channel; every read
    within a budget, so watching never stalls the game or the stream;
  * its RAM map (gbox/ram_map.py): the catalog game id, else the disc id read from RAM (GameCube / Wii);
  * live values: the map evaluated at most MAX_HZ times a second however many viewers poll, and while someone watches
    (the panel, a search labeler: watch()) a thread keeps evaluating it, logging each change of a watched field (enum /
    flags) as an event; the frame the control plane holds for the stream is kept with the newest events (a reference
    to bytes already there: no encoding, no request to the worker);
  * hex: a range now, optionally at the end of a pointer chain;
  * search (gbox/ram_search.py): snapshots of a region (MEM1 by default), Cheat Engine filters, and samples labeled
    "on" / "off" by the operator's buttons or a labeler thread: the screen-prompt watcher on the stream's frames
    (gbox/screen_prompt.py; vision only labels, it is never the answer) or a RAM-map field's condition;
  * promote: a found address into the game's map overlay (gbox-data/ram_maps), with name, type, description, enum.

Nothing here writes game memory, sends input or touches save states: it only reads.

  GET  /api/ram/maps                              the maps (id, title, fields, promoted fields)
  GET  /api/ram/maps/{map_id}                     one map, merged with its overlay
  POST /api/ram/maps/{map_id}/fields              {name, field}: add / replace a field in the overlay
  DELETE /api/ram/maps/{map_id}/fields/{name}     remove a promoted field
  GET  /api/sessions/{sid}/ram                    the inspector: map, reader, budget, watch, search
  GET  /api/sessions/{sid}/ram/live?since=N       the map's values now (rows) + events after seq N; keeps watching
  GET  /api/sessions/{sid}/ram/events?since=N     the event log
  GET  /api/sessions/{sid}/ram/frames/{fid}.jpg   the frame kept with an event
  GET  /api/sessions/{sid}/ram/hex?address=&length=&pointer=   bytes now (pointer: "base,off1,off2" chain)
  POST /api/sessions/{sid}/ram/search             {type, base?, size?, tolerance?}: start (first snapshot taken)
  GET  /api/sessions/{sid}/ram/search?limit=      status + candidates
  POST /api/sessions/{sid}/ram/search/sample      {label?: on|off, op?, value?, lo?, hi?}: one sample
  POST /api/sessions/{sid}/ram/search/auto        {source: screen_prompt|field|off, button?, field?, cond?, hz?,
                                                  tolerance?}: a labeler (a read counts once its label held after it)
  DELETE /api/sessions/{sid}/ram/search           end it (frees its memory)
  POST /api/sessions/{sid}/ram/promote            {name, address | pointer, type, description, enum, ...}
"""
from __future__ import annotations

import collections
import math
import threading
import time
from datetime import date

from fastapi import Depends, HTTPException, Response
from pydantic import BaseModel, Field

from . import ram_map, ram_reader
from .ram_search import OPS, TYPES, Search, SearchError

MAX_HZ = 10.0                       # evaluations per second per session, however many poll
WATCH_S = 15.0                      # a poll keeps the watcher running this long
EVENTS_KEPT, FRAMES_KEPT = 500, 40
FRAME_FRESH_S = 2.0                 # a frame older than this is not this moment
MAP_REFRESH_S = 5.0
HEX_MAX = 4096
MAX_SEARCHES = 2                    # searches at once on this control plane (each up to ram_search.MAX_BYTES)
AUTO_MAX_S = 1800.0                 # a labeler stops by itself after this
HZ_BY_KIND = {"shm": 10.0, "procmem": 10.0, "adapter": 4.0, "rpc": 4.0, "gdb": 2.0}
EVAL_WAIT_S = 0.05                  # a live read waits this long for its budget, then the last values are served
DISC_PLATFORMS = ("gamecube", "wii")


def _safe(v):
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, list):
        return [_safe(x) for x in v]
    return v


class Inspector:
    def __init__(self, sid: str, session: dict, reader, frame=None, clock=time.time, sleep=time.sleep, remake=None):
        self.sid, self.session, self.reader = sid, session, reader
        self.frame_fn, self.clock, self.sleep = frame, clock, sleep
        self.remake, self.remade_at = remake, -1e9     # a new reader when every read fails (the emulator relaunched)
        self.platform = str(session.get("platform") or "")
        self.game_id = str(session.get("game_id") or "")
        self.disc_id = None
        self.map: ram_map.RamMap | None = None
        self.map_error = None
        self.map_at = -1e9
        self.eval_lock, self.search_lock = threading.Lock(), threading.Lock()
        self.last: ram_map.RamValues | None = None
        self.last_at = -1e9
        self.events: collections.deque = collections.deque(maxlen=EVENTS_KEPT)
        self.seq = 0
        self.frames: collections.OrderedDict = collections.OrderedDict()
        self.demand_until = 0.0
        self.hz = HZ_BY_KIND.get(getattr(reader, "kind", ""), 4.0)
        self.thread = None
        self.closed = False
        self.error = None
        self.evaluations = self.throttled = 0
        self.search: Search | None = None
        self.search_info: dict = {}
        self.labeler: AutoLabel | None = None
        self._refresh_map(force=True)

    # -- the map --
    def _refresh_map(self, force: bool = False):
        now = self.clock()
        if not force and now - self.map_at < MAP_REFRESH_S:
            return
        self.map_at = now
        keys = {"game_id": self.game_id, "disc_id": self.disc_id}
        try:
            m = ram_map.find(keys)
            if m is None and self.platform in DISC_PLATFORMS and self.disc_id is None:
                raw = self.reader.read(0x80000000, 6, wait=1.0)        # the disc id at the start of MEM1
                self.disc_id = raw.decode("ascii") if raw.isalnum() else ""
                m = ram_map.find({"disc_id": self.disc_id}) if self.disc_id else None
            if m is None:
                mid = ram_map.detect(self.reader, self.platform) if not self.map else None
                m = ram_map.find(mid) if mid else None
            if m is not None:
                if self.map is None or m.spec != self.map.spec:      # a new map only when its files changed
                    self.map = m
                self.map_error = None
            elif self.map is None:
                self.map_error = (f"no RAM map for this game yet (profiles/gamedata/<{'disc id' if self.platform in DISC_PLATFORMS else 'game id'}>"
                                  f"{ram_map.SUFFIX}; docs/ram_maps.md): the hex view and search still work, and search can add fields")
        except Exception as e:                       # noqa: BLE001 - a broken map file must not take the inspector down
            self.map_error = f"{type(e).__name__}: {e}"[:400]

    def map_id(self) -> str:
        """The id a promoted field goes under: the map's, else the disc id (GameCube / Wii), else the game id."""
        if self.map is not None:
            return self.map.id
        if self.platform in DISC_PLATFORMS and self.disc_id is None:
            try:
                raw = self.reader.read(0x80000000, 6, wait=1.0)
                self.disc_id = raw.decode("ascii") if raw.isalnum() else ""
            except Exception:                        # noqa: BLE001
                self.disc_id = ""
        return self.disc_id or self.game_id

    def big_endian(self) -> bool:
        return (self.map.endian_name == "big") if self.map else self.platform in ram_map.BIG

    # -- live values and events --
    def values(self, max_age: float | None = None) -> ram_map.RamValues | None:
        """The map's values, read again when the last read is older than max_age (at most MAX_HZ reads a second)."""
        max_age = 1.0 / MAX_HZ if max_age is None else max(max_age, 1.0 / MAX_HZ)
        with self.eval_lock:
            self._refresh_map()
            now = self.clock()
            if self.map is None or (self.last is not None and now - self.last_at < max_age):
                return self.last
            try:
                vals = self.map.read(ram_map.Mem(self.reader, wait=EVAL_WAIT_S), clock=self.clock)
            except ram_reader.Throttled:
                self.throttled += 1
                return self.last
            except Exception as e:                   # noqa: BLE001 - the emulator went away / a broken reader
                self.error = f"{type(e).__name__}: {e}"[:300]
                return self.last
            if self.map.fields and len(vals.errors) == len(self.map.fields) and self._remake(now):
                return self.last                     # nothing read: a new reader tries next time
            self.error = None
            self.evaluations += 1
            if self.last is not None:
                self._log(ram_map.changes(self.last, vals), now)
            self.last, self.last_at = vals, now
            return vals

    def _remake(self, now: float) -> bool:
        if self.remake is None or now - self.remade_at < MAP_REFRESH_S:
            return False
        self.remade_at = now
        try:
            new = self.remake()
        except Exception:                            # noqa: BLE001
            new = None
        if new is None:
            return False
        old, self.reader = self.reader, new
        old.close()
        self.error = "every read failed: reading the session again (did its emulator restart?)"
        return True

    def _log(self, changes: list[dict], now: float):
        if not changes:
            return
        fid = None
        got = self.frame_fn(self.sid) if self.frame_fn else None
        if got and got[0] and now - (got[2] or 0) <= FRAME_FRESH_S:
            fid = self.seq + 1
            self.frames[fid] = got[0]                # the stream's own JPEG: a reference, nothing encoded
            while len(self.frames) > FRAMES_KEPT:
                self.frames.popitem(last=False)
        for c in changes:
            self.seq += 1
            self.events.append({"seq": self.seq, "t": round(now, 3), "field": c["field"], "old": _safe(c["old"]),
                                "new": _safe(c["new"]), "old_label": c.get("old_label"), "new_label": c.get("new_label"),
                                "frame": fid})

    def events_since(self, since: int = 0, limit: int = 200) -> list[dict]:
        return [e for e in self.events if e["seq"] > since][-max(1, min(limit, EVENTS_KEPT)):]

    def watch(self, seconds: float = WATCH_S):
        """Keep evaluating for `seconds` more (events are only seen while something watches)."""
        self.demand_until = max(self.demand_until, self.clock() + seconds)
        if self.closed or (self.thread is not None and self.thread.is_alive()):
            return
        self.thread = threading.Thread(target=self._run, daemon=True, name=f"ram-watch-{self.sid[-8:]}")
        self.thread.start()

    def _run(self):
        period = 1.0 / max(0.5, min(self.hz, MAX_HZ))
        while not self.closed and self.clock() < self.demand_until:
            t0 = time.monotonic()
            self.values(max_age=period * 0.9)
            self.sleep(max(0.01, period - (time.monotonic() - t0)))

    # -- hex --
    def hex(self, address: int, length: int = 256, pointer: list[int] | None = None) -> dict:
        length = max(1, min(int(length), HEX_MAX))
        chain = []
        if pointer:
            psize = self.map.pointer_size if self.map else 4
            lo, hi = self.map.pointer_range if self.map else ram_map.RAM_RANGE.get(self.platform, (1, 1 << 64))
            addr = pointer[0]
            for off in pointer[1:]:
                p = int.from_bytes(self.reader.read(addr, psize, wait=1.0), "big" if self.big_endian() else "little")
                chain.append({"at": ram_map.hexa(addr), "value": ram_map.hexa(p), "offset": f"0x{off:X}"})
                if not lo <= p < hi:
                    raise LookupError(f"null pointer: {ram_map.hexa(addr)} holds {ram_map.hexa(p)}")
                addr = p + off
            address = addr
        data = self.reader.read(int(address), length, wait=1.0)
        return {"address": int(address), "address_hex": ram_map.hexa(int(address)), "length": len(data),
                "hex": data.hex(), "chain": chain, "big_endian": self.big_endian(), "at": round(self.clock(), 3)}

    # -- search --
    def default_region(self) -> tuple[int, int]:
        if self.map is not None and self.map.regions:
            _, base, size = self.map.regions[0]
            return base, size
        try:
            from .tools import MAIN_RAM
            base, size = MAIN_RAM[self.platform][0]
            return base, size
        except (ImportError, KeyError, IndexError):
            raise SearchError(f"no main-RAM layout for {self.platform or 'this platform'}: give base and size")

    def search_start(self, type: str = "u8", base: int | None = None, size: int | None = None, tolerance: int = 0) -> dict:
        with self.search_lock:
            self._stop_labeler()
            self.search = None
            if base is None or size is None:
                base, size = self.default_region()
            s = Search(base, size, type, big_endian=self.big_endian(), tolerance=tolerance, clock=self.clock)
            self.search, self.search_info = s, {"started_by": None}
        self._sample(None, None, None, None, None, "first snapshot")
        return self.search_status()

    def search_end(self):
        with self.search_lock:
            self._stop_labeler()
            self.search = None

    def _read_sample(self, s: Search):
        ranges = s.candidate_ranges()
        if ranges is None:
            data, err = self.reader.snapshot(s.base, s.size, wait=30.0, stop=lambda: self.closed)
            if err:
                raise RuntimeError(f"RAM read stopped after {len(data):,} of {s.size:,} bytes: {err}")
            return data
        if not ranges:
            return []
        got = self.reader.read_many(ranges, wait=10.0)
        bad = [(a, d) for (a, _), d in zip(ranges, got) if isinstance(d, Exception)]
        if bad:
            raise RuntimeError(f"{len(bad)} candidate ranges unreadable, first at {ram_map.hexa(bad[0][0])}: {bad[0][1]}")
        return [(a, d) for (a, _), d in zip(ranges, got)]

    def _sample(self, label, op, value, lo, hi, note="", data=None, search=None):
        """Read the search's region (or its candidates) and apply one sample; data / search: a sample read earlier
        for that search (the labeler confirms its label first)."""
        with self.search_lock:
            s = self.search
            if s is None:
                raise SearchError("start a search first")
            if search is not None and s is not search:
                raise SearchError("the search was restarted")
            if data is None:
                data = self._read_sample(s)
            if self.search is not s:
                raise SearchError("the search was restarted")
            return s.sample(data, label=label, op=op, value=value, lo=lo, hi=hi, note=note)

    def search_sample(self, label=None, op=None, value=None, lo=None, hi=None, note="") -> dict:
        self._sample(label, op, value, lo, hi, note)
        return self.search_status()

    def search_status(self, limit: int = 60) -> dict:
        s = self.search
        if s is None:
            return {"active": False}
        out = {"active": True, **s.status(), "base_hex": ram_map.hexa(s.base),
               "candidates_list": [dict(c, address_hex=ram_map.hexa(c["address"])) for c in s.candidates(limit)]}
        if self.labeler is not None:
            out["auto"] = self.labeler.status()
        return out

    def auto(self, source: str, field: str | None = None, cond: dict | None = None, hz: float = 8.0,
             button: str | None = None, tolerance: int | None = None) -> dict:
        with self.search_lock:
            if self.search is None:
                raise SearchError("start a search first")
            self._stop_labeler()
            if source in ("off", "", None):
                return {"source": "off"}
            if tolerance is not None:                  # labels from vision are late at the edges: allow a few
                self.search.tolerance = max(0, int(tolerance))
            if source == "screen_prompt":
                label_fn = prompt_labeler(self, button)
            elif source == "field":
                label_fn = field_labeler(self, field, cond)
            else:
                raise SearchError("source is screen_prompt, field or off")
            self.labeler = AutoLabel(self, source, label_fn, hz=hz, detail={"field": field, "cond": cond, "button": button})
        self.labeler.start()
        return self.labeler.status()

    def _stop_labeler(self):
        if self.labeler is not None:
            self.labeler.stop()
            self.labeler = None

    # -- the rest --
    def status(self) -> dict:
        return {"session_id": self.sid, "platform": self.platform, "game_id": self.game_id, "disc_id": self.disc_id,
                "map": {"id": self.map.id, "title": self.map.title, "fields": len(self.map.fields),
                        "overlay_fields": self.map.overlay_fields} if self.map else None,
                "map_error": self.map_error, "map_id": self.map_id() if self.map is None else self.map.id,
                "reader": self.reader.describe(), "hz": self.hz, "watching": self.thread is not None and self.thread.is_alive(),
                "evaluations": self.evaluations, "throttled": self.throttled, "error": self.error, "events": self.seq,
                "search": self.search_status(limit=0) if self.search else {"active": False}}

    def close(self):
        self.closed = True
        self._stop_labeler()
        self.search = None
        t = self.thread
        if t is not None and t is not threading.current_thread():
            t.join(2.0)                              # its last read finishes before the reader goes
        try:
            self.reader.close()
        except Exception:                            # noqa: BLE001
            pass


# --- labelers ---------------------------------------------------------------------------------------------------------
def prompt_labeler(insp: Inspector, button: str | None = None):
    """on while the game shows a button prompt (gbox.screen_prompt on the stream's newest frame), else off; None when
    there is no fresh frame. Vision is only the labeler here: the search's answer is the RAM."""
    try:
        from . import screen_prompt
    except ImportError as e:
        raise SearchError(f"the screen-prompt watcher is not on this control plane ({e})")
    profile = insp.disc_id or (insp.map.id if insp.map else "")
    if profile not in screen_prompt.PROFILES:
        profile = screen_prompt.DEFAULT
    seen = {"frame": None, "label": None}

    def label():
        got = insp.frame_fn(insp.sid) if insp.frame_fn else None
        if not got or not got[0] or insp.clock() - (got[2] or 0) > FRAME_FRESH_S:
            return None, "no fresh frame"
        if got[1] == seen["frame"]:
            return seen["label"], "same frame"
        try:
            found = screen_prompt.detect(screen_prompt.decode(got[0]), profile)
        except Exception as e:                       # noqa: BLE001 - a torn frame
            return None, f"frame unreadable: {e}"
        on = bool(found) and (button is None or found["button"] == button)
        seen.update(frame=got[1], label="on" if on else "off")
        return seen["label"], (f"button {found['button']}" if found else "no prompt")
    return label


def field_labeler(insp: Inspector, field: str | None, cond: dict | None):
    """on while a RAM-map field meets cond ({"eq": 3} / {"ne": 0} / {"mask": "0x100", "ne": 0} / {"in": [..]}), else off."""
    if insp.map is None or field not in (insp.map.fields if insp.map else {}):
        raise SearchError(f"{field!r} is not a field of this game's map")
    if insp.map.fields[field].type == "struct":
        raise SearchError("label with a field that holds one value, not a struct array")
    cond = dict(cond or {"ne": 0})
    cond["field"] = "v"
    problems = ram_map._cond_check(cond, {"v"}, field)
    if problems:
        raise SearchError("; ".join(problems))

    def label():
        vals = insp.values(max_age=0.1)
        if vals is None or field in vals.errors or vals.get(field) is None:
            return None, "field unreadable"
        raw = vals.raw.get(field, vals.get(field))
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        on = ram_map._cond(cond, {"v": raw if raw is not None else vals.get(field)})
        return ("on" if on else "off"), f"{field} = {vals.display(field)}"
    return label


class AutoLabel:
    """Samples the search with a labeler's on / off. The RAM is read once a label has held for `stable` checks and
    `settle_s`, at every change of label and every `every_s` while it holds (only at changes while the search still
    keeps whole samples, so a long "off" stretch does not fill memory); that sample counts only if the label still
    holds `after_s` later. The stream's frame lags the RAM a little, so a read at either edge of a short prompt would
    carry the wrong label: settle_s covers the start, after_s the end (confirmed / discarded in status())."""

    def __init__(self, insp: Inspector, source: str, label_fn, hz: float = 8.0, stable: int = 2, settle_s: float = 0.25,
                 after_s: float = 0.3, every_s: float = 1.0, max_s: float = AUTO_MAX_S, detail: dict | None = None):
        self.insp, self.source, self.label_fn = insp, source, label_fn
        self.period = 1.0 / max(0.5, min(float(hz), MAX_HZ))
        self.stable, self.settle_s, self.after_s, self.every_s, self.max_s = stable, settle_s, after_s, every_s, max_s
        self.detail = {k: v for k, v in (detail or {}).items() if v is not None}
        self.stop_ev = threading.Event()
        self.started = insp.clock()
        self.current, self.since, self.run = None, 0.0, 0
        self.last_sampled, self.last_sample_at = None, 0.0
        self.pending = None                           # (label, data, read at, search): waiting for its confirmation
        self.samples = {"on": 0, "off": 0}
        self.discarded = 0
        self.checks, self.note, self.error = 0, "", None

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name=f"ram-label-{self.insp.sid[-8:]}").start()
        return self

    def stop(self):
        self.stop_ev.set()

    def step(self) -> str | None:
        """One check; returns the label of a sample it confirmed (applied to the search) now, if any."""
        insp = self.insp
        self.insp.watch(5.0)
        lab, self.note = self.label_fn()
        self.checks += 1
        now = insp.clock()
        if lab != self.current:
            if self.pending is not None:              # the label changed before the read was confirmed: not this one
                self.pending = None
                self.discarded += 1
            self.current, self.since, self.run = lab, now, 1
            return None
        if lab is None:
            return None
        self.run += 1
        s = insp.search
        if s is None:
            self.stop()
            return None
        if self.pending is not None:
            plab, data, at, search = self.pending
            if now - at < self.after_s:
                return None
            self.pending = None
            insp._sample(plab, None, None, None, None, f"auto {self.source}: {self.note}", data=data, search=search)
            self.samples[plab] += 1
            return plab
        if self.run < self.stable or now - self.since < self.settle_s:
            return None
        due = lab != self.last_sampled or (not s.dense and now - self.last_sample_at >= self.every_s)
        if not due:
            return None
        self.pending = (lab, insp._read_sample(s), now, s)
        self.last_sampled, self.last_sample_at = lab, now
        if self.after_s <= 0:                         # no confirmation asked: apply at once
            return self.step_pending()
        return None

    def step_pending(self) -> str | None:
        plab, data, _, search = self.pending
        self.pending = None
        self.insp._sample(plab, None, None, None, None, f"auto {self.source}: {self.note}", data=data, search=search)
        self.samples[plab] += 1
        return plab

    def _loop(self):
        while not self.stop_ev.is_set() and not self.insp.closed:
            if self.insp.clock() - self.started > self.max_s:
                self.error = f"stopped after {self.max_s:g} s"
                break
            t0 = time.monotonic()
            try:
                self.step()
                self.error = None
            except Exception as e:                   # noqa: BLE001 - a failed read: try again next check
                self.error = f"{type(e).__name__}: {e}"[:300]
            self.stop_ev.wait(max(0.02, self.period - (time.monotonic() - t0)))

    def status(self) -> dict:
        return {"source": self.source, **self.detail, "label": self.current, "note": self.note, "samples": dict(self.samples),
                "discarded": self.discarded, "checks": self.checks, "running": not self.stop_ev.is_set(), "error": self.error}


# --- the registry and the routes ----------------------------------------------------------------------------------------
_INSPECTORS: dict[str, Inspector] = {}
_LOCK = threading.Lock()


def close_all():
    with _LOCK:
        for insp in _INSPECTORS.values():
            insp.close()
        _INSPECTORS.clear()


class SearchIn(BaseModel):
    type: str = "u8"
    base: int | str | None = None
    size: int | str | None = None
    tolerance: int = Field(default=0, ge=0, le=50)    # labeled samples a candidate may have on the wrong side


class SampleIn(BaseModel):
    label: str | None = None
    op: str | None = None
    value: float | int | str | None = None
    lo: float | int | str | None = None
    hi: float | int | str | None = None
    note: str = Field(default="", max_length=200)


class AutoIn(BaseModel):
    source: str = "off"
    field: str | None = None
    cond: dict | None = None
    button: str | None = None
    hz: float = 8.0
    tolerance: int | None = Field(default=None, ge=0, le=50)


class PromoteIn(BaseModel):
    name: str
    type: str = "u8"
    address: int | str | None = None
    pointer: dict | list | None = None
    count: int | str | None = None
    stride: int | str | None = None
    description: str = ""
    group: str = ""
    units: str = ""
    scale: float | None = None
    enum: dict = {}
    flags: dict = {}
    watch: bool | None = None
    format: str = ""
    evidence: str = ""
    source: str = "scan"


class FieldIn(BaseModel):
    name: str
    field: dict


def _num(v, what: str) -> int:
    try:
        return ram_map.num(v, what)
    except ram_map.MapError as e:
        raise HTTPException(422, str(e))


def routes(app, store, auth, rpc=None, frame=None, data_dir=None):
    """rpc(sid, op, args, wait) -> data (the session channel, server._rpc_quick); frame(sid) -> (jpeg, seq, ts) | None
    (the stream's newest frame); data_dir: where promoted fields go (gbox-data/ram_maps)."""
    if data_dir is not None:
        from pathlib import Path
        ram_map.OVERLAY_DIRS[:] = [Path(data_dir) / "ram_maps"]

    def inspector(sid: str) -> Inspector:
        s = store.get("session", sid)
        if not s:
            raise HTTPException(404, "Session not found")
        with _LOCK:
            insp = _INSPECTORS.get(sid)
            ended = s.get("state") != "running" and _INSPECTORS.pop(sid, None)
        if ended:
            ended.close()
        if s.get("state") != "running":
            raise HTTPException(409, "This session has ended: open a running game to inspect its RAM")
        with _LOCK:
            gone = []
            for other, i in list(_INSPECTORS.items()):     # inspectors of sessions that ended
                o = store.get("session", other)
                if not o or o.get("state") != "running":
                    gone.append(_INSPECTORS.pop(other))
        for i in gone:
            i.close()
        if insp is not None:
            return insp
        game = s                                       # a new one, made outside the lock (its first read may be slow)
        if not s.get("platform") and s.get("game_id"):  # session records name the game, not its platform
            game = s | {"platform": (store.catalog_get(s["game_id"]) or {}).get("platform")}
        reader = ram_reader.for_session(sid, s, rpc=rpc)
        if reader is None:
            raise HTTPException(409, "No way to read this session's RAM from here")
        made = Inspector(sid, game, reader, frame=frame,
                         remake=lambda: ram_reader.for_session(sid, store.get("session", sid) or s, rpc=rpc))
        with _LOCK:
            insp = _INSPECTORS.setdefault(sid, made)
        if insp is not made:                           # another request made one meanwhile
            made.close()
        return insp

    def guard(fn, *a, **k):
        try:
            return fn(*a, **k)
        except HTTPException:
            raise
        except (SearchError, ram_map.MapError, LookupError) as e:
            raise HTTPException(422, str(e))
        except ram_reader.Throttled as e:
            raise HTTPException(429, str(e))
        except (RuntimeError, OSError, ValueError, TimeoutError) as e:
            raise HTTPException(502, f"{type(e).__name__}: {e}"[:400])

    @app.get("/api/ram/maps")
    def ram_maps(actor=Depends(auth)):
        return ram_map.summaries()

    @app.get("/api/ram/maps/{map_id}")
    def ram_map_get(map_id: str, actor=Depends(auth)):
        m = guard(ram_map.find, map_id)
        if m is None:
            raise HTTPException(404, f"No RAM map {map_id}")
        return m.describe()

    @app.post("/api/ram/maps/{map_id}/fields")
    def ram_map_add(map_id: str, body: FieldIn, actor=Depends(auth)):
        m = guard(ram_map.promote, map_id, body.name, body.field)
        store.audit(actor, "ram_map.field", map_id, {"name": body.name, "field": body.field})
        return m.describe()

    @app.delete("/api/ram/maps/{map_id}/fields/{name}")
    def ram_map_remove(map_id: str, name: str, actor=Depends(auth)):
        if not ram_map.unpromote(map_id, name):
            raise HTTPException(404, f"{name} is not a promoted field of {map_id} (repo fields change in a PR)")
        store.audit(actor, "ram_map.field_removed", map_id, {"name": name})
        return {"ok": True}

    @app.get("/api/sessions/{sid}/ram")
    def ram_status(sid: str, actor=Depends(auth)):
        return inspector(sid).status()

    @app.get("/api/sessions/{sid}/ram/live")
    def ram_live(sid: str, since: int = 0, actor=Depends(auth)):
        insp = inspector(sid)
        insp.watch()
        vals = insp.values()
        out = {"session_id": sid, "map": insp.map.id if insp.map else None, "map_error": insp.map_error,
               "title": insp.map.title if insp.map else None, "groups": insp.map.groups if insp.map else {},
               "rows": vals.rows() if vals is not None else [], "errors": len(vals.errors) if vals is not None else 0,
               "at": round(vals.at, 3) if vals is not None else None,
               "age_s": round(insp.clock() - insp.last_at, 3) if vals is not None else None,
               "events": insp.events_since(since), "seq": insp.seq, "reader": insp.reader.describe(),
               "error": insp.error, "hz": insp.hz}
        if vals is not None:
            out["reads"], out["bytes"] = getattr(vals, "reads", 0), getattr(vals, "bytes", 0)
        return out

    @app.get("/api/sessions/{sid}/ram/events")
    def ram_events(sid: str, since: int = 0, limit: int = 200, actor=Depends(auth)):
        insp = inspector(sid)
        return {"events": insp.events_since(since, limit), "seq": insp.seq}

    @app.get("/api/sessions/{sid}/ram/frames/{fid}.jpg")
    def ram_frame(sid: str, fid: int, actor=Depends(auth)):
        insp = inspector(sid)
        jpeg = insp.frames.get(fid)
        if not jpeg:
            raise HTTPException(404, "That frame is no longer kept")
        return Response(jpeg, media_type="image/jpeg", headers={"cache-control": "private, max-age=3600"})

    @app.get("/api/sessions/{sid}/ram/hex")
    def ram_hex(sid: str, address: str = "0", length: int = 256, pointer: str = "", actor=Depends(auth)):
        insp = inspector(sid)
        chain = [_num(x, "pointer") for x in pointer.replace(" ", "").split(",") if x] if pointer else None
        if chain is not None and len(chain) < 2:
            raise HTTPException(422, "pointer is base,offset[,offset...]")
        return guard(insp.hex, _num(address, "address") if not chain else 0, length, chain)

    @app.post("/api/sessions/{sid}/ram/search")
    def ram_search_start(sid: str, body: SearchIn, actor=Depends(auth)):
        insp = inspector(sid)
        if body.type not in TYPES:
            raise HTTPException(422, f"type is one of {', '.join(TYPES)}")
        with _LOCK:
            busy = [i for k, i in _INSPECTORS.items() if k != sid and i.search is not None]
        if len(busy) >= MAX_SEARCHES:
            raise HTTPException(409, f"{len(busy)} RAM searches are running on other sessions: end one first")
        base = _num(body.base, "base") if body.base is not None else None
        size = _num(body.size, "size") if body.size is not None else None
        out = guard(insp.search_start, body.type, base, size, body.tolerance)
        store.audit(actor, "ram.search", sid, {"type": body.type, "base": out.get("base"), "size": out.get("size")})
        return out

    @app.get("/api/sessions/{sid}/ram/search")
    def ram_search_status(sid: str, limit: int = 60, actor=Depends(auth)):
        return inspector(sid).search_status(max(0, min(limit, 500)))

    @app.post("/api/sessions/{sid}/ram/search/sample")
    def ram_search_sample(sid: str, body: SampleIn, actor=Depends(auth)):
        insp = inspector(sid)
        if body.label not in (None, "on", "off"):
            raise HTTPException(422, "label is on, off or none")
        if body.op is not None and body.op not in OPS:
            raise HTTPException(422, f"op is one of {', '.join(OPS)}")
        return guard(insp.search_sample, body.label, body.op, body.value, body.lo, body.hi, body.note)

    @app.post("/api/sessions/{sid}/ram/search/auto")
    def ram_search_auto(sid: str, body: AutoIn, actor=Depends(auth)):
        return guard(inspector(sid).auto, body.source, body.field, body.cond, body.hz, body.button, body.tolerance)

    @app.delete("/api/sessions/{sid}/ram/search")
    def ram_search_end(sid: str, actor=Depends(auth)):
        inspector(sid).search_end()
        return {"active": False}

    @app.post("/api/sessions/{sid}/ram/promote")
    def ram_promote(sid: str, body: PromoteIn, actor=Depends(auth)):
        insp = inspector(sid)
        if (body.address is None) == (body.pointer is None):
            raise HTTPException(422, "give an address or a pointer")
        field = {k: v for k, v in {
            "address": ram_map.hexa(_num(body.address, "address")) if body.address is not None else None,
            "pointer": body.pointer, "type": body.type, "count": body.count, "stride": body.stride,
            "description": body.description.strip() or None, "group": body.group.strip() or None,
            "units": body.units.strip() or None, "scale": body.scale, "enum": body.enum or None, "flags": body.flags or None,
            "watch": body.watch, "format": body.format or None, "source": body.source or "scan",
            "evidence": body.evidence.strip() or _evidence(insp), "added": date.today().isoformat(),
            "by": str(actor or "") or None}.items() if v is not None}
        mid = insp.map_id()
        if not mid:
            raise HTTPException(409, "This session has no game id to file the field under")
        base = {"title": insp.session.get("title") or mid, "platform": insp.platform,
                "match": {k: v for k, v in {"game_ids": [insp.game_id] if insp.game_id else None,
                                            "disc_id": insp.disc_id or None}.items() if v}}
        m = guard(ram_map.promote, mid, body.name.strip(), field, base)
        store.audit(actor, "ram_map.promote", mid, {"session": sid, "name": body.name, "field": field})
        insp._refresh_map(force=True)
        return {"map": mid, "field": next((f for f in m.describe()["fields"] if f["name"] == body.name.strip()), None),
                "overlay": str(ram_map.overlay_path(mid))}

    return inspector


def _evidence(insp: Inspector) -> str:
    """What the search behind a promoted field saw: samples per label, the labeler, the date."""
    s = insp.search
    if s is None:
        return f"added from the RAM inspector {date.today().isoformat()}"
    st = s.status()
    lab = insp.labeler.status() if insp.labeler else None
    return (f"RAM inspector search {date.today().isoformat()}: {st['type']} over {ram_map.hexa(st['base'])}+{st['size']:#x}, "
            f"{st['samples']['on']} on / {st['samples']['off']} off / {st['samples']['plain']} plain samples, "
            f"{st['candidates']} candidates left" + (f", labeler {lab['source']}" if lab else ""))
