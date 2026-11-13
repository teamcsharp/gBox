"""RE4 Switch: a boss on screen is neutralized at once (operator 2026-11-12), and the defensive Nitrous ring.

The measured failure this pins: session 7ef0908f (Village, three deaths) read boss_picks 0 in every round while a
6500-health chainsaw boss was fought - the profile had only a DANGEROUS health threshold, and the apex/heavy keep
rule then evaded the boss instead of finishing it. Every test is on synthetic snapshots (no game).
"""
import math

import pytest

from gbox.mercs import grenade_ring as G
from gbox.mercs.titles import re4_switch as D


@pytest.fixture(autouse=True)
def _no_weapon_ask_leak():
    """The mine ring's weapon request and its process clock are module state: isolate every test from them."""
    D.WEAPON_ASK.clear()
    D.MINE_RING_CLOCK.clear()
    D.MINE_RING_CLOCK.update(at=None, retry_at=0.0)
    yield
    D.WEAPON_ASK.clear()
    D.MINE_RING_CLOCK.clear()
    D.MINE_RING_CLOCK.update(at=None, retry_at=0.0)


def mm(p):
    return tuple(v * D.MM_PER_CM for v in p)


def snap(enemies=(), pos=(0.0, 0.0, 0.0), rot=0.0, hp=1860, stage=0, **extra):
    """The RE4 snapshot shape the boss rules read: enemies carry hp_max / class, the game its stage."""
    rows = []
    for i, item in enumerate(enemies):
        p, health = item[0], item[1]
        row = {"pos": mm(p), "hp": health, "hp_max": item[2] if len(item) > 2 else health,
               "class": 0xAE7050, "ptr": 100 + i}
        if len(item) > 3:
            row.update(item[3])
        # the driver's own annotation (re4_switch.snapshot): the stage's set list names the boss on the row
        key = D.boss_key(row, D.STAGES[stage])
        if key is not None:
            row.update(boss=True, key=key, chainsaw=key in D.CHAINSAW_KEYS)
        rows.append(row)
    return {"player": {"pos": mm(pos), "rot": rot, "hp": hp, "hp_max": 1860, "ptr": 1},
            "enemies": rows,
            "game": {"stage": stage, "phase": "playing", "in_control": True, "clock_running": True}, **extra}


def bot():
    return D.Bot(stats={}, director=False)


# ---- who is a boss -----------------------------------------------------------------------------------------------------

def test_a_6500_health_village_boss_is_named_by_the_set_list_and_is_a_chainsaw():
    key = D.boss_key({"hp_max": 6500, "hp": 6500}, "Village")
    assert key in D.CHAINSAW_KEYS and key in ("salvador", "bella"), "the set list holds both at 6500: a chainsaw either way"


def test_an_ordinary_ganado_is_not_a_boss():
    assert D.boss_key({"hp_max": 1800}, "Village") is None
    assert D.boss_key({"hp_max": 1000}, "Base") is None


def test_a_garrador_and_a_jj_are_bosses_even_below_the_health_threshold():
    assert D.boss_key({"hp_max": 2600}, "Castle") == "garrador"
    assert D.boss_key({"hp_max": 2000}, "Base") == "jj"
    assert "jj" in D.BOSS_KEYS and D.boss_key({"hp_max": 3000}, "Base") == "jj"


def test_boss_on_screen_respects_the_camera_and_the_distance():
    near = snap([((0.0, 0.0, 800.0), 6500)])
    assert D.boss_on_screen(near)["key"] in D.CHAINSAW_KEYS
    behind = snap([((0.0, 0.0, -800.0), 6500)])                    # 8 m behind him: not on screen
    assert D.boss_on_screen(behind) is None
    far = snap([((0.0, 0.0, 4000.0), 6500)])                       # 40 m: past BOSS_SIGHT_MM
    assert D.boss_on_screen(far) is None


# ---- the priority: the boss, not the nearer Ganado ---------------------------------------------------------------

def test_the_boss_is_picked_over_a_ganado_at_his_feet():
    b = bot()
    s = snap([((0.0, 0.0, 100.0), 400, 400), ((0.0, 0.0, 800.0), 6500, 6500)])
    dist, _err, e = b._choose(b._live(s["player"], s["enemies"]), 10.0, s["player"], s)
    assert e["hp_max"] == 6500 and b.stats["boss_engagements"] == 1
    assert b.doing == "boss" and "BOSS" in b.why


def test_the_boss_lock_survives_a_knockdown_and_ends_at_zero_health():
    b = bot()
    s = snap([((0.0, 0.0, 700.0), 6500, 6500)])
    first = b._choose(b._live(s["player"], s["enemies"]), 10.0, s["player"], s)
    assert first[2]["hp_max"] == 6500 and b.doing == "boss"
    # knocked down: it is out of the census for a moment - the bot keeps firing where it was
    empty = snap([])
    pick = b._choose(b._live(empty["player"], empty["enemies"]), 11.0, empty["player"], empty)
    assert pick is not None and pick[2].get("down") is True and b.doing == "boss"
    # back up and dead: the lock ends and the kill is counted
    dead = snap([((0.0, 0.0, 700.0), 0, 6500)])
    assert b._choose(b._live(dead["player"], dead["enemies"]), 12.0, dead["player"], dead) is None
    assert b.stats["boss_kills"] == 1 and "boss_on_screen" not in b.stats


def test_the_profile_tiers_a_boss_by_health_so_the_shared_scorer_sees_it():
    prof = D.combat_profile()
    assert prof.tier({"hp_max": 6500, "class": 0xAE7050}) == "boss"
    assert prof.tier({"hp_max": 2500, "class": 0xAE7050}) == "dangerous"     # a heavy at HEAVY_HP 2000
    assert prof.tier({"hp_max": 1800, "class": 0xAE7050}) == "normal"
    assert prof.tier({"hp_max": 400, "class": 0xAE7050}) == "normal"


# ---- the defensive Nitrous ring ------------------------------------------------------------------------------------

class Controller:
    """The minimum a ring decision / fire needs: the launcher's rounds and the flash."""

    def __init__(self, launcher=(), grenades=()):
        self._launcher, self._grenades = list(launcher), list(grenades)
        self.calls = []

    def launcher_kinds(self):
        return self._launcher

    def grenade_kinds(self):
        return self._grenades

    def grenade_ring(self, kind, **kw):
        self.calls.append((kind, kw))
        return {"state": "confirmed", "kind": kind, "detonated": kw.get("count") or 10}


def cm(s):
    """The snapshot as the ring rule sees it (centimetres)."""
    return G._scaled(s, D.MM_PER_CM)


def test_a_chainsaw_boss_approaching_earns_the_nitrous_ring():
    s = cm(snap([((0.0, 0.0, 900.0), 6500)]))
    d = G.decide(s, {"ring_last_at": 0.0, "ring_round_at": 0.0}, 100.0, G.policy(), title=D.TITLE_ID)
    assert d["fire"] is True and d["kind"] == "nitrous" and d["defend"] is True
    assert d["radius_cm"] >= 1100, "the ring grows to reach the boss, not only the bot's own feet"


def test_a_ganado_at_the_same_distance_is_no_defensive_ring():
    s = cm(snap([((0.0, 0.0, 900.0), 400, 400)]))
    d = G.decide(s, {"ring_last_at": 0.0, "ring_round_at": 0.0}, 100.0, G.policy(), title=D.TITLE_ID)
    assert not (d["fire"] and d.get("defend"))


def test_a_boss_winding_up_earns_it_even_from_further_out():
    s = cm(snap([((0.0, 0.0, 1300.0), 3000, 3000, {"windup": True})]))
    d = G.decide(s, {"ring_last_at": 0.0, "ring_round_at": 0.0}, 100.0, G.policy(), title=D.TITLE_ID)
    assert d["fire"] is True and d.get("defend") is True


def test_the_defensive_kind_is_the_nitrogen_shell_where_the_title_has_it_else_the_flash():
    re6 = Controller(launcher=[{"kind": "shell1304", "available": True}])
    assert G.defend_kind(re6) == ("shell1304", True)
    re4 = Controller(grenades=[{"kind": "flash", "available": False}, {"kind": "hand", "available": True}])
    assert G.defend_kind(re4) == ("flash", False)


def test_fire_resolves_nitrous_to_the_titles_freezing_round():
    re6 = Controller(launcher=[{"kind": "shell1302", "available": True}, {"kind": "shell1304", "available": True}])
    receipt = G.fire(None, {"kind": "nitrous", "count": 10, "radius_cm": 600.0}, {}, 5.0, ring=re6)
    assert receipt["state"] == "confirmed" and re6.calls[0][0] == "shell1304" and re6.calls[0][1]["count"] == 10
    re4 = Controller(grenades=[{"kind": "flash", "available": False}])
    receipt = G.fire(None, {"kind": "nitrous", "count": 10}, {}, 5.0, ring=re4)
    assert re4.calls[0][0] == "flash" and re4.calls[0][1]["allow_unverified"] is False

def test_the_re4_rule_reads_millimetres_as_centimetres():
    """The rule speaks cm; RE4's snapshot speaks mm. Without units_per_cm an 8 m boss read as 8000 "cm" and no
    threshold in the ring rule could see it (RE4's own ring counted only enemies inside 0.8 m)."""
    fake = Controller(grenades=[{"kind": "flash", "available": True}])
    step = G.control(None, {"map_id": D.TITLE_ID, "menus": "gbox.mercs.titles.re4_switch",
                            "units_per_cm": D.MM_PER_CM}, ring=fake)
    stats = {"ring_round_at": 0.0, "ring_last_at": 0.0, "screen": "playing", "kills": 0}
    s = snap([((0.0, 0.0, 900.0), 6500)])
    step(s, stats, 10.0, lambda _keys: True)              # the round's first tick: the start guard only observes
    out = step(s, stats, 100.0, lambda _keys: True)
    assert out.get("fired") is True and fake.calls and fake.calls[0][0] == "flash"
    assert stats.get("ring_defends") == 1


# ---- the mine-thrower ring (the operator's RE4 ring, through the weapon path) ---------------------------------------

def _ring_snap(enemies=(), equipped=D.MINE_RING_ITEM, **extra):
    s = snap(enemies, **extra)
    s["equipped_id"] = equipped
    return s


def test_the_mine_ring_asks_for_the_thrower_in_his_hand():
    b = bot()
    s = _ring_snap([((0.0, 0.0, 800.0), 400, 400)], equipped=0x20)      # a TMP in hand at the start
    b.tick(s, now=1.0)                                                  # the first tick arms the 90 s clock
    assert b.stats.get("mine_ring_starts", 0) == 0
    b.tick(s, now=1.0 + D.MINE_RING_EVERY_S + 0.5)
    assert D.WEAPON_ASK.get("item") == D.MINE_RING_ITEM
    assert b.stats["mine_ring_starts"] == 1 and b.doing == "mine_ring"


def test_the_mine_ring_sweeps_ten_darts_round_him():
    b = bot()
    s = _ring_snap([((0.0, 0.0, 800.0), 400, 400)], rot=0.0)
    b.stats["mine_ring_last_at"] = 1.0 - D.MINE_RING_EVERY_S            # the 1.5 minutes are up: sweep now
    darts, headings, now = 0, set(), 1.0
    for _ in range(90):                                                 # 90 ticks at 0.6 s: 54 s of play
        act = b.tick(s, now=now)
        if act.get("tap") == D.FIRE_BTN and str(b.why).startswith("dart "):
            darts += 1
            headings.add(str(b.why).rsplit(" at ", 1)[-1])
        if any(k in (act.get("hold") or ()) for k in (D.TURN["left"], D.TURN["right"])):
            # the game turns the body as the stick is held: follow the aim request's heading so the sweep can progress
            want = float((D.AIM_REQUEST or {}).get("yaw") or 0.0)
            rot = float(s["player"].get("rot") or 0.0)
            err = (want - rot + math.pi) % (2.0 * math.pi) - math.pi
            s["player"]["rot"] = rot + max(-0.45, min(0.45, err))
        now += 0.6
    assert darts == D.MINE_RING_N, "ten darts, one per 36 deg heading"
    assert len(headings) == D.MINE_RING_N, "the ten headings are all different"
    assert b.stats.get("mine_ring_shots") == D.MINE_RING_N
    assert b.stats["mine_ring_last_at"] and "complete" in b.stats["mine_ring_decision"]


def test_a_ring_that_cannot_arm_gives_up_instead_of_spinning():
    b = bot()
    s = _ring_snap([((0.0, 0.0, 800.0), 400, 400)], equipped=0x20)      # never the thrower
    b.stats["mine_ring_last_at"] = 1.0 - D.MINE_RING_EVERY_S
    b.tick(s, now=1.0)
    b.tick(s, now=1.0 + D.MINE_RING_ARM_S + 0.1)
    assert "not in his hand" in b.stats["mine_ring_decision"]
    assert b.stats["mine_ring_last_at"] is not None
    assert b.stats.get("mine_ring_shots", 0) == 0


def test_the_ring_waits_the_ninety_seconds_between_sweeps():
    b = bot()
    s = _ring_snap([((0.0, 0.0, 800.0), 400, 400)])
    b.stats["mine_ring_last_at"] = 1.0 - D.MINE_RING_EVERY_S
    now = 1.0
    for _ in range(60):
        b.tick(s, now=now)
        if D.AIM_REQUEST.get("owner") == "mine_ring":
            s["player"]["rot"] = D.AIM_REQUEST["yaw"]   # model the game's response to the facing write
        now += 0.6
    first = b.stats["mine_ring_last_at"]
    assert first is not None
    b.tick(s, now=first + 10.0)                                         # ten seconds later: no sweep
    assert b.stats["mine_ring_starts"] == 1
    b.tick(s, now=first + D.MINE_RING_EVERY_S + 0.5)                    # the 1.5 minutes are up: a new sweep
    assert b.stats["mine_ring_starts"] == 2


def test_equip_timeout_never_emits_a_ring_shot_and_retries_after_combat_interval():
    b = bot()
    s = _ring_snap(equipped=0x27)
    b.stats["mine_ring_last_at"] = -100.0
    assert b._mine_ring_step(s["player"], s, 1.0) == {"hold": set()}
    failed_at = 1.0 + D.MINE_RING_ARM_S + 0.1
    assert b._mine_ring_step(s["player"], s, failed_at) is None
    assert b.stats.get("mine_ring_shots", 0) == 0 and "_mine_ring" not in b.__dict__
    assert b._mine_ring_step(s["player"], s, failed_at + D.MINE_RING_RETRY_S - 0.1) is None
    b._mine_ring_step(s["player"], s, failed_at + D.MINE_RING_RETRY_S + 0.1)
    assert b.stats["mine_ring_starts"] == 2


def test_death_observation_runs_when_a_grab_or_ring_owns_the_inputs(tmp_path, monkeypatch):
    from gbox.mercs.core.death_lessons import DeathLessons
    b = bot()
    lessons = DeathLessons(D.TITLE_ID, paths=[tmp_path / "deaths.jsonl"], stats=b.stats)
    b._uc("threats").lessons = lessons
    b.new_round()
    s = _ring_snap(hp=1860)
    b.stats["mine_ring_last_at"] = -100.0
    b.tick(s, now=1.0)
    s["game"].update(phase="grabbed", in_control=False)
    s["player"]["hp"] = 700
    b.tick(s, now=2.0)
    assert [r["hp"] for r in lessons.window] == [1860, 700]
    s["game"].update(phase="dead")
    s["player"]["hp"] = 0
    b.tick(s, now=3.0)
    b.record_death(3.1)                                 # visual and native terminal witnesses deduplicate
    assert b.stats["death_lessons"] == 1
    b.new_round()
    assert not lessons.window and not lessons._dead


def test_the_ring_clock_survives_a_fresh_run():
    """MercMode relaunches the title every round: the 90 s clock must follow the process, not the run."""
    D.MINE_RING_CLOCK["at"] = 100.0
    b = bot()                                                           # a fresh run: its stats know nothing yet
    s = _ring_snap([((0.0, 0.0, 800.0), 400, 400)])
    b.tick(s, now=150.0)                                                # 50 s after the last ring: no ring
    assert b.stats.get("mine_ring_starts", 0) == 0
    b.tick(s, now=191.0)                                                # 91 s: due
    assert b.stats["mine_ring_starts"] == 1
