"""CP11: the editor's server-side views must render - the SVG preview and the ASCII map (door marks included)."""
import pathlib

import pytest

from gbox import pso_editor as E
from gbox import pso_editor_api as API

DISC = pathlib.Path(r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved"
                    r"\Phantasy Star Online Episode I & II Plus (USA).iso")


@pytest.fixture(scope="module")
def disc():
    from gbox import gcdisc
    if not DISC.is_file():
        pytest.skip("the disc is not on this machine")
    return gcdisc.GCDisc(str(DISC))


def test_the_set_list_is_available(disc):
    sets = E.sets(disc)
    assert len(sets) > 500                          # measured: 603 editable sets
    names = {s["name"] for s in sets}
    assert "map_ancient01_00_00o.dat" in names


def test_the_svg_preview_renders_one_dot_per_record(disc):
    data = E.placements(disc, "map_ancient01_00_00o.dat")
    records = data.get("records") or []
    svg = API.svg_of(data)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert svg.count("<circle") == len(records) == 234


def test_the_ascii_map_renders_and_marks_the_city_doors(disc):
    """`_mark_for` used a bare `CLASS_NAMES` (NameError) and then `.get` on the registry's tuple: both fixed."""
    data = E.placements(disc, "map_city00_00o.dat")
    records = data.get("records") or []
    text = E.ascii_map(records, "map_city00_00o.dat")
    assert len(text.splitlines()) > 10
    assert "G" in text and "S" in text              # the city's Guild and Shop doors are marked


def test_a_door_record_is_marked_by_its_door_name():
    mark = E._mark_for({"kind": 0, "class_index": -1})
    assert mark == "o"
