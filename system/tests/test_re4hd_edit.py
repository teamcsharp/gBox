"""The pack edit a sidebar needs: a material list, a hide, a scale, and a donor morph - each one in place.

Every call reports which materials, how many vertices, whether the triangle table moved, and the sha256 before and after, so a
build can state what it did. The cases here run against a real RE4 Switch pack (the Ganado) and skip where the RomFS is not
extracted, which is the same rule the other real-pack tests use.
"""
import os

import pytest

from gbox import re4gc_inventory as INV
from gbox import re4hd_edit as EDIT
from gbox import re4hd_models as R

PACK = os.path.join(os.path.expanduser("~/gBox_alt/switch/romfs"), "010099A00BC1E000", "bio4", "em", "em16.udas")
needs_pack = pytest.mark.skipif(not os.path.isfile(PACK), reason="the RE4 Switch RomFS is not extracted on this machine")


def pack_bytes() -> bytes:
    return open(PACK, "rb").read()


@needs_pack
def test_the_pack_lists_its_materials_in_order():
    census = EDIT.material_census(pack_bytes(), 0)
    assert len(census) > 1, "the Ganado pack has several materials"
    assert census[0]["triangle_start"] == 0
    for previous, current in zip(census, census[1:]):
        assert current["triangle_start"] == previous["triangle_end"], "the spans are contiguous"
    assert census[-1]["triangle_end"] == sum(entry["triangles"] for entry in census)


@needs_pack
def test_hide_reports_what_it_did_and_keeps_the_pack_the_same_size():
    data = pack_bytes()
    out, report = EDIT.edit_pack(data, 0, hide=[1], pack_name="em16.udas")
    assert report.operation == "hide" and report.vertices > 0
    assert report.before_sha256 != report.after_sha256
    assert len(out) == len(data), "a pack edit never changes the container's size"
    assert report.triangles > 0


@needs_pack
def test_scale_moves_a_material_and_leaves_the_triangles_alone():
    data = pack_bytes()
    out, report = EDIT.edit_pack(data, 0, scale=([0], 0.5), pack_name="em16.udas")
    assert report.operation == "scale" and report.vertices > 0
    assert len(out) == len(data)
    slot = INV.bin_slots(out, endian="<")[0]
    again = R.bin_read(out[slot["offset"]:slot["offset"] + slot["size"]])
    assert len(again.tris) == report.triangles, "the triangle table is untouched"


def test_a_scale_factor_outside_the_sanity_bound_is_refused():
    with pytest.raises(EDIT.EditError):
        EDIT.edit_pack(b"\x00" * 32, 0, scale=([0], 0.0))


def test_a_pack_without_a_bin_slot_is_refused():
    with pytest.raises(EDIT.EditError):
        EDIT.edit_pack(b"\x00" * 32, 0, hide=[0])


def test_no_operation_is_refused_before_the_pack_is_read():
    with pytest.raises(EDIT.EditError):
        EDIT.edit_pack(b"", 0)
