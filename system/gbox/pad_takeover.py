"""Pick up the controller, take over from the bot for a moment, put it down: the bot plays on.

Operator 2026-10-26 (the RE4 bot stuck on top of the Village clock tower): "pick up the controller and basically overwrite
the gameplay by the bot for a brief moment in order to guide the agent and train it ... and then just put down a
controller and give the gameplay back to the bot ... on any system that's remoted in through G Box, if I have the
application selected".

One lease per session, kept in the worker process that runs the game and its bot (tools.AUTOPLAY):
  claim / renew  operator input for the session while its bot runs: the worker PC's own controller (local(), from
                 padstate.watch_xinput) or the operator's input the desktop app forwards (inputs(), from tools._pump: events
                 the control plane stamped src player / ui and not lease false, see stamp()). Only a new press starts a
                 takeover (a stream reconnect's releases never do); every input renews it, and so does a key or a stick
                 that is still held.
  yield          the first press makes every Gate of the session release what its bot holds - before the operator's own
                 input is applied - and drop the bot's input from then on. The bot's decisions keep running (telemetry,
                 round maps); its live stats say operator_control, operator_control_since, operator_segment.
  resume         idle_s (gbox.toml takeover_idle_s, default IDLE_S = 3 s) after the last input with nothing held, the bot's
                 input goes through again from a clean held set: nothing it held before is pressed again. A bot that diffs
                 against its own held keys holds nothing while stats["operator_control"] is true (gbox.mercs.engine), so
                 its first decision afterwards presses what it wants now.
  record         every takeover is a segment (start / end, who and from where, the keys per BUCKET_S): segment(id) feeds
                 the round map (gbox.mercs.round_map: operator_segments, with the route it sampled meanwhile) and each
                 finished one is a JSON line in <data_dir>/autoplay/operator_segments/<day>.jsonl, for any bot. Nothing
                 here learns from them.
Stop / F3 keep their meaning: they stop the bot. A takeover never stops it and never marks it taken over (F5 and
MercMode carry on), and agents or automation never claim one: the control plane stamps only the operator's own app input
for a session that machine is viewing (stamp(), gbox.server put_input).
"""
from __future__ import annotations

import json
import threading
import time
import weakref
from pathlib import Path

IDLE_S = 3.0              # no operator input (and nothing held) this long: the bot takes back over
HOLD_MAX_S = 30.0         # a key or stick held this long without any other input no longer keeps the lease (a lost release)
BUCKET_S = 0.25           # a segment's keys: what the operator held or pressed in each quarter second
TICK_S = 0.1              # the watcher's period: stats, the resume and the segment's end on time while the bot sends nothing
RECENT_S = 10.0           # a bot that gives up this soon after a takeover was not facing a frozen game (tools._start_playbook)
MAX_EVENTS = 20000        # per segment: later input still renews the takeover, it is just not recorded
SEGMENTS_KEPT = 64
OPERATOR_SOURCES = ("player", "ui")
STAMPED = ("src", "lease", "by", "via")

_lock = threading.Lock()
LEASES: dict[str, "Lease"] = {}
SEGMENTS: dict[str, "Segment"] = {}          # segment id -> its record (open or finished), the newest SEGMENTS_KEPT


def spawn(fn, name: str) -> None:            # tests replace it: the watcher thread
    threading.Thread(target=fn, daemon=True, name=name).start()


def lease(sid: str) -> "Lease":
    with _lock:
        lz = LEASES.get(sid)
        if lz is None:
            lz = LEASES[sid] = Lease(sid)
        return lz


def forget(sid: str) -> None:
    """The session ended (tools._pump): its lease and gates go; its finished segments stay readable."""
    with _lock:
        lz = LEASES.pop(sid, None)
    if lz is not None:
        with lz.lock:
            if lz.since is not None:
                lz._end(lz.clock())
            lz.run = lz.relay = None


def bind(sid: str, run: dict, *, idle_s: float | None = None, applies=None, data_dir=None) -> "Lease":
    """tools: this autoplay run is the session's bot from now on. Its live stats show the takeover; applies() says whether
    one may start now (a live bot, not a human / co-op Mercenaries session). A takeover already running carries over to
    a restarted bot, which yields at its first input."""
    lz = lease(sid)
    with lz.lock:
        lz.run, lz.applies, lz.data_dir = run, applies, data_dir
        try:
            lz.idle_s = float(idle_s) if idle_s and float(idle_s) > 0 else IDLE_S
        except (TypeError, ValueError):
            lz.idle_s = IDLE_S
        lz._stats(lz.since is not None)
    return lz


def active(sid: str, now: float | None = None) -> bool:
    """The operator has the pad on this session right now."""
    lz = LEASES.get(sid)
    return bool(lz is not None and lz.active(now))


def recent(sid: str, within_s: float = RECENT_S, now: float | None = None) -> bool:
    """The operator has the pad, or gave it back less than within_s ago."""
    lz = LEASES.get(sid)
    if lz is None:
        return False
    now = lz.clock() if now is None else now
    return lz.active(now) or (lz.ended is not None and now - lz.ended < within_s)


def status(sid: str) -> dict:
    lz = LEASES.get(sid)
    if lz is None:
        return {"operator_control": False}
    on = lz.active()
    return {"operator_control": on, "operator_takeovers": lz.takeovers, "operator_idle_s": lz.idle_s,
            **({"operator_control_since": round(lz.since, 2), "operator_segment": lz.segment.id}
               if on and lz.segment is not None else {})}


def operator_event(e) -> bool:
    """An event that is the operator's own input and may claim / renew the lease: src player or ui (the control plane's
    stamp; unstamped events from an older control plane count as the player's), not refused (lease false), a key."""
    return (isinstance(e, dict) and "rpc" not in e and e.get("src", "player") in OPERATOR_SOURCES
            and e.get("lease", True) is not False and isinstance(e.get("key"), str) and bool(e["key"]))


def bot_event(e) -> bool:
    """The bot's own input relayed through the control plane (the mission / vision driver, a bot demo's presses)."""
    return isinstance(e, dict) and "rpc" not in e and e.get("src") == "autoplay"


def inputs(sid: str, events: list, send=None, *, now: float | None = None) -> list:
    """tools._pump, one batch from the control plane: the operator's events claim or renew the lease first - the bot lets
    go before they are applied - and the bot's own relayed events are dropped while the operator has the pad. Returns the
    events to apply, in their order."""
    lz = LEASES.get(sid)
    if lz is None or lz.run is None or not events:
        return events
    ops = [e for e in events if operator_event(e)]
    if ops:
        lz.touch(ops, now=now)
    if not any(bot_event(e) for e in events):
        return events
    if lz.active(now):
        return [e for e in events if not bot_event(e)]
    if send is not None:
        if lz.relay is None:
            lz.relay = Gate(sid, send, name="relay")
        lz.relay.track([e for e in events if bot_event(e)])
    return events


def local(sid: str, keys, *, now: float | None = None) -> bool:
    """padstate.watch_xinput: the worker PC's own controller as it is now (pressed buttons and pushed stick directions,
    RetroPad names). A new press claims the lease; any change, or anything still held, renews it. True: a takeover
    started."""
    lz = LEASES.get(sid)
    if lz is None or lz.run is None:
        return False
    return lz.local_state(set(keys), now=now)


def segment(seg_id: str, now: float | None = None) -> dict | None:
    """One takeover's record ({id, t_from, t_to, keys: [[t, [keys]], ...] per BUCKET_S, ...}); an open one up to now."""
    seg = SEGMENTS.get(seg_id)
    return seg.record(now) if seg is not None else None


def buckets(events, t_from: float, t_to: float, step: float = BUCKET_S) -> list:
    """[[t, [keys]], ...] from t_from through t_to, one row per step: the keys held at its start or pressed during it."""
    events = sorted(events, key=lambda e: e[0])
    out, held, i, k = [], set(), 0, 0
    while i < len(events) and events[i][0] < t_from:          # before the segment: only what it starts holding
        _, key, down = events[i]
        (held.add if down else held.discard)(key)
        i += 1
    span = max(0.0, t_to - t_from)
    for k in range(int(span / step + 1e-9) + 1):
        start = t_from + k * step
        keys = set(held)
        while i < len(events) and events[i][0] < start + step:
            _, key, down = events[i]
            if down:
                held.add(key)
                keys.add(key)
            else:
                held.discard(key)
            i += 1
        out.append([round(start, 2), sorted(keys)])
    return out


def stamp(events: list, source_of, *, lease: bool, actor: str, via: str = "") -> list:
    """The control plane's input route (gbox.server put_input): every pad event says who sent it - src from the
    authenticated actor (source_of(event), padstate._source), never what the client wrote - and the operator's own events
    say whether they may take the pad from the session's bot (lease: no agent or automation sent them and the machine
    that did is viewing the session) and who that was (by, via)."""
    out = []
    for e in events or ():
        if not isinstance(e, dict) or "rpc" in e:
            out.append(e)
            continue
        src = source_of(e)
        row = {k: v for k, v in e.items() if k not in STAMPED} | {"src": src}
        if src in OPERATOR_SOURCES:
            row |= {"lease": bool(lease), "by": str(actor or "operator")[:60]} | ({"via": str(via)[:80]} if via else {})
        out.append(row)
    return out


def _bot_alive(run) -> bool:
    """The run's bot thread still runs (or is about to start). A stopped bot's thread ends within a tick: until then a
    takeover in progress keeps the operator's held keys theirs (tools._release_all)."""
    if not run:
        return False
    th = run.get("thread")
    return th is None or th.ident is None or th.is_alive()


class Segment:
    """One takeover: when, who, from where and every key the operator pressed or let go."""

    def __init__(self, sid: str, n: int, t_from: float, source: str, actor: str, via: str):
        self.id = f"{sid}:{n}"
        self.sid, self.n, self.t_from, self.source, self.actor, self.via = sid, n, t_from, source, actor, via
        self.t_to: float | None = None
        self.last_input = t_from
        self.events: list[tuple[float, str, bool]] = []
        self.presses = 0
        self.held: set = set()

    def add(self, t: float, key: str, down: bool) -> None:
        if down and key not in self.held:
            self.presses += 1
        (self.held.add if down else self.held.discard)(key)
        self.last_input = t
        if len(self.events) < MAX_EVENTS:
            self.events.append((t, key, down))

    def record(self, now: float | None = None) -> dict:
        end = self.t_to if self.t_to is not None else (time.time() if now is None else now)
        last = min(max(self.last_input, self.t_from), end)
        return {"id": self.id, "session_id": self.sid, "t_from": round(self.t_from, 2),
                "t_to": round(self.t_to, 2) if self.t_to is not None else None, "last_input": round(last, 2),
                "seconds": round(end - self.t_from, 2), "source": self.source, "actor": self.actor,
                **({"via": self.via} if self.via else {}), "presses": self.presses,
                "bucket_s": BUCKET_S, "keys": buckets(self.events, self.t_from, last)}


class Lease:
    def __init__(self, sid: str):
        self.sid = sid
        self.lock = threading.RLock()
        self.clock = time.time
        self.run: dict | None = None             # the autoplay run whose bot yields (its live stats show the takeover)
        self.applies = None                      # () -> bool: a takeover may start now
        self.data_dir = None                     # where finished segments are logged
        self.idle_s = IDLE_S
        self.since: float | None = None          # the operator took the pad at (None: the bot has it)
        self.ended: float | None = None          # the last takeover ended at
        self.last = 0.0                          # the operator's last input
        self.held: set = set()                   # keys the operator holds (forwarded input: press until release)
        self.local: set = set()                  # the worker PC's own controller: what it holds right now
        self.segment: Segment | None = None
        self.takeovers = 0
        self.control_s = 0.0
        self.gates = weakref.WeakSet()
        self.relay: Gate | None = None           # the bot's input relayed through the control plane (src autoplay)
        self.watching = False

    # --- the rule ---
    def _expired(self, now: float) -> bool:
        if self.since is None:
            return False
        if not _bot_alive(self.run):              # the bot ended (Stop, its run over): nothing to give the pad back to
            return True
        if (self.held or self.local) and now - self.last < HOLD_MAX_S:
            return False
        return now - self.last >= self.idle_s

    def active(self, now: float | None = None) -> bool:
        with self.lock:
            if self.since is None:
                return False
            now = self.clock() if now is None else now
            if self._expired(now):
                self._end(now)
                return False
            return True

    def _may_start(self) -> bool:
        if not _bot_alive(self.run) or getattr(self.run.get("driver"), "stopped", False):
            return False
        try:
            return self.applies is None or bool(self.applies())
        except Exception:                         # noqa: BLE001 - an unreadable assignment never hands P1 over
            return False

    def touch(self, events: list, *, now: float | None = None) -> bool:
        """The operator's forwarded events (operator_event): a press starts a takeover, any event renews it."""
        now = self.clock() if now is None else now
        with self.lock:
            if self.since is not None and self._expired(now):
                self._end(now)
            started = False
            if self.since is None:
                press = next((e for e in events if e.get("down", True) is True), None)
                if press is None or not self._may_start():
                    return False
                self._start(now, "remote", str(press.get("by") or "operator")[:60], str(press.get("via") or "")[:80])
                started = True
            self._renew(now)
            for e in events:
                down = e.get("down", True)
                if down is not True and down is not False:
                    continue
                (self.held.add if down else self.held.discard)(e["key"])
                if self.segment is not None:
                    self.segment.add(now, e["key"], down)
            return started

    def local_state(self, keys: set, *, now: float | None = None) -> bool:
        now = self.clock() if now is None else now
        with self.lock:
            before, self.local = self.local, keys
            pressed, released = keys - before, before - keys
            if self.since is not None and self._expired(now):
                self._end(now)
            started = False
            if self.since is None:
                if not pressed or not self._may_start():
                    return False
                self._start(now, "pad", "operator", "this PC's controller")
                started = True
            if pressed or released or keys:
                self._renew(now)
            if self.segment is not None:
                for k in sorted(released):
                    self.segment.add(now, k, False)
                for k in sorted(pressed):
                    self.segment.add(now, k, True)
            return started

    def _renew(self, now: float) -> None:
        self.last = now
        if self.segment is not None:              # a key still held is input too: the timeline runs through it
            self.segment.last_input = max(self.segment.last_input, now)

    def publish(self) -> None:
        """The takeover's stats into the bot's live stats as they are now (a bot that replaced its stats dict)."""
        with self.lock:
            self._stats(self.since is not None)

    # --- takeover ---
    def _start(self, now: float, source: str, actor: str, via: str) -> None:
        self.since = self.last = now
        self.takeovers += 1
        self.segment = Segment(self.sid, self.takeovers, now, source, actor, via)
        with _lock:
            SEGMENTS[self.segment.id] = self.segment
            for old in list(SEGMENTS)[:-SEGMENTS_KEPT]:
                SEGMENTS.pop(old, None)
        for gate in list(self.gates):            # every bot input path of the session lets go, before the operator's
            gate.yield_now()
        self._stats(True)
        self._watch()

    def _end(self, now: float) -> None:
        seg, self.segment = self.segment, None
        if self.since is not None:
            self.control_s += max(0.0, now - self.since)
        self.since, self.ended = None, now
        self.held.clear()
        for gate in list(self.gates):            # each input path has the pad back (from a clean held set)
            gate.resume()
        if seg is not None:
            seg.t_to = now
            _log(self.data_dir, seg.record(now))
        self._stats(False)

    def _live(self) -> dict | None:
        run = self.run
        if run is None:
            return None
        live = run.get("live")
        if live is None:
            live = run["live"] = {}
        return live

    def _stats(self, on: bool) -> None:
        live = self._live()
        if live is None:
            return
        live["operator_control"] = bool(on)
        live["operator_idle_s"] = self.idle_s
        live["operator_takeovers"] = self.takeovers
        live["operator_control_s"] = round(self.control_s + (self.clock() - self.since if on and self.since else 0.0), 1)
        if on and self.since is not None and self.segment is not None:
            live["operator_control_since"] = round(self.since, 2)
            live["operator_segment"] = self.segment.id
        else:
            live.pop("operator_control_since", None)
            live.pop("operator_segment", None)

    def _watch(self) -> None:
        """While the operator has the pad: the stats stay up (a bot that replaced its live stats) and the takeover ends on
        time even when the bot sends nothing."""
        if self.watching:
            return
        self.watching = True

        def loop():
            try:
                while True:
                    time.sleep(TICK_S)
                    with self.lock:
                        if not self.active():
                            return
                        self._stats(True)
            finally:
                with self.lock:
                    self.watching = False
        try:
            spawn(loop, f"pad-takeover-{self.sid}")
        except Exception:                         # noqa: BLE001 - the gates still check the lease on every input
            self.watching = False


class Gate:
    """A bot's send(rows) on a session where the operator may take the pad (tools wraps every bot's input in one). While
    the operator has it, the bot's input is dropped; the moment they take it, what the bot holds is released."""

    def __init__(self, sid: str, send, *, name: str = "bot"):
        self.sid, self.raw, self.name = sid, send, name
        self.pressed: set = set()                # keys this gate has down in the game
        self.yielding = False
        self.generation = 0                      # one more each time the bot let go for the operator
        self.dropped = 0
        self.published = False
        self.lock = threading.RLock()
        lease(sid).gates.add(self)

    def __call__(self, rows, *args, **kwargs):
        rows = [r for r in (rows or ()) if isinstance(r, dict)]
        lz = LEASES.get(self.sid)
        if lz is not None and not self.published:  # the bot's first input: its stats dict is the one it plays with now
            self.published = True
            lz.publish()
        operator = lz is not None and lz.active()   # the lease's lock is never taken inside the gate's (yield_now order)
        with self.lock:
            if operator or (lz is not None and lz.since is not None):
                if not self.yielding:
                    self._yield()
                self.dropped += len(rows)
                return None
            self.yielding = False                # the bot has the pad again, from a clean held set
            out = self.raw(rows, *args, **kwargs)
            self._track(rows)
            return out

    def track(self, rows) -> None:
        """Rows that went to the game another way (the relayed batch, tools._pump)."""
        with self.lock:
            self.yielding = False
            self._track(rows)

    def resume(self) -> None:
        """The takeover ended: the next takeover releases whatever this path pressed since."""
        with self.lock:
            self.yielding = False

    def _track(self, rows) -> None:
        for r in rows:
            key, down = r.get("key"), r.get("down", True)
            if isinstance(key, str) and key:
                (self.pressed.discard if down is False else self.pressed.add)(key)

    def yield_now(self) -> None:
        with self.lock:
            if not self.yielding:
                self._yield()

    def _yield(self) -> None:
        ups = [{"key": k, "down": False} for k in sorted(self.pressed)]
        self.pressed.clear()
        self.yielding = True
        self.generation += 1
        if ups:
            try:
                self.raw(ups)
            except Exception:                     # noqa: BLE001 - a failed release never blocks the operator's input
                pass


def _log(data_dir, record: dict) -> None:
    """One finished segment as a JSON line under <data_dir>/autoplay/operator_segments (off the input path)."""
    if not data_dir:
        return

    def write():
        try:
            folder = Path(data_dir) / "autoplay" / "operator_segments"
            folder.mkdir(parents=True, exist_ok=True)
            day = time.strftime("%Y-%m-%d", time.localtime(record.get("t_from") or time.time()))
            with open(folder / f"{day}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(record, separators=(",", ":")) + "\n")
        except (OSError, TypeError, ValueError):
            pass
    try:
        spawn(write, "pad-takeover-log")
    except Exception:                             # noqa: BLE001
        pass
