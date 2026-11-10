"""Learned menu pace and the menu walk's clock: the one place every Mercenaries title's menu walk keeps its speed.

Operator 2026-11-10 ~12:30: "I need all of these Resident Evil games training the bot to race through these menu screens
as fast as possible to get to the matches without wasting any time. It is absolutely unacceptable and boring to sit on
title screens and not do anything."

Two parts, both kept per title in `gbox-data/mercs/learned/<title id>/menu_pace.json`:

* `Table`: a title's per-screen learned waits (knob -> (hand-set value, floor)). A press the game took (the next screen,
  or the cursor, showed it within TAKEN_S) shortens the waits it used x FAST; a press the game dropped (the same screen
  pressed again, or a move re-sent because it never showed) lengthens them x SLOW. Never under the knob's floor (a frame
  or two of the read, so a press is not dropped) and never over the hand-set value (the old walk is the worst case).
  RE4 Switch's frame walk keeps its waits here (re4_switch.Pace: settle / confirm_after / move_gap); the RAM-driven
  Navigator titles (RE5 / RE6 Switch) learn theirs per screen in gbox.mercs.menu_speed, the Navigator's own learner, and
  report them through the Clock below.
* `Clock`: every walk timed from its start - a boot's launch (the session's `_launched_at`, else the bot's start), or a
  round's end - to the next round's first in-round tick, with each screen's seconds and presses, the presses the game
  dropped, the best and the trend, so the operator sees the walk getting faster round after round. Its numbers go to the
  run's stats (telemetry keeps scalars): `menu_s`, `menu_walk_presses`, `menu_misses`, `menu_pace`, `menu_walk_screens`,
  `menu_s_trend`, `menu_boot_s_trend`, ... and the sidebar's menus line reads the kept walks (`status`).

A title screen (TITLE_SCREENS: PRESS ANY BUTTON, the title) is confirmed the moment the game's own state names it:
there is nothing on it to wait for (`title_hints`).
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

FAST, SLOW = 0.75, 1.5          # a taken press x FAST, a dropped one x SLOW
TAKEN_S = 3.0                   # a confirm whose screen changed within this was taken
SAVE_S = 2.0                    # the file is written at most this often (and at every walk's end)
KEEP_WALKS = 50                 # the walks kept in the file (each with its screens)
TREND_N = 10                    # the trend: the last this many walks of a kind, oldest first
MAX_WALK_S = 900.0              # a "walk" longer than this is a parked, stopped or stuck game, not a menu walk
TITLE_SCREENS = frozenset({"title", "press_any_button", "press_start"})
LEARNED = Path(__file__).resolve().parents[3] / "gbox-data" / "mercs" / "learned"


def path_for(map_id: str, data_dir=None) -> Path:
    """learned/<map id>/menu_pace.json under the deployment's data dir (an adapter's config.data_dir), else this
    checkout's gbox-data."""
    root = Path(data_dir) / "mercs" / "learned" if data_dir else LEARNED
    return root / str(map_id) / "menu_pace.json"


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def new_state() -> dict:
    """A Table's process state (a title module may keep one at module level so tests can swap it)."""
    return {"screens": None, "dirty": False, "saved": float("-inf")}


class Table:
    """One title's learned per-screen waits over its menu_pace.json ({"screens": {where: {knob: value, "taken": n,
    "missed": n}}, plus the Clock's "walks" / "best"). A view: the path and the state dict are the caller's, so a title
    that keeps them as module globals (re4_switch.PACE_FILE / _PACE) can build one per call.

    knobs: name -> (hand-set value, floor). floor(where, knob, floor) may raise a screen's floor (RE4's open-loop select
    moves); fast / slow / save_s default to the module's."""

    def __init__(self, path, knobs: dict | None = None, state: dict | None = None, floor=None,
                 fast: float | None = None, slow: float | None = None, save_s: float | None = None):
        self.path = Path(path)
        self.knobs = dict(knobs or {})
        self.state = state if state is not None else new_state()
        for key, value in new_state().items():
            self.state.setdefault(key, value)
        self.floor = floor
        self.fast = FAST if fast is None else fast
        self.slow = SLOW if slow is None else slow
        self.save_s = SAVE_S if save_s is None else save_s

    # --- the file ---------------------------------------------------------------------------------------------------
    def _load(self) -> dict:
        if self.state.get("screens") is None:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            if not isinstance(data, dict):
                data = {}
            screens = data.get("screens")
            self.state["screens"] = screens if isinstance(screens, dict) else {}
            self.state["doc"] = {k: v for k, v in data.items() if k != "screens"}
        if not isinstance(self.state.get("doc"), dict):
            self.state["doc"] = {}
        return self.state["screens"]

    def screens(self) -> dict:
        return self._load()

    def doc(self) -> dict:
        """The file's other top-level keys (the Clock's walks and bests), loaded with the screens."""
        self._load()
        return self.state["doc"]

    def touch(self) -> None:
        self.state["dirty"] = True

    def save(self, now: float | None = None, force: bool = False) -> None:
        """Write the file (at most every save_s unless forced), atomically: a reader never sees half of it."""
        now = time.monotonic() if now is None else now
        if not self.state.get("dirty") or (not force and now - self.state.get("saved", float("-inf")) < self.save_s):
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            body = {"screens": self.screens(), **{k: v for k, v in self.doc().items() if k != "screens"}}
            tmp.write_text(json.dumps(body, indent=1, sort_keys=True), encoding="utf-8")
            tmp.replace(self.path)
            self.state["dirty"], self.state["saved"] = False, now
        except (OSError, TypeError, ValueError):
            pass

    # --- the waits --------------------------------------------------------------------------------------------------
    def bounds(self, where, knob: str) -> tuple[float, float]:
        default, floor = self.knobs[knob]
        if self.floor is not None:
            floor = self.floor(where, knob, floor)
        return float(default), float(floor)

    def value(self, where, knob: str) -> float:
        """This screen's learned wait, the hand-set value until it has learned one (always within its bounds)."""
        default, floor = self.bounds(where, knob)
        v = (self.screens().get(str(where)) or {}).get(knob)
        return default if not _number(v) else max(floor, min(default, float(v)))

    def learn(self, where, knobs, faster: bool, now: float | None = None) -> None:
        """A press the game took (faster) or dropped on this screen: the knobs it used x fast / x slow, bounded."""
        row = self.screens().setdefault(str(where), {})
        for k in knobs:
            default, floor = self.bounds(where, k)
            row[k] = round(max(floor, min(default, self.value(where, k) * (self.fast if faster else self.slow))), 4)
        key = "taken" if faster else "missed"
        row[key] = int(row.get(key) or 0) + 1
        self.touch()
        self.save(now)

    def counts(self) -> tuple[int, int]:
        """(taken, missed) over every screen."""
        taken = missed = 0
        for row in self.screens().values():
            if isinstance(row, dict):
                taken += int(row.get("taken") or 0)
                missed += int(row.get("missed") or 0)
        return taken, missed

    def summary(self, names: dict | None = None, limit: int = 600) -> str:
        """One line per screen for the panel: "main_menu settle 0.06 confirm 0.10 move 0.08 (124 ok / 0 miss); ..."."""
        names = names or {k: k for k in self.knobs}
        parts = []
        for where in sorted(self.screens()):
            row = self.screens()[where]
            if not isinstance(row, dict):
                continue
            knobs = " ".join(f"{label} {self.value(where, k):.2f}" for k, label in names.items() if k in row)
            parts.append(f"{where} {knobs} ({int(row.get('taken') or 0)} ok / {int(row.get('missed') or 0)} miss)")
        return "; ".join(parts)[:limit]


def status(path) -> dict:
    """The sidebar's menus line from a title's kept walks (gbox.mercs.bot_logic.status: a title module's menu_status):
    "menus: 6.2 s (best 4.8 s) · boot 41 s (best 38 s)", the trends behind it and the last walk's screens. Read from the
    file each time (the panel's process is not the bot's)."""
    doc = Table(path).doc()
    walks = [w for w in doc.get("walks") or [] if isinstance(w, dict) and _number(w.get("menu_s"))]
    best = doc.get("best") or {}
    nxt = [w for w in walks if w.get("kind") == "next"]
    boot = [w for w in walks if w.get("kind") == "boot"]
    parts = []
    if nxt:
        parts.append(f"menus: {nxt[-1]['menu_s']:g} s" + (f" (best {best['next']:g} s)" if _number(best.get("next")) else ""))
    if boot:
        parts.append(("menus: " if not parts else "") + f"boot {boot[-1]['menu_s']:g} s"
                     + (f" (best {best['boot']:g} s)" if _number(best.get("boot")) else ""))
    last = walks[-1] if walks else {}
    return {"text": " · ".join(parts) if parts else "menus: not timed yet",
            "menu_seconds": nxt[-1]["menu_s"] if nxt else None, "menu_seconds_best": best.get("next"),
            "trend": [w["menu_s"] for w in nxt[-TREND_N:]], "boot_seconds": boot[-1]["menu_s"] if boot else None,
            "boot_best": best.get("boot"), "boot_trend": [w["menu_s"] for w in boot[-TREND_N:]],
            "screens": last.get("screens", ""), "presses": last.get("presses"), "misses": last.get("misses")}


def title_hints(where) -> dict:
    """The Navigator's waits on a title screen the game's own state names (PRESS ANY BUTTON, the title): none - the
    confirm goes in on the first read (gbox.mercs_bot.Navigator honours settle_s / step_s hints)."""
    return {"settle_s": 0.0, "step_s": 0.0} if where in TITLE_SCREENS else {}


# --- the walk's clock --------------------------------------------------------------------------------------------------
class Clock:
    """A title's menu walks, each timed from its start to the next round's first in-round tick.

    begin(): a run starts (kind "boot" on a fresh session: from its launch when the game dict carries `_launched_at`,
    else from the bot's start; "prepare" for a MercMode background walk). screen() every menu read, press() every press
    of the walk, miss() every press the game dropped, round_start() at the round's first tick (closes the walk and keeps
    it), round_end() at a round's end (opens a "next" walk). A walk that never saw a menu screen (a bot restarted inside
    a round) is not kept. stats(): the flat numbers for the run's stats."""

    def __init__(self, table: Table, wall=time.time, pace=None):
        self.table = table
        self.wall = wall
        self.pace = pace                         # () -> the per-screen learned waits as one line (menu_pace)
        self.open: dict | None = None
        self.last: dict | None = None
        self.misses = 0                          # this run's dropped presses (all walks)
        self.presses = 0                         # this run's walk presses (all walks)

    def _new(self, kind: str, start: float, **extra) -> dict:
        return {"kind": kind, "start": start, "screens": [], "presses": 0, "misses": 0, "menus": False, **extra}

    def begin(self, kind: str = "boot", launched_at=None, up_at=None, now: float | None = None) -> None:
        now = self.wall() if now is None else now
        start, extra = now, {"bot_at": round(now, 2)}
        if kind == "boot" and _number(launched_at) and 0 <= now - launched_at <= MAX_WALK_S:
            start = float(launched_at)
            extra["launched_at"] = round(float(launched_at), 2)
            if _number(up_at) and launched_at <= up_at <= now:
                extra["up_at"] = round(float(up_at), 2)
        self.open = self._new(kind, start, **extra)

    def screen(self, where, now: float | None = None) -> None:
        if where in (None, "playing"):
            return
        now = self.wall() if now is None else now
        if self.open is None:
            self.open = self._new("next", now)
        o = self.open
        if not o["screens"] or o["screens"][-1][0] != where:
            o["screens"].append([where, round(now - o["start"], 2), 0, 0])
        if where not in ("unknown", "loading"):
            o["menus"] = True

    def press(self, where, key=None, now: float | None = None) -> None:
        if self.open is None:
            return
        self.screen(where, now)
        self.open["presses"] += 1
        self.open["screens"][-1][2] += 1
        self.presses += 1

    def miss(self, where=None, now: float | None = None) -> None:
        self.misses += 1
        if self.open is None:
            return
        self.open["misses"] += 1
        if self.open["screens"]:
            self.open["screens"][-1][3] += 1

    def round_end(self, now: float | None = None) -> None:
        """A round's end (its death or its results): the walk to the next round counts from here."""
        now = self.wall() if now is None else now
        self.open = self._new("next", now)

    def round_start(self, now: float | None = None) -> dict | None:
        """The round's first in-round tick: the walk closes. Returns its record (None: nothing walked)."""
        now = self.wall() if now is None else now
        o, self.open = self.open, None
        if o is None or not o["menus"] or now - o["start"] > MAX_WALK_S:
            return None
        rec = self._record(o, now)
        doc = self.table.doc()
        walks = [w for w in doc.get("walks") or [] if isinstance(w, dict)]
        doc["walks"] = (walks + [rec])[-KEEP_WALKS:]
        if rec["kind"] != "prepare":
            best = doc.setdefault("best", {})
            key = rec["kind"]
            if not _number(best.get(key)) or rec["menu_s"] < best[key]:
                best[key] = rec["menu_s"]
        self.table.touch()
        self.table.save(now=now, force=True)
        self.last = rec
        return rec

    @staticmethod
    def timeline(o: dict, until: float) -> str:
        parts = []
        rows = o["screens"]
        for i, (where, at, presses, misses) in enumerate(rows):
            end = rows[i + 1][1] if i + 1 < len(rows) else until - o["start"]
            parts.append(f"{where} {max(0.0, end - at):.1f}s/{presses}p" + (f"/{misses}miss" if misses else ""))
        return ", ".join(parts)[:500]

    def _record(self, o: dict, now: float) -> dict:
        rec = {"kind": o["kind"], "at": round(now, 1), "menu_s": round(now - o["start"], 2),
               "presses": o["presses"], "misses": o["misses"], "screens": self.timeline(o, now)}
        if "launched_at" in o:
            rec["from"] = "launch"
            rec["bot_s"] = round(now - o["bot_at"], 2)                 # the bot's own part: its start to the round
            if "up_at" in o:
                rec["wait_s"] = round(o["bot_at"] - o["up_at"], 2)     # the game up, no bot yet (the scheduler's)
        elif o["kind"] == "boot":
            rec["from"] = "bot"
        return rec

    def stats(self, now: float | None = None) -> dict:
        """Flat numbers and text for the run's stats (telemetry keeps scalars only). Named apart from
        gbox.mercs.menu_speed's (menu_seconds, menu_screens, menu_boot_best, menu_open_s ...), which RE5 Switch's walk
        writes into the same stats: menu_s, menu_walk_*, menu_misses, menu_s_trend / menu_s_best (round to round),
        menu_boot_s_trend / menu_boot_s_best (from the launch), menu_launch_wait_s, menu_pace."""
        now = self.wall() if now is None else now
        doc = self.table.doc()
        walks = [w for w in doc.get("walks") or [] if isinstance(w, dict) and _number(w.get("menu_s"))]
        out: dict = {"menu_misses": self.misses}
        last = self.last
        if last is not None:
            out.update(menu_s=last["menu_s"], menu_walk_kind=last["kind"], menu_walk_presses=last["presses"],
                       menu_walk_misses=last["misses"], menu_walk_screens=last["screens"])
            for key, name in (("bot_s", "menu_walk_bot_s"), ("wait_s", "menu_launch_wait_s")):
                if key in last:
                    out[name] = last[key]
        for kind, name in (("next", "menu_s_trend"), ("boot", "menu_boot_s_trend")):
            row = [w["menu_s"] for w in walks if w.get("kind") == kind][-TREND_N:]
            if row:
                out[name] = ", ".join(f"{v:g}" for v in row)
        best = doc.get("best") or {}
        for kind, name in (("next", "menu_s_best"), ("boot", "menu_boot_s_best")):
            if _number(best.get(kind)):
                out[name] = best[kind]
        if self.open is not None and self.open["menus"]:
            out["menu_walk_open_s"] = round(now - self.open["start"], 1)
        if self.pace is not None:
            try:
                line = self.pace()
            except Exception:                    # noqa: BLE001 - a summary never costs the walk
                line = ""
            if line:
                out["menu_pace"] = line
        return out
