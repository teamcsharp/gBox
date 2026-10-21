"""Resident Evil 4 (GameCube G4BE08) Mercenaries autoplay playbook: an "any means necessary" run, played like a game.

setup() applies the hack package through re_mods (Mercenaries unlocked, Leon's loadout = the Hand Cannon at its own
fire rate with x99.9 damage (no explosive rounds: they kept him from firing close), infinite ammo, unlimited health, time pickups x3, combo window x3 and
frozen, every Ganado cloned twice more, the aim's stick speed x3 (a game constant: the aim routine's scale); not full
auto: that restarted the magnum's recoil every 3 frames and bent Leon's arm back over his head). play() then drives
Leon from RAM at ~20 Hz with the pad only, the way a player would
(operator 2026-10-20: "I want the game to be played like a normal game"; "it is unnatural and nightmare fuel"): it
reads Leon and never writes him - no facing, aim pitch or position writes:
  * reads Leon (player em: *0x802B3044, +0x94 position, +0xA4 facing) and every live Ganado (EmMgr 0x8027DF20 slots:
    flags & 0x601 and +0x398 != 0xFF, +0x94 position);
  * steering is closed loop on his real facing: the stick turns him (left = +heading, ~140-230 deg/s measured on the
    Spark; a target behind him: the quick turn, back + B), R aims (the stick then fine-turns, pulsed when close: the
    package sets the game's aim sensitivity x AIM_SPEED_X, ~30 -> ~90 deg/s), A is pressed once per shot once the aim
    is within FIRE_TOL (2 degrees) - the Hand Cannon fires on a press, so A held down fired once and then nothing; the
    aim height the same way: while R is held the stick moves the game's own pitch (+0x258, read) towards the target,
    pulsed when close, and A fires within PITCH_TOL; which stick direction raises it is learned from what a push does
    (an inverted aim setting just flips it);
  * fights any Ganado within ENGAGE;
  * with the disc's level map (gbox.re4_navmap: collision, the stage's item hourglasses, line of sight) it takes the
    reachable Time Bonus hourglasses in the planner's order (exact tour from where the round starts): runs its path
    (Up+B, ~3,300 units/s), pressing A at the fence / window waypoints, and takes each hourglass with A at its stand
    point (they are items: "TAKE"); a Combo Bonus when COMBO_CROWD Ganados are near (every kill in its 30 s scores
    more); then makes its stand: goes after the nearest Ganados; it fires only with a clear line of sight from the gun
    to the head. Without the map: the hourglass events in HOURGLASS, shot from range;
  * a learned map per stage (LearnedMap, saved after every round): every cell Leon walks is floor, the cell ahead of
    him when he runs into something is wall; paths are planned on it (A*) when the disc's level map is not there, so
    every round knows more of the level than the one before (operator 2026-10-20: "with every round that is played,
    the navigation map needs to improve");
  * presses what the screen asks for (operator 2026-10-20: "the characters ignore QTE opportunities ... detect that a
    press A dialogue is being required of them and press it"): prompt() (gbox.screen_prompt.Watcher on the session's
    picture: the button icon RE4 draws for JUMP OVER / JUMP THROUGH / TAKE / KICK / CLIMB / a grab) -> R let go,
    the button pressed, every PROMPT_EVERY s while it shows; a prompt still up after PROMPT_BURST presses in 3 s is
    left alone for PROMPT_REST s;
  * sees his shots (gbox.re4_threats.Shots): a press the gun could fire (35 frames since the last) is a shot; any
    Ganado's health falling, or one starting to die, within HIT_S of it is a hit (the Hand Cannon goes through
    bodies), else a miss (stats shots / hits / misses / kills / accuracy); MISSES_TO_ADJUST misses in a row at a raised
    or lowered target move the aim height to the next PITCH_STEPS offset, a hit keeps it (operator 2026-10-20: "every
    shot ... setting up the zombies to be stunned or eliminating them");
  * shoots only what he can hit (operator 2026-10-20: "shooting into walls near him and blowing himself up"): fires
    inside SHOOT_RANGE, not steeper down than STEEP_DOWN (that is the roof edge in front of him), at any range (no
    explosive rounds, so a point-blank shot is safe); further out he closes in; up on the start roof (HIGH_GROUND
    above the Ganados) he first runs to the edge towards them and jumps down;
  * threats first, from RAM (gbox.re4_threats; operator 2026-10-20: "too often I see Leon just sitting there just
    accepting an attack ... he should be proactive and shoot any attacking enemy", "shoot it out the air", "walking
    out of their attacks"): every tick ranks the Ganados by what their own code is doing - an attack (routine
    r_no_1 in the attack table) by the seconds until its hit frames (read ahead in the motion's event words), a
    weapon thrown at him (em 0x42) by its time to reach him, then the others by distance (dying ones are never
    shot at, knocked-down ones last); the most urgent is shot (lead for its speed; a level shot at the chest), or,
    when it lands before a shot can leave the gun (turn + aim pose + the gun's rate), run out of its reach (the
    quick turn when the way out is behind him; away from walls and other Ganados on the level map) or across a
    thrown weapon's line; two or more on top of him, or one there as he gets up from a hit: out first, then one by
    one. While he is hit or held (his routine 1) the game has him: play() presses SHAKE OFF / the QTE from RAM;
  * blocked while running (moved < STUCK_MOVE in STUCK_S, up and down included: a ladder moves him up, not along):
    taps A ("JUMP OVER" / "CLIMB" prompts), then detours; still blocked after that, backs off for BACK_S and tries the
    other side (no teleports: a position write mid-climb crashed the game with "Invalid read" in its area-event code,
    2026-10-20);
  * a target that soaks 6 s of fire without the combo moving (on a roof, behind a wall) is skipped for 10 s;
  * the Mercenaries clock stops while a prompt is up ("Take the Handgun Ammo?", a time pillar): answer Yes (A);
  * between rounds (results, the Mercenaries title, character / stage select, the briefing) it presses A until the
    next round starts: GAME START, Leon, the first stage, go - the hack package stays in RAM, so every round is
    played the same way and no menu stays on screen.
v1 (2026-10-20, facing writes + teleports): 19 in a row, 24,500 points on the Village; the operator saw Leon stuck at a
fence and aiming with his arm behind him.

Memory comes from Dolphin's shared RAM view (/proc/<pid>/mem on Linux, a whole EmMgr table per read) when available,
else the adapter's read_memory/write_memory. Input goes through the adapter's send_input with gBox pad names.
"""
from __future__ import annotations

import heapq
import json
import math
import os
import struct
import time
from pathlib import Path

try:
    from . import re4_ram_prompts                 # the game's own action-button state: prompts from RAM, vision after
except ImportError:                              # a tree without it: vision only
    re4_ram_prompts = None
from . import re4_threats as threats_ram         # who is attacking right now, what is thrown at him (RAM)

GAME_IDS = {"G4BE08"}
EMMGR, P_PLAYER, P_GLOBAL = 0x8027DF20, 0x802B9780 - 0x673C, 0x802B2280
G_ROOM, MERC_TIMER, MERC = 0x4FA8, 0x80279308, 0x8021392C
G_HP = 0x4FB0                                    # pG+0x4FB0 s16: Leon's health (0 on "You Are Dead")
ENGAGE = 3800.0                                  # Ganados this close are fought, else Leon goes for the time bonuses
TURN_TOL, FIRE_TOL = 0.35, 0.035                 # radians: turn with the stick until within TURN_TOL, aim-turn to FIRE_TOL
AIM_PITCH = 0x258                                # Leon (player em) +0x258: aim pitch, radians, + up (found 2026-10-20);
                                                 # read only: the stick moves it while R is held
HEAD_H, GUN_H, HOURGLASS_H = 1550.0, 1400.0, 900.0   # above the feet: a Ganado's head, Leon's gun, an hourglass
PITCH_MAX, PITCH_AFTER = 0.5, 0.25              # aim no further up / down (radians); read it once R is held this long
PITCH_TOL, PITCH_FINE, PITCH_LIMIT_S = 0.05, 0.15, 0.5   # fire within PITCH_TOL of the head; closer than PITCH_FINE the
                                                         # stick is pulsed; a push that moves nothing this long: the limit
SHOOT_RANGE = 2400.0                             # fire inside this
THREAT_R = 1600.0                                # a Ganado this close is about to strike: him first, before bonuses
PRESS_HOLD, PRESS_GAP = 0.09, 0.22               # the trigger: down this long, then up; a press at most this often
QUICK_TURN_ERR, QUICK_TURN_S = 2.3, 0.9          # a target this far round (radians): the quick turn (back + B), at
                                                 # most once in QUICK_TURN_S
TURN_RATE = 3.0                                  # radians a second, the stick turning him (not aiming)
URGENT_S = 2.5                                   # an attack landing within this is fought (or dodged) before anything
EVADE_S, EVADE_MARGIN = 0.8, 0.15                # run out of a swing this long; dodge when it lands this much sooner
                                                 # than he can shoot
CROWD_R, CROWD_N = 750.0, 2                      # this many Ganados this close: get out, then fight them one by one
AIM_SPEED_X = 3.0                                # the aim's stick speed x3 (re_mods aim_turn_speed: the constant pi at
                                                 # 0x801ED930 the aim routine scales the stick by): ~30 deg/s -> ~90
AIM_FINE = 0.12                                  # aiming, this close to the target (radians): the stick in pulses
EVADE_LOOK = 1500.0                              # a way out is clear this far ahead (the level map, other Ganados)
TURN_COST = 350.0                                # choosing among near ones: a radian to turn costs this many units
RECOVER_S = 1.2                                  # just up from a hit, a Ganado within CROWD_R: out of reach first
                                                 # (operator: "getting slapped on by these people over and over")
ELEV_DY = 600.0                                  # a target this far above / below: raise or lower the aim; else level
REAIM_PITCH = 0.15                               # a level target with the aim still this far up / down: aim again
STEEP_DOWN = -0.5                                # a shot this far down (radians) hits the ledge in front: move instead
HIGH_GROUND = 1500.0                             # Leon this far above the Ganados (the start roof): get down first
TAKE_R, VAULT_R = 450.0, 900.0                   # take an item hourglass this close to its stand point; vault from here
COMBO_CROWD, COMBO_NEAR = 5, 3500.0              # this many Ganados this close: take a combo bonus first (TAS route)
EM_HP = 0x320                                    # Ganado (EmMgr slot) +0x320 s16 health, +0x322 s16 max (found
                                                 # 2026-10-20: 1000 / 1800 at full, falls with hits, 0 at death)
MISSES_TO_ADJUST = 3                             # misses in a row at a raised / lowered target: the next aim height
PITCH_STEPS = (0.0, -0.05, 0.05, -0.1, 0.1, -0.15, 0.15)   # aim-height offsets tried in turn after misses (radians)
CELL = 400.0                                     # the learned map's grid (world units)
STUCK_S, STUCK_MOVE = 0.9, 250.0                 # running but moved less than this in that long (any way): blocked
BACK_S = 0.6                                     # still blocked after a vault and a detour: back off this long
BONUS_MAX = 400.0                                # the clock jumps up to this much for one bonus (time pickups x3: 270 s)
ARRIVE = 650.0                                   # a waypoint this close is reached
COLLECT_R, COLLECT_TRY_S = 1500.0, 4.0           # shoot an hourglass from this close; give up on it after this long
# Village (r400) time bonuses: the room's four small AEV events (live RAM 2026-10-20), (x, z) in world units
HOURGLASS = {0x400: [(19401.0, -6857.0), (-20476.0, -5294.0), (-8452.0, -20283.0), (5592.0, 16384.0)]}
MENU_AFTER, MENU_EVERY = 2.0, 1.5                 # out of a stage this long: press A this often (next round)
TRANSIENT_MAX = 20.0                             # a gap in a live Mercenaries room (grabbed, a pickup) waits this long
PROMPT_EVERY, PROMPT_BURST, PROMPT_REST = 0.6, 3, 5.0   # press a prompt this often; still up after this many presses
                                                       # within 3 s (a TAKE he can't carry): leave it alone this long
MENU_KEYS = ("up", "a")                          # each menu step: up (GAME START, the top stage row), then confirm; no
                                                 # left: Select Player wraps from Leon to Wesker (live 2026-10-20)
PACKAGE = [("mercenaries_unlock", {"on": True}),
           ("merc_loadout", {"character": "leon", "items": ["handcannon", "handcannon ammo:200"], "on": True}),
           ("weapon_mod", {"item": "handcannon", "reset": True, "damage": "99.9"}),   # its own fire rate (see above)
           ("infinite_ammo", {"on": True}), ("unlimited_health", {"on": True}),
           ("merc_time_bonus", {"multiplier": 3}), ("combo_time", {"multiplier": 3}),
           ("combo_freeze", {"on": True}), ("spawn_multiplier", {"count": 3, "on": True}),
           ("aim_turn_speed", {"multiplier": AIM_SPEED_X})]   # the game's aim sensitivity (a constant, not Leon)


def ptr_ok(p: int) -> bool:
    return 0x80000000 <= p < 0x81800000


class ShmMem:
    """Dolphin's 32 MiB MEM1 view in /dev/shm, read through /proc/<pid>/mem (Linux, same user): whole tables per read.
    Read-only. It takes the first Dolphin on this host running the game, so it is for standalone runs with no session;
    a session's playbook reads its own Dolphin (memory(ad))."""

    def __init__(self, game_id: bytes = b"G4BE08"):
        for pid in (p for p in os.listdir("/proc") if p.isdigit()):
            try:
                maps = open(f"/proc/{pid}/maps").read()
            except OSError:
                continue
            for line in maps.splitlines():
                if "/dev/shm/dolphin-emu" not in line:
                    continue
                a, b = (int(x, 16) for x in line.split()[0].split("-"))
                if b - a != 0x2000000:
                    continue
                try:
                    f = open(f"/proc/{pid}/mem", "rb", 0)
                    f.seek(a)
                    if f.read(6) == game_id:
                        self.f, self.base = f, a
                        return
                except OSError:
                    continue
        raise OSError("no Dolphin MEM1 view for this game")

    def rd(self, addr: int, n: int) -> bytes:
        self.f.seek(self.base + (addr & 0x1FFFFFF))
        return self.f.read(n)


class OwnShm:
    """The session's own Dolphin MEM1 (gbox.ram_dump.ShmRam: found only under the session's process, read-only), so two
    RE4 sessions on one host never read each other's game."""

    def __init__(self, ram):
        self.ram = ram

    def rd(self, addr: int, n: int) -> bytes:
        return self.ram.read(0x80000000 | (addr & 0x1FFFFFF), n)


class AdMem:
    def __init__(self, ad):
        self.ad = ad

    def rd(self, addr: int, n: int) -> bytes:
        return bytes(self.ad.read_memory(addr, n))

    def wr(self, addr: int, data: bytes) -> None:
        self.ad.write_memory(addr, data)


def memory(ad):
    """The session's RAM, read-only: its own Dolphin's shared view when it runs on this host, else the adapter's
    read_memory. Without a session (a standalone run), the one Dolphin on this host running the game."""
    if ad is None:
        return ShmMem()
    try:
        from .ram_dump import ShmRam
        ram = ShmRam.find(ad)
        if ram is not None:
            return OwnShm(ram)
    except Exception:                                  # noqa: BLE001 - the adapter's reads still work
        pass
    return AdMem(ad)


def u32(m, a):
    return struct.unpack(">I", m.rd(a, 4))[0]


def snapshot(m) -> dict:
    """room, Merc clock (s), combo, Leon's health, Leon {ptr, pos, rot, pitch, r (his routine bytes)}, live Ganados
    [{slot, pos, hp, hp_max} + gbox.re4_threats.em_fields: r (routine bytes), motion events, frame, ...], the thrown
    weapons in the air [{slot, pos}]."""
    pg = u32(m, P_GLOBAL)
    room = struct.unpack(">H", m.rd(pg + G_ROOM, 2))[0] if ptr_ok(pg) else None
    hp = struct.unpack(">h", m.rd(pg + G_HP, 2))[0] if ptr_ok(pg) else None
    pl = u32(m, P_PLAYER)
    player = None
    if ptr_ok(pl):
        player = {"ptr": pl, "pos": struct.unpack(">3f", m.rd(pl + 0x94, 12)),
                  "rot": struct.unpack(">f", m.rd(pl + 0xA4, 4))[0],
                  "pitch": struct.unpack(">f", m.rd(pl + AIM_PITCH, 4))[0],
                  "r": tuple(m.rd(pl + threats_ram.EM_ROUTINE, 4))}
    base, n, stride = u32(m, EMMGR), u32(m, EMMGR + 4), u32(m, EMMGR + 8)
    enemies, thrown = [], []
    if ptr_ok(base) and 0 < n <= 128 and 0x100 < stride < 0x2000:
        d = m.rd(base, n * stride)
        for k in range(1, n):
            o = k * stride
            if (not (struct.unpack_from(">I", d, o)[0] & 0x601) or d[o + 0x398] == 0xFF
                    or d[o + threats_ram.EM_ID] == threats_ram.THROWN_ID):
                continue
            hp, hp_max = struct.unpack_from(">hh", d, o + EM_HP)
            enemies.append({"slot": k, "pos": struct.unpack_from(">3f", d, o + 0x94), "hp": hp, "hp_max": hp_max,
                            **threats_ram.em_fields(d, o)})
        thrown = threats_ram.thrown(d, n, stride)
    return {"room": room, "hp": hp, "timer": round(u32(m, MERC_TIMER) / 30.0, 1), "combo": u32(m, MERC + 0x28),
            "player": player, "enemies": enemies, "thrown": thrown}


def in_mercenaries(snap: dict) -> bool:
    return snap["room"] is not None and (snap["room"] >> 8) == 4 and snap["player"] is not None


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _navmap():
    """gbox.re4_navmap (the level from the disc: walls, vault edges, hourglasses, paths) when it is installed."""
    try:
        from . import re4_navmap
        return re4_navmap
    except Exception:                                # noqa: BLE001 - straight lines and stuck handling without it
        return None


class LearnedMap:
    """What Leon has learned about one stage, round after round: cells he walked (floor) and cells he ran into (walls).
    path() plans on it with A*: walked cells are cheapest, unknown ones a little dearer, walls are avoided (a cell
    walked far more often than it blocked him is floor again: a Ganado was in the way, not a wall)."""

    def __init__(self, path: Path | None = None):
        self.path_file = path
        self.walked: dict[tuple, int] = {}
        self.blocked: dict[tuple, int] = {}
        if path is not None and path.is_file():
            try:
                d = json.loads(path.read_text())
                self.walked = {(i, j): n for i, j, n in d.get("walked", [])}
                self.blocked = {(i, j): n for i, j, n in d.get("blocked", [])}
            except (OSError, ValueError, TypeError):
                pass

    @staticmethod
    def cell(x: float, z: float) -> tuple:
        return int(math.floor(x / CELL)), int(math.floor(z / CELL))

    def walk(self, x: float, z: float) -> None:
        k = self.cell(x, z)
        self.walked[k] = min(self.walked.get(k, 0) + 1, 10000)

    def block(self, x: float, z: float) -> None:
        k = self.cell(x, z)
        self.blocked[k] = self.blocked.get(k, 0) + 1

    def wall(self, k: tuple) -> bool:
        b = self.blocked.get(k, 0)
        return b > 0 and b * 40 > self.walked.get(k, 0)

    def path(self, start: tuple, goal: tuple) -> list:
        """[(x, z)] waypoints from start to goal round the learned walls; [goal] when nothing is known."""
        a, b = self.cell(*start), self.cell(*goal)
        if not self.blocked or a == b:
            return [goal]
        known = list(self.walked) + list(self.blocked) + [a, b]
        lo_i, hi_i = min(k[0] for k in known) - 6, max(k[0] for k in known) + 6
        lo_j, hi_j = min(k[1] for k in known) - 6, max(k[1] for k in known) + 6
        h = lambda k: math.hypot(k[0] - b[0], k[1] - b[1])        # noqa: E731
        best, came, todo = {a: 0.0}, {}, [(h(a), a)]
        while todo:
            _, k = heapq.heappop(todo)
            if k == b:
                break
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    n = (k[0] + di, k[1] + dj)
                    if n == k or not (lo_i <= n[0] <= hi_i and lo_j <= n[1] <= hi_j) or (self.wall(n) and n != b):
                        continue
                    if di and dj and (self.wall((k[0] + di, k[1])) or self.wall((k[0], k[1] + dj))):
                        continue                                      # no squeezing past a wall corner
                    cost = best[k] + math.hypot(di, dj) * (1.0 if n in self.walked else 1.3)
                    if cost < best.get(n, float("inf")):
                        best[n], came[n] = cost, k
                        heapq.heappush(todo, (cost + h(n), n))
        if b not in came:
            return [goal]
        cells = [b]
        while cells[-1] != a:
            cells.append(came[cells[-1]])
        cells.reverse()
        way, last_dir = [], None                                      # keep only the corners
        for c0, c1 in zip(cells, cells[1:]):
            d = (c1[0] - c0[0], c1[1] - c0[1])
            if d != last_dir and c0 != a:
                way.append(((c0[0] + 0.5) * CELL, (c0[1] + 0.5) * CELL))
            last_dir = d
        return way + [goal]

    def save(self) -> None:
        if self.path_file is None:
            return
        try:
            self.path_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path_file.with_suffix(".tmp")
            tmp.write_text(json.dumps({"cell": CELL, "walked": [[i, j, n] for (i, j), n in self.walked.items()],
                                       "blocked": [[i, j, n] for (i, j), n in self.blocked.items()]}))
            tmp.replace(self.path_file)
        except OSError:
            pass


class Bot:
    """One decision per tick; the caller sends what it returns ({'hold': keys} / {'tap': key}) and sleeps. Pad only:
    the stick turns Leon, R aims, A fires / vaults, B runs."""

    def __init__(self, m, clock=time.time, nav=None, learn_dir: Path | None = None):
        self.m, self.clock = m, clock
        self.nav = nav if nav is not None else _navmap()
        self.learn_dir = learn_dir
        self.learned: LearnedMap | None = None
        self.r_since = None                           # since when the bot has held R (the aim pose is up after a moment)
        self.miss_run, self.pitch_i = 0, 0
        self.pitch_up, self.pitch_key = "up", None    # the stick direction that raises the aim (learned); held last tick
        self.pitch_seen, self.pitch_wrong, self.pitch_push = None, 0, None
        self.reaim_at = float("-inf")                 # when the aim was last lowered to come up level again
        self.st, self.items, self.combos, self.ordered = None, [], [], False
        self.hist: list = []
        self.last_timer, self.timer_since = None, clock()
        self.skip: dict[int, float] = {}
        self.aim = {"slot": None, "since": 0.0, "combo": 0}
        self.room = None
        self.bonus: list = []                         # time bonuses left this round [(x, z)]
        self.goal = None                              # {"pos", "since", "path"} the time bonus Leon is going for
        self.unstick = None                           # {"stage": "detour" | "back", "until", "dir"}
        self.detour_dir = 1
        self.stuck_n = 0
        self.dead = False                              # on the death screen (counted once per death)
        self.tracker = threats_ram.Tracker(m)         # who is attacking, what is thrown (RAM)
        self.shots = threats_ram.Shots()              # every shot scored by the Ganados' health
        self.trigger = {"down": False, "at": float("-inf")}   # A: pressed once per shot (the Hand Cannon is not auto)
        self.evade = None                             # {"slot", "since", "until", "turned"}: getting out of a swing
        self.leon_r0 = 0                              # his routine byte last tick (1: hit / held)
        self.target_slot = None
        self.qturn_at = float("-inf")
        self.recovered_at = float("-inf")              # when he last got up from a hit / a hold
        self._last_enemies: list = []
        self.stats = {"prompts": 0, "max_combo": 0, "vaults": 0, "detours": 0, "backoffs": 0, "time_bonus": 0,
                      "shots_s": 0.0, "learned_walls": 0, "replans": 0, "hits": 0, "misses": 0, "accuracy": 0.0,
                      "pitch_offset": 0.0, "shots": 0, "kills": 0, "hits_taken": 0, "evades": 0,
                      "attacks_seen": 0, "attacks_prevented": 0, "attacks_avoided": 0, "attacks_landed": 0,
                      "thrown_seen": 0, "thrown_shot": 0, "quick_turns": 0}

    # -- the round's time bonuses --
    def _round(self, room):
        if room != self.room:
            if self.learned is not None:
                self.learned.save()
            self.room = room
            self.learned = LearnedMap(self.learn_dir / f"r{room:03x}.json" if self.learn_dir else None)
            self.stats["learned_walls"] = len(self.learned.blocked)
            self.st, self.items, self.combos = None, [], []
            if self.nav is not None:
                try:
                    st = self.nav.stage(f"r{room:03x}")
                    hg = [h for h in st["hourglasses"] if h.get("reachable")]
                    self.st = st
                    self.items = [h for h in hg if h.get("kind") == "time_bonus"]
                    self.combos = [h for h in hg if h.get("kind") == "combo_bonus"]
                except Exception:                     # noqa: BLE001 - no map for this stage: the old way
                    self.st = None
            self.ordered = False
            self.bonus = [] if self.st is not None else list(HOURGLASS.get(room, []))
            self.goal = None

    def _path(self, start, goal):
        if self.st is not None:
            try:
                way = self.nav.path(self.st, start, goal)
                if way:
                    return [(w.x, w.z, w.action) if hasattr(w, "action") else tuple(w) for w in way]
            except Exception:                         # noqa: BLE001
                pass
        elif self.nav is not None and self.room is not None:
            try:
                way = self.nav.path(self.nav.stage(f"r{self.room:03x}"), start, goal)
                if way:
                    return [tuple(w) for w in way]
            except Exception:                         # noqa: BLE001
                pass
        if self.learned is not None:
            return self.learned.path(start[0::2] if len(start) == 3 else start, goal)
        return [goal]

    def _sight(self, p, target_xyz) -> bool:
        """A clear line from Leon's gun to target_xyz on the level map (True without a map)."""
        if self.st is None:
            return True
        try:
            gun = [p["pos"][0], p["pos"][1] + GUN_H, p["pos"][2]]
            return bool(self.nav.sight(self.st, gun, list(target_xyz)))
        except Exception:                             # noqa: BLE001
            return True

    def save(self):
        """Keep what this round taught (the caller calls it between rounds and at the end)."""
        if self.learned is not None:
            self.learned.save()

    # -- steering --
    def _turn(self, err: float, aiming: bool) -> set:
        keys = {"r"} if aiming else set()
        tol = FIRE_TOL if aiming else TURN_TOL
        if abs(err) <= tol:
            self.fine_pulse = False
            return keys
        if aiming and abs(err) < AIM_FINE:            # close: a tick on, a tick off (no overshoot at the faster aim)
            self.fine_pulse = not getattr(self, "fine_pulse", False)
            if not self.fine_pulse:
                return keys
        keys.add("left" if err > 0 else "right")
        return keys

    def _fight(self, p, tgt, now, s) -> dict:
        px, _, pz = p["pos"]
        tx, _, tz = tgt["pos"]
        err = wrap(heading(tx - px, tz - pz) - p["rot"])
        if tgt["slot"] != self.aim["slot"] or s["combo"] != self.aim["combo"]:
            self.aim = {"slot": tgt["slot"], "since": now, "combo": s["combo"]}
        elif now - self.aim["since"] > 6:                              # soaked 6 s of fire: out of reach
            self.skip[tgt["slot"]] = now + 10
            self.aim = {"slot": None, "since": now, "combo": s["combo"]}
            return {"hold": set()}
        dist = math.hypot(tx - px, tz - pz)
        down = math.atan2(tgt["pos"][1] + HEAD_H - (p["pos"][1] + GUN_H), max(dist, 1.0))
        if not tgt.get("thrown"):                                      # (a weapon in the air: shoot it from here)
            if p["pos"][1] - tgt["pos"][1] > HIGH_GROUND or down < STEEP_DOWN:   # up on a roof: get down to them
                self.r_since = None
                return self._go(p, (tx, tz), now)
            if dist > SHOOT_RANGE or not self._sight(p, (tx, tgt["pos"][1] + HEAD_H, tz)):   # can't hit him here
                self.r_since = None
                return self._run_to(p, (tx, tgt["pos"][1], tz), now)
        if abs(err) > TURN_TOL:
            self.r_since = None
            if abs(err) > QUICK_TURN_ERR and now - self.qturn_at > QUICK_TURN_S:   # behind him: the quick turn
                self.qturn_at = now                                             # (back + B), half a second for 180
                self.stats["quick_turns"] += 1
                return {"hold": {"down", "b"}}
            return {"hold": self._turn(err, aiming=False)}               # turn round first (fast)
        self.r_since = now if self.r_since is None else self.r_since
        if tgt.get("thrown") or abs(tgt["pos"][1] - p["pos"][1]) < ELEV_DY:
            if tgt.get("thrown"):                                       # a weapon in the air: at its own height
                height, level = self._aim_height(p, tgt["pos"][1], dist, now)
            else:                                                       # on his level: the gun level, at his chest
                cur = p.get("pitch")
                if (cur is not None and abs(cur) > REAIM_PITCH and now - self.r_since >= PITCH_AFTER
                        and now - self.reaim_at > 1.5):                 # still up from a higher one (the laser over his
                    self.reaim_at, self.r_since = now, None             # head, live 2026-10-20): lower and aim again
                    return {"hold": set()}
                height, level = self._aim_height(p, p["pos"][1] + GUN_H, dist, now, offset=False)
        else:
            height, level = self._aim_height(p, tgt["pos"][1] + HEAD_H, dist, now)   # up / down: the aim by stick
        if abs(err) > FIRE_TOL or not level:
            self.trigger["down"] = False
            return {"hold": self._turn(err, aiming=True) | height}       # aim (pose up), turn and raise onto him
        self.stats["shots_s"] = round(self.stats["shots_s"] + 0.05, 2)
        return {"hold": {"r"} | self._pull(now, tgt)}                    # on target: fire

    def _pull(self, now, tgt) -> set:
        """The trigger: pressed for a moment, then let go (the Hand Cannon fires once per press: A held down fired one
        shot and then nothing, which the old scoring counted as misses). A press the gun can fire is a shot."""
        tr = self.trigger
        if tr["down"]:
            if now - tr["at"] < PRESS_HOLD:
                return {"a"}
            tr["down"] = False
            return set()
        if now - tr["at"] < PRESS_GAP:
            return set()
        tr["down"], tr["at"] = True, now
        if self.shots.press(now):
            self.target_slot = tgt["slot"]
            if tgt.get("thrown"):
                self.stats["thrown_shot"] += 1
        return {"a"}

    # -- combat: the threats first --
    def _ready_in(self, p, t, now) -> float:
        """Seconds until a shot at threat t can leave the gun: the turn (the quick turn for anything behind), the aim
        pose, the gun's own rate."""
        px, _, pz = p["pos"]
        err = abs(wrap(heading(t.pos[0] - px, t.pos[2] - pz) - p["rot"]))
        turn = 0.0 if err <= FIRE_TOL else (0.55 if err > QUICK_TURN_ERR else err / TURN_RATE)
        pose = PITCH_AFTER
        if self.r_since is not None and err <= TURN_TOL:
            pose = max(0.0, PITCH_AFTER - (now - self.r_since))
        gun = max(0.0, self.shots.last_shot + self.shots.GUN_GAP - now)
        return max(turn + pose, gun) + 0.1

    @staticmethod
    def _as_target(t, lead_s: float = 0.0) -> dict:
        """A threat as _fight's target: a Ganado's slot and health, or a thrown weapon (negative slot), at the position
        it will have lead_s from now (on top of the tracker's own lead)."""
        e = dict(t.enemy) if t.kind != "thrown" else {"thrown": True}
        pos = tuple(t.pos[i] + t.vel[i] * lead_s for i in range(3))
        e.update(slot=t.slot if t.kind != "thrown" else -t.slot, pos=pos)
        return e

    def _watch(self, p, s, threats, now):
        """Combat stats from RAM: hits taken (his routine going to 1: hit or held), attacks seen and how they ended:
        prevented (the attacker died in it), avoided (over without a hit), landed (Leon hit while it ran)."""
        r0 = (p.get("r") or (0,))[0]
        if r0 == 1 and self.leon_r0 != 1:
            self.stats["hits_taken"] += 1
        if r0 != 1 and self.leon_r0 == 1:
            self.recovered_at = now                                 # on his feet again: out before the next one
        self.leon_r0 = r0
        for k in ("attacks_seen", "thrown_seen"):
            self.stats[k] = self.tracker.stats[k]
        for k in ("prevented", "avoided", "landed"):                # how each attack ended (re4_threats.Tracker)
            self.stats[f"attacks_{k}"] = self.tracker.stats.get(k, 0)

    def _way_out(self, p, t) -> float:
        """The heading to run: away from the attacker, turned up to 60 degrees towards open ground - no wall in the
        next EVADE_LOOK (the level map's line of sight), no other Ganado near where it leads."""
        px, py, pz = p["pos"]
        away = heading(px - t.pos[0], pz - t.pos[2])
        others = [e["pos"] for e in self._last_enemies if e["slot"] != t.slot and not threats_ram.dying(e)]
        best, best_cost = away, float("inf")
        for turn in (0.0, 0.5, -0.5, 1.0, -1.0):
            h = away + turn
            ex, ez = px + math.sin(h) * EVADE_LOOK, pz + math.cos(h) * EVADE_LOOK
            cost = abs(turn) * 300.0
            if not self._sight(p, (ex, py + GUN_H, ez)):
                cost += 5000.0
            for ox, _, oz in others:
                d = math.hypot(ox - ex, oz - ez)
                if d < 1200.0:
                    cost += 1200.0 - d
            if cost < best_cost:
                best, best_cost = h, cost
        return best

    def _evade(self, p, t, now, side: bool = False) -> dict:
        """Out of the way of an attack he can't stop in time: away from the attacker at a run (the quick turn first
        when the way out is behind him), for EVADE_S; side: across a thrown weapon's line (the side it passes on)."""
        px, _, pz = p["pos"]
        self.r_since = None
        self.trigger["down"] = False
        if self.evade is None or self.evade["slot"] != t.slot or now > self.evade["until"]:
            if side:
                vx, vz = t.vel[0], t.vel[2]
                cross = vx * (pz - t.pos[2]) - vz * (px - t.pos[0])     # which side of its line Leon is on
                away = heading(vz, -vx) if cross < 0 else heading(-vz, vx)
            else:
                away = self._way_out(p, t)
            self.evade = {"slot": t.slot, "since": now, "until": now + EVADE_S, "turned": False, "away": away,
                          "side": side}
            self.stats["evades"] += 1
        return self._run_out(p, now)

    def _run_out(self, p, now) -> dict:
        """The evade under way: the quick turn when the way out is behind him (once), then a run along it."""
        err = wrap(self.evade["away"] - p["rot"])
        if abs(err) > QUICK_TURN_ERR and not self.evade["turned"] and now - self.qturn_at > QUICK_TURN_S:
            self.evade["turned"] = True
            self.qturn_at = now
            self.stats["quick_turns"] += 1
            return {"hold": {"down", "b"}}
        keys = {"up", "b"}
        if err > TURN_TOL / 2:
            keys.add("left")
        elif err < -TURN_TOL / 2:
            keys.add("right")
        return {"hold": keys}

    def _combat(self, p, s, now) -> dict | None:
        """The fight, threats first (operator 2026-10-20: "shoot any attacking enemy to prevent them from attacking
        him", "shoot it out the air", "walking out of their attacks"): a Ganado in an attack (gbox.re4_threats: his
        routine in the attack table, the hit frames by its motion) is shot - the one closest to landing first - or,
        when it lands before a shot can leave the gun, dodged; a thrown weapon coming at him is shot; two or more on
        top of him: get out first. None: no fight here (the route goes on)."""
        threats = self.tracker.update(s, now)
        self._last_enemies = s["enemies"]
        self._watch(p, s, threats, now)
        self._score(s, now)
        if (p.get("r") or (0,))[0] == 1:                             # hit or held: the game has him (play() presses
            self.r_since, self.trigger["down"] = None, False       # SHAKE OFF / the QTE from RAM)
            return {"hold": set()}
        if self.evade and now < self.evade["until"]:                # an evade under way: through, unless the attacker
            t = next((x for x in threats if x.slot == self.evade["slot"] and x.kind != "thrown"), None)   # is gone
            if self.evade["side"] or (t is not None and t.dist < threats_ram.REACH.get(t.kind, 900.0) + 500.0):
                self.r_since, self.trigger["down"] = None, False
                return self._run_out(p, now)
        live = [t for t in threats if self.skip.get(t.slot, float("-inf")) < now or t.kind not in ("near", "down")]
        urgent = [t for t in live if t.kind not in ("near", "down") and t.eta < URGENT_S]
        for t in urgent:
            ready = self._ready_in(p, t, now)
            late = t.eta + EVADE_MARGIN < ready
            if t.kind == "thrown" and late:                       # can't shoot it in time: out of its line
                return self._evade(p, t, now, side=True)
            if t.kind in threats_ram.MELEE and t.dist < threats_ram.REACH.get(t.kind, 900.0) + 300.0 and late:
                return self._evade(p, t, now)                      # it lands first: out of its way
            lead = min(ready, t.eta) if t.kind == "thrown" else 0.0   # a weapon in the air: where it will be
            return self._fight(p, self._as_target(t, lead), now, s)
        close = [t for t in live if t.kind == "near" and t.dist < CROWD_R]
        if len(close) >= CROWD_N or (close and now - self.recovered_at < RECOVER_S):
            return self._evade(p, close[0], now)                    # on top of him / just hit: out, then one by one
        px, _, pz = p["pos"]

        def cost(t):                                           # near, and little to turn: a radian ~ TURN_COST units
            return t.dist + TURN_COST * abs(wrap(heading(t.pos[0] - px, t.pos[2] - pz) - p["rot"]))
        near = sorted((t for t in live if t.kind == "near" and t.dist < THREAT_R), key=cost)
        near += sorted((t for t in live if t.kind == "down" and t.dist < THREAT_R), key=cost)   # knocked down: last
        if near:
            return self._fight(p, self._as_target(near[0]), now, s)
        return None

    def _score(self, s, now):
        """What the shots did (gbox.re4_threats.Shots: a shot hit when a Ganado's health fell or one started dying
        within HIT_S of it). MISSES_TO_ADJUST misses in a row at a raised / lowered target try the next aim-height
        offset (kept while it lands); a level shot at the chest keeps no offset."""
        before = self.shots.stats["misses"], self.shots.stats["hits"]
        self.shots.update(s["enemies"], now)
        misses = self.shots.stats["misses"] - before[0]
        if self.shots.stats["hits"] > before[1]:
            self.miss_run = 0
        self.miss_run += misses
        if self.miss_run >= MISSES_TO_ADJUST:
            self.pitch_i = (self.pitch_i + 1) % len(PITCH_STEPS)
            self.stats["pitch_offset"] = PITCH_STEPS[self.pitch_i]
            self.miss_run = 0
        for k in ("shots", "hits", "misses", "kills", "accuracy"):
            self.stats[k] = self.shots.stats[k]

    def _aim_height(self, p, target_y: float, dist: float, now: float, offset: bool = True) -> tuple[set, bool]:
        """The stick key that moves the aim towards target_y while R is held, and whether the aim is there. Reads the
        game's own pitch (+0x258) and never writes it: the game keeps the pose and its limits. Which direction raises
        it is learned from what the last push did (two contradicting pushes in a row flip it). offset: add the aim
        height learned from misses (not for a level shot at the chest)."""
        cur = p.get("pitch")
        if cur is None or self.r_since is None or now - self.r_since < PITCH_AFTER:
            self.pitch_key, self.pitch_seen, self.pitch_push = None, None, None
            return set(), False                       # the aim pose is not up yet
        want = math.atan2(target_y - (p["pos"][1] + GUN_H), max(dist, 1.0)) + (PITCH_STEPS[self.pitch_i] if offset else 0.0)
        want = max(-PITCH_MAX, min(PITCH_MAX, want))
        seen = self.pitch_seen
        if seen is not None and seen[2] is not None and abs(cur - seen[1]) > 0.004:   # what the last push did
            if (cur > seen[1]) == (seen[2] == self.pitch_up):
                self.pitch_wrong = 0
            else:
                self.pitch_wrong += 1
                if self.pitch_wrong >= 2:             # inverted aim: this stick direction lowers it
                    self.pitch_up, self.pitch_wrong = ("down" if self.pitch_up == "up" else "up"), 0
        err = want - cur
        if abs(err) <= PITCH_TOL:
            self.pitch_key, self.pitch_seen, self.pitch_push = None, (now, cur, None), None
            return set(), True
        key = self.pitch_up if err > 0 else ("down" if self.pitch_up == "up" else "up")
        if self.pitch_push is None or self.pitch_push[2] != key:
            self.pitch_push = (now, cur, key)
        elif now - self.pitch_push[0] > PITCH_LIMIT_S and abs(cur - self.pitch_push[1]) < 0.01:
            self.pitch_key, self.pitch_seen = None, (now, cur, None)
            return set(), True                        # pushing moves nothing: the game's limit, as close as it gets
        if abs(err) < PITCH_FINE and self.pitch_key is not None:
            key = None                                # close: pulse the stick (a tick on, a tick off), no overshoot
        self.pitch_key, self.pitch_seen = key, (now, cur, key)
        return ({key} if key else set()), False

    def _take(self, p, h: dict, now, pool: list) -> dict:
        """Run to an item hourglass's stand point on the map's path and take it with A."""
        px, py, pz = p["pos"]
        sx, sy, sz = h["stand"]
        if not self.goal or self.goal.get("item") is not h:
            self.goal = {"item": h, "pos": (sx, sz), "since": now, "path": self._path((px, py, pz), (sx, sy, sz))}
        if math.hypot(sx - px, sz - pz) < TAKE_R:
            if now - self.goal.setdefault("take_since", now) > COLLECT_TRY_S:  # not taking it: leave it this round
                pool.remove(h)
                self.goal = None
                return {"hold": set()}
            self.r_since = None
            return {"tap": "a"}                                           # TAKE
        return self._follow(p, now)

    def _run_to(self, p, target_xyz, now) -> dict:
        """Close in on a Ganado round the walls (map path, refreshed as he moves) or straight without a map."""
        if self.st is None:
            return self._go(p, (target_xyz[0], target_xyz[2]), now)
        g = self.goal or {}
        if g.get("chase") is None or now - g.get("since", 0) > 1.5:
            self.goal = {"chase": True, "pos": (target_xyz[0], target_xyz[2]), "since": now,
                         "path": self._path(tuple(p["pos"]), tuple(target_xyz))}
        return self._follow(p, now)

    def _follow(self, p, now) -> dict:
        """Run the goal's path: drop waypoints as they are reached, A at a fence / window waypoint."""
        px, _, pz = p["pos"]
        way = self.goal["path"]
        while way:
            w = way[0]
            d = math.hypot(w[0] - px, w[1] - pz)
            if len(w) > 2 and w[2] == "vault" and d < VAULT_R:           # a fence / window: JUMP OVER it first
                way[0] = (w[0], w[1], "vaulted")
                self.stats["vaults"] += 1
                return {"tap": "a"}
            if len(way) > 1 and d < ARRIVE:
                way.pop(0)
                continue
            break
        w = way[0]
        self.r_since = None
        return self._go(p, (w[0], w[1]), now)

    def _go(self, p, goal_xz, now) -> dict:
        px, py, pz = p["pos"]
        if self.unstick and now < self.unstick["until"]:
            if self.unstick["stage"] == "detour":
                return {"hold": {"up", "b", "left" if self.unstick["dir"] > 0 else "right"}}
            if self.unstick["stage"] == "back":
                return {"hold": {"down"}}
        self.unstick = None
        self.hist = [h for h in self.hist if now - h[0] < STUCK_S + 0.3] + [(now, px, py, pz)]
        span = now - self.hist[0][0]
        moved = math.dist((px, py, pz), self.hist[0][1:])                # up a ladder counts: not blocked
        if span >= STUCK_S and moved < STUCK_MOVE:                       # running into something
            self.hist = []
            self.stuck_n += 1
            if self.learned is not None:                                 # learn the wall ahead of him; plan round it
                self.learned.block(px + math.sin(p["rot"]) * CELL * 0.8, pz + math.cos(p["rot"]) * CELL * 0.8)
                self.stats["learned_walls"] = len(self.learned.blocked)
                if self.goal and self.goal.get("pos") and self.st is None:
                    self.goal["path"] = self._path((px, pz), self.goal["pos"])
                    self.stats["replans"] += 1
            if self.stuck_n == 1:
                self.stats["vaults"] += 1
                return {"tap": "a"}                                       # a fence / window: JUMP OVER
            if self.stuck_n % 3 == 0:                                     # a vault and a detour didn't do it: back
                self.unstick = {"stage": "back", "until": now + BACK_S}   # off, then the other side
                self.stats["backoffs"] += 1
                return {"hold": {"down"}}
            self.detour_dir = -self.detour_dir
            self.unstick = {"stage": "detour", "until": now + 0.8, "dir": self.detour_dir}
            self.stats["detours"] += 1
            return {"hold": {"up", "b", "left" if self.detour_dir > 0 else "right"}}
        if span >= STUCK_S and moved > 3 * STUCK_MOVE:
            self.stuck_n = 0                                              # running freely again
        if self.learned is not None:
            self.learned.walk(px, pz)
        gx, gz = goal_xz
        err = wrap(heading(gx - px, gz - pz) - p["rot"])
        keys = {"up", "b"}
        if err > TURN_TOL / 2:
            keys.add("left")
        elif err < -TURN_TOL / 2:
            keys.add("right")
        if abs(err) > 1.6:                                               # behind him: turn on the spot first
            keys -= {"up", "b"}
        return {"hold": keys}

    def tick(self, s: dict) -> dict:
        now, p = self.clock(), s["player"]
        self.stats["max_combo"] = max(self.stats["max_combo"], s["combo"])
        if not p:
            return {"hold": set()}
        self._round(s["room"])
        if s["timer"] != self.last_timer:
            if self.last_timer is not None and self.last_timer > 1 and 5 < s["timer"] - self.last_timer < BONUS_MAX and self.bonus:   # a time bonus (not the next round's clock)
                px, _, pz = p["pos"]
                got = min(self.bonus, key=lambda b: (b[0] - px) ** 2 + (b[1] - pz) ** 2)
                self.bonus.remove(got)
                self.stats["time_bonus"] += 1
                self.goal = None
            elif self.last_timer is not None and self.last_timer > 1 and 5 < s["timer"] - self.last_timer < BONUS_MAX \
                    and (self.items or self.combos):
                px, _, pz = p["pos"]
                pool = self.items + self.combos
                got = min(pool, key=lambda h: (h["stand"][0] - px) ** 2 + (h["stand"][2] - pz) ** 2)
                (self.items if got in self.items else self.combos).remove(got)
                self.stats["time_bonus"] += 1
                self.goal = None
            self.last_timer, self.timer_since = s["timer"], now
            self.dead = False
        elif now - self.timer_since > 1.2 and s["timer"] > 0:           # the clock stopped: a prompt is up
            self.stats["prompts"] += 1
            if s.get("hp") is not None and s["hp"] <= 0:                 # "You Are Dead - Continue Yes / No": Yes
                if not self.dead:
                    self.dead = True
                    self.stats["deaths"] = self.stats.get("deaths", 0) + 1
                return {"tap": "a"}
            return {"tap": "b" if now - self.timer_since > 6 else "a"}
        px, _, pz = p["pos"]
        act = self._combat(p, s, now)                                     # attacks, thrown weapons, a Ganado on him:
        if act is not None:                                               # before any bonus or route
            return act
        pool = [e for e in s["enemies"] if self.skip.get(e["slot"], float("-inf")) < now and not threats_ram.dying(e)]
        near = min(pool, key=lambda e: (e["pos"][0] - px) ** 2 + (e["pos"][2] - pz) ** 2) if pool else None
        dist = math.hypot(near["pos"][0] - px, near["pos"][2] - pz) if near else None
        crowd = sum(1 for e in pool if math.hypot(e["pos"][0] - px, e["pos"][2] - pz) < COMBO_NEAR)
        if self.st is not None and self.combos and crowd >= COMBO_CROWD:     # a combo window while they crowd in
            c = min(self.combos, key=lambda h: math.hypot(h["stand"][0] - px, h["stand"][2] - pz))
            if math.hypot(c["stand"][0] - px, c["stand"][2] - pz) < 2 * COMBO_NEAR:
                return self._take(p, c, now, self.combos)
        if near and dist < ENGAGE:
            return self._fight(p, near, now, s)
        if self.st is not None:
            if self.items and not self.ordered:                            # the round's route: best order from here
                try:
                    order = self.nav.tour(self.st, tuple(p["pos"]), targets=self.items)
                    self.items = [self.items[i] for i in order]
                except Exception:                     # noqa: BLE001
                    pass
                self.ordered = True
            if self.items:
                return self._take(p, self.items[0], now, self.items)
        if self.bonus:                                                    # the time bonuses, nearest first
            if not self.goal or self.goal["pos"] not in self.bonus:
                pos = min(self.bonus, key=lambda b: (b[0] - px) ** 2 + (b[1] - pz) ** 2)
                self.goal = {"pos": pos, "since": now, "path": self._path((px, pz), pos)}
            gx, gz = self.goal["pos"]
            d = math.hypot(gx - px, gz - pz)
            if d < COLLECT_R:                                             # break it: aim at it and fire
                if now - self.goal.setdefault("shoot_since", now) > COLLECT_TRY_S:
                    self.bonus.remove(self.goal["pos"])                  # not breaking: leave it for this round
                    self.goal = None
                    return {"hold": set()}
                err = wrap(heading(gx - px, gz - pz) - p["rot"])
                if abs(err) > TURN_TOL:
                    self.r_since = None
                    return {"hold": self._turn(err, aiming=False)}
                self.r_since = now if self.r_since is None else self.r_since
                height, _ = self._aim_height(p, p["pos"][1] + HOURGLASS_H, d, now)
                return {"hold": {"r", "a"} | (self._turn(err, aiming=True) - {"r"}) | height}
            way = self.goal["path"]
            while len(way) > 1 and math.hypot(way[0][0] - px, way[0][1] - pz) < ARRIVE:
                way.pop(0)
            self.r_since = None
            return self._go(p, way[0], now)
        if near:                                                          # the stand: go and meet them
            self.r_since = None
            return self._go(p, (near["pos"][0], near["pos"][2]), now)
        return {"hold": set()}


def setup(ad) -> list[str]:
    """Apply the hack package (re_mods); returns the ops that failed."""
    from . import re_mods_tool as RM
    g = RM.RE4(ad)
    failed = []
    for op, kw in PACKAGE:
        try:
            RM.run(ad, op, g=g, **kw)
        except Exception as e:                       # noqa: BLE001 - one failed mod never stops the run
            failed.append(f"{op}: {e}")
    return failed


def learn_dir_for(ad) -> Path:
    """Where the learned stage maps live: the worker's runtime folder (or ~/.gbox for a standalone run)."""
    rt = getattr(getattr(ad, "config", None), "runtime", None)
    return (Path(rt) if rt else Path.home() / ".gbox") / "re4_learned"


def play(ad, send, stopped, sleep=time.sleep, m=None, tick_s: float = 0.05, stats: dict | None = None,
         clock=time.time, learn_dir: Path | None = None, rerun=None, prompt=None, ram_prompt=None) -> dict:
    """Drive Leon until stopped(); send(rows) presses keys. Returns the run's stats (stats, when given, is filled live:
    the watch panel shows it): backoffs, prompts, max_combo, combo, timer, rounds, menu_presses.

    The button prompts come from RAM first (ram_prompt: () -> button | None, raising re4_ram_prompts.Unknown when
    RAM can't tell; default: gbox.re4_ram_prompts on m, False = none) and from prompt (vision, gbox.screen_prompt)
    only when RAM fails or can't tell (operator 2026-10-20: "Vision analysis to me should be the last level that we
    have to fall back to"). stats["prompt_source"] says which one answered last."""
    m = m or memory(ad)
    bot, held = Bot(m, clock=clock, learn_dir=learn_dir or learn_dir_for(ad)), set()
    if stats is not None:
        stats.update(bot.stats)
        bot.stats = stats
    bot.stats.update(rounds=1, menu_presses=0)
    out_since, last_press, was_in = None, 0.0, True
    bot.stats["prompt_presses"] = 0
    prompt_taps: list = []                         # times the current prompt was pressed
    prompt_rest = 0.0
    if ram_prompt is None and re4_ram_prompts is not None:
        ram_prompt = re4_ram_prompts.source(m, bot.stats)
    unknown = re4_ram_prompts.Unknown if re4_ram_prompts is not None else LookupError

    def ask():
        """The button the game asks for: RAM (the game's own action state), else vision."""
        if ram_prompt:
            try:
                button = ram_prompt()
                bot.stats["prompt_source"] = "ram"
                return button
            except unknown:
                pass                               # not a state RAM can name: the screen decides
        if prompt is not None:
            bot.stats["prompt_source"] = "vision"
            return prompt()
        return None

    def hold(keys):
        nonlocal held
        rows = [{"key": k, "down": False} for k in sorted(held - keys)] + [{"key": k, "down": True} for k in sorted(keys - held)]
        if rows:
            send(rows)
        held = set(keys)
    while not stopped():
        s = snapshot(m)
        now = clock()
        if not in_mercenaries(s) or s["timer"] <= 0:   # the Result screen (same room, clock at 0), the title, select
            hold(set())
            out_since = out_since or now
            # Leon grabbed / a pickup animation: still the Mercenaries room with time on the clock - not the round's
            # end (a 2 s gap there reran a 49,370 round with 21 s left, 2026-10-20); wait it out
            transient = s["room"] is not None and (s["room"] >> 8) == 4 and s["timer"] > 0.5
            if transient and now - out_since < TRANSIENT_MAX:
                sleep(0.25)
                continue
            if rerun is not None and now - out_since > MENU_AFTER:
                # the menu save state (Select Player, taken before the hooks): load it, hooks back in, character,
                # stage, go - blind A presses walked from the Result screen to the main title and started a story
                # game with the Mercenaries hooks in, which crashed the game (2026-10-20)
                try:
                    rerun()
                    bot.stats["reruns"] = bot.stats.get("reruns", 0) + 1
                except Exception as e:             # noqa: BLE001 - the next pass tries again
                    bot.stats["rerun_error"] = f"{type(e).__name__}: {e}"[:200]
                out_since, last_press = None, clock()
                sleep(1.0)
                continue
            if now - out_since > MENU_AFTER and now - last_press > MENU_EVERY:
                # up before every A: GAME START on the Mercenaries title (a stray "down" from the back-step had put the
                # cursor on EXIT, the presses went on to the main title's START: a story game with the Mercenaries
                # hooks in, which crashed Dolphin, 2026-10-20); Select Player and Select Stage keep the last round's
                # choice (Leon, the Village); harmless on the Result screen and the briefing
                for key in MENU_KEYS:
                    send([{"key": key, "down": True}])
                    sleep(0.12)
                    send([{"key": key, "down": False}])
                    sleep(0.12)
                last_press = clock()
                bot.stats["menu_presses"] += 1
            was_in = False
            sleep(0.25)
            continue
        if not was_in:
            bot.stats["rounds"] += 1
            bot.save()                                 # what the last round taught
            was_in = True
        out_since = None
        bot.stats.update(combo=s["combo"], timer=s["timer"])
        button = ask() if now >= prompt_rest else None
        if button:                                     # the game asks for a button: press it (not aiming: A acts)
            prompt_taps = [t for t in prompt_taps if now - t < 3.0]
            if len(prompt_taps) >= PROMPT_BURST:
                prompt_rest, prompt_taps = now + PROMPT_REST, []
            elif not prompt_taps or now - prompt_taps[-1] >= PROMPT_EVERY:
                hold(set())
                # one button, a QTE's pair pressed together (A+B, L+R), or SHAKE OFF's run of stick flicks and A / B
                chords = re4_ram_prompts.KEYS.get(button, [(button,)]) if re4_ram_prompts is not None else [(button,)]
                for chord in chords:
                    send([{"key": k, "down": True} for k in chord])
                    sleep(0.12 if len(chords) == 1 else 0.06)
                    send([{"key": k, "down": False} for k in chord])
                    if len(chords) > 1:
                        sleep(0.04)
                prompt_taps.append(clock())
                bot.stats["prompt_presses"] += 1
                sleep(0.15)
                continue
        else:
            prompt_taps = []
        act = bot.tick(s)
        if "tap" in act:
            hold(set())
            sleep(0.15)
            send([{"key": act["tap"], "down": True}])
            sleep(0.25)
            send([{"key": act["tap"], "down": False}])
            sleep(0.4)
            continue
        hold(act["hold"])
        sleep(tick_s)
    hold(set())
    bot.save()
    return bot.stats


def matches(ad, g: dict) -> bool:
    """This playbook plays this session: RE4 GameCube NTSC-U in a Mercenaries stage."""
    if g.get("platform") != "gamecube":
        return False
    try:
        m = memory(ad)
        return m.rd(0x80000000, 6).decode("ascii", "replace") in GAME_IDS and in_mercenaries(snapshot(m))
    except Exception:                                # noqa: BLE001
        return False
