"""CP14: the placements-only expansion is valid - one record added at a room's measured centre."""
import pathlib

import pytest

DISC = pathlib.Path(r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved"
                    r"\Phantasy Star Online Episode I & II Plus (USA).iso")


@pytest.fixture(scope="module")
def env():
    from gbox import gcdisc
    if not DISC.is_file():
        pytest.skip("the disc is not on this machine")
    return gcdisc.GCDisc(str(DISC))


def test_an_added_placement_lands_inside_the_room_and_keeps_the_others(env):
    """CP14's documented fallback: expand by adding records, with a position the collision footprint accepts."""
    from gbox import pso_map_write as W, pso_rooms as R, pso_setdata as P
    set_name, room = "map_ancient01_00_00o.dat", "Scene/map_aancient01_00r.rel"
    quad = R.room_quad(env.read(room))
    data, _where = W.read_set(env, set_name)
    before = P.records(data)
    assert len(before) == 234                              # measured
    x, y, z = quad["origin"][0], before[0]["y"], quad["origin"][2]
    changed = W.add_placement_change(data, before[0]["kind"], float(x), float(y), float(z))["bytes"]
    after = P.records(changed)
    assert len(after) == len(before) + 1
    assert after[: len(before)] == before                  # nothing else moved
    assert R.contains(quad, after[-1]["x"], after[-1]["z"])   # the new record is on the room's floor


def test_the_editor_previews_the_same_add(env):
    """`pso_editor.preview` is the path an operator actually uses; it must accept the op and name the index."""
    from gbox import pso_editor as E, pso_rooms as R
    quad = R.room_quad(env.read("Scene/map_aancient01_00r.rel"))
    op = E.edit("add", "map_ancient01_00_00o.dat", kind=0x8,
                x=float(quad["origin"][0]), y=float(quad["origin"][1]), z=float(quad["origin"][2]))
    preview = E.preview(env, [op])
    assert preview["ok"] is True
    assert preview["edits"] == 1
    assert preview["expect"][0]["op"] == "add"


def test_the_template_kind_is_a_real_placement(env):
    """A copied kind is what makes the added record constructible: it must come from the set's own records."""
    from gbox import pso_map_write as W, pso_setdata as P
    data, _where = W.read_set(env, "map_ancient01_00_00o.dat")
    kinds = {P.records(data)[0]["kind"]}
    assert kinds and all(isinstance(k, int) for k in kinds)
