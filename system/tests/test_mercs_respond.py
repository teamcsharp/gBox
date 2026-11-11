"""The doctrine's answer to a threat (gbox.mercs.core.respond): every threatened tick is a flash, a mine or fire -
never nothing - and the stats that measure it. Synthetic state only: the cores on hand-made rows, each title's path
through its own Bot with its fight stubbed where a full snapshot would be needed."""
import math

import pytest

from gbox.mercs import threat_memory
from gbox.mercs.core import combat, respond
from gbox.mercs.titles import re4_switch as R4
from gbox.mercs.titles import re5_switch as R5
from gbox.mercs.titles import re5_switch_mines as M5
from gbox.mercs.titles import re6_switch as R6

PROF = combat.TitleProfile(title="t", grab_r_cm=120.0, level_dy_cm=120.0)
FIRE = {"hold": ("zl", "zr")}
WALK = {"hold": ("lup",)}


def foe(i, x, z, hp=800, cls="uEm10"):
    return {"ptr": 100 + i, "pos": (float(x), 0.0, float(z)), "hp": hp, "hp_max": 800, "class": cls}


def me(hp=1000):
    return {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": hp, "hp_max": 1000}


class Kit:
    """A title's kit that records what the doctrine asked of it."""

    def __init__(self, flash=True, mine=True, clear=True, fire_act=FIRE):
        self.calls, self.fire_act = [], fire_act
        self.kit = respond.Kit(fire=self.fire, flash=self.flash if flash else None, mine=self.mine if mine else None,
                               clear=(lambda e: clear), attack=frozenset({"melee"}), aim=frozenset({"aim", "turn"}),
                               busy=frozenset({"held"}), mine_doings=frozenset({"mine"}))

    def fire(self, e, pool):
        self.calls.append(("fire", e["ptr"], [x["ptr"] for x in pool]))
        return dict(self.fire_act)

    def flash(self, why):
        self.calls.append(("flash", why))
        return True

    def mine(self, why):
        self.calls.append(("mine", why))
        return True


def run(r, k, ticks, act=WALK, doing="walk", memory=None):
    """ticks: [(now, player, enemies)] -> the acts sent; each tick settled with what it sent."""
    out = []
    for now, p, enemies in ticks:
        sent = r.respond(PROF, now, p, enemies, act, k.kit, doing, memory)
        r.settle(sent, None if sent is not act else doing)
        out.append(sent)
    return out


def closing(i, start, step, n, dt=0.1, t0=0.0):
    """A Majini walking straight at him along +z: [(now, his row)]."""
    return [(t0 + j * dt, foe(i, 0.0, start - j * step)) for j in range(n)]


# --- the verdict ------------------------------------------------------------------------------------------------------
def test_a_majini_closing_within_reach_while_he_walks_gets_the_fight_instead():
    r, k = respond.Responder({}), Kit(flash=False, mine=False)
    sent = run(r, k, [(t, me(), [e]) for t, e in closing(0, 240.0, 10.0, 5)])
    assert sent[-1] == FIRE and ("fire", 100, [100]) in k.calls
    assert r.stats["threat_forced_fire"] >= 1 and r.stats["threat_unanswered"] == 0
    assert r.stats["threat_answered_fire"] == r.stats["threat_ticks"] >= 1


def test_one_standing_still_at_two_metres_is_no_threat_and_his_own_action_stands():
    r, k = respond.Responder({}), Kit()
    sent = run(r, k, [(j * 0.1, me(), [foe(0, 0.0, 200.0)]) for j in range(6)])
    assert all(a is WALK for a in sent) and not k.calls and r.stats["threat_ticks"] == 0


def test_a_hit_taken_while_he_did_none_of_the_three_is_hurt_while_idle():
    r, k = respond.Responder({}, respond.Rules()), Kit(flash=False, mine=False)
    still = foe(0, 0.0, 300.0)                            # 3 m off, not closing: no threat before the hit
    run(r, k, [(0.0, me(1000), [still]), (0.1, me(1000), [still])])
    assert r.stats["threat_ticks"] == 0
    run(r, k, [(0.2, me(900), [still])])                   # his health fell: a hit, he had done nothing
    assert r.stats["threat_hits"] == 1 and r.stats["hurt_while_idle"] == 1
    assert r.stats["threat_ticks"] == 1 and k.calls[-1][0] == "fire", "hurt: the nearest one is the threat, fired at"


def test_a_hit_taken_while_he_fires_is_not_hurt_while_idle():
    r, k = respond.Responder({}), Kit(flash=False, mine=False)
    e = foe(0, 0.0, 300.0)
    run(r, k, [(0.0, me(1000), [e]), (0.1, me(1000), [e])], act=FIRE, doing="fire")
    run(r, k, [(0.2, me(900), [e])], act=FIRE, doing="fire")
    assert r.stats["threat_hits"] == 1 and r.stats["hurt_while_idle"] == 0


def test_three_near_him_get_the_flash_then_the_fire_on_the_stunned_ones():
    r, k = respond.Responder({}), Kit(mine=False)
    crowd = [foe(0, 0.0, 200.0), foe(1, 150.0, 100.0), foe(2, -150.0, 150.0)]
    hurt = [(0.0, me(1000), crowd), (0.1, me(950), crowd)]
    run(r, k, hurt)
    assert [c[0] for c in k.calls] == ["flash"] and r.stats["threat_answered_flash"] == 1
    run(r, k, [(0.5, me(950), crowd)])                     # inside flash_answer_s: the flash still answers
    assert [c[0] for c in k.calls] == ["flash"] and r.stats["threat_answered_flash"] == 2
    run(r, k, [(1.3, me(900), crowd)])                     # past it, the next flash not due: fire on them
    assert [c[0] for c in k.calls] == ["flash", "fire"]
    assert r.stats["threat_flash_asks"] == 1 and r.stats["threat_answered_fire"] == 1
    assert r.stats["threat_unanswered"] == 0


def test_a_title_without_a_flash_says_so_and_fires():
    r, k = respond.Responder({}), Kit(flash=False, mine=False)
    crowd = [foe(0, 0.0, 200.0), foe(1, 150.0, 100.0), foe(2, -150.0, 150.0)]
    run(r, k, [(0.0, me(1000), crowd), (0.1, me(950), crowd)])
    assert r.stats["threat_lacks_flash"] == 1 and k.calls[-1][0] == "fire"
    assert r.stats["threat_answered_fire"] == 1 and r.stats["threat_unanswered"] == 0


def test_two_converging_from_beyond_the_plant_margin_get_a_mine_then_the_cycle_answers():
    r, k = respond.Responder({}, respond.Rules(mine_min_cm=250.0)), Kit(flash=False)
    a, b = closing(0, 600.0, 15.0, 4), closing(1, 640.0, 15.0, 4)
    hurt = [(t, me(1000 if j < 3 else 950), [ea, dict(eb, pos=(80.0, 0.0, eb["pos"][2]))])
            for j, ((t, ea), (_t, eb)) in enumerate(zip(a, b))]
    run(r, k, hurt)
    assert ("mine" in [c[0] for c in k.calls]) and r.stats["threat_mine_asks"] == 1
    assert k.calls[-1][0] == "fire", "the plant starts next tick: this tick he fires"
    run(r, k, [(0.5, me(950), hurt[-1][2])], act={"hold": ("ddown",)}, doing="mine")
    assert r.stats["threat_answered_mine"] == 1


def test_a_class_that_hurt_him_is_a_threat_from_its_learned_reach_and_counts_double():
    tm = threat_memory.ThreatMemory(None, default_reach_cm=300.0)
    tm.data["classes"]["uEm10"] = {"starts": {}, "hits": {}, "through": 0, "hit_count": 3, "reach_cm": 400.0}
    mem = respond.Memory(tm, default_reach_cm=300.0)
    r, k = respond.Responder({}), Kit(mine=False)
    known, fresh = foe(0, 0.0, 380.0, cls="uEm10"), foe(1, 0.0, 380.0, cls="uEm99")
    run(r, k, [(0.0, me(), [fresh]), (0.1, me(), [fresh])], memory=mem)
    assert r.stats["threat_ticks"] == 0, "3.8 m, not closing, never hurt him: no threat"
    run(r, k, [(0.2, me(), [known]), (0.3, me(), [known])], memory=mem)
    assert r.stats["threat_ticks"] == 2 and r.stats["threat_learned_ticks"] == 2
    assert k.calls[-1][0] == "fire"
    two = [foe(2, 0.0, 300.0, cls="uEm10"), foe(3, 100.0, 300.0, cls="uEm10")]
    run(r, k, [(5.0, me(), two)], memory=mem)
    assert k.calls[-1][0] == "flash", "two of a class that hurt him weigh as four: the flash"


def test_a_hold_is_not_his_choice_and_is_never_overridden():
    r, k = respond.Responder({}), Kit()
    sent = run(r, k, [(t, me(), [e]) for t, e in closing(0, 240.0, 10.0, 4)], act={"hold": ("b",)}, doing="held")
    assert all(a == {"hold": ("b",)} for a in sent)
    assert r.stats["threat_busy"] >= 1 and r.stats["threat_unanswered"] == 0 and r.stats["threat_ticks"] == 0


def test_no_wall_shots_a_threat_behind_a_wall_is_left_unanswered_and_said():
    r, k = respond.Responder({}), Kit(flash=False, mine=False, clear=False)
    run(r, k, [(t, me(), [e]) for t, e in closing(0, 240.0, 10.0, 4)])
    assert not [c for c in k.calls if c[0] == "fire"]
    assert r.stats["threat_unanswered"] >= 1 and "wall" in r.stats["threat_unanswered_why"]


def test_at_point_blank_right_after_a_hit_the_line_is_his_whatever_the_mesh_says():
    r, k = respond.Responder({}), Kit(flash=False, mine=False, clear=False)
    e = foe(0, 0.0, 100.0)
    run(r, k, [(0.0, me(1000), [e]), (0.1, me(900), [e])])
    assert k.calls[-1][0] == "fire"


def test_the_gun_up_without_a_shot_past_the_raise_grace_is_unanswered():
    aim = {"hold": ("zl",)}
    r, k = respond.Responder({}), Kit(flash=False, mine=False, fire_act=aim)   # his fight only ever aims
    ticks = [(j * 0.1, me(), [foe(0, 0.0, 245.0 - 5.0 * j)]) for j in range(30)]   # closing at 50 cm/s
    run(r, k, ticks, act=aim, doing="aim")
    assert r.stats["threat_answered_fire"] >= 1, "the raise is the start of the fire"
    assert r.stats["threat_unanswered"] >= 1 and "no shot" in r.stats["threat_unanswered_why"]


def test_measured_only_when_enforce_is_off(monkeypatch):
    monkeypatch.setattr(respond, "ENFORCE", False)
    r, k = respond.Responder({}), Kit()
    sent = run(r, k, [(t, me(), [e]) for t, e in closing(0, 240.0, 10.0, 5)])
    assert all(a is WALK for a in sent) and not k.calls
    assert r.stats["threat_ticks"] >= 1 and r.stats["threat_unanswered"] == r.stats["threat_ticks"]


def test_the_counters_are_in_every_switch_drivers_round_counters():
    for drv in (R4.RE4Switch, R5.RE5Switch, R6.RE6Switch):
        assert set(respond.COUNTERS) <= set(drv.round_counters), drv.__name__


# --- RE4 Switch: no flash, no mines - the fight on the threat, no run-off ------------------------------------------
def mm(p):
    return tuple(v * R4.MM_PER_CM for v in p)


def r4_snap(z_cm, hp=300):
    return {"player": {"pos": mm((0.0, 0.0, 0.0)), "rot": 0.0, "hp": hp, "hp_max": 1000, "ptr": 1},
            "enemies": [{"pos": mm((0.0, 0.0, z_cm)), "hp": 400, "hp_max": 400, "ptr": 100, "class": 0xAE7050}]}


@pytest.mark.parametrize("on", [True, False])
def test_re4_low_life_with_a_ganado_closing_fires_instead_of_running(monkeypatch, on):
    monkeypatch.setattr(R4, "RESPOND", on)
    b = R4.Bot(stats={}, director=False)
    for j in range(6):                                     # 2.4 m -> 1.9 m in 0.5 s: closing at 100 cm/s
        b.tick(r4_snap(240.0 - 10.0 * j), now=10.0 + 0.1 * j)
    if on:
        assert b.doing in ("turn", "aim", "fire"), b.why
        assert b.stats["threat_forced_fire"] >= 1 and b.stats["threat_lacks_flash"] >= 1, \
            "low health wants the flash: RE4 has none, so fire"
        assert b.stats["threat_unanswered"] == 0
    else:
        assert b.doing == "retreat", "off: the low-life run as before"
        assert "threat_ticks" not in b.stats or b.stats["threat_ticks"] == 0


def test_re4_unanswered_threats_are_zero_when_his_own_fight_already_shoots():
    b = R4.Bot(stats={}, director=False)
    for j in range(8):
        b.tick(r4_snap(240.0 - 8.0 * j, hp=1000), now=10.0 + 0.1 * j)
    assert b.stats["threat_ticks"] >= 1 and b.stats["threat_unanswered"] == 0
    assert b.stats["threat_answered_fire"] == b.stats["threat_ticks"]


# --- RE5 Switch: the native flash, the mine controller, the fight on the threats --------------------------------------
def r5_snap(enemies, hp=1000):
    return {"mercenaries_phase": R5.PHASE_PLAYING, "player": {"ptr": 7, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": hp,
                                                              "hp_max": 1000, "motion": 0},
            "enemies": enemies, "inventory": [{"id": M5.MINE_ID, "rounds": 3, "grid": 1}], "kills": 0,
            "ground_mines": []}


def r5_bot(monkeypatch):
    b = R5.Bot(stats={}, clock=lambda: 0.0)
    asked = []
    monkeypatch.setattr(b, "_goal_decide", lambda p, pool, flat, e, d, snap, now: (asked.append(
        ("fire", [x["ptr"] for x in pool])), setattr(b, "doing", "fire"), dict(FIRE))[-1])
    monkeypatch.setattr(b, "_native_flash", lambda snap, now, why, counter: asked.append(("flash", why)) or True)
    return b, asked


def test_re5_a_closing_majini_while_he_walks_is_fired_at(monkeypatch):
    b, asked = r5_bot(monkeypatch)
    b.mines = None
    for j in range(5):
        b.doing = "walk"                                   # his own decision: a walk (a door, the locate run)
        s = r5_snap([foe(0, 0.0, 240.0 - 10.0 * j)])
        act = b._respond(s, dict(WALK), 0.1 * j)
        b._respond_settle(act)
    assert ("fire", [100]) in asked and act == FIRE
    assert b.stats["threat_answered_fire"] >= 1 and b.stats["threat_unanswered"] == 0


def test_re5_a_crowd_gets_the_native_flash(monkeypatch):
    b, asked = r5_bot(monkeypatch)
    b.mines = None
    b.doing = "walk"
    crowd = [foe(0, 0.0, 200.0), foe(1, 150.0, 100.0), foe(2, -150.0, 150.0)]
    b._respond_settle(b._respond(r5_snap(crowd), dict(WALK), 0.0))
    b._respond_settle(b._respond(r5_snap(crowd, hp=900), dict(WALK), 0.1))
    assert asked and asked[0][0] == "flash" and b.stats["threat_answered_flash"] == 1


def test_re5_converging_majini_urge_the_mine_controller_which_then_skips_its_cadence(monkeypatch):
    b, asked = r5_bot(monkeypatch)
    b.mines = M5.Mines(b.stats)
    b.mines.new_round(0.0)
    b.doing = "walk"
    for j in range(4):
        rows = [foe(0, 0.0, 600.0 - 15.0 * j), foe(1, 80.0, 640.0 - 15.0 * j)]
        b._respond_settle(b._respond(r5_snap(rows, hp=1000 if j < 3 else 950), dict(WALK), 0.1 * j))
    assert b.stats["threat_mine_asks"] == 1 and b.stats["mine_urges"] == 1
    p, s = {"pos": (0.0, 0.0, 0.0), "hp": 1000, "hp_max": 1000}, r5_snap([])
    assert b.mines.due(p, s, [], 0.4) == "due", "urged: no wait for every_s"
    assert b.mines.due(p, s, [], 0.4 + M5.URGE_S + 0.1) is None, "the urge lapses: the cadence again"


def test_re5_off_the_doctrine_leaves_the_tick_alone(monkeypatch):
    monkeypatch.setattr(R5, "RESPOND", False)
    b, asked = r5_bot(monkeypatch)
    for j in range(5):
        assert b._respond(r5_snap([foe(0, 0.0, 240.0 - 10.0 * j)]), WALK, 0.1 * j) is WALK
    assert not asked


# --- RE6 Switch: the native flash on the session's adapter, the remote bomb, the fight -----------------------------
def r6_snap(enemies, hp=1000, bomb=None):
    return {"mercenaries_phase": R6.PHASE_PLAYING,
            "player": {"ptr": 9, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": hp, "hp_max": 1000,
                       "bomb": bomb or {"count": 0}},
            "enemies": enemies}


def r6_bot(monkeypatch):
    b = R6.Bot(stats={}, clock=lambda: 0.0)
    asked = []
    monkeypatch.setattr(b, "_decide", lambda p, pool, flat, e, d, snap, now: (asked.append(
        ("fire", [x["ptr"] for x in pool])), setattr(b, "doing", "fire"), dict(FIRE))[-1])
    return b, asked


def test_re6_without_the_session_a_crowd_is_fired_at_and_the_missing_flash_counted(monkeypatch):
    b, asked = r6_bot(monkeypatch)
    b.doing = "walk"
    crowd = [foe(0, 0.0, 200.0), foe(1, 150.0, 100.0), foe(2, -150.0, 150.0)]
    b._respond(r6_snap(crowd), dict(WALK), 0.0)
    act = b._respond(r6_snap(crowd, hp=900), dict(WALK), 0.1)
    assert act == FIRE and b.stats["threat_lacks_flash"] >= 1


def test_re6_with_the_session_a_surround_gets_the_native_flash_and_its_fever(monkeypatch):
    b, asked = r6_bot(monkeypatch)

    class Ctl:
        def flash(self):
            asked.append(("native_flash",))
            return {"state": "confirmed"}

    class Now:
        def __init__(self, target, daemon=None, name=None):
            self.target = target

        def start(self):
            self.target()
    from gbox.mercs import interventions
    monkeypatch.setattr(interventions, "native_controller", lambda ad: Ctl())
    monkeypatch.setattr(R6.threading, "Thread", Now)
    b._doctrine_m = type("M", (), {"adapter": object(), "mercs_no_modifications": False})()
    b.doing = "walk"
    crowd = [foe(0, 0.0, 200.0), foe(1, 150.0, 100.0), foe(2, -150.0, 150.0), foe(3, 100.0, -150.0)]   # 4 within 3 m
    b._respond(r6_snap(crowd), dict(WALK), 0.0)
    b._respond(r6_snap(crowd, hp=900), dict(WALK), 0.1)
    assert ("native_flash",) in asked and b.stats["threat_flashes"] == 1
    assert b.stats.get("native_flash_confirmed_at"), "the receipt _emergency_flashbang turns into the fever"
    assert b.stats["flash_reason_last"] == "respond: surrounded"
    asked.clear()
    b._respond(r6_snap(crowd, hp=800), dict(WALK), 5.1)       # within the minute (FLASH_MIN_GAP_S): fire instead
    assert ("native_flash",) not in asked, "the doctrine's own gap is the live minute too"


def test_re6_three_near_are_no_tight_situation_so_the_doctrine_fires(monkeypatch):
    b, asked = r6_bot(monkeypatch)

    class Ctl:
        def flash(self):
            asked.append(("native_flash",))
            return {"state": "confirmed"}
    from gbox.mercs import interventions
    monkeypatch.setattr(interventions, "native_controller", lambda ad: Ctl())
    monkeypatch.setattr(R6.threading, "Thread", lambda target, daemon=None, name=None: type("T", (), {"start": lambda s: target()})())
    b._doctrine_m = type("M", (), {"adapter": object(), "mercs_no_modifications": False})()
    b.doing = "walk"
    crowd = [foe(0, 0.0, 200.0), foe(1, 150.0, 100.0), foe(2, -150.0, 150.0)]
    b._respond(r6_snap(crowd), dict(WALK), 0.0)
    act = b._respond(r6_snap(crowd, hp=900), dict(WALK), 0.1)
    assert ("native_flash",) not in asked and act == FIRE and b.stats["flash_untight_skips"] >= 1
    big = [foe(i, 50.0 * i, 100.0, hp=5000) for i in range(5)]  # heavies: a flash does not stop them
    for e in big:
        e["hp_max"] = 5000
    b._respond(r6_snap(big, hp=800), dict(WALK), 0.2)
    assert ("native_flash",) not in asked


def test_re6_converging_zombies_make_the_remote_bomb_due(monkeypatch):
    b, asked = r6_bot(monkeypatch)
    b.doing = "walk"
    for j in range(4):
        rows = [foe(0, 0.0, 600.0 - 15.0 * j), foe(1, 80.0, 640.0 - 15.0 * j)]
        b._respond(r6_snap(rows, hp=1000 if j < 3 else 950, bomb={"count": 2, "out": False}), dict(WALK), 0.1 * j)
    assert b.stats["threat_mine_asks"] == 1 and b.mine_due is not None
