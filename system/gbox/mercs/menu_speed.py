"""Learned menu cadence: how fast a title's menus can be pressed and still confirm in RAM.

The Navigator's cursor knobs (stable_s, retry_s, poll_s) were tuned once per title by hand. This turns them into a
measured, adaptive profile: every confirmed screen change records how long the press took to show in RAM, and the
profile is nudged toward the fastest cadence that still confirms - faster after a confirmed step (x0.92), slower after a
missed confirmation (x1.45), bounded so a bad frame can never make it press faster than the ROM accepts. The profile
persists per title under the bot's data dir, so a reload keeps what earlier rounds learned, and `stats["menu_speed"]`
carries the live numbers (steps, confirm_ms, cadence_s, fast_steps) for the receipts.

Measured for reference (RE5 PS3, 2026-10-26): ~1.1 s per cursor step with the hand-set values; the target here is
0.1-0.3 s a step once a screen's confirmation latency is known.

Per screen (2026-11-09, operator: "learn, train and master navigating these menu screens to get through them faster
and faster until it is instantaneous"): every screen learns its own waits - how soon after it appears a press is taken
(settle_s), how soon after a cursor move (step_s), how long a D-pad press may go unseen before it is sent again
(retry_s) and how long a press is held (hold_s / dir_hold_s). A press RAM shows taken (the screen, its unit or its
cursor changed) lowers that screen's knobs x FAST; a press RAM never showed raises them x SLOW and remembers the value
that failed as the screen's floor, so the walk does not go under it again until many later presses have been taken
there. A title's screen() hands these to gbox.mercs_bot.Navigator as hints (settle_s / step_s / retry_s / hold_s /
dir_hold_s / poll_s on the screen dict); every hint is capped at the Navigator's own fixed wait, so the worst case is
the old walk. The same profile keeps each screen's RAM cursor-jump record (jump_* below) and the transitions: from a
round's end (or a run's first menu) to the menus done and to the next round's clock running, with each screen's time
and presses - menu_seconds, menu_seconds_best, menu_seconds_trend and the seconds to gameplay, per run.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

MIN_STABLE_S, MAX_STABLE_S = 0.04, 0.45
MIN_RETRY_S, MAX_RETRY_S = 0.18, 1.20
MIN_POLL_S, MAX_POLL_S = 0.02, 0.25
FAST, SLOW = 0.92, 1.45

# A screen's own knobs: name -> (start, floor, ceiling). Start and ceiling are the Navigator's fixed waits
# (gbox.mercs_bot.Navigator STABLE_S 0.5 / its cursor cadence / RETRY_S / HOLD_S 0.3 / DIR_HOLD_S 0.18), so a screen that
# never confirms anything waits exactly as long as before. The floors keep a press inside what an emulated frame can see.
SCREEN_KNOBS = {"settle_s": (0.45, 0.03, 0.50), "step_s": (0.30, 0.03, 0.50), "retry_s": (0.60, 0.15, 1.20),
                "hold_s": (0.30, 0.10, 0.30), "dir_hold_s": (0.18, 0.05, 0.18)}
FLOOR_DECAY = 0.995          # each taken press lowers its screen's remembered failing values by 0.5 %
FAST_POLL_S = 0.03           # a learned menu screen is read this often (two frames at 60 fps): a press on its first frame
DIR_MISS_S = 0.9             # a D-pad press RAM has not shown in this long (past its retry) was not taken
CONFIRM_MISS_S = 2.5         # a confirm (A / B / +) RAM has not shown in this long was not taken
TREND_N, KEEP_TRANSITIONS = 10, 50
MAX_TRANSITION_S = 600.0     # a "transition" longer than this is a parked or stopped game, not a menu walk
SAVE_EVERY_S = 2.0           # the profile is written at most this often (and at every transition's end)
MENU_SCREENS = frozenset({"alert_ok", "alert_leaderboard", "alert", "title", "main_menu", "play_game",
                          "extra_content", "mercs_title", "mercs_mode", "select_stage", "select_player", "results",
                          "dead", "loading"})
SELECTS_DONE = "select_player"   # the walk's last choice: after it, loading / the intro means the menus are done


def default_profile() -> dict:
    return {"stable_s": 0.10, "retry_s": 0.30, "poll_s": 0.05,
            "confirm_ms": None, "steps": 0, "fast_steps": 0, "misses": 0, "runs": 0}


def default_screen() -> dict:
    out = {k: v[0] for k, v in SCREEN_KNOBS.items()}
    out.update(floors={}, presses=0, hits=0, misses=0, confirm_ms=None, visits=0, dwell_ms=None, best_ms=None,
               jumps=0, jump_proven=0, jump_fails=0, jump_off=False, max_cursor=None)
    return out


class Speed:
    """One title's menu cadence: `stable_s`/`retry_s`/`poll_s` in the Navigator's NAV_CURSOR shape, learned."""

    def __init__(self, profile: dict | None = None, path: Path | None = None, clock=time.monotonic):
        self.data = default_profile() | dict(profile or {})
        # the live dict the Navigator holds: updated in place so learning applies to the steps that follow
        self.live = {key: self.data[key] for key in ("stable_s", "retry_s", "poll_s")}
        self.path = Path(path) if path else None
        self.clock = clock
        self.pressed_at: float | None = None
        self.pressed_where: str | None = None
        self.last_where: str | None = None
        self.initialized = False
        self._screen_state()

    def _screen_state(self) -> None:
        """The per-screen learner's run state (also called on an instance a hot reload kept from an older class)."""
        self.data.setdefault("screens", {})
        self.data.setdefault("transitions", [])
        self.data.setdefault("best", {})
        self.pending = None                 # the press RAM has not shown yet: {where, key, at, kind, knobs}
        self.sig = None                     # the last (where, unit, cursor, token) seen
        self.sig_where = None
        self.change_kind = "settle"         # what the last change was: a new screen (settle) or a cursor move (step)
        self.where_since = None             # when the current screen (where) was first seen
        self.open = None                    # the transition being timed (round end / run start -> gameplay)
        self.next_kind = "boot"             # what the next transition opened by a menu screen is
        self.in_round = False               # a round's clock was seen running since the last round end
        self.last = None                    # the last closed transition
        self.saved_at = float("-inf")

    def _ready(self) -> None:
        if not hasattr(self, "pending"):    # an instance kept across a reload from the class before the screens
            self._screen_state()

    # --- the Navigator reads these through the module's NAV_CURSOR ---
    def profile(self) -> dict:
        return self.live

    def _sync(self) -> None:
        self.live.update({key: self.data[key] for key in ("stable_s", "retry_s", "poll_s")})

    def pressed(self, where: str | None) -> None:
        """A press went in on `where`: the next confirmed screen change measures its latency."""
        self.pressed_at, self.pressed_where = self.clock(), where

    def observed(self, where: str | None, now: float | None = None) -> None:
        """The RAM now names `where`: if that is a change after a press, learn from how long it took."""
        now = self.clock() if now is None else now
        if not self.initialized:
            self.initialized, self.last_where = True, where
            return
        if where == self.last_where:
            return
        self.data["steps"] += 1
        if self.pressed_at is not None:
            latency = max(0.0, now - self.pressed_at)
            if latency <= MAX_STABLE_S * 3:
                self.data["fast_steps"] += 1
                previous = self.data.get("confirm_ms")
                self.data["confirm_ms"] = round(latency * 1000) if previous is None else round(
                    0.7 * previous + 0.3 * latency * 1000)
                self.data["stable_s"] = _clamp(self.data["stable_s"] * FAST, MIN_STABLE_S, MAX_STABLE_S)
                self.data["retry_s"] = _clamp(self.data["retry_s"] * FAST, MIN_RETRY_S, MAX_RETRY_S)
                self.data["poll_s"] = _clamp(self.data["poll_s"] * FAST, MIN_POLL_S, MAX_POLL_S)
            else:
                self.data["misses"] += 1
                self.data["stable_s"] = _clamp(self.data["stable_s"] * SLOW, MIN_STABLE_S, MAX_STABLE_S)
                self.data["retry_s"] = _clamp(self.data["retry_s"] * SLOW, MIN_RETRY_S, MAX_RETRY_S)
                self.data["poll_s"] = _clamp(self.data["poll_s"] * SLOW, MIN_POLL_S, MAX_POLL_S)
        self.pressed_at = None
        self.last_where = where
        self._sync()
        self.save()

    def stats(self) -> dict:
        return {"cadence_s": round(self.data["stable_s"], 3), "confirm_ms": self.data["confirm_ms"],
                "steps": self.data["steps"], "fast_steps": self.data["fast_steps"], "misses": self.data["misses"]}

    # --- per screen ---------------------------------------------------------------------------------------------------
    def screen(self, where: str) -> dict:
        """The learned record of one screen (made with the starting values on first use)."""
        self._ready()
        rec = self.data["screens"].get(where)
        if not isinstance(rec, dict):
            rec = self.data["screens"][where] = default_screen()
        for key, value in default_screen().items():
            rec.setdefault(key, value)
        return rec

    def hints(self, where: str | None) -> dict:
        """The Navigator's waits for this screen (gbox.mercs_bot.Navigator honours each, capped at its own)."""
        if where not in MENU_SCREENS or where == "loading":
            return {}
        rec = self.screen(where)
        out = {k: round(float(rec[k]), 3) for k in SCREEN_KNOBS}
        out["poll_s"] = FAST_POLL_S
        return out

    def seen(self, where: str | None, sig=None, now: float | None = None) -> None:
        """One read of the screen: `sig` is what a press changes (the screen, its unit, its cursor, a dialog token).
        A change after a pending press confirms it (its screen's knobs go x FAST); a press unseen for too long is a
        miss (x SLOW). The transition being timed keeps the screens it passes and their times."""
        self._ready()
        now = self.clock() if now is None else now
        sig = (where,) if sig is None else tuple(sig)
        if self.sig is None:
            self.sig, self.sig_where, self.where_since = sig, where, now
            self._transition_screen(where, now)
            return
        p = self.pending
        if sig != self.sig:
            same_screen = where == self.sig_where and sig[:2] == self.sig[:2]
            if p is not None:
                self._learn(p, True, now)
            self.change_kind = "step" if same_screen else "settle"
            if where != self.sig_where:
                self._dwell(self.sig_where, now)
                self.where_since = now
            self.sig, self.sig_where = sig, where
            self._transition_screen(where, now)
        elif p is not None and now - p["at"] > (DIR_MISS_S if p["key"].startswith("d") else CONFIRM_MISS_S):
            self._learn(p, False, now)
        if now - self.saved_at >= SAVE_EVERY_S and self.path:
            self.save()

    def press(self, where: str | None, key: str, now: float | None = None, learn: bool = True) -> None:
        """A press went in on `where` (the Navigator's): a press still unseen before it was not taken. learn False: a
        probe whose "not taken" is the answer (a walk pressing on at a list's end), neither it nor the one before it
        teaches the screen's waits."""
        self._ready()
        now = self.clock() if now is None else now
        if self.pending is not None and learn:
            self._learn(self.pending, False, now)
        key = str(key or "")
        if where not in MENU_SCREENS or where == "loading" or not learn:
            self.pending = None
        else:
            dpad = key.startswith("d")
            first = "step_s" if self.change_kind == "step" else "settle_s"
            knobs = (first, "dir_hold_s", "retry_s") if dpad else (first, "hold_s")
            rec = self.screen(where)
            self.pending = {"where": where, "key": key, "at": now,
                            "knobs": {k: float(rec[k]) for k in knobs}}
            rec["presses"] = int(rec.get("presses") or 0) + 1
        if self.open is not None:
            self.open["presses"] += 1
            if self.open["screens"]:
                self.open["screens"][-1][2] += 1

    def _learn(self, p: dict, taken: bool, now: float) -> None:
        self.pending = None
        rec = self.screen(p["where"])
        floors = rec.setdefault("floors", {})
        for knob, used in p["knobs"].items():
            start, low, high = SCREEN_KNOBS[knob]
            if taken:
                floor = float(floors.get(knob) or 0.0) * FLOOR_DECAY
                floors[knob] = round(floor, 4) if floor >= low else 0.0
                # never back down onto a value that failed: 10 % above it, until enough taken presses wear it away
                rec[knob] = round(_clamp(min(rec[knob], used) * FAST, max(low, min(high, floor * 1.1)), high), 4)
            else:
                floors[knob] = round(max(float(floors.get(knob) or 0.0), used), 4)
                rec[knob] = round(_clamp(max(rec[knob], used) * SLOW, low, high), 4)
        if taken:
            rec["hits"] = int(rec.get("hits") or 0) + 1
            ms = max(0.0, now - p["at"]) * 1000
            rec["confirm_ms"] = round(ms) if rec.get("confirm_ms") is None else round(0.7 * rec["confirm_ms"] + 0.3 * ms)
        else:
            rec["misses"] = int(rec.get("misses") or 0) + 1

    def _dwell(self, where: str | None, now: float) -> None:
        if where not in MENU_SCREENS or self.where_since is None:
            return
        ms = max(0.0, now - self.where_since) * 1000
        rec = self.screen(where)
        rec["visits"] = int(rec.get("visits") or 0) + 1
        rec["dwell_ms"] = round(ms) if rec.get("dwell_ms") is None else round(0.7 * rec["dwell_ms"] + 0.3 * ms)
        if where != "loading" and (rec.get("best_ms") is None or ms < rec["best_ms"]):
            rec["best_ms"] = round(ms)

    # --- RAM cursor jumps (the title writes the cursor; this keeps each screen's record) -----------------------------
    def jump_allowed(self, where: str) -> bool:
        rec = self.screen(where)
        return not rec.get("jump_off")

    def jump_direct(self, where: str, prove_n: int) -> bool:
        """Whether the game's own cursor step has confirmed enough approach jumps on this screen for a direct write."""
        return int(self.screen(where).get("jump_proven") or 0) >= prove_n

    def jump_result(self, where: str, outcome: str, fail_n: int = 2) -> None:
        """outcome: "wrote" (a write that held), "proven" (the game's own step moved off it onto the target), "failed"
        (the write did not hold or the game ignored it). A screen that fails fail_n times more than it was proven goes
        back to stepping option by option (jump_off, persisted; the bot_logic knob turned off and on clears it)."""
        rec = self.screen(where)
        if outcome == "wrote":
            rec["jumps"] = int(rec.get("jumps") or 0) + 1
        elif outcome == "proven":
            rec["jump_proven"] = int(rec.get("jump_proven") or 0) + 1
        elif outcome == "failed":
            rec["jump_fails"] = int(rec.get("jump_fails") or 0) + 1
            if rec["jump_fails"] >= fail_n and rec["jump_fails"] > int(rec.get("jump_proven") or 0):
                rec["jump_off"] = True
        if self.open is not None and outcome == "wrote":
            self.open["jumps"] += 1
        self.save()

    def jumps_reset(self) -> None:
        for rec in self.data.get("screens", {}).values():
            if isinstance(rec, dict):
                rec["jump_off"], rec["jump_fails"] = False, 0
        self.save()

    def note_cursor(self, where: str, cursor) -> None:
        """A cursor value the game itself produced on this screen (never one the bot wrote): the largest is the
        highest entry known to exist, the bound of a cursor jump on a screen whose entry count is not fixed."""
        if not isinstance(cursor, int) or isinstance(cursor, bool) or not 0 <= cursor < 256:
            return
        rec = self.screen(where)
        if rec.get("max_cursor") is None or cursor > rec["max_cursor"]:
            rec["max_cursor"] = cursor

    # --- transitions: a round's end (or a run's first menu) to the next round's clock running ------------------------
    def begin_run(self, prepare: bool = False, now: float | None = None) -> None:
        """A menus walk starts (gbox.mercs_bot.play): a MercMode preparation is timed as such and never counts in the
        best or the trend (it walks a paused game in the background); a stale open transition is dropped."""
        self._ready()
        now = self.clock() if now is None else now
        o = self.open
        if o is not None and (o["kind"] == "prepare" or now - o["start"] > MAX_TRANSITION_S):
            if o["kind"] == "prepare" and o.get("menu_s") is not None:
                self._close(o, now, play=False)
            self.open = None
        if prepare:
            self.open, self.next_kind, self.in_round = None, "prepare", False
        elif self.open is None:
            # a new run starts in the menus (a boot) or in a round (the first clock tick says so again): a round of an
            # earlier run of this title that ended without its end being seen must not keep the menus from being timed
            self.next_kind, self.in_round = "boot", False

    def round_end(self, now: float | None = None) -> None:
        """A round's end (its death or its results, the first engine tick after its clock ran): the next transition
        counts from here."""
        self._ready()
        now = self.clock() if now is None else now
        if not self.in_round:
            return
        self.in_round = False
        self.open = self._new("next", now)

    def gameplay(self, now: float | None = None) -> dict | None:
        """The round's clock is running: the open transition closes (its seconds to gameplay). Returns its record."""
        self._ready()
        now = self.clock() if now is None else now
        o, self.open, self.in_round = self.open, None, True
        if o is None:
            return None
        if now - o["start"] > MAX_TRANSITION_S:
            return None
        return self._close(o, now, play=True)

    def _new(self, kind: str, now: float) -> dict:
        return {"kind": kind, "start": now, "menu_s": None, "presses": 0, "jumps": 0, "screens": [],
                "selects": False}

    def _transition_screen(self, where: str | None, now: float) -> None:
        if self.open is None:
            if where in MENU_SCREENS and where not in ("loading", "dead") and not self.in_round:
                self.open = self._new(self.next_kind, now)
                self.next_kind = "boot" if self.next_kind != "prepare" else "prepare"
            else:
                return
        o = self.open
        if not o["screens"] or o["screens"][-1][0] != where:
            o["screens"].append([where, round(now - o["start"], 2), 0])
        if where == SELECTS_DONE:
            o["selects"] = True
        elif where in ("loading", "playing", "intro") and o["selects"] and o["menu_s"] is None:
            o["menu_s"] = round(now - o["start"], 2)     # the last select confirmed: the menus are done

    def _close(self, o: dict, now: float, play: bool) -> dict:
        kind = o["kind"]
        if kind == "next" and not o["selects"] and not any(s[0] in MENU_SCREENS - {"dead", "loading"}
                                                            for s in o["screens"]):
            kind = "retry"                                  # Continue? Yes: the same round again, no menus at all
        play_s = round(now - o["start"], 2) if play else None
        menu_s = o["menu_s"] if o["menu_s"] is not None else play_s
        screens = o["screens"]
        parts = []
        for i, (where, at, presses) in enumerate(screens):
            until = screens[i + 1][1] if i + 1 < len(screens) else (play_s if play_s is not None else at)
            parts.append(f"{where} {max(0.0, until - at):.1f}s/{presses}p")
        rec = {"kind": kind, "at": round(time.time(), 1), "menu_s": menu_s, "play_s": play_s,
               "presses": o["presses"], "jumps": o["jumps"], "screens": ", ".join(parts)[:400]}
        self.data["transitions"] = (self.data.get("transitions") or [])[-(KEEP_TRANSITIONS - 1):] + [rec]
        best = self.data.setdefault("best", {})
        if kind != "prepare":
            for field in ("menu_s", "play_s"):
                value = rec[field]
                if isinstance(value, (int, float)) and value > 0:
                    key = f"{kind}_{field}"
                    if best.get(key) is None or value < best[key]:
                        best[key] = value
        self.last = rec
        self.save()
        return rec

    def stats_view(self) -> dict:
        """Flat numbers and text for the run's stats (telemetry keeps scalars only)."""
        self._ready()
        rows = [r for r in self.data.get("transitions") or [] if isinstance(r, dict)]
        nxt = [r for r in rows if r.get("kind") == "next"]
        best = self.data.get("best") or {}
        out = {}
        if nxt:
            out["menu_seconds"] = nxt[-1].get("menu_s")
            out["menu_play_seconds"] = nxt[-1].get("play_s")
            out["menu_seconds_trend"] = ", ".join(f"{r['menu_s']:g}" for r in nxt[-TREND_N:]
                                                  if isinstance(r.get("menu_s"), (int, float)))
            out["menu_play_trend"] = ", ".join(f"{r['play_s']:g}" for r in nxt[-TREND_N:]
                                               if isinstance(r.get("play_s"), (int, float)))
            out["menu_screens"] = nxt[-1].get("screens") or ""
            out["menu_presses_last"] = nxt[-1].get("presses")
            out["menu_jumps_last"] = nxt[-1].get("jumps")
        for key, name in (("next_menu_s", "menu_seconds_best"), ("next_play_s", "menu_play_best"),
                          ("boot_menu_s", "menu_boot_best"), ("boot_play_s", "menu_boot_play_best")):
            if best.get(key) is not None:
                out[name] = best[key]
        boot = [r for r in rows if r.get("kind") == "boot"]
        if boot:
            out["menu_boot_seconds"] = boot[-1].get("menu_s")
            out["menu_boot_play_seconds"] = boot[-1].get("play_s")
        if self.last is not None:
            out["menu_last_kind"] = self.last.get("kind")
        screens = self.data.get("screens") or {}
        lat = []
        for where in sorted(screens):
            rec = screens[where]
            if isinstance(rec, dict) and (rec.get("presses") or rec.get("visits")):
                lat.append(f"{where} settle {rec.get('settle_s', 0):.2f}s confirm {rec.get('confirm_ms') or 0}ms"
                           + (f" jump {rec.get('jump_proven', 0)}/{rec.get('jumps', 0)}" if rec.get("jumps") else "")
                           + (" OFF" if rec.get("jump_off") else ""))
        if lat:
            out["menu_latency"] = "; ".join(lat)[:600]
        if self.open is not None:
            out["menu_open_s"] = round(self.clock() - self.open["start"], 1)
        return out

    def status(self) -> dict:
        """The sidebar's line and numbers (bot_logic.status: the re5_mods live_controls view)."""
        view = self.stats_view()
        last, best = view.get("menu_seconds"), view.get("menu_seconds_best")
        if isinstance(last, (int, float)):
            text = f"menus: {last:g} s" + (f" (best {best:g} s)" if isinstance(best, (int, float)) else "")
            play = view.get("menu_play_seconds")
            if isinstance(play, (int, float)):
                text += f" · to play {play:g} s"
        elif isinstance(view.get("menu_boot_seconds"), (int, float)):
            text = f"menus: boot {view['menu_boot_seconds']:g} s (no round-to-round walk timed yet)"
        else:
            text = "menus: not timed yet"
        trend = [float(x) for x in str(view.get("menu_seconds_trend") or "").split(", ") if x]
        return {"text": text, "menu_seconds": last, "menu_seconds_best": best, "trend": trend,
                "play_seconds": view.get("menu_play_seconds"), "play_best": view.get("menu_play_best"),
                "screens": view.get("menu_screens", ""), "latency": view.get("menu_latency", "")}

    # --- persistence ---
    def save(self) -> None:
        self.saved_at = self.clock()
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        except (OSError, TypeError, ValueError):
            pass

    @classmethod
    def load(cls, path: Path | None, **kwargs) -> "Speed":
        profile = None
        if path and Path(path).is_file():
            try:
                profile = json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                profile = None
        if not isinstance(profile, dict):
            profile = None
        return cls(profile, path=path, **kwargs)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


_CACHE: dict[str, Speed] = {}
RELOAD_KEEP = ("_CACHE",)            # a hot reload keeps each title's learner (its open transition, its pending press)


def for_title(map_id: str, data_dir: str | Path | None = None) -> Speed:
    """The title's learned cadence (one per process), persisted under <data dir>/mercs/learned/<map_id>/menu_speed.json."""
    if map_id in _CACHE:
        speed = _CACHE[map_id]
        if not hasattr(speed, "pending"):            # kept by a reload from the class before the per-screen learner
            speed._screen_state()
        return speed
    path = None
    if data_dir:
        path = Path(data_dir) / "mercs" / "learned" / map_id / "menu_speed.json"
    _CACHE[map_id] = Speed.load(path)
    return _CACHE[map_id]


def cached(map_id: str) -> Speed | None:
    """The title's learner if this process has one (the sidebar's read: never creates or loads one)."""
    return _CACHE.get(map_id)
