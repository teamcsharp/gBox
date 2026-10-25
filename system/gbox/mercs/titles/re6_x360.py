"""Resident Evil 6 (Xbox 360, Xenia) Mercenaries: the menus interface gbox/mercs_bot.py boots through
(`screen(m)`, `step(scr)`, `wandered(scr)`, `pressed(scr, key)`, `BOOT_KEY`), modelled on re5_ps3 (docs/mercenaries_engine.md).

What RAM can name today (request 3023's partial map, docs/re6-ram-map-0871eee3b68cdea3.json): a round (player 1's uPlayer
through sPlayer 0x83CA52FC +0x28, its Life +0xF20 / LifeMax +0xF22), and the save's Mercenaries masks. The menu state
machine (title, Extra Content, stage page 0x82AD4160, character list 0x82ACFBF8) is NOT yet measured in RAM (no live
session: Xenia opened no window on i9-NUC, jobs 495c71b2439d48ee / f5a8831bef23496e). So `screen()` names the screens it
can prove and takes the rest from `menu_state(m)`, a hook that returns {"where", "cursor"} once a unit/cursor address is
measured; until then out-of-round is "unknown" and the bot only presses BOOT_KEY (never A: on the title, A takes
Campaign). The stage and character picks work blind meanwhile: StagePick / Roster count D-pad presses the Navigator
reports (like RE5's StagePick) and take the cursor from RAM when menu_state provides it.

Round play (the Driver interface): the player uPlayer's position (+0x2C0 vPosition) and yaw (+0x2D4) are read for the
Bot's sight-gated fire and navmesh routing. Five addresses stay unknown (round timer, enemy array, time bonuses, aim
yaw, navmesh root); the Bot degrades gracefully - no timer in snapshots, no enemies listed, no bonuses, no mesh-driven
routing until `configure()` receives them. Firing requires proof of sight: the game's own visible flag when an enemy
entry carries one, else open navmesh floor between player and enemy. No proof = no shot.
"""
from __future__ import annotations

import math
import random
import struct

SPLAYER = 0x83CA52FC                     # sPlayer singleton; +0x28 = player 1's uPlayer
P1 = 0x28
LIFE, LIFE_MAX = 0xF20, 0xF22            # s16 each
SAVE_MGR = 0x83CA4F98                    # save manager; save data = [it] + 0x30
MERC_STAGE_MASK, MERC_CHAR_MASK = 0x974, 0x978
PTR_LO, PTR_HI = 0x40000000, 0xA0000000

# Round gameplay addresses (partially verified; see module note)
S_PLAYER = SPLAYER                        # alias for the round snapshot reader
PL_FIRST = P1                             # player 1's uPlayer offset in sPlayer
PL_POS = 0x2C0                            # vPosition (3 f32)
PL_YAW = 0x2D4                            # facing yaw (f32)
PL_LIFE = LIFE                            # s16 hp

# Unknown addresses (configure() receives them when measured)
ADDR: dict = {
    "timer": None,                        # round timer (f32 or s32)
    "enemy_arr": None,                    # enemy array base
    "enemy_n": None,                      # enemy count
    "time_bonus": None,                   # time bonus array
    "aim_yaw": None,                      # aim yaw (f32)
    "s_ai": None,                         # navmesh root (for re5_nav.read's s_ai)
}

STAGES = ("Urban Chaos", "Steel Beast", "Mining the Depths")          # this disc's three (docs/re6.md)
CHARACTERS = ("Leon", "Helena", "Chris", "Piers", "Jake", "Sherry", "Ada", "Carla", "Agent")   # Mercenaries list order

# Out of a round, the one key that confirms what RAM can't name. START, not A: PRESS START takes only START, and A on the
# title menu would take Campaign (a story game); the notices are pressed through by re6_tool._auto_title.
BOOT_KEY = "start"
STEPS = {"results": "start", "dead": "a", "title": "start", "select_stage": "a", "alert": "a"}
CURSORED = ("select_player",)
MAX_ROW = len(CHARACTERS) - 1

# Bot tuning (mirrors RE5's combat constants)
SIGHT_R = 2500.0                         # max engagement distance (mm)
SIGHT_BEND = 1.4                         # route may bend this much over the straight-line distance
SIGHT_SLACK = 200.0                      # plus this absolute slack (mm)
FLOOR_DY = 400.0                         # vertical separation that rules out a shot (mm)
TURN_TOL = math.radians(4.0)             # dead zone before turning
AIM_TOL = math.radians(6.0)              # must face the target at least this closely to fire
ARRIVE_R = 250.0                         # a waypoint this close is considered reached (mm)


def configure(**addrs) -> None:
    """Set discovered addresses (keys of ADDR); an unknown key raises."""
    for k, v in addrs.items():
        if k not in ADDR:
            raise KeyError(k)
        ADDR[k] = v


def ptr_ok(p: int) -> bool:
    return PTR_LO <= p < PTR_HI and p % 4 == 0


def u32(m, a: int) -> int:
    return struct.unpack(">I", m.rd(a, 4))[0]


def _u32(m, a: int) -> int:
    return struct.unpack(">I", m.rd(a, 4))[0]


def _f32(m, a: int) -> float:
    return struct.unpack(">f", m.rd(a, 4))[0]


def _ok(p: int) -> bool:
    return PTR_LO <= p < PTR_HI and p % 4 == 0


def heading(dx: float, dz: float) -> float:
    """The yaw that faces (dx, dz) in the game's world (XZ plane)."""
    return math.atan2(dx, dz)


def wrap(a: float) -> float:
    """Wrap an angle to (-pi, pi]."""
    while a > math.pi:
        a -= 2.0 * math.pi
    while a <= -math.pi:
        a += 2.0 * math.pi
    return a


def player(m) -> dict | None:
    """Player 1's life from RAM, or None out of a round (no sPlayer / uPlayer yet)."""
    try:
        sp = u32(m, SPLAYER)
        if not ptr_ok(sp):
            return None
        up = u32(m, sp + P1)
        if not ptr_ok(up):
            return None
        hp, hp_max = struct.unpack(">hh", m.rd(up + LIFE, 4))
    except Exception:                                   # noqa: BLE001 - guest memory not mapped yet (boot)
        return None
    return {"hp": hp, "hp_max": hp_max}


def unlocked(m) -> dict | None:
    """The save's Mercenaries masks (stage 10 bits, character + costume 30 bits), when the save is loaded."""
    try:
        sv = u32(m, SAVE_MGR)
        if not ptr_ok(sv):
            return None
        stages, chars = struct.unpack(">II", m.rd(sv + 0x30 + MERC_STAGE_MASK, 8))
    except Exception:                                   # noqa: BLE001
        return None
    return {"stages": stages, "characters": chars}


def menu_state(m) -> dict | None:
    """Hook for the measured menu state machine: {"where": one of title / select_stage / select_player / loading /
    alert / ..., "cursor": int | None}. None until its RAM is measured live (see the module note)."""
    return None


def screen(m, merc=None) -> dict:
    """Where RE6 is: playing / dead from the round's own life; out of a round what menu_state names, else unknown."""
    p = player(m)
    out = {"where": "unknown", "cursor": None, "target": None}
    if p and p["hp_max"] > 0:
        out["where"] = "playing" if p["hp"] > 0 else "dead"
        if out["where"] == "playing" and (ROSTER.pick is not None or ROSTER.round is None):
            out["character"] = ROSTER.started()
        return out
    st = menu_state(m)
    if st and st.get("where"):
        out.update(where=st["where"], cursor=st.get("cursor"))
        if out["where"] == "select_player":
            out["target"] = ROSTER.want()
    return out


class Roster:
    """A random character each round (like RE5's Roster): drawn among those played least, never the one just played.
    With the cursor unread the pick is a count of D-pad rights from the list's start; pressed() counts them."""

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.pick, self.last, self.round = None, None, None
        self.played = {c: 0 for c in CHARACTERS}
        self.left = None                       # blind moves still to make on this visit

    def want(self) -> int:
        if self.pick is None:
            least = min(self.played[c] for c in CHARACTERS if c != self.last)
            pool = [i for i, c in enumerate(CHARACTERS) if self.played[c] == least and c != self.last]
            self.pick = self.rng.choice(pool)
        return self.pick

    def started(self) -> str:
        name = CHARACTERS[self.pick] if self.pick is not None else (self.last or CHARACTERS[0])
        if self.round is None or self.round != name or self.pick is not None:
            self.played[name] += 1
            self.round = name
        self.last, self.pick, self.left = name, None, None
        return name


ROSTER = Roster()


class StagePick:
    """A random stage each visit to the stage page: a random count of D-pad rights (0..2) then A; mercs_bot's Navigator
    reports every press it sends through pressed(), so a press held back never counts."""
    MAX_MOVES = len(STAGES) - 1

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.left = None

    def key(self, scr: dict) -> str:
        if self.left is None:
            self.left = self.rng.randint(0, self.MAX_MOVES)
        return "dright" if self.left > 0 else "a"

    def pressed(self, scr: dict, key: str) -> None:
        if scr.get("where") != "select_stage":
            return
        if key == "dright" and self.left:
            self.left -= 1
        elif key == "a":
            self.left = None


STAGE_PICK = StagePick()


def pressed(scr: dict, key: str) -> None:
    STAGE_PICK.pressed(scr, key)
    if scr.get("where") == "select_player" and scr.get("cursor") is None:
        if key == "dright" and ROSTER.left:
            ROSTER.left -= 1
        elif key == "a":
            ROSTER.left = None                           # taken: started() clears the pick when the round is up


def step(scr: dict) -> str | None:
    """The one press towards the next round: START on the title / results, A on the stage page after the random moves,
    the character row moved to the pick (cursor from RAM, or counted blind) then A, A after a lost round. Nothing on
    a screen RAM can't name (the bot's BOOT_KEY is separate)."""
    where = scr.get("where")
    if where == "select_stage":
        return STAGE_PICK.key(scr)
    if where == "select_player":
        cur, tgt = scr.get("cursor"), scr.get("target")
        if tgt is None:
            return None
        if cur is None:                                  # blind: tgt D-pad rights from the list's first character
            if ROSTER.left is None:
                ROSTER.left = tgt
            return "dright" if ROSTER.left > 0 else "a"
        if cur == tgt:
            return "a"
        return "dright" if cur < tgt else "dleft"
    return STEPS.get(where)


def wandered(scr: dict) -> str | None:
    """A story / other mode: the menu state names a screen that is not the Mercenaries'."""
    where = scr.get("where")
    if where in ("campaign", "story", "agent_hunt", "options"):
        return f"RE6 left The Mercenaries ({where})"
    return None


# ---------------------------------------------------------------------------
# Round gameplay (the Driver interface)
# ---------------------------------------------------------------------------

def snapshot(m) -> dict:
    """The round as the Bot reads it: player pos / hp / yaw, enemies, timer, bonuses. Unknown fields are absent."""
    out: dict = {}
    try:
        sp = _u32(m, S_PLAYER)
        if not _ok(sp):
            return {}
        pl = _u32(m, sp + PL_FIRST)
        if not _ok(pl):
            return {}
        pos = struct.unpack(">3f", m.rd(pl + PL_POS, 12))
        hp, hp_max = struct.unpack(">hh", m.rd(pl + PL_LIFE, 4))
        yaw = _f32(m, pl + PL_YAW)
        out["player"] = {"pos": pos, "hp": hp, "hp_max": hp_max, "rot": yaw}
    except Exception:                                   # noqa: BLE001 - guest memory not mapped yet
        return {}
    # Unknown addresses contribute nothing until configure() receives them.
    if ADDR.get("timer") is not None:
        try:
            out["timer"] = _f32(m, ADDR["timer"])
        except Exception:                               # noqa: BLE001
            pass
    enemies = []
    if ADDR.get("enemy_arr") is not None and ADDR.get("enemy_n") is not None:
        try:
            base = _u32(m, ADDR["enemy_arr"])
            n = _u32(m, ADDR["enemy_n"])
            if _ok(base) and 0 < n <= 64:
                for i in range(n):
                    ep = _u32(m, base + 4 * i)
                    if not _ok(ep):
                        continue
                    epos = struct.unpack(">3f", m.rd(ep + PL_POS, 12))
                    ehp, _ = struct.unpack(">hh", m.rd(ep + PL_LIFE, 4))
                    enemies.append({"pos": epos, "hp": ehp})
        except Exception:                               # noqa: BLE001
            pass
    out["enemies"] = enemies
    bonuses = []
    if ADDR.get("time_bonus") is not None:
        try:
            base = _u32(m, ADDR["time_bonus"])
            if _ok(base):
                for i in range(8):                      # a generous cap; the real count is unknown
                    bp = _u32(m, base + 4 * i)
                    if not _ok(bp):
                        continue
                    bpos = struct.unpack(">3f", m.rd(bp + PL_POS, 12))
                    bonuses.append({"pos": bpos})
        except Exception:                               # noqa: BLE001
            pass
    out["bonuses"] = bonuses
    return out


def own_screen(snap: dict) -> str:
    p = snap.get("player") if snap else None
    if not p:
        return "loading"
    if p["hp"] <= 0:
        return "dead"
    if snap.get("timer") is not None and snap["timer"] <= 0:
        return "results"
    return "playing"


def read_mesh(m, cache: dict | None = None):
    """The navmesh through the unverified s_ai chain, or None while that address is unknown."""
    if ADDR["s_ai"] is None:
        return None
    from . import re5_nav
    return re5_nav.read(m, cache, s_ai=ADDR["s_ai"])


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[2] - b[2])


class Bot:
    def __init__(self, m=None, clock=None, stats=None, mesh=None):
        self.m, self.clock = m, clock
        self.stats = stats if stats is not None else {}
        for k in ("ticks", "shots", "withheld", "walked"):
            self.stats.setdefault(k, 0)
        self._mesh = mesh                # a fixed mesh (tests); else read from RAM on demand
        self._cache: dict = {}
        self._last = None                # (pos) for the heading estimate when the yaw address is unknown
        self._rot = 0.0

    def mesh(self):
        return self._mesh if self._mesh is not None else (read_mesh(self.m, self._cache) if self.m else None)

    def _facing(self, p) -> float:
        if p.get("rot") is not None:
            return p["rot"]
        if self._last is not None and _dist(self._last, p["pos"]) > 5.0:
            self._rot = heading(p["pos"][0] - self._last[0], p["pos"][2] - self._last[2])
        self._last = p["pos"]
        return self._rot

    def sighted(self, p, e, mesh) -> bool:
        """Proof that p can see and shoot e: the game's flag, else open mesh floor between them. No proof = False."""
        if abs(e["pos"][1] - p["pos"][1]) > FLOOR_DY:
            return False
        d = _dist(p["pos"], e["pos"])
        if d > SIGHT_R:
            return False
        if e.get("visible") is not None:
            return e["visible"]
        if mesh is None or not mesh.floor_segment(p["pos"], e["pos"]):
            return False
        r = mesh.route(p["pos"], e["pos"])
        if r is None:
            return False
        length, cur = 0.0, p["pos"]
        for w in r:
            length += _dist(cur, w)
            cur = w
        return length <= d * SIGHT_BEND + SIGHT_SLACK

    def _turn(self, err: float) -> set:
        if abs(err) <= TURN_TOL:
            return set()
        return {"rleft"} if err > 0 else {"rright"}

    def _walk_to(self, p, goal, mesh, rot) -> set:
        route = mesh.route(p["pos"], goal) if mesh is not None else None
        if not route:
            return set()
        wp = route[0]
        if len(route) > 1 and _dist(p["pos"], wp) < ARRIVE_R:
            wp = route[1]
        err = wrap(heading(wp[0] - p["pos"][0], wp[2] - p["pos"][2]) - rot)
        keys = self._turn(err)
        if abs(err) < math.radians(60):
            keys.add("lup")
        self.stats["walked"] += 1
        return keys

    def _route_len(self, mesh, a, b):
        r = mesh.route(a, b) if mesh is not None else None
        if not r:
            return None
        n, cur = 0.0, a
        for w in r:
            n += _dist(cur, w)
            cur = w
        return n

    def tick(self, snap: dict) -> dict:
        self.stats["ticks"] += 1
        p = snap.get("player") if snap else None
        if not p:
            return {"hold": set()}
        if p["hp"] <= 0:
            return {"tap": "a"}
        mesh = self.mesh()
        rot = self._facing(p)
        foes = [e for e in snap.get("enemies", []) if e.get("hp", 1) > 0]
        seen = sorted((e for e in foes if self.sighted(p, e, mesh)), key=lambda e: _dist(p["pos"], e["pos"]))
        if foes and not seen:
            self.stats["withheld"] += 1           # enemies exist, none provably in sight: no shot
        if seen:
            t = seen[0]
            err = wrap(heading(t["pos"][0] - p["pos"][0], t["pos"][2] - p["pos"][2]) - rot)
            keys = {"l2"} | self._turn(err)
            if abs(err) <= AIM_TOL:
                keys.add("r2")
                self.stats["shots"] += 1
            return {"hold": keys}
        for pool in (snap.get("bonuses", []), foes):
            scored = [(self._route_len(mesh, p["pos"], b["pos"]), b) for b in pool]
            scored = [(n, b) for n, b in scored if n is not None]
            if scored:
                return {"hold": self._walk_to(p, min(scored, key=lambda s: s[0])[1]["pos"], mesh, rot)}
        return {"hold": set()}

    def prompt_ok(self, button, snap, now) -> bool:
        return True

    def save(self) -> None:
        pass


class RE6X360:
    map_id = "0871eee3b68cdea3"

    def snapshot(self, m) -> dict:
        return snapshot(m)

    def screen(self, m, snap: dict | None) -> str:
        return own_screen(self.snapshot(m) if snap is None else snap)

    def brain(self, m, stats: dict, clock, learn_dir=None, nav=None):
        return Bot(m, clock=clock, stats=stats)

    def progress(self, snap: dict) -> dict:
        return {"timer": snap.get("timer")}


DRIVER = RE6X360
