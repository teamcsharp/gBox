"""RE5 Switch flash grenades when he is overwhelmed, then a bomb at his heels and out (operator 2026-10-27 21:0x: "Have
them throw flashbangs all the time ... If they're overwhelmed, have them just throw flashbangs in order to just disarm
and get out of the situation ... use flashbangs to disarm them and work their way through with melee"; 21:1x: "they
need to throw flash grenades and then drop mines and leave the area" - never stay to shoot it out).

The supply: re5_switch_mods.flash_loadout puts the flash grenade x5 (0x108, WP08 GRENADE_FLASH) on a D-pad grid of every
Mercenaries loadout (Chris (BSAA): grid 7, D-pad down); infinite_ammo's no-ammo flag on WP08 keeps the stack (so the
count does not fall on a throw: the throw is read from the motion and the hand flag).

Overwhelmed (OVER_*): OVER_N or more Majini on his level within OVER_R, one of those winding up (re5_switch.Bot._winding:
the grab's lunge, the swings, the attack flag), or his health falling within HURT_S with HURT_N within OVER_R. Then, at
most once every GAP_S after the last cycle ended (the operator wants them "all the time"):
  neutral  the pad rests NEUTRAL_S (the trigger let go: an item is never in hand with ZR held, the RE6 lesson)
  equip    the flash's D-pad grid, until its slot's hand flag (EQUIP_S, else given up)
  face     with them on one side (their unit vectors' mean over FACE_SIDE) the body turns to their centre first
           (FACE_S at most); all round: at his feet (the flash does not hurt the player)
  aim      ZL held AIM_S, the aim's pitch (P_AIM_PITCH, + = down) pushed toward the centre's elevation or FEET_PITCH
  throw    ZL + ZR one tick, then everything let go; confirmed by the throw's motion or the flash leaving his hand
           within THROW_S (flashes; else flash_unconfirmed - he leaves all the same)
  leave    the push-through (pushthroughs): a run (B) through the widest gap among the Majini NOT flashed (the flashed
           ones: alive within FLASH_R of him at the throw, for STUN_S), toward the nearest standing statue when it lies
           in that gap; the flashed ones in his way show the game's melee prompt, which re5_switch's prompt reader
           presses ahead of everything (flash_melees counts the ones taken on a flashed Majini)
  bomb     once nobody stands within MINE_CLEAR_R and he is MINE_AFTER_CM from where he threw (a Majini within ~1 m
           sets a bomb off, and its blast took 700 of his 1000 at 3.8 m): the bomb's D-pad grid, ZL tapped PRESS_S,
           confirmed by a new uWp0a near him, the count, or the placing motion (flash_mines); handed to re5_switch_mines
           (its blast guard and spacing); none clear within LEAVE_MAX_S: no bomb this time (flash_mine_skips)
  away     out of the bomb's blast through the widest gap, the bomb counted among the Majini (AWAY_CM / AWAY_S)
  rearm    the gun back by its D-pad grid - the shotgun first, then an automatic, then a magnum - before the fight's ZL
Bot tuning, not decoded game values: OVER_*, FLASH_R, STUN_S, the pitches. MOTION_THROW is the shot / placing motion
byte (the egg and the bomb share it); the motions of the flashed Majini a second after a throw go to stats
flash_motions, to learn their stunned motion. Counters: flashes, flash_attempts, flash_unconfirmed, flash_aborts,
flash_melees, flash_mines, flash_mine_skips, pushthroughs, overwhelmed_s.
"""
from __future__ import annotations

import collections
import math

FLASH_ID, BOMB_ID = 0x108, 0x10A
QUICK = {1: "dup", 3: "dleft", 5: "dright", 7: "ddown"}
RUN = ("b", "lup")
KNIVES = frozenset({0x01, 0x0E, 0x14, 0x23, 0x24})
THROWN = frozenset({0x06, 0x07, 0x08, 0x0A})
GUN_ORDER = ("shotgun", "automatic", "magnum")       # the gun back after the cycle (re5_weapons families)
OVER_N, OVER_R, HURT_N, HURT_S, LEVEL_DY = 3, 300.0, 2, 1.0, 120.0
GAP_S = 1.5
NEUTRAL_S, EQUIP_S = 0.2, 1.0
FACE_SIDE, FACE_ERR, FACE_S = 0.5, math.radians(50), 0.4
AIM_S, PITCH_TOL, FEET_PITCH, FAR_PITCH, MUZZLE_H = 0.35, 0.08, 0.9, 0.3, 140.0
THROW_S, MOTION_THROW = 1.0, 29
MOTION_UP = frozenset({22, 24, 26})                  # the item coming up / raised (not a throw yet)
FLASH_R, STUN_S = 600.0, 5.0
SENSE_R, TURN_DEAD, STATUE_R = 800.0, math.radians(15), 2500.0
MINE_CLEAR_R, MINE_AFTER_CM, MINE_SPACING_CM, LEAVE_MAX_S = 250.0, 150.0, 600.0, 3.0
PRESS_S, PLACE_S, SETTLE_S, CONFIRM_CM, MOTION_PLACE = 0.25, 1.5, 1.6, 200.0, 29
AWAY_CM, AWAY_S, REARM_S, REARM_TAP_S, CYCLE_MAX_S = 800.0, 3.0, 1.5, 0.6, 12.0
LABEL_BREAK_FREE = 28                                # a grab's prompt: never a melee
COUNTERS = ("flashes", "flash_attempts", "flash_unconfirmed", "flash_aborts", "flash_melees", "flash_mines",
            "flash_mine_skips", "pushthroughs", "overwhelmed_s")


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


def flat(a, b) -> float:
    return math.hypot(b[0] - a[0], b[2] - a[2])


def stack(inv, idw) -> dict | None:
    """The item's live slot on a D-pad grid (the no-ammo flag keeps its rounds above 0)."""
    return next((s for s in inv or () if s.get("id") == idw and (s.get("rounds") or 0) > 0
                 and s.get("grid") in QUICK), None)


def key(e):
    return e.get("ptr", e.get("slot"))


class Nades:
    """The flash cycle (the module doc): tick() returns this tick's pad action while a cycle runs or one starts, None
    otherwise; watch() runs every tick whatever the bot decided (the health falls, the melee prompts, the motions)."""

    def __init__(self, stats: dict):
        self.stats = stats
        self.state, self.t, self.c = "idle", 0.0, None
        self.last_end = -1e9                         # when the last cycle ended (GAP_S)
        self.flashed: set = set()                    # the Majini the last flash caught
        self.flash_at = None                         # when it was thrown (confirmed or not)
        self._hp, self._hp_fall_at = None, -1e9
        self._over_t, self._melee_btn, self._motions_due = None, None, None
        for k in COUNTERS:
            self.stats.setdefault(k, 0)

    def new_round(self, now: float) -> None:
        self.state, self.t, self.c, self.last_end = "idle", now, None, -1e9
        self.flashed, self.flash_at, self._hp, self._motions_due = set(), None, None, None

    # --- every tick ----------------------------------------------------------------------------------------------
    def watch(self, p: dict, snap: dict, now: float) -> None:
        hp = p.get("hp")
        if type(hp) is int and type(self._hp) is int and hp < self._hp:
            self._hp_fall_at = now
        self._hp = hp
        pr = snap.get("prompt")
        if pr and self.flash_at is not None and now - self.flash_at <= STUN_S and pr.get("label") != LABEL_BREAK_FREE \
                and (pr.get("owner") in self.flashed or pr.get("target") in self.flashed):
            if pr.get("button") != self._melee_btn:      # a melee prompt on a flashed Majini (the prompt reader takes it)
                self._melee_btn = pr.get("button")
                self.stats["flash_melees"] += 1
        elif not pr:
            self._melee_btn = None
        if self._motions_due is not None and now >= self._motions_due:
            self._motions_due = None
            seen = collections.Counter(e.get("motion") for e in snap.get("enemies") or ()
                                       if key(e) in self.flashed and (e.get("hp") or 0) > 0)
            self.stats["flash_motions"] = " ".join(f"{m}:{n}" for m, n in seen.most_common(6))

    def overwhelmed(self, p: dict, live: list, now: float, winding=None) -> str | None:
        py = p["pos"][1]
        near = [e for e in live if flat(p["pos"], e["pos"]) <= OVER_R and abs(e["pos"][1] - py) <= LEVEL_DY]
        if len(near) >= OVER_N:
            return f"{len(near)} within {OVER_R / 100:.0f} m"
        if winding is not None and any(winding(e) for e in near):
            return "one winding up within %.0f m" % (OVER_R / 100)
        if len(near) >= HURT_N and now - self._hp_fall_at <= HURT_S:
            return f"hit with {len(near)} within {OVER_R / 100:.0f} m"
        return None

    # --- the cycle -----------------------------------------------------------------------------------------------
    def tick(self, p: dict, snap: dict, live: list, now: float, *, busy: bool = False, winding=None,
             mines=None) -> dict | None:
        inv = snap.get("inventory") or ()
        why = self.overwhelmed(p, live, now, winding)
        dt = 0.0 if self._over_t is None else max(0.0, min(now - self._over_t, 0.25))
        self._over_t = now
        if why:
            self.stats["overwhelmed_s"] = round(self.stats["overwhelmed_s"] + dt, 2)
        flash = stack(inv, FLASH_ID)
        if self.state == "idle":
            if why is None or busy or flash is None or now - self.last_end < GAP_S \
                    or (mines is not None and mines.state != "idle"):
                return None
            held = next((s for s in inv if s.get("hand")), None)
            self.c = {"since": now, "origin": tuple(p["pos"]), "why": why, "confirmed": False, "throw_t": None,
                      "site": None, "tap_at": -1e9}
            self.stats["flash_attempts"] += 1
            self._go("neutral", now, f"overwhelmed ({why}): the flash")
            if flash.get("hand") and not (held and held.get("type") == 1 and held.get("item") not in THROWN):
                self.state = "face"
            return {"hold": ()}
        c = self.c
        if now - c["since"] > CYCLE_MAX_S and self.state not in ("rearm",):
            self.stats["flash_aborts"] += 1
            self._go("rearm", now, "the cycle ran too long: the gun back")
        if self.state == "neutral":
            if now - self.t < NEUTRAL_S:
                return {"hold": ()}
            if flash is None:
                return self._abort(now, "no flash on a D-pad grid")
            if flash.get("hand"):
                self._go("face", now, "the flash in hand")
            else:
                self._go("equip", now, "the flash's D-pad grid")
                return {"tap": QUICK[flash["grid"]]}
        if self.state == "equip":
            if flash is not None and flash.get("hand"):
                self._go("face", now, "the flash in hand")
            elif now - self.t > EQUIP_S:
                return self._abort(now, "the flash did not come to hand")
            else:
                return {"hold": ()}
        if self.state == "face":
            err, want = self._aim_at(p, live)
            if err is not None and abs(err) > FACE_ERR and now - self.t < FACE_S:
                return {"hold": (("rleft",) if err > 0 else ("rright",))}
            c["pitch"] = want
            self._go("aim", now, "the flash raised")
        if self.state == "aim":
            if flash is None or not flash.get("hand"):
                return self._abort(now, "the flash left his hand before the throw")   # never ZR without it
            if now - self.t < AIM_S:
                keys = ["zl"]
                ap = p.get("aim_pitch")
                if ap is None or ap < c["pitch"] - PITCH_TOL:
                    keys.append("rdown")
                elif ap > c["pitch"] + PITCH_TOL:
                    keys.append("rup")
                return {"hold": tuple(keys)}
            c["throw_t"] = now
            self.flash_at = now
            self.flashed = {key(e) for e in snap.get("enemies") or ()
                            if (e.get("hp") or 0) > 0 and flat(p["pos"], e["pos"]) <= FLASH_R}
            self._motions_due = now + 1.0
            self._go("throw", now, f"the flash thrown ({c['why']})")
            return {"hold": ("zl", "zr")}
        if self.state == "throw":                   # everything let go at once: no item raised with a trigger down
            self.stats["pushthroughs"] += 1
            self._go("leave", now, "through the gap")
            return {"hold": ()}
        if c["throw_t"] is not None and c["confirmed"] is False:
            left = flash is None or not flash.get("hand")
            if p.get("motion") == MOTION_THROW or left:
                c["confirmed"] = True
                self.stats["flashes"] += 1
            elif now - c["throw_t"] > THROW_S:
                c["confirmed"] = None                   # (counted once; he leaves all the same)
                self.stats["flash_unconfirmed"] += 1
        if self.state == "leave":
            bomb = stack(inv, BOMB_ID)
            mine_on = mines is None or getattr(mines, "enabled", True)
            spaced = mines is None or all(flat(p["pos"], b) >= MINE_SPACING_CM for b in mines.bombs.values())
            clear = not any(flat(p["pos"], e["pos"]) < MINE_CLEAR_R for e in live)
            if bomb is not None and mine_on and spaced and clear and now - c["throw_t"] >= 0.3 \
                    and flat(c["origin"], p["pos"]) >= MINE_AFTER_CM:
                self._go("bomb_equip", now, "clear of them: a bomb at his heels")
                if not bomb.get("hand"):
                    return {"tap": QUICK[bomb["grid"]]}
            elif now - self.t > LEAVE_MAX_S:
                if bomb is not None and mine_on:
                    self.stats["flash_mine_skips"] += 1
                self._go("rearm", now, "out of the crowd: the gun back")
            else:
                return self._run(p, live, snap, None, now)
        if self.state == "bomb_equip":
            bomb = stack(inv, BOMB_ID)
            if bomb is not None and bomb.get("hand"):
                c.update(count0=bomb.get("rounds"), ground0={g["ptr"] for g in snap.get("ground_mines") or ()},
                         site=tuple(p["pos"]), saw=False)
                self._go("bomb_place", now, "the bomb down")
                return {"hold": ("zl",)}
            if now - self.t > EQUIP_S or any(flat(p["pos"], e["pos"]) < MINE_CLEAR_R * 0.6 for e in live):
                self.stats["flash_mine_skips"] += 1
                self._go("away", now, "no bomb this time: on out")
                return self._run(p, live, snap, None, now)
            return {"hold": ()}
        if self.state == "bomb_place":
            bomb = stack(inv, BOMB_ID)
            c["saw"] = c["saw"] or p.get("motion") == MOTION_PLACE
            spent = bomb is None or (c.get("count0") is not None and (bomb.get("rounds") or 0) < c["count0"])
            new = [g for g in snap.get("ground_mines") or ()
                   if g["ptr"] not in c["ground0"] and flat(c["site"], g["pos"]) <= CONFIRM_CM]
            if spent or new or (c["saw"] and now - self.t >= PLACE_S * 0.5):
                self.stats["flash_mines"] += 1
                if new:
                    c["site"] = tuple(new[0]["pos"])
                if mines is not None:                   # the mines module's blast guard and spacing know it
                    if new:
                        mines.bombs[new[0]["ptr"]] = c["site"]
                    mines.last_at, mines.last_pos = now, c["site"]
                self._go("settle", now, "the bomb down: out of its blast")
                return {"hold": ()}
            if now - self.t > PLACE_S:
                self.stats["flash_mine_skips"] += 1
                self._go("away", now, "the bomb unconfirmed: out all the same")
                return self._run(p, live, snap, c["site"], now)
            return {"hold": ("zl",)} if now - self.t < PRESS_S else {"hold": ()}
        if self.state == "settle":                  # the placing motion: he cannot move until it ends
            if p.get("motion") == MOTION_PLACE and now - self.t < SETTLE_S:
                return {"hold": ()}
            self._go("away", now, "out of the bomb's blast")
        if self.state == "away":
            site = c.get("site")
            if (site is not None and flat(p["pos"], site) >= AWAY_CM) or now - self.t > AWAY_S:
                self._go("rearm", now, "the gun back")
            else:
                return self._run(p, live, snap, site, now)
        if self.state == "rearm":
            gun = self._gun(inv)
            if gun is None or gun.get("hand") or now - self.t > REARM_S:
                self.state, self.c, self.last_end = "idle", None, now
                return None
            if now - self.t < 0.25 or now - c["tap_at"] < REARM_TAP_S:
                return {"hold": ()}                     # a neutral pad before the D-pad
            c["tap_at"] = now
            return {"tap": QUICK[gun["grid"]]}
        return None

    # --- helpers -------------------------------------------------------------------------------------------------
    def _go(self, state: str, now: float, status: str) -> None:
        self.state, self.t = state, now
        self.stats["flash_status"] = f"{state}: {status}"

    def _abort(self, now: float, why: str) -> dict:
        self.stats["flash_aborts"] += 1
        self._go("rearm", now, why)
        return {"hold": ()}

    @staticmethod
    def _gun(inv) -> dict | None:
        """The gun back after the cycle: the shotgun first, then an automatic, then a magnum, else any on a D-pad grid."""
        from . import re5_weapons
        guns = [s for s in inv or () if s.get("type") == 1 and s.get("grid") in QUICK
                and s.get("item") not in KNIVES and s.get("item") not in THROWN]
        fam = lambda s: getattr(re5_weapons.WEAPONS.get(s.get("item")), "family", None)
        return min(guns, key=lambda s: GUN_ORDER.index(fam(s)) if fam(s) in GUN_ORDER else len(GUN_ORDER), default=None)

    @staticmethod
    def _aim_at(p: dict, live: list) -> tuple:
        """(the body's turn to their centre or None for all round, the throw's pitch): their unit vectors' mean length
        over FACE_SIDE is one side (the centre's elevation from the muzzle), else at his feet."""
        pos = p["pos"]
        near = [e for e in live if flat(pos, e["pos"]) <= OVER_R + 100.0 and abs(e["pos"][1] - pos[1]) <= LEVEL_DY]
        if not near:
            return None, FEET_PITCH
        vx = sum((e["pos"][0] - pos[0]) / max(flat(pos, e["pos"]), 1.0) for e in near) / len(near)
        vz = sum((e["pos"][2] - pos[2]) / max(flat(pos, e["pos"]), 1.0) for e in near) / len(near)
        if math.hypot(vx, vz) < FACE_SIDE:
            return None, FEET_PITCH
        cx = sum(e["pos"][0] for e in near) / len(near)
        cz = sum(e["pos"][2] for e in near) / len(near)
        d = math.hypot(cx - pos[0], cz - pos[2])
        return wrap(heading(vx, vz) - p["rot"]), max(FAR_PITCH, min(FEET_PITCH, math.atan2(MUZZLE_H, max(d, 1.0))))

    def _run(self, p: dict, live: list, snap: dict, site, now: float) -> dict:
        """B + the stick through the widest gap among the Majini not flashed (and the bomb at site), toward the nearest
        statue when it lies in that gap; nobody to avoid: the statue, else away from the flashed ones' centre."""
        pos = p["pos"]
        stunned = self.flash_at is not None and now - self.flash_at <= STUN_S
        foes = [e for e in live if flat(pos, e["pos"]) < SENSE_R and abs(e["pos"][1] - pos[1]) <= LEVEL_DY
                and not (stunned and key(e) in self.flashed)]
        bear = sorted(heading(e["pos"][0] - pos[0], e["pos"][2] - pos[2]) for e in foes)
        if site is not None and flat(pos, site) > 1.0:
            bear = sorted(bear + [heading(site[0] - pos[0], site[2] - pos[2])])
        statues = [b["pos"] for b in snap.get("bonuses") or () if b.get("pos") and flat(pos, b["pos"]) <= STATUE_R]
        statue = min(statues, key=lambda s: flat(pos, s), default=None)
        sb = heading(statue[0] - pos[0], statue[2] - pos[2]) if statue is not None else None
        if bear:
            gaps = [((bear[(i + 1) % len(bear)] - a) % (2 * math.pi) or 2 * math.pi, a) for i, a in enumerate(bear)]
            gap, start = max(gaps)
            out = wrap(start + gap / 2)
            if sb is not None and 0.25 * gap <= (sb - start) % (2 * math.pi) <= 0.75 * gap:
                out = sb                                 # the statue lies well inside the gap: there
        elif sb is not None:
            out = sb
        else:
            crowd = [e for e in live if key(e) in self.flashed and flat(pos, e["pos"]) < SENSE_R]
            if crowd:
                cx = sum(e["pos"][0] for e in crowd) / len(crowd)
                cz = sum(e["pos"][2] for e in crowd) / len(crowd)
                out = heading(pos[0] - cx, pos[2] - cz)
            else:
                out = p["rot"]
        err = wrap(out - p["rot"])
        turn = () if abs(err) < TURN_DEAD else (("rleft",) if err > 0 else ("rright",))
        return {"hold": RUN + turn}
