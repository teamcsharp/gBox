"""The universal Mercenaries doctrine: the operator's standing goals for every title, weighed against each other all
round, measured on every tick, and handed to whichever title's bot is playing.

The operator, 2026-11-09, watching RE5 ("I want the logic universal for our mercmode bot. I need to be able to enhance
the logic across titles because much of the mercenaries advice I'm giving is universal ... I want these rules worked
into the logic weight wheel system where all of these goals can be weighted dynamically resulting in dynamic and
robust gameplay avoiding posturing in the same place and meandering without being proactive"):

    engage      "on sight, shoot, always shoot" / "if the character has enemies around them, they need to fire
                brutally until they are not impeding movement" / "I do not like seeing the bot idle in any title"
    combo       "the combo must always be maintained" / "every 2-5 seconds the player needs to be extending the combo
                never letting it drop"
    explore     "always be moving" / "the bot spends too much time in the same place and needs to have the goal of
                exploring the entire level"
    explosives  "spam grenades / grenade launcher / mines / remote mines to mobs"
    interrupt   "enemies transitioning into attack animations need to be shot, dispatched, meleed or interrupted"
    boss        "dispatch bosses on sight"

RULES holds those words. A new piece of universal advice is a row there, an urgency in Director._urgencies, and a
weight (WEIGHTS; a dot on the behavior wheel, gbox.mercs.core.control_axes): nothing title-specific.

How it reaches a title. Every title's bot already takes the operator's instant commands (gbox.mercs.directives:
fight, score, hunt, explore, mine ...) and keeps its own safeguards while it does. The Director is an automatic
operator: every DECIDE_S it scores each goal as weight x urgency from the round as it is (who is near, how long since
the last kill, how long he has stood in one place, how big the crowd is) and issues the winning goal's command into
the live stats (doctrine_directive*), where directives.Reader hands it to the bot exactly like a typed one. The real
operator's command always wins: while one is in force the Director only measures.

What it measures, the same names on every title (stats, so the watch panel, the round reports and the learning loop
see them): doctrine_idle_s (enemies in sight and he neither moves nor attacks), doctrine_passive_s (enemies in his way
and no attack input), doctrine_still_s, doctrine_anchor_s (how long within ANCHOR_M of one spot), doctrine_cells (the
CELL_M squares of the level he has stood in), doctrine_since_kill_s, doctrine_combo_drops, doctrine_goal and
doctrine_status (what it is asking for and why). The hard floor: idle past IDLE_MAX_S or passive past PASSIVE_MAX_S is
a violation (doctrine_violations) and "fight" goes out at once, whatever the weights say.

The view. A title's snapshot in the doctrine's own terms (metres, seconds): driver.doctrine_view(snap) when the title
has one, else view() reads the common snapshot shape (player pos or r, enemies with pos or r and hp, kills, combo) with
the title's units (driver.units_per_m, default 100: RE5 and RE6 are in cm) and, when the title's module names them, its
wind-up motions and attack flag (WINDUP_MOTIONS, E_ATTACKING).

Nothing here reads or writes the game, and nothing here presses a key.
"""
from __future__ import annotations

import collections
import math
import sys

# The operator's words, the goal they are, and the command that asks a bot for it (None: measured, the title's own
# rule acts - the wind-up interrupt lives in each bot's fight, where the frame data is).
RULES = (
    ("engage", "fight", "on sight, shoot, always shoot; with enemies around him he fires brutally until they are not "
                        "impeding movement; never idle in any title"),
    ("combo", "score", "the combo must always be maintained: every 2-5 seconds he extends it, never letting it drop"),
    ("explore", "hunt", "always be moving; never posturing in the same place; the goal is exploring the entire level"),
    ("explosives", "mine", "spam grenades / grenade launcher / mines / remote mines to mobs"),
    ("interrupt", None, "enemies transitioning into attack animations are shot, dispatched, meleed or interrupted"),
    ("boss", "fight", "dispatch bosses on sight"),
)
GOALS = tuple(r[0] for r in RULES)
COMMAND = {r[0]: r[1] for r in RULES}
# The weights (0..1; the behavior wheel's goal dots). A title's module may carry its own under GOAL_<NAME> (what the
# operator's bot-logic sidebar sets, gbox.mercs.bot_logic); these are what a title without them plays by.
WEIGHTS = {"engage": 1.0, "combo": 0.9, "explore": 0.7, "explosives": 0.6, "interrupt": 1.0, "boss": 1.0}

IMPEDE_M = 3.5                    # an enemy this near is in his way
LEVEL_M = 2.5                     # ... on his own floor: one this far above or below is neither in his way nor in sight
                                  # (a command sent for a Majini on a roof walked RE5's bot at the wall under it)
SIGHT_M = 18.0                    # ... this near is "on sight"
CROWD_N, CROWD_M = 4, 6.0         # a mob: this many within this far
COMBO_MIN_S, COMBO_MAX_S = 2.0, 5.0   # the operator's window: a kill every 2-5 seconds
ANCHOR_M, ANCHOR_MIN_S, ANCHOR_MAX_S = 6.0, 8.0, 20.0   # within this of one spot this long: posturing
CELL_M = 5.0                      # the level in squares this wide: the ones he has stood in are "explored"
MOVE_M_S = 0.6                    # slower than this over MOVE_WINDOW_S: standing
MOVE_WINDOW_S = 1.0
IDLE_MAX_S, PASSIVE_MAX_S = 0.75, 1.5   # the hard floor (see the module text)
DECIDE_S = 0.5                    # a decision this often; a command lasts HOLD_S and is extended while its goal still wins
HOLD_S = 4.0
ISSUE_MIN = 0.45                  # weight x urgency under this: no command, the bot's own judgement
EXPLOSIVE_GAP_S = 10.0            # between explosives commands (each title's own cooldowns apply on top)
BOSS_HP_MIN = 3000                # gbox.mercs.weapon_choice.BOSS_HP_MIN: this much health is a boss
# The operator, 2026-11-09: "the bot should place themself at least 15 meters from the mine to avoid hurting
# themselves". Every title's mine / remote-bomb logic leaves its own explosive by this much and stays this far from
# any of his still down (RE5 Switch: re5_switch_mines RETREAT_CM / BLAST_CM; live the same day one blast cost 350 hp).
MINE_STANDOFF_M = 15.0
TICK_MAX_S = 0.5                  # a longer gap between ticks (a loading screen, a held frame) counts as this much
ATTACK_KEYS = frozenset({"zr", "zl", "r1", "l1", "r2", "l2", "rt", "lt", "r", "square", "x"})   # the gun up, or fired
MOVE_KEYS = frozenset({"lup", "ldown", "lleft", "lright", "up", "down", "left", "right"})
COUNTERS = ("doctrine_idle_s", "doctrine_passive_s", "doctrine_still_s", "doctrine_violations",
            "doctrine_combo_drops", "doctrine_commands", "doctrine_played_s")


def _ramp(x: float, lo: float, hi: float) -> float:
    return 0.0 if x <= lo else 1.0 if x >= hi else (x - lo) / (hi - lo)


def title_module(drv):
    """The module the title's driver lives in: where its GOAL_* weights and its wind-up tables are, if it has them."""
    return sys.modules.get(type(drv).__module__) if drv is not None else None


def weights(module=None) -> dict:
    """The goal weights in force: the title module's GOAL_<NAME> where it carries one, else WEIGHTS."""
    out = {}
    for goal, default in WEIGHTS.items():
        v = getattr(module, "GOAL_" + goal.upper(), default) if module is not None else default
        out[goal] = min(max(float(v), 0.0), 1.0) if isinstance(v, (int, float)) and not isinstance(v, bool) else default
    return out


def view(snap: dict, drv=None, module=None) -> dict | None:
    """The round in the doctrine's terms, or None when no player is up (a menu, a loading screen):
    {"pos": (x, z) m, "foes": [{"d": m, "boss": bool, "windup": bool}], "kills", "combo"}."""
    custom = getattr(drv, "doctrine_view", None)
    if callable(custom):
        got = custom(snap)
        if got is not None:
            return got
    p = snap.get("player") if isinstance(snap, dict) else None
    if not isinstance(p, dict):
        return None
    pos = p.get("pos") or p.get("r")
    if not pos or len(pos) < 3:
        return None
    scale = float(getattr(drv, "units_per_m", 100.0) or 100.0)
    px, pz = pos[0] / scale, pos[2] / scale
    if not (math.isfinite(px) and math.isfinite(pz)):
        return None
    module = module if module is not None else title_module(drv)
    winding = getattr(module, "WINDUP_MOTIONS", ()) or ()
    flag = getattr(module, "E_ATTACKING", 0) or 0
    foes = []
    for e in snap.get("enemies") or ():
        if not isinstance(e, dict) or (e.get("hp") or 0) <= 0:
            continue
        q = e.get("pos") or e.get("r")
        if not q or len(q) < 3:
            continue
        d = math.hypot(q[0] / scale - px, q[2] / scale - pz)
        if not math.isfinite(d):
            continue
        if abs(q[1] - pos[1]) / scale > LEVEL_M:        # another floor: alive, but not this moment's business
            continue
        foes.append({"d": d, "boss": bool(e.get("boss")) or (e.get("hp_max") or 0) >= BOSS_HP_MIN,
                     "windup": bool(e.get("windup")) or e.get("motion") in winding
                     or bool(flag and (e.get("act") or 0) & flag)})
    return {"pos": (px, pz), "foes": foes, "kills": snap.get("kills"), "combo": snap.get("combo")}


def _commands():
    from .. import directives
    return directives


class Reader:
    """A bot's view of its commands: the operator's first (gbox.mercs.directives.Reader), else the doctrine's.

    Every bot builds this one. directives itself is never hot-reloaded (it holds the chat's in-memory store), so a
    worker that has not restarted since the doctrine arrived still runs a directives.Reader that knows nothing of
    doctrine_directive*: the fallback lives here, in a module that does reload, and is a no-op once the restarted
    worker's own Reader already hands the doctrine's command over."""

    def __init__(self):
        self.base = _commands().Reader()
        self.seen_auto = None

    def current(self, stats: dict, now: float | None = None) -> tuple:
        import time
        now = time.time() if now is None else now
        cmd, fresh = self.base.current(stats, now)
        if cmd is not None:
            if cmd == stats.get("doctrine_directive") and stats.get("doctrine_directive_seq") is not None \
                    and not (stats.get("directive") and now < float(stats.get("directive_until") or 0)):
                self.seen_auto = stats.get("doctrine_directive_seq")     # the base handed the doctrine's over itself
            return cmd, fresh
        auto, aseq = stats.get("doctrine_directive"), stats.get("doctrine_directive_seq")
        if auto in _commands().COMMANDS and aseq is not None \
                and now < float(stats.get("doctrine_directive_until") or 0):
            fresh = aseq != self.seen_auto
            self.seen_auto = aseq
            return auto, fresh
        return None, False


class Director:
    """One round's doctrine: observe() every playing tick -> the goal in force (or None).

    stats is the bot's live dict; the weights come from weights_of() each decision, so a dot dragged on the wheel
    changes the very next one."""

    def __init__(self, stats: dict, weights_of=None):
        self.stats = stats
        self.weights_of = weights_of or (lambda: dict(WEIGHTS))
        self.seq = 0
        self.reset()

    def reset(self, now: float | None = None) -> None:
        self.t = None                                  # the previous tick
        self.trail = collections.deque(maxlen=128)     # (t, x, z): the last MOVE_WINDOW_S
        self.anchor, self.anchor_at = None, None       # the spot he is "at", since when
        self.cells: set = set()
        self.kills, self.combo = None, None
        self.kill_at = now                             # the last kill (the round's start until there is one)
        self.idle_run = self.passive_run = 0.0
        self.floored = False                           # under the hard floor right now (a violation counts once)
        self.decided_at = -1e9
        self.explosive_at = -1e9
        self.goal, self.goal_until = None, 0.0
        for k in COUNTERS:
            self.stats[k] = 0 if k in ("doctrine_violations", "doctrine_combo_drops", "doctrine_commands") else 0.0
        self.stats.update(doctrine_goal=None, doctrine_status="", doctrine_anchor_s=0.0, doctrine_cells=0,
                          doctrine_since_kill_s=0.0, doctrine_longest_idle_s=0.0, doctrine_engaged_pct=None)
        for k in ("doctrine_directive", "doctrine_directive_until", "doctrine_directive_seq"):
            self.stats.pop(k, None)

    # --- the tick ---
    def observe(self, v: dict | None, act: dict | None, now: float) -> str | None:
        """One playing tick: the view (None: no player up), the bot's action this tick, the wall clock."""
        if v is None:
            self.t = None                              # a gap: the next tick starts fresh, nothing accrues over it
            return self.goal
        dt = 0.0 if self.t is None else min(max(now - self.t, 0.0), TICK_MAX_S)
        self.t = now
        if self.kill_at is None:
            self.kill_at = now
        st = self.stats
        x, z = v["pos"]
        keys = set((act or {}).get("hold", ()) or ())
        if (act or {}).get("tap"):
            keys.add(act["tap"])
        foes = v.get("foes") or ()
        impeding = sum(1 for f in foes if f["d"] <= IMPEDE_M)
        in_sight = sum(1 for f in foes if f["d"] <= SIGHT_M)
        crowd = sum(1 for f in foes if f["d"] <= CROWD_M)
        # moving: the ground covered over the last MOVE_WINDOW_S (a stick held into a wall is not moving)
        self.trail.append((now, x, z))
        while len(self.trail) > 2 and now - self.trail[1][0] >= MOVE_WINDOW_S:
            self.trail.popleft()
        t0, x0, z0 = self.trail[0]
        span = now - t0
        speed = math.hypot(x - x0, z - z0) / span if span >= 0.25 else None
        moving = speed >= MOVE_M_S if speed is not None else bool(keys & MOVE_KEYS)
        attacking = bool(keys & ATTACK_KEYS)
        # kills and the combo
        kills, combo = v.get("kills"), v.get("combo")
        if isinstance(kills, int) and isinstance(self.kills, int) and kills > self.kills:
            self.kill_at = now
        if isinstance(combo, int) and isinstance(self.combo, int) and self.combo >= 2 and combo < self.combo \
                and combo <= 1:
            st["doctrine_combo_drops"] += 1
        self.kills = kills if isinstance(kills, int) else self.kills
        self.combo = combo if isinstance(combo, int) else self.combo
        since_kill = now - self.kill_at
        # where he has been, and how long he has stood about here
        self.cells.add((math.floor(x / CELL_M), math.floor(z / CELL_M)))
        if self.anchor is None or math.hypot(x - self.anchor[0], z - self.anchor[1]) > ANCHOR_M:
            self.anchor, self.anchor_at = (x, z), now
        anchor_s = now - self.anchor_at
        # the measures
        idle = in_sight > 0 and not moving and not attacking
        passive = impeding > 0 and not attacking
        self.idle_run = self.idle_run + dt if idle else 0.0
        self.passive_run = self.passive_run + dt if passive else 0.0
        st["doctrine_played_s"] = round(st["doctrine_played_s"] + dt, 2)
        if idle:
            st["doctrine_idle_s"] = round(st["doctrine_idle_s"] + dt, 2)
        if passive:
            st["doctrine_passive_s"] = round(st["doctrine_passive_s"] + dt, 2)
        if in_sight and not moving:
            st["doctrine_still_s"] = round(st["doctrine_still_s"] + dt, 2)
        st["doctrine_longest_idle_s"] = round(max(st.get("doctrine_longest_idle_s") or 0.0, self.idle_run), 2)
        played = st["doctrine_played_s"]
        st.update(doctrine_anchor_s=round(anchor_s, 1), doctrine_cells=len(self.cells),
                  doctrine_since_kill_s=round(since_kill, 1),
                  doctrine_engaged_pct=round(100.0 * (1.0 - st["doctrine_passive_s"] / played), 1) if played else None)
        # the hard floor, then the weighted decision
        floor = self.idle_run >= IDLE_MAX_S or self.passive_run >= PASSIVE_MAX_S
        if floor and not self.floored:                  # counted once a lapse, however long it lasts
            st["doctrine_violations"] += 1
            self.decided_at = -1e9                      # decide now
        self.floored = floor
        if now - self.decided_at >= DECIDE_S:
            self.decided_at = now
            w = self.weights_of()
            u = self._urgencies(foes, impeding, in_sight, crowd, since_kill, anchor_s, now)
            if floor:
                u["engage"] = max(u["engage"], 1.0)
            scored = sorted(((w.get(g, 0.0) * u.get(g, 0.0), g) for g in GOALS if COMMAND[g]), reverse=True)
            score, goal = scored[0]
            if floor:
                score, goal = max(score, 1.0), "engage"
            self._issue(goal if score >= ISSUE_MIN else None, score, u, now)
        return self.goal

    def _urgencies(self, foes, impeding, in_sight, crowd, since_kill, anchor_s, now) -> dict:
        boss = any(f["boss"] and f["d"] <= SIGHT_M for f in foes)
        windup = any(f["windup"] and f["d"] <= IMPEDE_M for f in foes)
        mob = crowd >= CROWD_N and now - self.explosive_at >= EXPLOSIVE_GAP_S
        return {
            # in his way: brutal fire until the way is clear; on sight further off: fire, but the combo and the level
            # may outweigh it
            "engage": 1.0 if impeding else 0.5 if in_sight else 0.0,
            # the operator's window: nothing owed before COMBO_MIN_S, everything by COMBO_MAX_S
            "combo": _ramp(since_kill, COMBO_MIN_S, COMBO_MAX_S) if in_sight else 0.0,
            # posturing: the longer about one spot the stronger; with enemies in his way they come first
            "explore": _ramp(anchor_s, ANCHOR_MIN_S, ANCHOR_MAX_S) * (0.4 if impeding else 1.0),
            "explosives": min(1.0, 0.55 + 0.1 * (crowd - CROWD_N)) if mob else 0.0,
            "interrupt": 1.0 if windup else 0.0,
            "boss": 1.0 if boss else 0.0,
        }

    def _issue(self, goal, score, u, now) -> None:
        st = self.stats
        operator = st.get("directive") and now < float(st.get("directive_until") or 0)
        if goal != self.goal or goal is None:
            self.goal = goal
            if goal is not None:
                self.seq += 1
                st["doctrine_commands"] += 1
                if goal == "explosives":
                    self.explosive_at = now
        self.goal_until = now + HOLD_S if goal else 0.0
        st["doctrine_goal"] = goal
        why = ", ".join(f"{g} {u[g]:.2f}" for g in GOALS if u.get(g))
        if goal is None or operator:
            for k in ("doctrine_directive", "doctrine_directive_until", "doctrine_directive_seq"):
                st.pop(k, None)
            st["doctrine_status"] = ("the operator's command is in force; measuring only" if operator
                                     else f"no goal pressing ({why or 'nobody in sight'})")
            return
        st.update(doctrine_directive=COMMAND[goal], doctrine_directive_until=self.goal_until,
                  doctrine_directive_seq=f"d{self.seq}",
                  doctrine_status=f"{goal} -> {COMMAND[goal]} (score {score:.2f}; {why})")
