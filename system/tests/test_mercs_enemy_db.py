"""gbox.mercs.enemy_db: the enemy knowledge database (operator 2026-10-27: "the aimbot learns enemy activity and builds a
database fof how to dispatch them and the aimbot improves based on the ram byte information").

The learning (synthetic shots converge on the zone and offset that dispatch a class, the danger states and their wind-up
lead, the range), the "no data returns the current constants" default, persistence across a restart and a bot hot
reload, the cross-title class map, aging and bounds, queue-only recording, the brain's outcome dicts, the read route,
the round's numbers in stats and the round report, rebuild() and the seed import."""
import importlib
import json
import random
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from gbox.mercs import enemy_db as K

RE5S, RE6S, RE5P, RE4 = "010018100CD46000", "01002A000CD48000", "BLUS30491", "G4BE08"
NOW = time.time()
MAJINI = {"head": (1.63, 0.4, 400), "chest": (1.08, 0.8, 120), "legs": (0.70, 0.6, 100)}


@pytest.fixture(autouse=True)
def db(tmp_path):
    K.configure(tmp_path / "knowledge")
    K.reset()
    yield tmp_path / "knowledge"
    K.flush(wait=True)
    K.configure(None)
    K.reset()


def shots(title, cls, n, rng, truth, t0, weapon=0x102, dist=(1.0, 8.0), **kw):
    """n shots at zones drawn evenly; truth: zone -> (where hits land: height m, hit rate, damage)."""
    t = t0
    for _ in range(n):
        t += 0.4
        zone = rng.choice(sorted(truth))
        h, p, dmg = truth[zone]
        hit = rng.random() < p
        K.record_shot(title, cls, None, rng.uniform(*dist), weapon, (h + rng.gauss(0, 0.04), rng.gauss(0.08, 0.03)),
                      "hit" if hit else "miss", -dmg if hit else None, zone=zone, t=t, **kw)
    return t


def rows(db, title, sql="select kind, cls, dist_m, outcome, hp_delta, up_m, zone, attack from samples order by id"):
    with sqlite3.connect(db / title / K.DB_NAME) as c:
        return c.execute(sql).fetchall()


def test_with_no_data_the_plan_is_the_titles_current_constants():
    p = K.dispatch_plan(RE5S, "hp800", None, 3.0, 0x102)
    assert p.aim.value == K.Aim(1.10, 0.0, "chest") and p.aim.source == "default"
    assert p.aim.confidence == 0.0 and p.aim.samples == 0 and p.family == "humanoid" and p.band == "2-5"
    assert p.range.value == (1.5, 22.0) and p.fire_mode.value == "hold" and p.danger.value == 0.0
    assert p.shots_to_kill.value is None and p.hit_rate.value is None and p.windup.value is None
    assert p.lead_s.value is None and p.attack.value is None
    assert all(getattr(p, f).source == "default" for f in ("aim", "range", "fire_mode", "danger", "shots_to_kill"))
    assert K.dispatch_plan(RE5S, "hp800", None, 2.0).danger.value == 1.0             # inside re5_switch.THREAT_R
    re6 = K.dispatch_plan(RE6S, "uEm5200", None, 5.0, 0x0F)
    assert re6.aim.value.up_m == 1.15 and re6.fire_mode.value == "hold" and re6.range.value == (1.4, 18.0)
    assert K.dispatch_plan(RE6S, "uEm5200", None, 5.0, 0x03).fire_mode.value == "tap"   # not in AUTO_IDS
    ps3 = K.dispatch_plan(RE5P, "uEm10", None, 4.0, 0x15)
    assert ps3.fire_mode.value == "hold" and ps3.range.value == (1.1, 30.0) and ps3.danger.value == 0.0
    assert K.dispatch_plan(RE5P, "hp6000", None, 4.0, hp_max=6000).danger.value == 1.0  # a boss: kept off 4.5 m
    re4 = K.dispatch_plan(RE4, "em16.0b.hp1400", (1, 0x26), 1.0, 0x2D)
    assert re4.aim.value == K.Aim(1.52, 0.0, "head") and re4.fire_mode.value == "tap"     # the Striker is a shotgun
    assert re4.danger.value == 1.0 and re4.lead_s.value == pytest.approx(0.7)            # a swing within its reach
    assert K.dispatch_plan(RE4, "em16.0b.hp1400", (1, 0x03), 2.0).danger.value == 0.0
    assert K.dispatch_plan(RE4, "em16.0b.hp6500", None, 1.9).danger.value == 1.0         # the chainsaw: CHAINSAW_KEEP
    p = K.dispatch_plan(RE5S, "hp800", None, 3.0, defaults={"zone": "head", "far_m": 12, "fire_mode": "tap"})
    assert p.aim.value == K.Aim(1.60, 0.0, "head") and p.range.value == (1.5, 12.0) and p.fire_mode.value == "tap"
    unknown = K.dispatch_plan("NEWTITLE", "x", None, None)
    assert unknown.aim.value.zone == "chest" and unknown.danger.value == 0.0
    json.dumps(p.to_dict())


def test_synthetic_shots_converge_on_the_zone_and_offset_that_dispatch_him():
    rng = random.Random(7)
    shots(RE5S, "hp800", 600, rng, MAJINI, NOW - 600)       # headshots land less often but do far more
    assert K.flush(wait=True)
    p = K.dispatch_plan(RE5S, "hp800", None, 4.0, 0x102)
    assert p.aim.value.zone == "head" and p.aim.value.up_m == pytest.approx(1.63, abs=0.03)
    assert p.aim.value.lateral_m == pytest.approx(0.08, abs=0.03)
    assert p.aim.source == "class" and p.aim.confidence > 0.6 and p.aim.samples > 30
    assert p.aim.detail["probe"] == "0x102/2-5"                         # the most specific level with enough hits
    assert p.hit_rate.value == pytest.approx(0.6, abs=0.12) and p.hit_rate.source == "class"
    armoured = {"head": (1.90, 0.3, 120), "chest": (1.30, 0.85, 120), "legs": (0.80, 0.6, 120)}
    shots(RE5S, "uEm21", 600, rng, armoured, NOW - 600)    # his head is no better per hit: the chest stays
    K.flush(wait=True)
    q = K.dispatch_plan(RE5S, "uEm21", None, 4.0, 0x102)
    assert q.aim.value.zone == "chest" and q.aim.value.up_m == pytest.approx(1.30, abs=0.03) and q.family is None


def test_without_health_changes_the_zone_is_chosen_by_hits_and_kills():
    rng = random.Random(4)
    t = NOW - 500
    for _ in range(500):
        t += 0.4
        zone = rng.choice(("head", "chest", "legs"))
        hit = rng.random() < {"head": 0.5, "chest": 0.55, "legs": 0.3}[zone]
        kill = hit and zone == "head" and rng.random() < 0.8              # head hits kill, body hits rarely do
        K.record_shot(RE5S, "hp700", None, 2.5, 0x102, None, "kill" if kill else "hit" if hit else "miss",
                      zone=zone, t=t)
    K.flush(wait=True)
    aim = K.dispatch_plan(RE5S, "hp700", None, 2.5, 0x102).aim               # the default is the chest
    assert aim.value.zone == "head" and aim.value.up_m == 1.60 and aim.source == "class"   # no dot heights: the zone's


def test_the_preferred_range_follows_the_bands_whose_shots_work():
    rng = random.Random(3)
    t = NOW - 900
    for _ in range(500):
        t += 0.4
        d = rng.uniform(0.5, 25.0)
        hit = rng.random() < (0.85 if 5.0 <= d < 10.0 else 0.25)
        K.record_shot(RE5S, "hp700", None, d, 0x102, None, "hit" if hit else "miss", -150 if hit else None, t=t)
    K.flush(wait=True)
    r = K.dispatch_plan(RE5S, "hp700", None, 7.0, 0x102).range
    assert r.value == (5.0, 10.0) and r.source == "class" and r.confidence > 0.5
    assert set(r.detail["bands"]) == set(K.BAND_NAMES)


def test_danger_learns_which_states_come_right_before_the_hits():
    t = NOW - 300.0
    for _ in range(40):                     # a Majini walks (0x10) 2 s, winds up a grab (0x6a) 0.6 s, and it lands
        for _ in range(20):
            t += 0.1
            K.observe(RE5S, [{"id": 7, "cls": "hp800", "state": 0x10, "dist_m": 2.2},
                             {"id": 8, "cls": "hp700", "state": 0x10, "dist_m": 40.0}], t=t)   # too far: not counted
        for _ in range(6):
            t += 0.1
            K.observe(RE5S, [{"id": 7, "cls": "hp800", "state": 0x6A, "dist_m": 1.0}], t=t)
        K.record_damage(RE5S, "hp800", 0x6A, 1.0, "grab", 120, enemy_id=7, t=t)
    K.flush(wait=True)
    grab = K.dispatch_plan(RE5S, "hp800", 0x6A, 1.0)
    walk = K.dispatch_plan(RE5S, "hp800", 0x10, 2.2)
    assert grab.windup.value == pytest.approx(1.0, abs=0.05) and grab.windup.samples >= 35
    assert grab.lead_s.value == pytest.approx(0.5, abs=0.05) and grab.attack.value == "grab"
    assert grab.danger.source == "class" and grab.danger.detail["p"] > 0.5 > walk.danger.detail["p"]
    assert walk.windup.value == pytest.approx(0.0, abs=0.05)               # its onsets come 2.6 s before: no wind-up
    assert "hp700" not in K._classes(K._state()["models"][RE5S])            # 40 m away is not exposure
    # without observe(), the brain's own time in the state still teaches the lead
    for i in range(6):
        K.record_damage(RE5S, "hp700", "lunge", 1.4, "melee", 80, in_state_s=0.8, t=NOW - 20 + i)
    K.flush(wait=True)
    assert K.dispatch_plan(RE5S, "hp700", "lunge", 1.4).lead_s.value == pytest.approx(0.8)


def test_learning_survives_a_service_restart_and_a_bot_hot_reload(db):
    rng = random.Random(11)
    shots(RE6S, "uEm5200", 300, rng, {"head": (1.58, 0.5, 300), "chest": (1.12, 0.8, 100), "legs": (0.72, 0.5, 80)},
          NOW - 400, weapon=0x0F)
    K.flush(wait=True)
    before = K.dispatch_plan(RE6S, "uEm5200", None, 4.0, 0x0F).to_dict()
    assert before["aim"]["source"] == "class" and (db / RE6S / K.DB_NAME).is_file()
    K.reset()                                                  # a restart: nothing in memory
    assert K.dispatch_plan(RE6S, "uEm5200", None, 4.0, 0x0F).aim.source == "default"   # loading, the constants
    K.flush(wait=True)
    assert K.dispatch_plan(RE6S, "uEm5200", None, 4.0, 0x0F).to_dict() == before
    from gbox import hot_reload                                # a bot reload (hot_reload.swap's carry of RELOAD_KEEP)
    snap = dict(K.__dict__)
    mod = importlib.reload(K)
    hot_reload._carry(mod, snap, (*hot_reload.KEEP.get(mod.__name__, ()), *mod.RELOAD_KEEP))
    assert mod._STATE is snap["_STATE"] and mod is K
    assert mod.dispatch_plan(RE6S, "uEm5200", None, 4.0, 0x0F).to_dict() == before
    assert type(mod.dispatch_plan(RE6S, "uEm5200", None, 4.0, 0x0F)) is mod.Plan        # no stale cached plan class
    assert hot_reload.allowed(mod.__name__)                    # a bot module: it reloads in place


def test_the_class_map_shares_equivalent_classes_across_titles():
    assert K.family(RE4, "em16.0b.hp6500") == "chainsaw" and K.family(RE4, "em16.0b.hp1400") == "humanoid"
    assert K.family(RE4, "em20.16.hp3500") == "chainsaw" and K.family(RE4, "em20.0e.hp700") == "humanoid"
    assert K.family(RE5P, "uEm10") == K.family(RE5S, "hp800") == K.family(RE6S, "uEm5200") == "humanoid"
    assert K.family(RE5P, "uEm32") == "crawler" and K.family(RE5S, "hp1") == "critter"
    assert K.family(RE5S, "uEm21") is None and K.family(RE6S, "uEm9999") is None   # nothing says what they are
    assert K.family(RE4, "em99.00.hp10") is None and K.family(RE5S, "unknown") is None
    assert all(r["evidence"] and r["family"] in K.FAMILIES for r in K.class_rows())
    rng = random.Random(5)                       # RE5's Majini teach RE6's zombies until those have data of their own
    shots(RE5S, "hp800", 500, rng, {"head": (1.62, 0.5, 400), "chest": (1.10, 0.8, 120), "legs": (0.70, 0.6, 100)},
          NOW - 600)
    K.flush(wait=True)
    z = K.dispatch_plan(RE6S, "uEm5200", None, 4.0)
    # another title shares where hits land on such a body (RE5's chest hits at 1.10 m, not RE6's default 1.15), but
    # not which zone, range or hit rate: those take RE6's own shots
    assert z.aim.source == "family" and z.aim.value.zone == "chest" and z.aim.value.up_m == pytest.approx(1.10, abs=0.02)
    assert z.range.source == z.hit_rate.source == "default"
    same = K.dispatch_plan(RE5S, "uEm10", None, 4.0)                                      # same title, same family:
    assert same.aim.source == "title_family" and same.aim.value.zone == "head"            # all of it
    assert K.dispatch_plan(RE6S, "uEm9999", None, 4.0).aim.source == "default"           # unmapped: nothing shared
    assert K.dispatch_plan(RE5S, "uEm21", None, 4.0).aim.source == "title"               # ... but its own title's
    assert K.extend_classes(RE6S, {"uEm9999": "humanoid"}, evidence="test: a J'avo") == 1
    assert K.family(RE6S, "uEm9999") == "humanoid" and K.class_rows(RE6S)[0]["match"] == "uEm9999"
    assert K.dispatch_plan(RE6S, "uEm9999", None, 4.0).aim.source == "family"
    assert K.extend_classes(RE4, {"em16.*": "heavy"}, evidence="test override") == 1        # a driver's row wins
    assert K.family(RE4, "em16.0b.hp6500") == "heavy"


def test_old_evidence_ages_out_and_the_store_stays_bounded(db, monkeypatch):
    old = NOW - K.HALF_LIFE_S
    for i in range(40):
        K.record_shot(RE5S, "hp800", None, 3.0, 0x102, None, "hit", -100, t=old + i)
    K.flush(wait=True)
    assert K.dispatch_plan(RE5S, "hp800", None, 3.0, 0x102).hit_rate.samples == pytest.approx(20, abs=1)
    for i in range(1200):                                       # a cell's effective count is capped
        K.record_shot(RE5S, "hp800", None, 3.0, 0x102, None, "miss" if i % 3 else "hit", t=NOW - 100 + i * 0.05)
    K.flush(wait=True)
    cell = K._state()["models"][RE5S]["shot|hp800|*|*|*"]
    assert cell["n"] <= K.CAPS["n"] + 1e-6 and cell["h"] / cell["n"] == pytest.approx(1 / 3, abs=0.05)
    assert cell["N"] == 1240                                    # ... while the raw total keeps every sample
    monkeypatch.setattr(K, "MAX_SAMPLES", 50)
    monkeypatch.setattr(K, "PRUNE_EVERY_S", 0.0)
    for i in range(10):
        K.record_shot(RE5S, "hp800", None, 3.0, 0x102, None, "miss", t=NOW - K.MAX_AGE_S - 1000 + i)
    K.record_shot(RE5S, "hp800", None, 3.0, 0x102, None, "hit", -100, t=NOW)
    K.flush(wait=True)
    n, oldest = rows(db, RE5S, "select count(*), min(ts) from samples")[0]
    assert n <= 50 and oldest >= NOW - K.MAX_AGE_S
    assert K.dispatch_plan(RE5S, "hp800", None, 3.0, 0x102).hit_rate.value is not None


def test_recording_only_queues_on_the_bot_thread(monkeypatch):
    calls = []
    real = K._connect

    def spy(path):
        calls.append(threading.current_thread() is threading.main_thread())
        return real(path)
    monkeypatch.setattr(K, "_connect", spy)
    t0 = time.perf_counter()
    for i in range(2000):
        K.record_shot(RE5S, "hp800", 0x10, 3.0, 0x102, (1.1, 0.0), "hit" if i % 2 else "miss", -100, enemy_id=i // 4)
        K.observe(RE5S, [{"id": i // 4, "cls": "hp800", "state": 0x10 + i % 3, "dist_m": 3.0}])
        K.dispatch_plan(RE5S, "hp800", 0x10, 3.0, 0x102)
    per_tick = (time.perf_counter() - t0) / 2000
    assert K.flush(wait=True)
    assert calls and not any(calls)                             # SQLite only ever on the learner's thread
    assert per_tick < 0.003                                     # three calls: well under a 30 Hz tick
    assert len(rows(K.root(), RE5S, "select id from samples")) == 2000
    K.record_shot("", "hp800", None, 3.0, None, None, "hit")    # bad input is dropped, never raised
    K.record_shot(RE5S, "hp800", None, float("nan"), None, ("x", 1), "maybe")
    K.record_damage(None, None, None, None, None, None)
    K.observe(RE5S, [None, (1,), {"cls": "hp800"}, ("hp800", 1, "far")])
    assert isinstance(K.dispatch_plan(None, None, object(), "far", []), K.Plan)


def test_the_last_facts_are_written_when_the_process_exits(db, monkeypatch):
    monkeypatch.setattr(K, "_kick", lambda force=False: None)        # at interpreter shutdown no thread can start
    K.record_shot(RE5S, "hp800", None, 3.0, 0x102, None, "hit", -100, t=NOW)
    K.observe(RE5S, [{"id": 1, "cls": "hp800", "state": 1, "dist_m": 2.0}], t=NOW)
    K.observe(RE5S, [{"id": 1, "cls": "hp800", "state": 2, "dist_m": 2.0}], t=NOW + 0.2)
    assert not (db / RE5S / K.DB_NAME).exists()
    K._at_exit()
    assert rows(db, RE5S, "select kind, outcome from samples") == [("shot", "hit")]
    assert rows(db, RE5S, "select seconds, onsets from exposure") == [(pytest.approx(0.2), 1.0)]
    K._at_exit()                                                     # nothing left: no work, no error


def test_shots_to_kill_counts_the_shots_at_one_enemy_until_the_kill():
    t = NOW - 200
    for enemy in range(8):
        for k in range(4):                                      # three misses then the kill: 4 shots each
            t += 0.5
            K.record_shot(RE5S, "hp800", None, 3.0, 0x102, None, "kill" if k == 3 else "miss",
                          -800 if k == 3 else None, enemy_id=1000 + enemy, t=t)
    K.flush(wait=True)
    p = K.dispatch_plan(RE5S, "hp800", None, 3.0, 0x102, hp=400, hp_max=800)
    assert p.shots_to_kill.detail["full_health_shots"] == pytest.approx(4.0)
    assert p.shots_to_kill.value == pytest.approx(2.0) and p.shots_to_kill.source == "class"   # half his health left
    t = NOW - 100                                               # no kills seen: estimated from damage per shot
    for i in range(40):
        K.record_shot(RE6S, "uEm5210", None, 3.0, 0x0F, None, "hit" if i % 2 else "miss", -100 if i % 2 else None, t=t + i)
    K.flush(wait=True)
    est = K.dispatch_plan(RE6S, "uEm5210", None, 3.0, 0x0F, hp_max=700).shots_to_kill
    assert est.source == "estimate" and est.value == pytest.approx(14.0)   # 700 / (0.5 x 100)


def test_fire_mode_switches_only_when_another_mode_does_clearly_more():
    t = NOW - 400
    for i in range(120):                                        # taps: a shot every 0.5 s, 60 % hits
        t += 0.5
        K.record_shot(RE6S, "uEm5200", None, 4.0, 0x03, None, "hit" if i % 5 < 3 else "miss", -100 if i % 5 < 3 else None,
                      fire_mode="tap", t=t)
    t += 5
    for i in range(120):                                        # held: a shot every 0.1 s, 40 % hits
        t += 0.1
        K.record_shot(RE6S, "uEm5200", None, 4.0, 0x03, None, "hit" if i % 5 < 2 else "miss", -100 if i % 5 < 2 else None,
                      fire_mode="hold", t=t)
    K.flush(wait=True)
    f = K.dispatch_plan(RE6S, "uEm5200", None, 4.0, 0x03).fire_mode
    assert f.value == "hold" and f.source == "class" and f.detail["per_s"]["hold"] > f.detail["per_s"]["tap"]


def test_the_brains_outcome_dicts_map_onto_the_database(db):
    base = {"kind": "shot", "title": RE5S, "enemy_id": 0x1234, "enemy_class": "hp800", "state": 0x10,
            "distance": 350.0, "weapon": 0x102, "aim_offset": (0.0, 160.0, 0.0), "plan_source": "default"}
    K.record_outcome({**base, "t": NOW - 6, "hit": True, "hp_delta": -400, "where": "head"})
    K.record_outcome({**base, "t": NOW - 5, "hit": False, "where": "wall"})
    K.record_outcome({**base, "t": NOW - 4, "hit": True, "hp_delta": -100, "where": "body"})   # 1.6 m is no body height
    K.record_outcome({"kind": "damage", "title": RE5S, "t": NOW - 3, "enemy_id": 0x1234, "enemy_class": "hp800",
                      "state": 0x6A, "distance": 90.0, "hp_delta": -120, "attack": "grab"})
    K.record_outcome("not a dict")
    K.flush(wait=True)
    assert rows(db, RE5S) == [("shot", "hp800", 3.5, "hit", -400.0, 1.6, "head", None),
                              ("shot", "hp800", 3.5, "miss", None, 1.6, "head", None),
                              ("shot", "hp800", 3.5, "hit", -100.0, None, "chest", None),
                              ("damage", "hp800", 0.9, None, 120.0, None, None, "grab")]


def test_class_and_state_keys_come_from_what_the_drivers_read():
    assert K.class_key({"class": "uEm10", "hp_max": 800}) == "uEm10"
    assert K.class_key({"id": 0x16, "type": 0x0B, "hp_max": 6500}) == "em16.0b.hp6500"
    assert K.class_key({"ptr": 0x30000000, "native_aim": {"kind": "uEm32"}, "hp_max": 900}) == "uEm32"
    assert K.class_key({"slot": 3, "ptr": 0x30000000, "hp": 800, "hp_max": 800}) == "hp800"
    assert K.class_key({"id": 0x7F00001234, "type": 3, "hp_max": 700}) == "hp700"   # a pointer is no EmMgr id
    assert K.class_key({"class": None, "hp_max": 400, "state": 3}) == "hp400"
    assert K.class_key(None) == K.class_key({}) == "unknown"
    assert K.state_key((1, 0x26)) == "01:26" and K.state_key(0x6A) == "0x6a" and K.state_key("free") == "free"
    assert K.state_key(None) is None and K.state_key("*") == "_*" and K.state_key(b"\x01\x2d") == "01:2d"
    assert K.state_kind(RE4, "01:26") == "swing" and K.state_kind(RE4, "01:30") == "hold"
    assert K.state_kind(RE4, "02:26") is None and K.state_kind(RE5S, "0x6a") is None
    assert K.extend_states(RE5S, {"0x6a": "grab"}, evidence="test") == 1 and K.state_kind(RE5S, "0x6a") == "grab"
    assert K.band(1.99) == "0-2" and K.band(25) == "20+" and K.band(None) is None and K.band(-1) is None
    off = K.Aim(1.6, 0.5, "head").world_offset((0, 0, 0), (0, 0, 1000))   # facing +z, the right is -x
    assert off == pytest.approx((-50.0, 160.0, 0.0))
    up, lat = K._offset((-50.0, 160.0, 1000.0), (0.0, 0.0, 1000.0), (0.0, 0.0, 0.0), 100.0)
    assert up == pytest.approx(1.6) and lat == pytest.approx(0.5)


def test_the_read_route_shows_each_class_plan_samples_and_recent_outcomes(tmp_path):
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from gbox.mercs import reviewer
    K.configure(tmp_path / "mercs" / "knowledge")
    rng = random.Random(2)
    shots(RE5S, "hp800", 120, rng, MAJINI, NOW - 300)
    K.record_damage(RE5S, "hp800", 0x6A, 1.0, "grab", 100, t=NOW - 10)
    K.flush(wait=True)
    app = FastAPI()

    def auth(request: Request):
        return request.headers.get("x-gbox-actor", "operator")
    reviewer.routes(app, SimpleNamespace(data_dir=tmp_path), auth)
    c = TestClient(app)
    listing = c.get("/api/mercs/enemy-knowledge", headers={"x-gbox-actor": "agent"}).json()
    assert listing["titles"] == [{"title": RE5S, "shots": 120, "damage": 1, "sources": {"live": 121},
                                  "last_sample_at": listing["titles"][0]["last_sample_at"], "classes": 1,
                                  "cells": listing["titles"][0]["cells"]}]
    one = c.get("/api/mercs/enemy-knowledge", params={"title": RE5S, "recent": 5}).json()
    row = one["classes"][0]
    assert row["class"] == "hp800" and row["family"] == "humanoid" and row["plan"]["aim"]["source"] == "class"
    assert row["samples"]["shots"] == pytest.approx(120, abs=1) and row["samples"]["damage"] == pytest.approx(1)
    assert row["samples"]["shots_total"] == 120 and row["samples"]["damage_total"] == 1
    assert len(row["recent"]) == 5 and row["recent"][0]["kind"] == "damage"
    assert set(row["danger_by_band"]) == set(K.BAND_NAMES)
    assert any(s["state"] == "0x6a" and s["attack"] == "grab" for s in row["states"])
    assert any(r["match"] == "hp800" for r in one["class_map"])
    assert c.get("/api/mercs/enemy-knowledge", params={"title": RE5S, "enemy_class": "hp800"}).status_code == 200
    assert c.get("/api/mercs/enemy-knowledge", params={"title": RE5S, "enemy_class": "uEm99"}).status_code == 404
    assert c.get("/api/mercs/enemy-knowledge", params={"title": "NOPE"}).status_code == 404
    assert c.get("/api/mercs/enemy-knowledge", params={"title": "../x"}).status_code == 400


def test_the_round_numbers_reach_stats_and_the_round_report():
    from gbox.mercs import round_reports as R
    K.round_begin(RE5S)
    rng = random.Random(9)
    shots(RE5S, "hp800", 80, rng, MAJINI, NOW - 100)
    K.record_damage(RE5S, "hp800", None, 1.2, "melee", 90, t=NOW - 50)
    K.flush(wait=True)
    stats = {}
    out = K.round_end(RE5S, stats)
    assert out == {k: stats[k] for k in out} and stats["enemy_db_shots"] == 80 and stats["enemy_db_damage"] == 1
    assert stats["enemy_db_classes_seen"] == 1 and stats["enemy_db_classes"] == 1 and stats["enemy_db_samples"] >= 80
    assert stats["enemy_db_summary"].startswith("hp800(humanoid): 80 shots") and len(stats["enemy_db_summary"]) <= 600
    row = {"id": "a" * 32, "ts": NOW, "stage": "s", "mode": "no_mercy", "character": "Chris", "outcome": "died",
           "observed": dict(stats)}
    report = R.report_for(RE5S, row, {"state": "unavailable", "rounds": []}, None)
    assert report["metrics"]["enemy_knowledge"]["enemy_db_shots"] == 80
    assert report["enemy_knowledge"] == stats["enemy_db_summary"]
    assert "enemy knowledge database" in R.request_document(report, 1, NOW)["body"]
    K.round_begin(RE5S)                                       # the next round starts from zero
    assert K.round_stats(RE5S)["enemy_db_shots"] == 0 and K.round_stats(RE5S)["enemy_db_classes"] == 1


def test_play_round_opens_and_closes_the_rounds_numbers(tmp_path, monkeypatch):
    from gbox.mercs import engine, lessons
    from gbox.mercs.driver import Driver
    monkeypatch.setattr(lessons, "ROOT", tmp_path / "mercs" / "lessons")
    clock = [NOW]

    class Drv(Driver):
        map_id = RE5S

        def __init__(self):
            self.n = 0

        def snapshot(self, m):
            self.n += 1
            return {"player": {"ptr": 1, "hp": 100, "hp_max": 100}, "timer": 50.0 if self.n < 6 else 0.0}

        def screen(self, m, snap):
            return "playing" if self.n < 6 else "results"

    class Brain:
        _round_started = 1.0
        shots = 0

        def tick(self, snap):
            self.shots += 1
            K.record_shot(RE5S, "hp800", None, 3.0, 0x102, None, "hit", -100, t=clock[0])
            return {"hold": set()}

        def prompt_ok(self, *a):
            return False

        def save(self):
            pass

    def sleep(s):
        clock[0] += s
    stats, brain = {"enemy_db_shots": 99}, Brain()
    why = engine.play_round({"map_id": RE5S}, object(), lambda rows: None, lambda: clock[0] > NOW + 30, stats,
                            driver=Drv(), brain=brain, sleep=sleep, clock=lambda: clock[0])
    assert why == "round" and brain.shots == 5 and stats["enemy_db_shots"] == 5     # opened at the round's start
    assert stats["enemy_db_classes_seen"] == 1 and "enemy_db_error" not in stats
    with sqlite3.connect(tmp_path / "mercs" / "curriculum" / RE5S / "rounds.sqlite") as c:
        (data,), = c.execute("select data from rounds").fetchall()
    assert json.loads(data)["enemy_db_shots"] == 5                                   # in the round's Notebook row


def test_rebuild_replays_the_samples_into_the_same_cells(db):
    rng = random.Random(13)
    shots(RE5S, "hp800", 200, rng, MAJINI, NOW - 300, enemy_id=None)
    t = NOW - 100.0
    for _ in range(14):
        for state, n in ((0x10, 10), (0x6A, 5)):
            for _ in range(n):
                t += 0.1
                K.observe(RE5S, [{"id": 3, "cls": "hp800", "state": state, "dist_m": 1.5}], t=t)
        K.record_damage(RE5S, "hp800", 0x6A, 1.5, "grab", 100, enemy_id=3, t=t)
    K.flush(wait=True)
    live = K.dispatch_plan(RE5S, "hp800", 0x6A, 1.5, 0x102).to_dict()
    counts = K.rebuild(RE5S)
    assert counts["shots"] == 200 and counts["damage"] == 14 and counts["exposure_days"] >= 1
    K.reset()
    K.dispatch_plan(RE5S, "hp800", 0x6A, 1.5, 0x102)
    K.flush(wait=True)
    again = K.dispatch_plan(RE5S, "hp800", 0x6A, 1.5, 0x102).to_dict()
    assert again["aim"]["value"]["zone"] == live["aim"]["value"]["zone"]
    assert again["aim"]["value"]["up_m"] == pytest.approx(live["aim"]["value"]["up_m"], abs=0.01)
    assert again["range"]["value"] == pytest.approx(live["range"]["value"])
    for field in ("hit_rate", "windup", "lead_s"):
        assert again[field]["value"] == pytest.approx(live[field]["value"], abs=0.05), field
        assert again[field]["source"] == live[field]["source"] != "default"
    assert again["attack"]["value"] == live["attack"]["value"] == "grab"
    assert again["danger"]["detail"]["events"] == pytest.approx(live["danger"]["detail"]["events"], abs=0.5)
    assert again["danger"]["detail"]["exposure_s"] == pytest.approx(live["danger"]["detail"]["exposure_s"], rel=0.05)


def test_a_running_bot_picks_up_a_rebuilt_database(db):
    K.record_shot(RE5S, "hp800", None, 3.0, 0x102, None, "hit", -100, t=NOW - 50)
    K.flush(wait=True)
    with sqlite3.connect(db / RE5S / K.DB_NAME) as c:              # another process (the seed) adds samples
        for i in range(30):
            c.execute(f"insert into samples({','.join(K.SAMPLE_COLS)}) values ({','.join('?' * len(K.SAMPLE_COLS))})",
                      (NOW - 40 + i, "shot", "hp800", None, "0x102", 3.0, "hit", -100.0, None, None, None, None, None,
                       None, None, "seed:test", None))
    K.rebuild(RE5S)
    K.record_shot(RE5S, "hp800", None, 3.0, 0x102, None, "miss", t=NOW - 5)   # the bot's next fact: a reload first
    K.flush(wait=True)
    assert K.dispatch_plan(RE5S, "hp800", None, 3.0, 0x102).hit_rate.samples == 32


# --- the seed import ------------------------------------------------------------------------------------------------------
def seed_tree(tmp_path):
    """A data dir with an RE4 and an RE5 PS3 round map and a ledger of two RE5 Switch hits (one held)."""
    from gbox.store import Store
    data = tmp_path / "data"
    maps = data / "mercs" / "round_maps"
    (maps / RE4 / "r400").mkdir(parents=True)
    (maps / RE5P / "Prison").mkdir(parents=True)
    t0 = NOW - 3600
    (maps / RE4 / "r400" / "a.json").write_text(json.dumps({"title": RE4, "round_id": "r4", "started": t0, "shots": [],
        "events": [{"t": t0 + 5, "kind": "hit", "by": "swing slot 51 id 0x16 type 0xb hp 1400/1400 at 1000 (eta 0.0)",
                    "attack": "swing", "dist": 1000},
                   {"t": t0 + 9, "kind": "hit", "by": "boss chainsaw slot 22 id 0x16 type 0xc hp 6500/6500 at 1500 (eta 0.4)",
                    "attack": "chainsaw", "dist": 1500},
                   {"t": t0 + 12, "kind": "hit", "attack": "unattributed", "dist": 23000},
                   {"t": t0 + 13, "kind": "stuck"}]}))
    (maps / RE5P / "Prison" / "b.json").write_text(json.dumps({"title": RE5P, "round_id": "r5", "started": t0,
        "shots": [{"t": 1.0, "wid": 21, "result": "hit", "dist": 350, "where": "head", "zone": "body"},
                  {"t": 2.0, "wid": 21, "result": "miss", "dist": 1200, "where": None, "zone": "body"},
                  {"t": 3.0, "wid": 21, "result": "unattributed", "dist": 400}],
        "events": [{"t": t0 + 4, "kind": "hit", "attack": "melee", "dist": 120, "loss": 63, "boss": False}]}))
    (maps / RE5S / "Public_Assembly").mkdir(parents=True)          # the same hits the ledger has: never twice
    (maps / RE5S / "Public_Assembly" / "c.json").write_text(json.dumps({"title": RE5S, "round_id": "r7", "started": t0,
        "events": [{"t": t0 + 30, "kind": "hit", "attack": "melee", "dist": 50, "loss": 30}]}))
    runs = data / "mercs" / "lessons" / RE5P / "runs"
    runs.mkdir(parents=True)
    (runs / "20261026-1.jsonl").write_text("\n".join(json.dumps(r) for r in (
        {"kind": "navigation_sample", "t": t0},
        {"kind": "shot", "t": t0 + 1.5, "result": "hit", "dot": "body", "dist_cm": 350, "weapon": 21},   # the map's
        {"kind": "shot", "t": t0 - 100, "result": "headshot", "dot": None, "dist_cm": 800, "weapon": 21},
        {"kind": "shot", "t": t0 + 500, "result": "miss: the ray passed him (aim)", "dot": None, "dist_cm": 300,
         "weapon": 3},
        {"kind": "shot", "t": t0 + 501, "result": "bow impact unconfirmed: no attributable damage", "weapon": 15},
    )) + "\nnot json\n")
    store = Store(data)
    snap = {"player": {"ptr": 1, "pos": [0.0, 0.0, 0.0], "hp": 485, "hp_max": 1000, "motion": 107},
            "enemies": [{"slot": 0, "ptr": 11, "pos": [50.0, 0.0, 0.0], "hp": 550, "hp_max": 800},
                        {"slot": 1, "ptr": 12, "pos": [900.0, 0.0, 0.0], "hp": 700, "hp_max": 700},
                        {"slot": 2, "ptr": 13, "pos": [10.0, 0.0, 0.0], "hp": 0, "hp_max": 800}]}
    look = {"shots": [{"t": t0 + 20, "weapon": "0x102", "gate": "dot on body", "target": {"id": "12", "kind": "majini",
                       "dist_m": 9.0, "bearing_deg": 0}, "dot_on": "target", "outcome": "hit:majini", "hp_delta": -250},
                      {"t": t0 + 21, "weapon": "0x102", "gate": "point blank", "target": {"id": "99", "dist_m": 0.6},
                       "dot_on": "target", "outcome": "miss:no_damage", "hp_delta": None},
                      {"t": t0 + 22, "weapon": "0x102", "gate": "dot on head", "target": {"id": "11", "dist_m": 0.5},
                       "outcome": "unknown"}]}
    later = {"shots": [{"t": t0 + 40, "weapon": "0x102", "gate": "dot on body", "target": {"id": "12", "dist_m": 8.0},
                        "dot_on": "target", "outcome": "hit:majini", "hp_delta": -700}]}   # killed: gone from the next
    gone = {**snap, "enemies": [e for e in snap["enemies"] if e["ptr"] != 12]}             # snapshot
    for k, (motion, now_snap, now_look) in enumerate(((107, snap, look), (0, snap, look), (0, gone, later))):
        event = {"schema": "gbox.player_damage/1", "event_id": f"e{k}" * 4, "session_id": "s1", "round_id": "r6",
                 "title": RE5S, "observed_at": t0 + 30 + k * 10, "loss": 30, "hp_before": 515, "hp_after": 485,
                 "hp_max": 1000, "snapshot": {**now_snap, "player": {**snap["player"], "motion": motion}},
                 "logic": {"look": now_look}}
        ref = store.put_artifact(json.dumps({"event": event, "moment": {}}).encode(), "r.json", "application/json", {})
        store.put("player_damage", f"d{k}", {"id": f"d{k}", "event_id": event["event_id"], "session_id": "s1",
                                             "game_id": "52d15709be0fda1a", "observed_at": event["observed_at"],
                                             "receipt": ref.sha256, "loss": 30})
    store.db.close()
    return data


def test_the_seed_reads_round_maps_and_the_damage_ledger_read_only(tmp_path):
    from gbox.mercs import enemy_db_seed as S
    data = seed_tree(tmp_path)

    def files():                                             # (SQLite may add its -shm / -wal beside a reader)
        return sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in data.rglob("*")
                      if p.is_file() and not p.name.endswith(("-shm", "-wal")))
    before = files()
    by_title, stats = S.collect(data)
    found = S.tally(by_title)
    assert found[RE4]["classes"] == {"em16.0b.hp1400": {"shots": 0, "hits": 0, "damage": 1, "bands": {"0-2": 1}},
                                     "em16.0c.hp6500": {"shots": 0, "hits": 0, "damage": 1, "bands": {"0-2": 1}},
                                     "(unattributed)": {"shots": 0, "hits": 0, "damage": 1, "bands": {"20+": 1}}}
    assert found[RE5P]["classes"]["unknown"] == {"shots": 4, "hits": 2, "damage": 1,
                                                  "bands": {"2-5": 2, "10-20": 1, "5-10": 1, "0-2": 1}}
    assert found[RE5P]["sources"] == {S.SOURCE_MAPS: 3, S.SOURCE_LESSONS: 2}   # the lesson row the map has: once
    assert stats["lesson_shots_in_round_maps"] == 1
    assert [e["z"] for e in by_title[RE5P] if e["src"] == S.SOURCE_LESSONS] == ["head", None]
    re5s = found[RE5S]["classes"]
    assert re5s["hp800"]["damage"] == 3 and re5s["hp700"] == {"shots": 2, "hits": 2, "damage": 0, "bands": {"5-10": 2}}
    assert re5s["unknown"]["shots"] == 1                     # a target no snapshot of the session ever showed
    assert stats["look_classes_remembered"] == 1             # the killed one: his class from the session's last sight
    assert found[RE5S]["sources"] == {S.SOURCE_LEDGER: 3, S.SOURCE_LOOK: 3}   # the shots once, not per receipt
    held = [e for e in by_title[RE5S] if e["k"] == "damage"]
    assert [e["a"] for e in held] == ["hold", None, None] and held[0]["d"] == pytest.approx(0.5)
    kinds = {e["c"]: e["s"] for e in by_title[RE4] if e["c"]}
    assert kinds == {"em16.0b.hp1400": "~swing", "em16.0c.hp6500": "~chainsaw"}
    assert stats["maps"] == 3 and stats["receipts"] == 3 and stats["map_hits_in_ledger"] == 1
    assert files() == before                                 # nothing in the data dir changed
    out = tmp_path / "knowledge"
    written = S.write(by_title, out)
    assert written[RE4]["damage"] == 3 and written[RE5S]["shots"] == 3 and written[RE5P]["shots"] == 4
    K.configure(out)
    K.dispatch_plan(RE4, "em16.0b.hp1400", (1, 0x26), 1.0)
    K.flush(wait=True)
    plan = K.dispatch_plan(RE4, "em16.0b.hp1400", (1, 0x26), 1.0)
    assert plan.attack.value is None                         # one hit is not yet a pattern (MIN attack 3)
    view = K.inspect(RE4, root_dir=out)
    assert {c["class"] for c in view["classes"]} == {"em16.0b.hp1400", "em16.0c.hp6500"}
    assert json.loads(view["meta"]["seeded"])["samples"] == {"seed:round_maps": 3}
    again = S.write(by_title, out)                           # a second run replaces its own seed, never doubles it
    assert again[RE4]["damage"] == 3
    assert S.main(["--data-dir", str(data), "--dry-run"]) == 0
