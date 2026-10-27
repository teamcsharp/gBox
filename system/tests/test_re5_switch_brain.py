"""RE5 Switch on the RE5 PS3 combat core (gbox.mercs.titles.re5_switch_brain; operator 2026-10-27: "I assume the bot
will get the same mind that we trained on the ps5"): the Switch snapshot in the PS3 combat layer's fields, the title IO,
the PS3 pad on Type D, and the Switch bot handing its fight over while its survival rules still come first."""
import pytest

from gbox.mercs.titles import re5_combat as C
from gbox.mercs.titles import re5_switch as R
from gbox.mercs.titles import re5_switch_brain as SB

MUZZLE = (0.0, 140.0, 30.0)
GUN = {"slot": 3, "id": 0x102, "type": 1, "item": 0x02, "rounds": 50, "cap": 50, "grid": 3, "hand": True}
FOE = (0.0, 0.0, 500.0)


@pytest.fixture(autouse=True)
def _brain(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", True)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)


def snap(enemies=((FOE, 800),), dot=None, motion=0, up=None, hp=1000):
    """Chris at the origin facing +z (a Switch snapshot: re5_switch.snapshot's fields)."""
    return {"player": {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": hp, "hp_max": 1000,
                       "motion": motion},
            "enemies": [{"slot": i, "ptr": 10 + i, "pos": pos, "hp": h, "hp_max": 800} for i, (pos, h) in enumerate(enemies)],
            "inventory": [dict(GUN)], "timer": 100.0, "kills": 0, "combo": 0, "combo_timer": 0.0, "score": 0,
            "laser": {"from": MUZZLE, "at": dot, "up": True if up is None else up} if dot else
                     {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot(tmp_path):
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0], learn_dir=tmp_path, lessons=lambda e: None), clock


def test_the_switch_snapshot_in_the_ps3_combat_layers_fields(tmp_path):
    f = SB.Fighter(None, {}, lambda: 0.0, learn_dir=tmp_path, lessons=lambda e: None)
    assert isinstance(f.combat, C.Combat) and isinstance(f.combat.io, SB.SwitchIO) and f.combat.map_id == SB.MAP_ID
    v = f.view(snap(dot=(0.0, 110.0, 500.0), motion=26), 1.0)
    assert v["player"]["action"] == 2 and v["player"]["pitch"] is None and v["laser"] == {"from": MUZZLE,
                                                                                         "at": (0.0, 110.0, 500.0)}
    assert v["enemies"][0]["ptr"] == 10 and v["inventory"][0]["item"] == 0x02 and v["prompt"] is None
    assert f.io.player_ptr() == 0x5D00001000 and f.io.fire_command(0x5D00001000) == 0
    assert [SB.action_of(m) for m in (0, 1, 7, 22, 26, 29, 32, 106, 113)] == [0, 1, 1, 0, 2, 2, 0, 4, 4]
    shot = f.view(snap(dot=(0.0, 110.0, 500.0), motion=29, up=False), 1.3)     # the dropout in a shot
    assert shot["laser"] == v["laser"] and f.flickering and f.io.fire_command(1) == 4
    late = f.view(snap(dot=(0.0, 110.0, 500.0), motion=29, up=False), 1.0 + SB.FLICKER_S + 0.1)
    assert late["laser"] is None and not f.flickering
    f.view(snap(motion=22), 3.0)
    assert f.last_ray is None                                       # the gun went down: no stand-in


def test_the_ps3_pad_on_type_d():
    assert SB.switch_act({"hold": {"l1", "r1", "rleft"}}) == {"hold": ("rleft", "zl", "zr")}
    assert SB.switch_act({"hold": {"ldown", "cross"}}) == {"hold": ("b", "ldown")}       # the quick turn
    assert SB.switch_act({"hold": {"l1", "cross"}}) == {"hold": ("b", "zl")}             # reload (ZL + B)
    assert SB.switch_act({"tap": "square"}) == {"tap": "y"} and SB.switch_act({"hold": set()}) == {"hold": ()}


def test_the_bot_raises_fires_through_a_dropout_and_steers_by_the_ps3_core(tmp_path):
    b, clock = bot(tmp_path)
    assert b.tick(snap())["hold"] == ("zl",) and b.doing == "raise"
    clock[0] = 0.3
    assert b.tick(snap(dot=(0.0, 110.0, 500.0), motion=26))["hold"] == ("zl", "zr") and b.doing == "fire"
    clock[0] = 0.35
    assert b.tick(snap(dot=(0.0, 111.0, 500.0), motion=29))["hold"] == ("zl", "zr")
    clock[0] = 0.4
    assert b.tick(snap(dot=(0.0, 111.0, 500.0), motion=29, up=False))["hold"] == ("zl", "zr")   # dropout: still
    assert b.stats["trigger_s"] == pytest.approx(0.1) and b.stats["flicker_s"] == pytest.approx(0.05)
    clock[0] = 0.45
    act = b.tick(snap(dot=(60.0, 111.0, 500.0), motion=26))                    # 7 deg right of him: slew left
    assert act["hold"] == ("rright", "zl") and b.doing == "aim" and "slewing" in b.why
    assert b.stats["fire_gate"].startswith("slewing")


def test_one_behind_gets_the_ps3_cores_quick_turn_on_type_d(tmp_path):
    b, clock = bot(tmp_path)
    act = b.tick(snap(enemies=(((0.0, 0.0, -500.0), 800),)))
    assert act["hold"] == ("b", "ldown") and b.doing == "quick_turn"


def test_survival_still_comes_first_and_a_brain_error_falls_back(tmp_path, monkeypatch):
    b, clock = bot(tmp_path)
    act = b.tick(snap(motion=106))                                           # held: break free, not the fight
    assert b.doing == "held" and act["hold"] in (("lleft",), ("lright",))
    b, clock = bot(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("torn snapshot")
    monkeypatch.setattr(b.fighter, "fight", boom)
    act = b.tick(snap())
    assert b.stats["brain_error"] == "fight RuntimeError: torn snapshot" and act["hold"] == ("zl",)   # the Switch's


def test_the_combat_layer_writes_into_the_switch_look_and_the_round_counters(tmp_path):
    b, clock = bot(tmp_path)
    assert b.fighter.combat.look is b.look
    for k in R.BRAIN_COUNTERS + ("flicker_s", "trigger_s", "t_fire", "t_reposition"):
        assert k in R.RE5Switch.round_counters
    b.save()                                                                 # the round's learning: no error
    assert "brain_error" not in b.stats
