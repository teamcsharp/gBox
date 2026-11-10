"""RE5 Switch: doors and windows (operator 2026-11-10: "the bot should know tapping on the key allows them to kick open
the door thus being able to go through it and pressing it opens the door ... If an on screen indicator for a door or
window pops up. Have the bot log, and internalize that and remember it for next time"). Live that night (Prison, No
Mercy, Sheva, 00:08 UTC): "(Y) Open" up at a door for over 10 s and never pressed, kills 390 of 400 for 136 s, every
one left in the census a crow - the door's prompt was typed "other", pressed only with an enemy within PROMPT_CLEAR_R."""
import json
import math

import pytest

from gbox.mercs.titles import re5_switch as R

STAGE = R.STAGE_KEY.format("unknown")                 # (no stage read in a synthetic round)
DOOR_OBJ, PLAYER = 0x5D60000000, 0x5D00001000


@pytest.fixture(autouse=True)
def _quiet(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    monkeypatch.setattr(R, "MINES", False)
    monkeypatch.setattr(R, "DOOR_FILE", tmp_path / "door_spots.json")
    monkeypatch.setattr(R, "DOOR_LOG", tmp_path / "re5-switch-doors.jsonl")
    monkeypatch.setattr(R, "MAP_GOAL_LOG", tmp_path / "map-goals.log")


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def door(label=41, kind=1, token="press:y", keys=("y",), mode=1, owner=DOOR_OBJ, cls=None, target_pos=None):
    """A stage object's button as re5_switch_prompt.selected_prompt reads it (+ snapshot's prompt_owner fields)."""
    return {"token": token, "keys": keys, "button": 0x5D20000000, "kind": kind, "mode": mode, "priority": 33,
            "key_index": 1, "label": label, "owner": owner, "target": 0, "count": 0, "owner_class": cls,
            "target_pos": target_pos}


def majini(i, pos, **more):
    return {"ptr": 10 + i, "pos": pos, "hp": 800, "hp_max": 800, "class": "uEm10", **more}


def crow(i, pos):
    return {"ptr": 40 + i, "pos": pos, "hp": 1, "hp_max": 1, "class": "uEm62"}


def snap(enemies=(), pr=None, pos=(0.0, 0.0, 0.0), rot=0.0, kills=390, motion=0):
    return {"player": {"ptr": PLAYER, "pos": pos, "rot": rot, "hp": 1000, "hp_max": 1000, "motion": motion,
                       "aim_pitch": None},
            "enemies": list(enemies), "inventory": [], "kills": kills,
            "laser": {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}, "prompt": pr, "prompt_read": True}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def remembered(*spots):
    R.DOOR_FILE.write_text(json.dumps({STAGE: [list(s_) for s_ in spots]}), encoding="utf-8")


def events():
    return [json.loads(line)["event"] for line in R.DOOR_LOG.read_text(encoding="utf-8").splitlines()]


ROOF_CROWS = [crow(0, at(900, 0, y=400.0)), crow(1, at(1500, 120, y=600.0))]


# --- which prompt is a door's ---------------------------------------------------------------------------------------
def test_a_door_prompt_is_taken_at_once_with_only_crows_around():
    b, clock = bot()
    act = b.tick(snap(ROOF_CROWS, pr=door()))        # (main: "other", nobody within PROMPT_CLEAR_R - never pressed)
    assert act["hold"] == ("y",) and b.doing == "prompt" and b.stats["prompts_seen_door"] == 1
    clock[0] = 0.05
    assert b.tick(snap(ROOF_CROWS, pr=door()))["hold"] == ()                 # let go: the next one a fresh press
    clock[0] = 0.1
    assert b.tick(snap(ROOF_CROWS, pr=door()))["hold"] == ("y",)            # ... the double tap kicks it open
    b2, _ = bot()                                     # the kick: his own action, tapped, nobody near
    act = b2.tick(snap(ROOF_CROWS, pr=door(label=43, kind=2, token="mash:y", mode=3, owner=PLAYER)))
    assert act["hold"] == ("y",) and b2.stats["prompts_seen_door"] == 1
    b3, _ = bot()                                     # a crow at his feet never holds a door
    act = b3.tick(snap([crow(0, at(80, 10))] + ROOF_CROWS, pr=door()))
    assert act["hold"] == ("y",) and not b3.stats.get("door_holds")


@pytest.mark.parametrize("pr, near, want, what", [
    (door(cls="uOm1103"), (), "door", "window"),                              # the window's class: whatever its kind
    (door(kind=3, label=12, cls="uOm100c"), (), "door", "door"),
    (door(kind=0, label=256, owner=0x5D50000000), (), "other", None),         # the item chest (the start's box)
    (door(kind=0, label=99, cls="uOm088a"), (), "other", None),               # ... by its class too
    (door(kind=3, label=12), (), "other", None),                              # an area pickup
    (door(kind=2, label=100, token="press:zl", keys=("zl",)), (), "other", None),   # the bomb's Place
    (door(kind=2, label=43, token="mash:y", mode=3, owner=PLAYER), (majini(0, at(150, 0)),), "other", None),  # melee
    (door(kind=1, label=1), (), "other", None),                               # (a pickup's label on a stage object)
])
def test_what_is_a_door(pr, near, want, what):
    b, _ = bot()
    s = snap(list(near), pr=pr)
    assert b._prompt_type(pr, s) == want
    assert b._door_kind(pr, s) == what


def test_a_door_waits_while_a_majini_is_about_to_hit_him_then_is_taken():
    b, clock = bot()
    b.tick(snap([majini(0, at(100, 20))], pr=door()))                       # at arm's length
    assert b.doing != "prompt" and b.stats["door_holds"] == 1
    clock[0] = 0.05
    b.tick(snap([majini(0, at(220, 20), motion=80)], pr=door()))            # 2.2 m off and winding up: still
    assert b.doing != "prompt"
    clock[0] = 0.1
    act = b.tick(snap([majini(0, at(100, 20), hp=0)], pr=door()))           # down: the door
    assert act["hold"] == ("y",) and b.doing == "prompt" and b.stats["door_holds"] == 1
    b2, _ = bot()
    assert b2.tick(snap([majini(0, at(220, 20))], pr=door()))["hold"] == ("y",)   # 2.2 m off, not winding: the door
    assert "held" in events()


def test_a_door_that_never_opens_is_let_be():
    b, clock = bot()
    for k in range(int(R.DOOR_PRESS_MAX_S / 0.05) + 4):
        clock[0] = 0.05 * k
        act = b.tick(snap([], pr=door()))
    assert "y" not in act["hold"] and b.stats["door_giveups"] == 1
    spot = json.loads(R.DOOR_FILE.read_text())[STAGE][0]
    assert spot[4]["misses"] == 1 and "gave_up" in events()


# --- remembered, and the way through --------------------------------------------------------------------------------
def test_a_door_is_remembered_with_its_button_and_the_way_through_it():
    b, clock = bot()
    pr = door(cls="uOm100c", target_pos=(0.0, 0.0, 90.0))                  # the door 0.9 m ahead of him
    for k in range(3):
        clock[0] = 0.05 * k
        b.tick(snap([], pr=pr))
    clock[0] = 0.15
    act = b.tick(snap([]))                                                   # gone: taken - on through it at a run
    assert b.stats["doors_taken"] == 1 and {"lup", "b"} <= set(act["hold"]) and b.doing == "prompt"
    clock[0] = 0.6
    b.tick(snap([], pos=(0.0, 0.0, 200.0)))                                  # 1.1 m past the door
    assert b.stats["doors_through"] == 1 and b.__dict__.get("_door_after") is None
    data = json.loads(R.DOOR_FILE.read_text())
    spot = data[STAGE][0]
    assert spot[:4] == [0, 0, 0, 41]
    info = spot[4]
    assert (info["type"], info["what"], info["token"], info["keys"], info["kind"], info["owner_class"]) \
        == ("door", "door", "press:y", ["y"], 1, "uOm100c")
    assert (info["seen"], info["taken"], info["through"]) == (1, 1, 1)
    assert info["to"] == [0, 0, 200] and info["at"] == [0, 0, 90] and info["face"] == 0.0
    assert data[R.DOOR_LABELS_KEY]["41"]["through"] == 1                     # the label learned as a door's
    assert events() == ["seen", "taken", "through"]
    assert b.stats["door_trace"].startswith('{"t"') and '"through"' in b.stats["door_trace"]


def test_a_learned_door_label_is_a_door_whatever_its_kind():
    R.DOOR_FILE.write_text(json.dumps({R.DOOR_LABELS_KEY: {"77": {"through": 2, "what": "window"}}}))
    b, _ = bot()
    pr = door(kind=3, label=77)                                              # (an area-kind button: else never)
    assert b._prompt_type(pr, snap([], pr=pr)) == "door" and b._door_kind(pr, snap([], pr=pr)) == "window"


def test_a_door_seen_again_is_counted_on_its_spot_and_a_flicker_is_not():
    b, clock = bot()
    b.tick(snap([], pr=door()))
    clock[0] = 0.05
    b.tick(snap([]))                                                         # (gone: taken)
    clock[0] = 0.1
    b.tick(snap([], pr=door()))                                              # back within DOOR_SEEN_GAP_S: a flicker
    clock[0] = 0.15
    b.tick(snap([]))
    clock[0] = 10.0
    b.tick(snap([], pr=door(), pos=(30.0, 0.0, 20.0)))                       # seen again later, 36 cm off
    spots = json.loads(R.DOOR_FILE.read_text())[STAGE]
    assert len(spots) == 1 and spots[0][4]["seen"] == 2 and spots[0][4]["taken"] == 2
    assert events().count("seen") == 2


# --- exploring by the doors he knows ---------------------------------------------------------------------------------
EAST = R.heading(1.0, 0.0)                                                    # the door at x 1000, faced along +x
KNOWN = (1000, 0, 0, 41, {"type": "door", "what": "door", "token": "press:y", "keys": ["y"], "face": EAST,
                          "seen": 2, "taken": 1, "through": 1})


def test_with_no_majini_alive_he_walks_to_an_untried_remembered_door_and_takes_it():
    remembered(KNOWN)
    b, clock = bot()
    act = b.tick(snap(ROOF_CROWS))                    # only crows: nobody to fight
    assert {"lup", "b"} <= set(act["hold"]) and b.doing == "walk" and "exploring" in b.why
    assert "rleft" in act["hold"] and b.stats["door_explores"] == 1         # (turning toward it, on his left)
    clock[0] = 1.0
    b.tick(snap(ROOF_CROWS, pos=(960.0, 0.0, 0.0), rot=EAST))              # there: onto its spot, facing it
    assert b.stats["door_explore_arrivals"] == 1 and "prompt" in b.why
    clock[0] = 1.05
    act = b.tick(snap(ROOF_CROWS, pr=door(), pos=(960.0, 0.0, 0.0), rot=EAST))   # its prompt: taken
    assert act["hold"] == ("y",) and b.doing == "prompt"
    clock[0] = 1.1
    act = b.tick(snap(ROOF_CROWS, pos=(960.0, 0.0, 0.0), rot=EAST))
    assert b.stats["doors_taken"] == 1 and {"lup", "b"} <= set(act["hold"])   # through it
    clock[0] = 1.6
    b.tick(snap(ROOF_CROWS, pos=(1200.0, 0.0, 0.0), rot=EAST))
    assert b.stats["doors_through"] == 1 and b.__dict__.get("_explore_st") is None
    info = json.loads(R.DOOR_FILE.read_text())[STAGE][0][4]
    assert (info["seen"], info["taken"], info["through"]) == (3, 2, 2)
    assert events()[:3] == ["explore", "explore_arrived", "seen"] and events()[-2:] == ["taken", "through"]


def test_at_a_remembered_door_with_no_prompt_he_walks_on_through_it():
    remembered(KNOWN)
    b, clock = bot()
    b.tick(snap([], pos=(980.0, 0.0, 0.0), rot=EAST))                        # on its spot: the prompt awaited
    t = 0.0
    while t < R.DOOR_ARRIVE_S + 0.2:
        t += 0.05
        clock[0] = t
        act = b.tick(snap([], pos=(980.0, 0.0, 0.0), rot=EAST))
    assert {"lup", "b"} <= set(act["hold"]) and "on through" in b.why       # an open door: on through it
    clock[0] = t + 0.5
    b.tick(snap([], pos=(1200.0, 0.0, 0.0), rot=EAST))
    assert b.stats["doors_through"] == 1 and "explore_no_prompt" in events() and events()[-1] == "through"


def test_with_the_majini_out_of_reach_and_no_kill_for_a_while_he_explores():
    remembered(KNOWN)
    b, clock = bot()
    up = majini(0, at(1300, 200, y=400.0))           # up on a walkway, no mesh read: no way known up there
    b.tick(snap([up], kills=390))
    assert not b.stats.get("door_explores")
    clock[0] = R.DOOR_EXPLORE_S + 0.5
    b.tick(snap([up], kills=390, pos=(-300.0, 0.0, 200.0)))                 # (walked about meanwhile: no kill)
    assert b.stats["door_explores"] == 1 and "none of the 1 Majini reachable" in b.why


def test_a_majini_he_can_reach_or_the_operators_mark_comes_before_the_doors():
    remembered(KNOWN)
    b, clock = bot()
    b.tick(snap([majini(0, at(1500, 180))]))          # one on his floor: the fight (or the run to him)
    clock[0] = R.DOOR_EXPLORE_S + 1.0
    b.tick(snap([majini(0, at(1500, 180))]))
    assert not b.stats.get("door_explores")
    b2, clock2 = bot()
    b2.tick(snap([]))                                 # nobody: off to the door ...
    assert b2.stats["door_explores"] == 1
    g = b2._goals()
    b2.receive_map_goal({"round": g.round, "id": "m1", "kind": "point", "entity_id": 0, "pos": [-1500.0, 0.0, 0.0],
                         "label": "Go to the marked spot"})
    b2._goals().received_at = 0.0
    for k in range(1, 4):                             # ... until the operator marks a spot: his mark, by the map
        clock2[0] = 0.05 * k
        act = b2.tick(snap([], pos=(-10.0 * k, 0.0, 0.0), rot=-math.pi / 2))
        assert "operator's spot" in b2.why and "lup" in act["hold"]
    assert b2.stats["door_explores"] == 1 and not b2.stats.get("door_explore_misses")


def test_a_broken_door_file_never_costs_a_tick():
    R.DOOR_FILE.write_text(json.dumps({STAGE: [[1, 2], "x", [None, 0, 0, 41], {"a": 1}, list(KNOWN)],
                                       R.DOOR_LABELS_KEY: {"41": 3, "42": None}}))
    b, clock = bot()
    act = b.tick(snap([]))                            # the good row still explored
    assert b.stats["door_explores"] == 1 and "lup" in act["hold"] and not b.stats.get("door_error")
    clock[0] = 0.05
    assert b.tick(snap([], pr=door(label=41)))["hold"] == ("y",)
    assert not b.stats.get("door_error")


def test_a_bot_from_before_the_hot_reload_takes_doors_and_remembers_them():
    b, clock = bot()
    b.tick(snap([]))                                   # the round under way
    for k in [k for k in b.stats if k.startswith("door") or k == "prompts_seen_door"]:
        del b.stats[k]
    for k in ("_door_after", "_door_watch", "_explore_st", "_explore_kills", "_door_lbl", "_door_tried"):
        b.__dict__.pop(k, None)
    clock[0] = 0.05
    assert b.tick(snap([], pr=door()))["hold"] == ("y",)
    clock[0] = 0.1
    b.tick(snap([]))
    clock[0] = 0.5
    b.tick(snap([], pos=(0.0, 0.0, 300.0)))
    assert b.stats["doors_taken"] == 1 and b.stats["doors_through"] == 1
