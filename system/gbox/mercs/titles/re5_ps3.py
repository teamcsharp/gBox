"""Title #2: Resident Evil 5 Gold Edition, PS3 (BLUS30491, app 01.01) - the Mercenaries driver (The Mercenaries Reunion).

RE5 is MT Framework: the game's managers are singletons whose instance pointers sit next to their class descriptors
(MtDTI) in .bss, so every chain starts at a static address (found live 2026-10-20 on the Spark's RPCS3; the class of
any object comes from its vtable's getDTI: slot 5 returns the MtDTI, whose +4 is the class name):

    sPlayer   [0x017FEB34]   +0x28  -> the player (uPl00ChrisCos4 ...): +0x30 pos (x, y up, z), +0x40 rotation
                                     quaternion (yaw = 2 atan2(qy, qw), the atan2(dx, dz) convention: forward =
                                     (sin, 0, cos)), +0x845 u8 action (0 stand, 1 move / run, 2 aim), +0x1AA0 f32
                                     aim pitch while aiming (radians, + = down), +0x14A4 s16 health, +0x14A6 maximum
    sEnemy    [0x017FDB60]   +0x28 count, +0x34 -> array of enemy pointers (uEm10 / uEm11 Majini ...): +0x30 pos,
                                     +0x40 rotation, +0x14A4 s16 health, +0x14A6 maximum (Majini 800, 700)
    sBioMain  [0x0191CEE4]   +0x182D4 -> cGameSys: +0x3E0 f32 seconds left, +0x3E4 f32 the round's start time,
                                     +0x3F4 s32 kills, +0x3FC s32 combo, +0x404 f32 combo window left, +0x418 s32 score
    sActionButton [0x017B7174], sItem [0x017FE574], sUnit [0x0191D700], sBioPad [0x0191CF38]

Controls (Type D, the game's default here; gBox pad names = PS3 buttons, gbox.adapters.RPCS3_KEYPAD): left stick
moves / strafes (lup ...), right stick turns (rleft = larger heading, rright = smaller; while aiming it turns ~30 deg/s
and raises / lowers the aim: rup = up), L1 = ready the weapon, L1 + R1 = fire, L2 + R1 = knife, up + cross = run,
L1 + cross = reload. Measured live: the stick turns ~150 deg/s, walking ~145 units/s (world units are cm).
"""
from __future__ import annotations

import math
import struct
import time

from ..driver import Driver

S_PLAYER, S_ENEMY, S_MAIN = 0x017FEB34, 0x017FDB60, 0x0191CEE4
S_ACTION, S_ITEM, S_UNIT = 0x017B7174, 0x017FE574, 0x0191D700
S_CAMERA, CAM_CTRL, CAM_EYE, CAM_AT = 0x0191CA6C, 0x104, 0x30, 0x50   # sBioCamera +0x104 -> uCameraCtrl: eye, look-at
MAIN_GAMESYS = 0x182D4
P_POS, P_ROT, P_PITCH, P_ACTION, P_HP = 0x30, 0x40, 0x1AA0, 0x845, 0x14A4
E_POS, E_HP = 0x30, 0x14A4
GS_TIMER, GS_START, GS_KILLS, GS_COMBO, GS_COMBO_T, GS_SCORE = 0x3E0, 0x3E4, 0x3F4, 0x3FC, 0x404, 0x418
MAX_ENEMIES = 64
ACTIONS = {0: "stand", 1: "move", 2: "aim", 5: "hit"}

HEAD_H, GUN_H = 160.0, 140.0           # above the feet: a Majini's head, the player's gun (cm)
ENGAGE, SHOOT_RANGE, TOO_CLOSE = 3000.0, 2200.0, 110.0
BODY_R = 35.0                          # half a body: a shot inside atan(BODY_R / dist) hits
TURN_TOL = math.radians(12)            # turn with the stick (not aiming) until within this
AIM_TOL, PITCH_TOL = math.radians(2.5), math.radians(2.5)   # fire inside these
FINE = math.radians(6)                 # closer than this: pulse the stick (a tick on, a tick off)
MAX_DY = 450.0                         # targets this far above / below are out of reach (rooftops): not chosen
STUCK_S, STUCK_MOVE = 1.0, 60.0


def ptr_ok(p) -> bool:
    return isinstance(p, int) and 0x30000000 <= p < 0x40000000


def u32(m, a) -> int:
    return struct.unpack(">I", m.rd(a, 4))[0]


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


def yaw_of(q) -> float:
    """The quaternion (x, y, z, w) about +y -> heading (atan2(dx, dz) convention)."""
    return wrap(2.0 * math.atan2(q[1], q[3]))


def snapshot(m) -> dict:
    """The round from RAM: the player, the enemies, the Mercenaries counters (None where a pointer is not there)."""
    snap: dict = {"player": None, "enemies": [], "timer": None, "timer_start": None, "score": None, "kills": None,
                  "combo": None, "combo_timer": None}
    sp = u32(m, S_PLAYER)
    p = u32(m, sp + 0x28) if ptr_ok(sp) else 0
    if ptr_ok(p):
        pos = struct.unpack(">3f", m.rd(p + P_POS, 12))
        rot = struct.unpack(">4f", m.rd(p + P_ROT, 16))
        pitch = -struct.unpack(">f", m.rd(p + P_PITCH, 4))[0]        # + = up
        hp, hp_max = struct.unpack(">hh", m.rd(p + P_HP, 4))
        action = m.rd(p + P_ACTION, 1)[0]
        snap["player"] = {"ptr": p, "pos": pos, "rot": wrap(yaw_of(rot)), "pitch": pitch, "action": action,
                          "state": ACTIONS.get(action, action), "hp": hp, "hp_max": hp_max}
    se = u32(m, S_ENEMY)
    if ptr_ok(se):
        n, arr = u32(m, se + 0x28), u32(m, se + 0x34)
        if ptr_ok(arr) and 0 < n <= MAX_ENEMIES:
            ptrs = struct.unpack(f">{n}I", m.rd(arr, 4 * n))
            for slot, e in enumerate(ptrs):
                if not ptr_ok(e):
                    continue
                pos = struct.unpack(">3f", m.rd(e + E_POS, 12))
                hp, hp_max = struct.unpack(">hh", m.rd(e + E_HP, 4))
                snap["enemies"].append({"slot": slot, "ptr": e, "pos": pos, "hp": hp, "hp_max": hp_max})
    cm = u32(m, S_CAMERA)
    cc = u32(m, cm + CAM_CTRL) if ptr_ok(cm) else 0
    if ptr_ok(cc):
        snap["camera"] = {"eye": struct.unpack(">3f", m.rd(cc + CAM_EYE, 12)),
                          "at": struct.unpack(">3f", m.rd(cc + CAM_AT, 12))}
    main = u32(m, S_MAIN)
    gs = u32(m, main + MAIN_GAMESYS) if ptr_ok(main) else 0
    if ptr_ok(gs):
        t, t0 = struct.unpack(">2f", m.rd(gs + GS_TIMER, 8))
        snap.update(timer=round(t, 2), timer_start=t0, kills=struct.unpack(">i", m.rd(gs + GS_KILLS, 4))[0],
                    combo=struct.unpack(">i", m.rd(gs + GS_COMBO, 4))[0],
                    combo_timer=round(struct.unpack(">f", m.rd(gs + GS_COMBO_T, 4))[0], 2),
                    score=struct.unpack(">i", m.rd(gs + GS_SCORE, 4))[0])
    return snap


MENU_KEYS = ("start", "cross")         # results: START (OK); stage / character select: cross; "Continue?": cross = Yes


def menu_key(n: int) -> str:
    """The n-th press that walks Reunion's screens back into a round when RAM says no round is up: START and cross in
    turn (live 2026-10-20: START leaves the results screen and does nothing on the selects; cross picks the stage and
    the character - the last ones played - and does nothing on the results), so a press never wanders off."""
    return MENU_KEYS[n % len(MENU_KEYS)]


def own_screen(snap: dict) -> str:
    """playing / dead / results / loading from the round's fields: the player present with health and time left =
    playing; health 0 = dead ("You Are Dead - Continue?"); time 0 = results; no player = loading or menus."""
    p = snap.get("player")
    if not p:
        return "loading"
    if p.get("hp") is not None and p["hp"] <= 0:
        return "dead"
    if (snap.get("timer") or 0) <= 0:
        return "results"
    return "playing"


class Bot:
    """One decision per tick from the snapshot: turn to the nearest Majini with the right stick, ready the gun (L1),
    raise / lower the laser onto his head with the right stick (closed loop on the game's own aim point), fire (R1)
    inside AIM_TOL / PITCH_TOL; back off one that is too close; walk to the next one when nobody is in range.
    Reads only; presses only (gBox pad names)."""

    def __init__(self, m=None, clock=time.time, stats: dict | None = None):
        self.m, self.clock = m, clock
        self.stats = stats if stats is not None else {}
        for k in ("shots_s", "hits", "kills_seen", "max_combo", "turns", "backoffs", "stuck"):
            self.stats.setdefault(k, 0)
        self.target = None
        self.aiming_since = None
        self.pulse = 0
        self.hist: list = []
        self.hp_seen: dict = {}
        self.unstick_until = 0.0
        self.unstick_dir = 1
        self.dead_tap = 0.0

    # --- the engine's brain interface ---
    def prompt_ok(self, button, snap, now) -> bool:
        return True

    def save(self):
        pass

    def tick(self, snap: dict) -> dict:
        now = self.clock()
        p = snap.get("player")
        self.stats["max_combo"] = max(self.stats["max_combo"], snap.get("combo") or 0)
        if not p:
            return {"hold": set()}
        if p.get("hp") is not None and p["hp"] <= 0:        # "You Are Dead - Continue? Yes / No": Yes (cross)
            if now - self.dead_tap > 1.5:
                self.dead_tap = now
                self.stats["deaths_continued"] = self.stats.get("deaths_continued", 0) + 1
                return {"tap": "cross"}
            return {"hold": set()}
        self._score_hits(snap)
        # Majini and the like: alive, more than 1 health (crows are "enemies" with 1), not far above or below
        live = [e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0 and (e.get("hp_max") or 0) > 1
                and abs(e["pos"][1] - p["pos"][1]) < MAX_DY]
        if not live:
            self.aiming_since = None
            return {"hold": set()}
        px, py, pz = p["pos"]
        tgt = min(live, key=lambda e: self._cost(p, e))
        tx, ty, tz = tgt["pos"]
        dist = math.hypot(tx - px, tz - pz)
        want = heading(tx - px, tz - pz)
        if dist > ENGAGE:                                   # nobody near: walk toward the nearest
            self.aiming_since = None
            return {"hold": self._walk(p, want, now)}
        aiming = p.get("action") == 2
        if dist < TOO_CLOSE and not aiming:                 # on top of him: a step back while facing him
            self.aiming_since = None
            self.stats["backoffs"] += 1
            return {"hold": {"ldown"} | self._turn(wrap(want - p["rot"]), aiming=False)}
        if not aiming:
            err = wrap(want - p["rot"])
            if abs(err) > TURN_TOL:                         # turn round first (fast, not aiming)
                self.aiming_since = None
                self.stats["turns"] += 1
                return {"hold": self._turn(err, aiming=False)}
            self.aiming_since = self.aiming_since or now
            return {"hold": {"l1"}}                         # ready the gun; the aim pose comes up
        # aiming: close the loop on the crosshair - the camera's look ray (over the shoulder, along the aim) - onto
        # his head; without a camera, on the body's heading and the player's own pitch value
        cam = snap.get("camera")
        if cam:
            (ex, ey, ez), (cx, cy, cz) = cam["eye"], cam["at"]
            look_yaw = heading(cx - ex, cz - ez)
            look_pitch = math.atan2(cy - ey, max(math.hypot(cx - ex, cz - ez), 1e-3))
            tgt_pitch = math.atan2(ty + HEAD_H - ey, max(math.hypot(tx - ex, tz - ez), 1.0))
            yaw_err = wrap(heading(tx - ex, tz - ez) - look_yaw)
            pitch_err = tgt_pitch - look_pitch
        else:
            tgt_pitch = math.atan2(ty + HEAD_H - (py + GUN_H), max(dist, 1.0))
            yaw_err = wrap(want - p["rot"])
            pitch_err = tgt_pitch - (p.get("pitch") or 0.0)
        keys = {"l1"} | self._turn(yaw_err, aiming=True)
        if abs(pitch_err) > PITCH_TOL:
            close = abs(pitch_err) < FINE
            self.pulse ^= 1
            if not close or self.pulse:
                keys.add("rup" if pitch_err > 0 else "rdown")
        tol = max(AIM_TOL, math.atan2(BODY_R, max(dist, 1.0)))   # close up the body is wide
        if abs(yaw_err) <= tol and abs(pitch_err) <= max(PITCH_TOL * 2, tol) and dist <= SHOOT_RANGE:
            keys.add("r1")                                  # on him: fire
            self.stats["shots_s"] = round(self.stats["shots_s"] + 0.05, 2)
        self.target = tgt["slot"]
        self.stats["aim"] = (f"slot {tgt['slot']} d {dist:.0f} dy {ty - py:+.0f} yaw_err {math.degrees(yaw_err):+.1f} "
                             f"pitch {math.degrees(p.get('pitch') or 0):+.1f} want {math.degrees(tgt_pitch):+.1f} "
                             f"keys {','.join(sorted(keys))}")
        return {"hold": keys}

    # --- helpers ---
    @staticmethod
    def _cost(p, e) -> float:
        px, _, pz = p["pos"]
        d = math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
        off = abs(wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - p["rot"]))
        return d * (1.0 + off / math.pi)                    # near and in front first

    def _turn(self, err: float, aiming: bool) -> set:
        tol = AIM_TOL if aiming else TURN_TOL
        if abs(err) <= tol:
            return set()
        if abs(err) < FINE:                                 # close: pulse, no overshoot
            self.pulse ^= 1
            if not self.pulse:
                return set()
        return {"rleft"} if err > 0 else {"rright"}         # left = larger heading (measured)

    def _walk(self, p, want: float, now: float) -> set:
        px, py, pz = p["pos"]
        if now < self.unstick_until:
            return {"lup", "cross", "lleft" if self.unstick_dir > 0 else "lright"}
        self.hist = [h for h in self.hist if now - h[0] < STUCK_S + 0.3] + [(now, px, pz)]
        if now - self.hist[0][0] >= STUCK_S and math.hypot(px - self.hist[0][1], pz - self.hist[0][2]) < STUCK_MOVE:
            self.hist, self.unstick_dir = [], -self.unstick_dir
            self.unstick_until = now + 0.8
            self.stats["stuck"] += 1
        err = wrap(want - p["rot"])
        keys = self._turn(err, aiming=False)
        if abs(err) < math.radians(60):
            keys |= {"lup", "cross"}                        # run (up + cross)
        return keys

    def _score_hits(self, snap):
        for e in snap.get("enemies") or ():
            prev = self.hp_seen.get(e["ptr"])
            if prev is not None and e["hp"] < prev:
                self.stats["hits"] += 1
                if e["hp"] <= 0 < prev:
                    self.stats["kills_seen"] += 1
            self.hp_seen[e["ptr"]] = e["hp"]


class RE5PS3(Driver):
    map_id = "BLUS30491"

    def snapshot(self, m) -> dict:
        return snapshot(m)

    def screen(self, m, snap: dict | None) -> str:
        return own_screen(self.snapshot(m) if snap is None else snap)

    def brain(self, m, stats: dict, clock, learn_dir=None, nav=None):
        return Bot(m, clock=clock, stats=stats)

    def progress(self, snap: dict) -> dict:
        return {"timer": snap.get("timer"), "combo": snap.get("combo"), "score": snap.get("score"),
                "kills": snap.get("kills")}


DRIVER = RE5PS3
