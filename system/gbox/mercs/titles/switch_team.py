"""Split-screen co-op in RE5 / RE6 on Switch (docs/research/switch-coop-bot.md): the title's own brain plays either
player from that player's own RAM, and this module adds what a solo bot never does.

Operator 2026-10-27: "play alongside the bot in games where they are able to use their level understanding bot skills
and modifications to help me", and "have the bot team up with itself playing two play split screen".

    View(m, index)    a memory view whose title snapshot is player `index`'s (mercs_player_index), with mercs_coop set so
                      the title reads that player's own laser sight (and camera, RE6) instead of the solo "first one"
    participants(m)   both players from sPlayer's slots, each checked by its own index byte (static, both mains)
    shape(...)        the enemies one brain sees: a held partner's grabbers first; the operator's own targets left to
                      them (teammate); a crowd split by who is nearer (two bots)
    Teammate          one brain plus the team's overrides: help a dying or held partner, follow back when far
    Pair              two Teammates on one engine loop: Player 2's keys come back prefixed "p2:" (SessionRuntime's
                      bots_p1_p2 routing sends them to Player 2's pad)
    CoopDriver        the engine's driver for either mode, one title driver per player (own timers, tallies, stats)
    MenuPartner       Player 2's own presses between rounds (its character select), rate-limited

Nothing here writes memory. A missing or unverified Player 2 gives a plain solo snapshot back, never Player 1's keys
for the bot: the input fence lives in SessionRuntime and the adapter (gbox.switch_coop).
"""
from __future__ import annotations

import math
import struct
import time

from ..driver import Driver
from . import re5_switch, re6_switch

TEAMMATE, PAIR = "teammate", "pair"     # (a) the operator's P1 with the bot as P2; (b) bots on both
P2_PREFIX = "p2:"
FOLLOW_R, FOLLOW_STOP_R = 800.0, 450.0  # cm: farther than this from the partner (and nothing near): walk back, to this
SELF_THREAT_R = 300.0                   # an enemy this near the bot is always its business
GRAB_R = 150.0                          # the enemies this near a held partner are the ones holding him
HELP_R = 140.0                          # this near a held / dying partner: the partner action (A) frees / helps him
FRONT_R, FRONT_CONE = 250.0, math.radians(35)   # the operator's own fight: close in front of them, inside this cone
RUN_R = 1500.0                          # following from this far: run (the stick plus B on both titles)
TURN_TOL = math.radians(20)
PULSE_DOWN_S, PULSE_UP_S = 0.12, 0.25   # the partner action's presses
TAP_S = 0.12                            # a brain's "tap" held this long when two brains share the pad loop
MENU_PRESS_S, MENU_GAP_S = 0.3, 1.5     # Player 2's menu presses (the menus take 0.3 s presses on both titles)
P2_STATS = ("act", "shots", "hits", "holds", "heals", "tablets", "team_act", "team_shaped", "team_follow_s",
            "team_helps", "team_revives")


class Title:
    """What the team needs from one title's RAM (static findings in docs/research/switch-coop-bot.md)."""

    def __init__(self, mod, *, slots: int, index_at: int, count_at: int, held, dying_hp: int, camera_turns: bool):
        self.mod, self.slots, self.index_at, self.count_at = mod, slots, index_at, count_at
        self.held, self.dying_hp, self.camera_turns = held, dying_hp, camera_turns
        self.map_id = mod.MAP_ID

    def dying(self, p) -> bool:
        return bool(p) and p.get("hp") == self.dying_hp and (p.get("hp_max") or 0) > self.dying_hp


TITLES = {
    re5_switch.MAP_ID: Title(re5_switch, slots=4, index_at=re5_switch.P_INDEX, count_at=re5_switch.S_PLAYER_COUNT,
                             held=lambda p: bool(p) and p.get("motion") in re5_switch.MOTION_HELD,
                             dying_hp=re5_switch.DYING_HP, camera_turns=False),
    re6_switch.MAP_ID: Title(re6_switch, slots=8, index_at=re6_switch.P_INDEX, count_at=re6_switch.S_PLAYER_COUNT,
                             held=lambda p: bool(p) and p.get("state") in re6_switch.HELD_STATES,
                             dying_hp=re6_switch.DYING_HP, camera_turns=True),
}


def title_of(map_id: str) -> Title:
    try:
        return TITLES[map_id]
    except KeyError:
        raise LookupError(f"split-screen co-op covers RE5 and RE6 on Switch, not {map_id}") from None


class View:
    """The session's memory, seen as player `index`: reads go to the memory itself; the title's snapshot reads
    [sPlayer + 0x30 + 8 * index] and that player's own laser / camera (mercs_coop)."""

    def __init__(self, m, index: int, *, mods: bool = True):
        object.__setattr__(self, "_m", m)
        object.__setattr__(self, "mercs_player_index", index)
        object.__setattr__(self, "mercs_coop", True)
        if not mods:                                      # this player's driver keeps its hands off the live mods
            object.__setattr__(self, "mercs_no_modifications", True)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "_m"), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_m"), name, value)   # module_base and the title's caches stay shared


def participants(m, title: Title) -> list[dict]:
    """The players in sPlayer's slots whose own index byte matches the slot: [{slot (1-based), index, actor, pos, hp,
    hp_max}], at most two (split screen). Read only; [] when main is not found."""
    mod = title.mod
    base = mod.module_base(m)
    if base is None:
        return []
    out = []
    try:
        sp = mod.u64(m, base + mod.S_PLAYER)
        if not mod.ptr_ok(sp):
            return []
        for index in range(2):
            p = mod.u64(m, sp + mod.P_FIRST + 8 * index)
            if not mod.ptr_ok(p) or m.rd(p + title.index_at, 1)[0] != index:
                continue
            pos = struct.unpack("<3f", m.rd(p + mod.P_POS, 12))
            hp, hp_max = struct.unpack("<hh", m.rd(p + mod.P_HP, 4))
            if not all(math.isfinite(v) and abs(v) < 1e7 for v in pos) or not 0 < hp_max <= 30000:
                continue
            out.append({"slot": index + 1, "id": f"p{index + 1}", "index": index, "actor": p, "ptr": p, "pos": pos,
                        "hp": hp, "hp_max": hp_max, "native_actor_verified": True,
                        "provenance": {"kind": "native_ram", "read_only": True, "native_actor_verified": True,
                                       "title": title.map_id, "slot_address": sp + mod.P_FIRST + 8 * index,
                                       "index_address": p + title.index_at}})
    except (ValueError, OSError, struct.error):
        return []
    return out


def _live(e) -> bool:
    return isinstance(e, dict) and (e.get("hp") or 0) > 0 and isinstance(e.get("pos"), (tuple, list))


def _flat(a, b) -> float:
    return math.hypot(a[0] - b[0], a[2] - b[2])


def engaged(title: Title, mate: dict, laser: dict | None, enemies) -> set:
    """The enemies the operator is fighting: their laser's ray runs through one (or its dot sits on him), or one stands
    close in front of them. Those are theirs: the teammate leaves them unless they come for the teammate."""
    out = set()
    mod = title.mod
    origin, dot = (laser or {}).get("from"), (laser or {}).get("at")
    aiming = bool(laser and laser.get("up") and origin and dot)
    facing = mate.get("rot")
    for e in enemies:
        foot = e["pos"]
        if aiming and (mod.dot_on(dot, foot) is not None or mod.through(origin, dot, foot)):
            out.add(id(e))
            continue
        if facing is not None and _flat(mate["pos"], foot) <= FRONT_R:
            bearing = mod.heading(foot[0] - mate["pos"][0], foot[2] - mate["pos"][2])
            if abs(mod.wrap(bearing - facing)) <= FRONT_CONE:
                out.add(id(e))
    return out


def shape(snap: dict, title: Title, mode: str) -> dict:
    """The snapshot one brain sees: its enemies chosen for the team. A held partner: his grabbers (and whoever is on the
    bot). TEAMMATE: the operator's own fight is left to them. PAIR: each bot takes the enemies nearer to it than to
    its partner. Anything within SELF_THREAT_R of the bot always stays. Dead enemies pass through unchanged."""
    me, mate = snap.get("player"), snap.get("partner")
    if not me or not mate or not snap.get("enemies"):
        return snap
    live = [e for e in snap["enemies"] if _live(e)]
    rest = [e for e in snap["enemies"] if not _live(e)]
    near_me = [e for e in live if _flat(e["pos"], me["pos"]) <= SELF_THREAT_R]
    why = "all"
    if title.held(mate):
        grabbers = [e for e in live if _flat(e["pos"], mate["pos"]) <= GRAB_R]
        keep = grabbers + [e for e in near_me if e not in grabbers]
        why = "partner_held" if grabbers else why
        if not grabbers:
            keep = live
    elif mode == TEAMMATE:
        theirs = engaged(title, mate, snap.get("partner_laser"), live)
        keep = [e for e in live if id(e) not in theirs or e in near_me]
        why = "operator_targets_left" if len(keep) < len(live) else why
    else:
        keep = [e for e in live if _flat(e["pos"], me["pos"]) <= _flat(e["pos"], mate["pos"]) or e in near_me]
        why = "crowd_split" if len(keep) < len(live) else why
        if not keep:                                      # all nearer the partner: help him with the nearest of them
            keep = sorted(live, key=lambda e: _flat(e["pos"], me["pos"]))[:2]
            why = "partner_crowd"
    out = dict(snap)
    out["enemies"] = keep + rest
    out["team_shaped"] = {"why": why, "kept": len(keep), "dropped": len(live) - len(keep)}
    return out


def move_keys(title: Title, snap: dict, target, *, run: bool = False) -> set:
    """Hold keys that walk the bot toward target: RE5 by its own heading (Type D: forward is where he faces, the right
    stick turns him, rleft = a larger heading), RE6 along its own camera (the left stick walks where the camera looks,
    the right stick turns it, rleft = a larger yaw). The stick plus B runs on both."""
    me = snap["player"]
    mod = title.mod
    want = mod.heading(target[0] - me["pos"][0], target[2] - me["pos"][2])
    cam = snap.get("camera") if title.camera_turns else None
    have = cam["yaw"] if cam and cam.get("yaw") is not None else me.get("rot", 0.0)
    err = mod.wrap(want - have)
    keys: set = set()
    if abs(err) > TURN_TOL:
        keys.add("rleft" if err > 0 else "rright")
    if abs(err) < math.radians(75) or title.camera_turns:
        keys.add("lup")
        if run and abs(err) < math.radians(30):
            keys.add("b")
    return keys


class Teammate:
    """One title brain with the team's overrides on top. Priorities: the bot's own trouble (held, dying, dead) is the
    brain's; then a dying partner (walk over, the partner action); a held partner within reach (the partner action),
    else his grabbers are the brain's only targets; then following back when the partner is far and nothing is near;
    otherwise the brain fights on the shaped snapshot."""

    def __init__(self, bot, title: Title, mode: str, stats: dict, clock=time.monotonic):
        self.bot, self.title, self.mode, self.stats, self.clock = bot, title, mode, stats, clock
        self.following = False
        self._pulse_at, self._pulse_down = -1e9, False
        self._follow_since = None
        for key in ("team_helps", "team_revives"):
            stats.setdefault(key, 0)

    def __getattr__(self, name):                          # the engine's view of the brain (_round_started, _threats ...)
        if name.startswith("__") or name == "bot":
            raise AttributeError(name)
        return getattr(self.bot, name)

    def _pulse(self, now, counter: str) -> set:
        """The partner action: A held PULSE_DOWN_S, released PULSE_UP_S, again; each press counted in counter."""
        if self._pulse_down and now - self._pulse_at >= PULSE_DOWN_S:
            self._pulse_down, self._pulse_at = False, now
        elif not self._pulse_down and now - self._pulse_at >= PULSE_UP_S:
            self._pulse_down, self._pulse_at = True, now
            self.stats[counter] = self.stats.get(counter, 0) + 1
        return {"a"} if self._pulse_down else set()

    def _act(self, name: str, keys: set) -> dict:
        self.stats["team_act"] = name
        return {"hold": keys}

    def tick(self, snap: dict) -> dict:
        now = self.clock()
        me, mate = snap.get("player"), snap.get("partner")
        title = self.title
        if not me or not mate or (me.get("hp") or 0) <= 0 or title.held(me) or title.dying(me) \
                or (mate.get("hp") or 0) <= 0:
            self.following = False
            self.stats["team_act"] = "brain"
            return self.bot.tick(snap)
        live = [e for e in snap.get("enemies") or () if _live(e)]
        threat = any(_flat(e["pos"], me["pos"]) <= SELF_THREAT_R for e in live)
        gap = _flat(me["pos"], mate["pos"])
        if title.dying(mate) and not threat:
            if gap <= HELP_R:
                return self._act("revive", self._pulse(now, "team_revives"))
            return self._act("to_dying_partner", move_keys(title, snap, mate["pos"], run=gap > RUN_R))
        if title.held(mate) and gap <= HELP_R:
            return self._act("help_held", self._pulse(now, "team_helps"))
        # a held partner farther off: his grabbers are the brain's targets (shape), never a walk past them
        self.following = not threat and not title.held(mate) and (
            gap > FOLLOW_R or self.following and gap > FOLLOW_STOP_R)
        if self.following:
            if self._follow_since is None:
                self._follow_since = now
            self.stats["team_follow_s"] = round(now - self._follow_since, 1)
            return self._act("follow", move_keys(title, snap, mate["pos"], run=gap > RUN_R))
        self._follow_since = None
        shaped = shape(snap, title, self.mode)
        self.stats["team_shaped"] = (shaped.get("team_shaped") or {}).get("why", "all")
        self.stats["team_act"] = "fight"
        return self.bot.tick(shaped)

    def prompt_ok(self, button, snap, now) -> bool:
        return self.bot.prompt_ok(button, snap, now)

    def save(self) -> None:
        self.bot.save()


class Pair:
    """Mode (b): two Teammates on one engine loop. Player 1's keys as they are, Player 2's prefixed P2_PREFIX; a brain's
    "tap" becomes a hold of TAP_S (the engine's tap path would pause the other bot). The engine's view of the brain
    (round markers, threats, prompts) is Player 1's."""

    def __init__(self, one: Teammate, two: Teammate, stats: dict, clock=time.monotonic):
        self.one, self.two, self.stats, self.clock = one, two, stats, clock
        self._taps = {1: {}, 2: {}}

    def __getattr__(self, name):
        if name.startswith("__") or name == "one":
            raise AttributeError(name)
        return getattr(self.one, name)

    def _keys(self, act: dict, player: int, now: float) -> set:
        taps = self._taps[player]
        if isinstance(act, dict) and act.get("tap"):
            taps[act["tap"]] = now + TAP_S
        for key in [k for k, until in taps.items() if until <= now]:
            taps.pop(key)
        return set(act.get("hold", ()) if isinstance(act, dict) else ()) | set(taps)

    def tick(self, snap: dict) -> dict:
        now = self.clock()
        a1 = self.one.tick(snap)
        second = snap.get("p2")
        if isinstance(second, dict):
            a2 = self.two.tick(second)
        else:                                             # no Player 2 this tick: nothing held for it, taps dropped
            a2 = {"hold": set()}
            self._taps[2].clear()
        for key in P2_STATS:
            if key in self.two.stats:
                self.stats["p2_" + key] = self.two.stats[key]
        return {"hold": self._keys(a1, 1, now) | {P2_PREFIX + k for k in self._keys(a2, 2, now)}}

    def prompt_ok(self, button, snap, now) -> bool:
        return self.one.prompt_ok(button, snap, now)

    def save(self) -> None:
        for brain in (self.one, self.two):
            try:
                brain.save()
            except Exception:                             # noqa: BLE001 - one brain's file never costs the other's
                pass


def mate_view(m, title: Title, index: int) -> dict:
    """The partner as a brain needs him (light: no enemies): {player, laser, camera} from the title's own snapshot."""
    snap = title.mod.snapshot(View(m, index))
    return {"player": snap.get("player"), "laser": snap.get("laser"), "camera": snap.get("camera")}


class CoopDriver(Driver):
    """The engine's driver in split screen. TEAMMATE: the bot's snapshot is Player 2's (the partner is the operator's
    Player 1); PAIR: Player 1's snapshot carries Player 2's under "p2", each with the other as its partner. Screens,
    tallies and mods go through the controlling player's own title driver (TEAMMATE: Player 2's; PAIR: Player 1's).
    A round without a verified Player 2 snapshot gives the brain no partner, so the team overrides stay off."""

    solo_p1 = False

    def __init__(self, map_id: str, mode: str, clock=time.monotonic):
        if mode not in (TEAMMATE, PAIR):
            raise ValueError("split-screen mode is teammate or pair")
        self.title = title_of(map_id)
        self.mode, self.clock = mode, clock
        cls = self.title.mod.DRIVER
        self.drivers = {0: cls(clock=clock), 1: cls(clock=clock)}
        self.map_id = self.title.map_id
        self.round_counters = tuple(getattr(cls, "round_counters", ()) or ())
        self.p2_stats: dict = {}

    @property
    def control(self) -> int:
        """The player whose screen and tally the engine follows: the bot (P2) as a teammate, P1 with two bots."""
        return 1 if self.mode == TEAMMATE else 0

    def snapshot(self, m) -> dict:
        title = self.title
        if self.mode == TEAMMATE:
            snap = self.drivers[1].snapshot(View(m, 1))
            mate = mate_view(m, title, 0)
            snap.update(partner=mate["player"], partner_laser=mate["laser"], partner_camera=mate["camera"])
        else:
            snap = self.drivers[0].snapshot(View(m, 0))
            second = self.drivers[1].snapshot(View(m, 1, mods=False))
            snap["p2"] = second
            snap["partner"], second["partner"] = second.get("player"), snap.get("player")
            snap["partner_laser"], second["partner_laser"] = second.get("laser"), snap.get("laser")
        snap["coop_mode"] = self.mode
        return snap

    def screen(self, m, snap) -> str:
        return self.drivers[self.control].screen(View(m, self.control), snap)

    def brain(self, m, stats: dict, clock, learn_dir=None, nav=None):
        title = self.title
        if self.mode == TEAMMATE:
            bot = self.drivers[1].brain(View(m, 1), stats, clock, learn_dir=learn_dir)
            return Teammate(bot, title, TEAMMATE, stats, clock)
        self.p2_stats = {}
        one = Teammate(self.drivers[0].brain(View(m, 0), stats, clock, learn_dir=learn_dir), title, PAIR, stats, clock)
        # Player 2's driver never maintains the live mods: they track one player per session (RE5's fire-rate time
        # scale is put back on the player it raised), and Player 1's driver owns them in this mode
        two = Teammate(self.drivers[1].brain(View(m, 1, mods=False), self.p2_stats, clock, learn_dir=learn_dir),
                       title, PAIR, self.p2_stats, clock)
        return Pair(one, two, stats, clock)

    def result_ready(self, snap, now) -> bool:
        ready = getattr(self.drivers[self.control], "result_ready", None)
        return ready(snap, now) if callable(ready) else True

    def menu_handoff(self, m, snap, where) -> bool:
        handoff = getattr(self.drivers[self.control], "menu_handoff", None)
        return bool(callable(handoff) and handoff(m, snap, where))

    def prompt_keys(self, button) -> list:
        return self.drivers[self.control].prompt_keys(button)

    def progress(self, snap: dict) -> dict:
        return {**self.drivers[self.control].progress(snap), "coop_mode": self.mode}

    # --- SessionRuntime's native evidence (gbox.mercs.session_runtime) ---
    def participants(self, m, snap=None) -> list:
        return participants(m, self.title)

    def readiness(self, m) -> dict:
        """Player 2's actor from RAM, and Player 2's pad from the adapter (gbox.switch_coop.readiness). The Switch
        bots read prompts from RAM motion / state bytes (no prompt reader to scope), RE5's bot turns by its own heading
        (no camera to own), RE6's reads its own camera through the player's pointer, checked by its owner field."""
        rows = participants(m, self.title)
        second = next((r for r in rows if r["slot"] == 2), None)
        adapter = getattr(m, "adapter", None)
        try:
            pad = getattr(adapter, "teammate_pad_status", lambda: {})() or {}
        except Exception:                                 # noqa: BLE001
            pad = {}
        camera_ok = True
        if second is not None and self.title.camera_turns:
            camera_ok = bool((mate_view(m, self.title, 1) or {}).get("camera"))
        verified = second is not None and pad.get("verified") is True and camera_ok
        reason = ("Player 2's actor, pad and view verified" if verified else
                  "Player 2 has not joined the round (split screen, a prepared Player 2 pad)" if second is None else
                  pad.get("reason") or "Player 2's pad is not verified for this launch" if pad.get("verified") is not True
                  else "Player 2's own camera is not readable yet")
        return {"p2_verified": verified, "p2_actor_verified": second is not None,
                "controller2_verified": pad.get("verified") is True, "controller2_prepared": bool(pad.get("prepared")),
                "camera2_verified": second is not None and camera_ok, "prompt2_verified": second is not None,
                "human_observer_verified": any(r["slot"] == 1 for r in rows),
                "active_players": rows, "reason": reason}


class MenuPartner:
    """Player 2's own presses between rounds: on the character select, A every MENU_GAP_S (a 0.3 s press) so Player 2
    takes its character once Player 1 has; nothing anywhere else (Player 1 drives the shared menus). TEAMMATE waits
    `after_s` on the select first, so the operator picks before the bot."""

    def __init__(self, send2, clock=time.monotonic, *, after_s: float = 0.0, sleep=time.sleep):
        self.send2, self.clock, self.after_s, self.sleep = send2, clock, after_s, sleep
        self._since, self._last = None, -1e9
        self.presses = 0

    def step(self, scr: dict) -> bool:
        now = self.clock()
        if (scr or {}).get("where") != "select_player":
            self._since = None
            return False
        if self._since is None:
            self._since = now
        if now - self._since < self.after_s or now - self._last < MENU_GAP_S:
            return False
        self._last = now
        self.send2([{"key": "a", "down": True, "player": 2}])
        self.sleep(MENU_PRESS_S)
        self.send2([{"key": "a", "down": False, "player": 2}])
        self.presses += 1
        return True

