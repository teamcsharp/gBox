"""RE5 Switch weapon mastery (operator 2026-11-09: "Any weapon that I choose to equip the bot with, I need the bot able to
masterfully use that. So if I choose to have the bot use rotten eggs or a bow and arrow, they need to be able to spam
fire that"): one controller per family on synthetic snapshots - the spam measured as trigger edges (shots / throws /
swings) per second while a target is in the weapon's band - the operator's weapon kept in hand, the per-family stats,
the raise-flicker regression (413 raises in 28 s live), and the per-weapon rate mods (egg_rate / bow_rate)."""
import math
import struct

import pytest

from gbox import merc_live_controls as LC
from gbox.mercs.titles import re5_switch as R
from gbox.mercs.titles import re5_switch_aim as A
from gbox.mercs.titles import re5_switch_mods as SM
from gbox.mercs.titles import re5_weapons as W

PTR = 0x5D00001000


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    monkeypatch.setattr(R, "MINES", False)
    monkeypatch.setattr(R, "CALM", False)


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def row(item, *, grid=3, hand=True, rounds=5, slot=0, kind=1):
    return {"slot": slot, "id": (kind << 8) | item, "type": kind, "item": item, "rounds": rounds, "cap": 5,
            "grid": grid, "hand": hand}


class Sim:
    """A synthetic round: the right stick turns him (160 deg/s with the stance down, 40 deg/s aimed) and the camera
    pitch (40 deg/s), ZL held is the aimed stance (motion 26), the left stick walks him (the game's own physics are not
    modelled: this measures the controller's inputs, never damage or the game's real fire rate)."""

    def __init__(self, inv, enemies, *, laser=None, cam=True, extra=None, rot=0.0, pos=(0.0, 0.0, 0.0), hz=30.0):
        self.inv, self.enemies, self.laser, self.cam, self.extra = inv, list(enemies), laser, cam, extra or {}
        self.rot, self.pitch, self.pos, self.hz, self.kills = rot, 0.0, pos, hz, 0
        self.hp = {10 + i: 800 for i in range(len(self.enemies))}
        self.clock = [0.0]
        self.bot = R.Bot(stats={}, clock=lambda: self.clock[0])
        self.ticks, self.where, self.aimed = [], [], False
        self.motion = None                           # a forced motion byte (else 26 aimed / 0)

    def snap(self):
        s = {"player": {"ptr": PTR, "generation": 1, "pos": self.pos, "rot": self.rot, "hp": 1000, "hp_max": 1000,
                        "motion": self.motion if self.motion is not None else (26 if self.aimed else 0),
                        "aim_pitch": -self.pitch},
             "enemies": [{"ptr": 10 + i, "pos": e, "hp": self.hp[10 + i], "hp_max": 800}
                         for i, e in enumerate(self.enemies)],
             "inventory": [dict(r) for r in self.inv], "kills": self.kills, "mercenaries_phase": R.PHASE_PLAYING,
             "laser": self.laser(self) if callable(self.laser) else
             (self.laser or {"from": (0.0, 0.0, 0.0), "at": (0.0, 0.0, 0.0), "up": False})}
        if self.cam:
            s["aim_cam"] = {"player": PTR, "generation": 1, "pitch": self.pitch, "heading": self.rot}
        s.update(self.extra)
        return s

    def step(self):
        act = self.bot.tick(self.snap())
        hold = set(act.get("hold") or ())
        dt = 1.0 / self.hz
        self.aimed = "zl" in hold
        turn = math.radians(40.0 if self.aimed else 160.0) * dt
        self.rot = R.wrap(self.rot + (turn if "rleft" in hold else -turn if "rright" in hold else 0.0))
        self.pitch += math.radians(40.0) * dt * ((1 if "rup" in hold else 0) - (1 if "rdown" in hold else 0))
        fwd = (1 if "lup" in hold else 0) - (1 if "ldown" in hold else 0)
        side = (1 if "lleft" in hold else 0) - (1 if "lright" in hold else 0)
        if not self.aimed and "l" not in hold and (fwd or side):      # he walks only with the weapon down
            v = (450.0 if "b" in hold else 300.0) * dt / math.hypot(fwd, side)
            h, left = self.rot, self.rot + math.pi / 2
            self.pos = (self.pos[0] + v * (fwd * math.sin(h) + side * math.sin(left)), self.pos[1],
                        self.pos[2] + v * (fwd * math.cos(h) + side * math.cos(left)))
        self.ticks.append((self.clock[0], hold, act.get("tap"), self.bot.doing))
        self.where.append(self.pos)
        self.clock[0] = round(self.clock[0] + dt, 6)
        return hold

    def run(self, seconds):
        for _ in range(int(round(seconds * self.hz))):
            self.step()
        return self

    def edges(self, since=0.0, key="zr"):
        n, last = 0, False
        for t, hold, _tap, _d in self.ticks:
            on = key in hold
            if on and not last and t >= since:
                n += 1
            last = on
        return n

    def share(self, key, since=0.0):
        rows = [h for t, h, _tap, _d in self.ticks if t >= since]
        return sum(1 for h in rows if key in h) / max(len(rows), 1)


def rate(sim, since, seconds):
    return sim.edges(since) / seconds


# --- the raise flicker -----------------------------------------------------------------------------------------------
def test_reposition_step_no_longer_raises_the_gun_every_tick():
    """Live 2026-11-09 (Ancient Ruins, the first 28 s): 413 raises - keep_active's 0.65 s step put the gun down every
    tick and the crowd fire raised it again the next. A shotgun, three within 5 m, the dot on none of them (the aim
    stalls, the step runs): before the fix this scene counted 41 raises in 3 s (13.7 a second); now one per stalled
    acquisition, and no ZL on the pad while the step moves him."""
    crowd = [at(250, 40), at(350, 60), at(300, -100)]
    sim = Sim([row(0x04, grid=5)], crowd, laser={"from": (0.0, 140.0, 30.0), "at": (0.0, 140.0, 400.0), "up": True})
    sim.motion = 26
    for _ in range(90):                                  # (his aim never turns here: the dot stays off them, it stalls)
        sim.bot.tick(sim.snap())
        sim.clock[0] = round(sim.clock[0] + 1 / 30, 6)
    st = sim.bot.stats
    assert st["aim_repositions"] >= 1 and st["raise_holds"] > 0
    assert st["raises"] <= 4, st["raises"]


def test_during_the_step_the_pad_moves_him_with_the_gun_down_every_tick():
    crowd = [at(250, 40), at(350, 60), at(300, -100)]
    laser = {"from": (0.0, 140.0, 30.0), "at": (0.0, 140.0, 400.0), "up": True}
    clock = [0.0]
    bot = R.Bot(stats={}, clock=lambda: clock[0])
    stepping, raises_at = [], []
    for i in range(60):
        clock[0] = i / 30.0
        s = {"player": {"ptr": PTR, "generation": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000,
                        "motion": 26}, "enemies": [{"ptr": 10 + k, "pos": e, "hp": 800, "hp_max": 800}
                                                   for k, e in enumerate(crowd)],
             "inventory": [row(0x04, grid=5)], "kills": 0, "laser": laser}
        before = bot.stats.get("raises", 0)
        act = bot.tick(s)
        if bot.stats.get("raises", 0) > before:
            raises_at.append(clock[0])
        if bot.doing == "escape":
            stepping.append(set(act["hold"]))
    assert stepping and all("zl" not in h and h & {"lup", "ldown", "lleft", "lright"} for h in stepping)
    window = max(sum(1 for t in raises_at if t0 <= t < t0 + 1.0) for t0 in raises_at)
    assert window <= 2                                   # the flicker was ~15 a second


# --- the longbow -----------------------------------------------------------------------------------------------------
def test_the_longbow_spams_arrows_while_aligned_and_never_lowers_between_them():
    sim = Sim([row(0x0F)], [at(800, 10), at(900, 14)]).run(3.0)
    st = sim.bot.stats
    assert st["raises"] == 1                             # up once, kept up: no flicker
    assert sim.share("zl", since=0.5) == 1.0
    assert rate(sim, 1.0, 2.0) >= 10.0                   # a fresh ZR edge every second tick (15/s at 30 Hz)
    assert st["wm_bow_shots_per_s"] >= 10.0 and st["wm_bow_range_s"] > 2.5
    assert "longbow" in st["wm_controller"] and st["wm_gate"].startswith("longbow")


def test_the_longbow_never_presses_before_it_is_aligned():
    sim = Sim([row(0x0F)], [at(800, 30)])                # 30 deg off: the stance up, the aim turning onto him
    rots = []
    for _ in range(60):
        rots.append(sim.rot)
        sim.step()
    tol = W.fire_tol(W.MASTERY["bow"], 800.0)
    want = R.heading(*at(800, 30)[::2])
    for (t, hold, _tap, _d), rot in zip(sim.ticks, rots):
        if "zr" in hold:
            assert abs(R.wrap(want - rot)) <= tol + 1e-6
    assert sim.edges() > 0


def test_the_longbow_reaims_between_arrows_when_he_moves():
    sim = Sim([row(0x0F)], [at(800, 0)]).run(1.5)
    first = sim.edges()
    sim.enemies[0] = at(800, 25)                         # he steps aside: off the window
    sim.run(0.3)
    assert any("rleft" in h for t, h, _tap, _d in sim.ticks if t >= 1.5)   # the aim follows him
    sim.run(1.5)
    assert sim.edges(since=2.2) >= 8 and sim.edges() > first
    assert abs(R.wrap(R.heading(sim.enemies[0][0], sim.enemies[0][2]) - sim.rot)) < math.radians(5)


def test_no_floor_corridor_is_a_soft_preference_not_a_silent_bow():
    """What kept the bow silent: the corridor requirement. A mesh that knows no floor line to him still lets him fire;
    with two Majini the one with a corridor costs less."""
    class Mesh:
        def floor_segment(self, a, b):
            return b[0] > 0.0                            # the one on his left has no corridor
    sim = Sim([row(0x0F)], [at(800, 5)], extra={"nav": Mesh()})
    sim.enemies = [at(800, -5)]
    sim.run(2.0)
    assert sim.edges(since=0.5) >= 10                    # no corridor: still arrows
    ok, why = W.bow_fire_policy(0x0F, corridor=False, aligned=True, loaded=True)
    assert ok and "soft preference" in why and "cover unconfirmed" in why
    assert not W.bow_fire_policy(0x0F, corridor=True, aligned=True, loaded=True, wall=True)[0]
    bot = R.Bot(stats={}, clock=lambda: 0.0)
    bot._item, bot._mesh = 0x0F, Mesh()
    p = {"pos": (0.0, 0.0, 0.0), "rot": 0.0}
    with_corridor = {"ptr": 1, "pos": at(800, 5), "hp": 800, "hp_max": 800}
    without = {"ptr": 2, "pos": at(800, -5), "hp": 800, "hp_max": 800}
    assert bot._kcost(p, with_corridor, 0.0) < bot._kcost(p, without, 0.0)


# --- rotten eggs and grenades ------------------------------------------------------------------------------------------
def test_rotten_eggs_are_thrown_at_the_crowds_centre_as_fast_as_the_throw_takes_a_press():
    crowd = [at(600, -10), at(650, 0), at(700, 10), at(600, 30)]
    sim = Sim([row(0x36)], crowd).run(3.0)
    st = sim.bot.stats
    assert st["raises"] == 1 and rate(sim, 1.0, 2.0) >= 10.0
    assert st["wm_egg_shots_per_s"] >= 10.0
    centre, n = W.crowd_point(crowd[0], [{"pos": e, "hp": 1} for e in crowd])
    assert n >= 3
    assert abs(R.wrap(R.heading(centre[0], centre[2]) - sim.rot)) <= math.radians(6)   # the centre, not the nearest
    assert sim.pitch > 0.0                               # lofted for the arc


@pytest.mark.parametrize("item", [0x06, 0x07])
def test_explosive_grenades_are_thrown_at_range_and_never_inside_their_own_blast(item):
    far = Sim([row(item, grid=1)], [at(900, 0), at(950, 8), at(1000, -6)], extra={"preferred_weapon": {"item": item}})
    far.run(2.5)
    assert rate(far, 1.0, 1.5) >= 10.0
    crowd = [at(300, 0), at(320, 15)]
    near = Sim([row(item, grid=1)], crowd, extra={"preferred_weapon": {"item": item}}).run(3.0)
    centre = W.crowd_point(crowd[0], [{"pos": e, "hp": 1} for e in crowd])[0]
    assert near.ticks[0][3] == "backoff" and near.bot.stats["wm_thrown_backoffs"] > 10
    assert all(h & {"lup", "ldown", "lleft", "lright"} for t, h, _tap, d in near.ticks if d == "backoff")   # moving
    for (t, hold, _tap, _d), pos in zip(near.ticks, near.where):
        if "zr" in hold:                                 # never a throw into his own blast: out first, then throws
            assert math.hypot(centre[0] - pos[0], centre[2] - pos[2]) >= W.MASTERY["thrown"].blast_cm
    assert near.edges() > 0


def test_a_flash_grenade_has_no_self_blast_and_goes_at_a_close_crowd():
    sim = Sim([row(0x08, grid=1)], [at(300, 0), at(320, 15)], extra={"preferred_weapon": {"item": 0x08}}).run(2.0)
    assert rate(sim, 0.8, 1.2) >= 10.0


# --- the launchers ---------------------------------------------------------------------------------------------------
def _dot_on(target):
    def laser(sim):
        if not sim.aimed:
            return {"from": (0.0, 0.0, 0.0), "at": (0.0, 0.0, 0.0), "up": False}
        e = target(sim)
        jitter = 0.5 * (len(sim.ticks) % 3)              # a live laser never reads twice the same (RAY_STALE_S)
        return {"from": (0.0, 140.0, 30.0), "at": (e[0] + jitter, e[1] + R.CHEST_H, e[2]), "up": True}
    return laser


def test_the_grenade_launcher_fires_into_the_crowd_from_beyond_its_blast():
    crowd = [at(900, 0), at(950, 5), at(1000, -5)]
    sim = Sim([row(0x0C)], crowd, laser=_dot_on(lambda s: s.enemies[0])).run(2.5)
    assert rate(sim, 1.0, 1.5) >= 10.0 and sim.bot.stats["wm_launcher_shots"] >= 15


def test_a_launcher_dot_on_a_wall_inside_the_blast_holds_the_trigger():
    wall = lambda s: {"from": (0.0, 140.0, 30.0), "at": (0.0, 140.0, 200.0), "up": True} if s.aimed else \
        {"from": (0.0, 0.0, 0.0), "at": (0.0, 0.0, 0.0), "up": False}
    sim = Sim([row(0x0C)], [at(900, 0), at(950, 5)], laser=wall).run(2.0)
    assert sim.edges() == 0                              # the impact would be 1.7 m from him


def test_the_rocket_launcher_steps_out_of_its_seven_metre_blast_first():
    sim = Sim([row(0x0D)], [at(500, 0), at(520, 10)]).run(0.5)
    assert sim.edges() == 0 and sim.bot.stats["wm_rocket_backoffs"] > 10 and sim.where[-1][2] < -50.0   # backing out
    far = Sim([row(0x0D)], [at(1500, 0), at(1550, 5)]).run(2.0)
    assert rate(far, 0.8, 1.2) >= 10.0


# --- melee and the flamethrower --------------------------------------------------------------------------------------
@pytest.mark.parametrize("item", [0x01, 0x22])
def test_knife_and_stun_rod_swing_in_contact_and_close_in_otherwise(item):
    sim = Sim([row(item, grid=9)], [at(120, 3)], extra={"preferred_weapon": {"item": item}}).run(2.0)
    assert sim.share("l", since=0.2) == 1.0 and rate(sim, 0.5, 1.5) >= 10.0
    far = Sim([row(item, grid=9)], [at(600, 0)], extra={"preferred_weapon": {"item": item}}).run(0.5)
    assert far.edges() == 0 and all("lup" in h for t, h, _tap, d in far.ticks if d == "walk")
    assert any(d == "walk" for t, h, _tap, d in far.ticks)


def test_the_flamethrower_is_held_at_short_range_and_closes_in_from_beyond():
    sim = Sim([row(0x21)], [at(300, 2), at(330, -4)]).run(2.0)
    assert sim.share("zr", since=0.5) >= 0.95 and sim.edges() == 1   # held, one long burst
    assert sim.bot.stats["wm_flame_trigger_s"] >= 1.7
    far = Sim([row(0x21)], [at(800, 0)]).run(0.5)
    assert far.edges() == 0 and any("lup" in h for t, h, _tap, d in far.ticks)


# --- the laser guns ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("item,dist", [(0x02, 600), (0x0B, 600), (0x13, 600), (0x04, 500), (0x05, 1200)])
def test_hitscan_guns_hold_the_trigger_while_the_dot_is_on_him(item, dist):
    sim = Sim([row(item)], [at(dist, 0)], cam=False, laser=_dot_on(lambda s: s.enemies[0])).run(2.0)
    assert sim.bot.stats["raises"] == 1
    assert sim.share("zr", since=0.5) >= 0.9             # a held trigger: the gun's own pace x fire_rate
    fam = W.WEAPONS[item].family
    assert sim.bot.stats[f"wm_{fam}_range_s"] > 1.5 and sim.bot.stats[f"wm_{fam}_trigger_s"] >= 1.5


def _feedback_bot(item, target, laser_at, now=1.0):
    bot = R.Bot(stats={}, clock=lambda: now)
    bot.aim_since, bot.target, bot.doing = 0.0, 10, "fire"
    snap = {"player": {"ptr": PTR, "generation": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000,
                       "motion": 26},
            "enemies": [{"ptr": 10, "pos": target, "hp": 800, "hp_max": 800}],
            "inventory": [row(item)], "aim_cam": {"player": PTR, "generation": 1, "pitch": 0.0, "heading": 0.0},
            "laser": {"from": (0.0, 140.0, 30.0), "at": laser_at, "up": True}}
    return bot, snap


def test_a_shotgun_point_blank_into_the_crowd_counts_as_contact_but_never_through_a_wall():
    target = at(200, 0)
    beside = (math.sin(math.radians(14)) * 600, 120.0, 30 + math.cos(math.radians(14)) * 600)   # past him, 14 deg off
    bot, snap = _feedback_bot(0x04, target, beside)
    out = A.apply(bot, snap, {"hold": ("zl", "zr")}, 1.0)
    assert "zr" in out["hold"] and bot.stats["target_feedback_gate"] == "shotgun point blank"
    bot, snap = _feedback_bot(0x04, target, (10.0, 140.0, 90.0))   # the ray stops 0.6 m out: a wall, not him
    assert "zr" not in A.apply(bot, snap, {"hold": ("zl", "zr")}, 1.0)["hold"]
    bot, snap = _feedback_bot(0x02, target, beside)                # a handgun gets no such window
    assert "zr" not in A.apply(bot, snap, {"hold": ("zl", "zr")}, 1.0)["hold"]


def test_an_automatic_is_held_through_its_burst_for_a_bounded_moment():
    target = at(300, 0)
    chest = (target[0], R.CHEST_H, target[2])
    bot, snap = _feedback_bot(0x13, target, chest)
    assert "zr" in A.apply(bot, snap, {"hold": ("zl", "zr")}, 1.0)["hold"]          # on the body
    off = (math.sin(math.radians(9)) * 700, 110.0, 30 + math.cos(math.radians(9)) * 700)
    snap["laser"]["at"] = off
    bot.clock = lambda: 1.1
    assert "zr" in A.apply(bot, snap, {"hold": ("zl", "zr")}, 1.1)["hold"]          # slid off: still held
    assert bot.stats["target_feedback_gate"] == "automatic hold"
    assert "zr" not in A.apply(bot, snap, {"hold": ("zl", "zr")}, 1.35)["hold"]     # bounded (AUTO_HOLD_S)


def test_rifles_prefer_range_and_magnums_big_targets():
    assert W.band_cost(0x05, 200) > W.band_cost(0x05, 2000)
    assert W.band_cost(0x0B, 1000, hp_max=5000) < W.band_cost(0x0B, 1000, hp_max=800)
    assert W.band_cost(0x04, 1500) > W.band_cost(0x04, 500)                          # the shotgun: near
    assert W.band_cost(0x02, 1000) == 1.0                                            # handguns: no preference


def test_every_family_has_a_controller_and_the_bomb_stays_the_mine_controllers():
    families = {w.family for w in W.WEAPONS.values()} - {"mine"}
    assert families <= set(W.MASTERY) and W.mastery(0x0A) is None
    assert all(m.buttons for m in W.MASTERY.values())
    assert {W.mastery(i).mode for i in (0x0F, 0x36, 0x06, 0x0C, 0x0D, 0x01, 0x21)} == \
        {"arrow", "throw", "splash", "contact", "stream"}


# --- the operator's weapon ---------------------------------------------------------------------------------------------
CROWD5 = [at(250, 5), at(350, 60), at(300, -40)]


def test_the_operators_bow_is_kept_in_a_crowd_and_spammed():
    inv = [row(0x0F), row(0x04, grid=5, hand=False, slot=1)]
    sim = Sim(inv, CROWD5, extra={"preferred_weapon": {"item": 0x0F}}).run(2.0)
    assert not any("dright" in h or tap == "dright" for t, h, tap, _d in sim.ticks)   # never the shotgun
    assert sim.bot.stats.get("rampage_swaps", 0) == 0 and sim.edges(since=0.5) >= 10


def test_without_a_choice_the_crowd_fire_still_puts_the_shotgun_up():
    inv = [row(0x0F), row(0x04, grid=5, hand=False, slot=1)]
    sim = Sim(inv, CROWD5).run(0.2)
    assert sim.bot.stats["rampage_swaps"] == 1 and any("dright" in h for t, h, _tap, _d in sim.ticks)


def test_the_operators_grenade_stays_in_hand_and_without_a_choice_the_gun_comes_back():
    inv = [row(0x06, grid=1), row(0x02, grid=3, hand=False, slot=1)]
    chosen = Sim(inv, [at(900, 0), at(950, 5)], extra={"preferred_weapon": {"item": 0x06}}).run(2.0)
    assert not any(tap or "dleft" in h for t, h, tap, _d in chosen.ticks) and chosen.edges() >= 10
    default = Sim(inv, [at(900, 0), at(950, 5)]).run(0.2)
    assert any(tap == "dleft" for t, h, tap, _d in default.ticks)      # today's rule: the gun back first
    knife = [row(0x01, grid=9), row(0x02, grid=3, hand=False, slot=1)]
    unchosen = Sim(knife, [at(900, 0)]).run(0.2)                         # a knife nobody chose: the gun, as a grenade
    assert any(tap == "dleft" for t, h, tap, _d in unchosen.ticks)
    chosen_knife = Sim(knife, [at(120, 0)], extra={"preferred_weapon": {"item": 0x01}}).run(0.5)
    assert not any(tap for t, h, tap, _d in chosen_knife.ticks) and chosen_knife.edges() > 3


def test_an_empty_chosen_gun_reloads_while_it_can_and_only_then_the_fallback():
    inv = [row(0x0B, rounds=0), row(0x02, grid=3, hand=False, slot=1), row(0x01, kind=2, grid=11, hand=False, slot=2,
                                                                          rounds=12)]
    inv[0]["grid"] = 5
    sim = Sim(inv, [at(900, 0)], extra={"preferred_weapon": {"item": 0x0B}})
    sim.run(R.WM_RELOAD_WAIT_S - 0.2)
    assert all(h == {"zl", "b"} for t, h, tap, _d in sim.ticks[1:]) and sim.bot.stats["wm_reload_waits"] > 10
    sim.run(1.0)
    assert any(tap == "dleft" for t, h, tap, _d in sim.ticks)          # still empty: the loaded fallback
    dry = Sim([row(0x0B, rounds=0, grid=5), row(0x02, grid=3, hand=False, slot=1)], [at(900, 0)],
              extra={"preferred_weapon": {"item": 0x0B}}).run(0.2)
    assert any(tap == "dleft" for t, h, tap, _d in dry.ticks)          # no ammo at all: at once


# --- the per-family stats ----------------------------------------------------------------------------------------------
def test_per_family_stats_shots_hits_kills_time_idle_spent_and_motions():
    sim = Sim([row(0x0F, rounds=50)], [at(800, 0)])
    sim.run(1.0)
    sim.kills = 2
    sim.hp[10] = 600                                     # his health falls just after a press
    sim.inv[0]["rounds"] = 45
    sim.motion = 41                                      # a motion byte the bow plays (unknown id: recorded)
    sim.run(1.0)
    st = sim.bot.stats
    assert st["wm_bow_shots"] == sim.edges() and st["wm_bow_range_shots"] == sim.edges()
    assert 1.9 <= st["wm_bow_hand_s"] <= 2.1 and 1.9 <= st["wm_bow_range_s"] <= 2.1
    assert st["wm_bow_kills"] == 2 and st["wm_bow_kills_per_min"] > 0
    assert st["wm_bow_hits"] >= 1 and st["wm_bow_spent"] == 5
    assert st["wm_bow_idle_s"] < 0.5                     # the raise only
    assert st["weapon_motions_seen"]["0x0f"]["41"] > 5 and "0x0f: 41x" in st["weapon_motions_seen_text"]
    assert "bow" in st["wm_summary"] and st["wm_family"] == "bow"


def test_idle_with_a_target_counts_when_the_trigger_is_held_back():
    sim = Sim([row(0x0F, rounds=0)], [at(800, 0)]).run(1.5)   # nothing loaded: aimed, no arrow
    assert sim.edges() == 0 and sim.bot.stats["wm_bow_idle_s"] > 1.0


# --- the per-weapon rate mods ------------------------------------------------------------------------------------------
def test_egg_and_bow_rates_are_ops_with_their_own_ranges_and_aliases():
    from tests.test_re5_switch_parity import parity_guest
    from tests.test_re5_switch_mods import Adapter
    ad = Adapter(parity_guest())
    st = SM.tool_run(ad, "status")["status"]
    assert st["egg_rate_x"] == 20.0 and st["bow_rate_x"] == 10.0          # the operator's defaults
    assert st["capabilities"]["egg_rate"]["available"] and st["capabilities"]["bow_rate"]["available"]
    out = SM.tool_run(ad, "egg_rate", 30, True)
    assert out["verified"] and out["egg_rate_x"] == 30.0 and out["status"]["egg_rate_x"] == 30.0
    assert out["motions_known"] is False and "weapon_motions_seen" in out["note"]
    assert SM.tool_run(ad, "bow_speed", 15, True)["status"]["bow_rate_x"] == 15.0   # an alias
    assert SM.tool_run(ad, "bow_rate", 15, False)["bow_rate_x"] == 1.0              # on=false: the game's
    for op, bad in (("egg_rate", 41), ("egg_rate", 0.5), ("bow_rate", 21), ("bow_rate", float("nan"))):
        with pytest.raises(ValueError):
            SM.tool_run(ad, op, bad, True)


def _snap_with(g, item, motion):
    snap = R.snapshot(g)
    snap["player"] = dict(snap["player"], motion=motion)
    snap["inventory"] = [row(item)]
    return snap


def test_the_egg_rate_scales_only_the_eggs_own_motions_and_the_guns_keep_fire_rate(monkeypatch):
    from tests.test_re5_switch_mods import scale, weapon_guest, Adapter
    monkeypatch.setattr(SM, "FIRE_MAX", 5.0)
    g = weapon_guest()
    ad = Adapter(g)
    SM.run(ad, "fire_rate", multiplier=80)                                # capped: the guns' FIRE_MAX
    SM.tool_run(ad, "egg_rate", 30, True)
    assert SM.maintain(ad, _snap_with(g, 0x36, 41))["writes"] == 0 and scale(g) == 1.0   # its motions not known yet
    monkeypatch.setitem(W.RATE_MOTIONS, 0x36, frozenset({41}))               # (once measured live)
    out = SM.maintain(ad, _snap_with(g, 0x36, 41))
    assert out["active"] and scale(g) == 30.0 and out["weapon_rate"]["x"] == 30.0   # FIRE_MAX is the guns' cap only
    assert SM.maintain(ad, _snap_with(g, 0x36, SM.MOTION_SHOT))["writes"] == 1 and scale(g) == 1.0   # not its motion
    assert SM.maintain(ad, _snap_with(g, 0x02, SM.MOTION_SHOT))["writes"] == 1 and scale(g) == 5.0   # a gun: fire_rate
    SM.maintain(ad, _snap_with(g, 0x02, 26))
    monkeypatch.setitem(W.RATE_MOTIONS, 0x0F, frozenset({57}))
    SM.maintain(ad, _snap_with(g, 0x0F, 57))
    assert scale(g) == 10.0                                                 # the bow's default 10x


def test_the_live_panel_lists_the_two_rate_sliders_with_their_bounds():
    status = {"egg_rate_x": 20.0, "bow_rate_x": 10.0, "capabilities": {"egg_rate": {"available": True},
                                                                        "bow_rate": {"available": True}}}
    rows = {c["id"]: c for c in LC.control_inventory("re5", {}, status)}
    egg, bow = rows["mod.egg_rate"], rows["mod.bow_rate"]
    assert egg["label"] == "Rotten egg throw rate ×" and (egg["min"], egg["max"]) == (1, 40) and egg["available"]
    assert bow["label"] == "Bow fire rate ×" and (bow["min"], bow["max"]) == (1, 20) and bow["value"] == 10.0
    assert LC.change_input(egg, 25) == {"op": "egg_rate", "multiplier": 25, "on": True}
    with pytest.raises(ValueError):
        LC.change_input(bow, 25)
