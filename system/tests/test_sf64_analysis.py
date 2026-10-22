"""Tests for gbox.sf64_analysis against the owned Star Fox 64 (USA) Rev A ROM.

The ROM image is a build artifact kept outside the repo; tests skip unless it
exists (set SF64_ROM to override the default cache path).
"""

import os

import pytest

from gbox import sf64_analysis as sa
from gbox import sf64_inventory as sf

ROM_PATH = os.environ.get("SF64_ROM") or os.path.expanduser(
    "~/gbox-cache/59a2755566b669ed/rom.z64")

needs_rom = pytest.mark.skipif(
    not os.path.exists(ROM_PATH), reason="owned ROM not cached")


@needs_rom
def test_object_table_located_and_signature_verified():
    report = sa.probe(sf.load_rom(ROM_PATH))
    tbl = report["object_table"]
    assert tbl["rom_offset"] == 0xCCD24
    assert tbl["vram"] == 0x80CC124
    assert tbl["entry_count"] == 406
    assert tbl["signature_verified"] is True
    first = tbl["first_entry"]
    assert first["id"] == 0
    assert first["draw"] == 0x06015F00          # aCoStoneArchDL
    assert first["draw_kind"] == "segmented-dlist"
    assert first["drawType"] == 0
    assert first["action"] == 0
    assert first["hitbox"] == 0x0603E3E0         # aCoStoneArchHitbox
    assert first["cullDistance"] == 800.0
    assert first["damage"] == 39
    assert first["targetOffset"] == 0.0


@needs_rom
def test_playable_craft_objects_enumerated():
    report = sa.probe(sf.load_rom(ROM_PATH))
    craft = report["playable_craft_objects"]
    assert set(craft) == {195, 197, 198, 199}
    # the team craft actors share the all-range draw function
    assert craft[197]["drawType"] == 1
    assert craft[198]["drawType"] == 1
    # every entry's draw is a function or a display list, never garbage
    for info in craft.values():
        assert info["draw_kind"] in ("segmented-dlist", "vram-function")


@needs_rom
def test_arwing_skeleton_and_animations_resolve_to_slot_3():
    report = sa.probe(sf.load_rom(ROM_PATH))
    aw = report["arwing_model"]
    assert aw["segment"] == "ast_arwing"
    assert aw["v_begin"] == 0x8BFC00
    limbs = aw["skeleton_root_limbs"]
    assert len(limbs) >= 10
    # every root limb pointer is a segmented address in slot 0x3
    assert all(sa.segmented_parts(p)[0] == 0x03 for p in limbs)
    # geometry limbs (non-null dList) resolve inside ast_arwing; transform-only
    # bones legitimately carry dList == 0
    geom = [l for l in aw["limbs"].values() if l["dList"] != 0]
    assert len(geom) >= 6
    assert all(l["dList_in_arwing"] for l in geom)
    # the body + wing display lists appear among the skeleton's geometry limbs
    geom_offsets = {l["dList"] & 0xFFFFFF for l in geom}
    assert 0x9B60 in geom_offsets    # aAwBodyDL
    assert 0x15D80 in geom_offsets   # aAwRightWingDL
    assert 0x16660 in geom_offsets   # aAwLeftWingDL
    for sym, anim in aw["animations_parsed"].items():
        assert anim["limbCount"] == 18
        assert anim["frameCount"] == 30
        assert anim["frameData_in_arwing"]
        assert anim["jointKey_in_arwing"]


@needs_rom
def test_pilot_head_display_list_offsets():
    report = sa.probe(sf.load_rom(ROM_PATH))
    aw = report["arwing_model"]
    by_symbol = {d["symbol"]: d for d in aw["display_lists_offsets"]}
    # the four playable pilot heads + James sit at distinct segment offsets
    for sym in ("aAwFoxHeadDL", "aAwFalcoHeadDL", "aAwSlippyHeadDL",
                "aAwPeppyHeadDL", "aAwJamesHeadDL"):
        assert sym in by_symbol
    # Fox's head is the first display list in the segment (offset 0x90)
    assert by_symbol["aAwFoxHeadDL"]["file_offset"] == 0x8BFC00 + 0x90
    # body/wing geometry
    assert by_symbol["aAwBodyDL"]["file_offset"] == 0x8BFC00 + 0x9B60
