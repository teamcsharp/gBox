"""The two object-class registry modules agree (CP0 step 4's cross-check).

`gbox/pso_classes.py` is the self-calibrating reader: it finds the table in a `PsoV3.dol` from the
`TObjCityDoor_Shop` anchor and decodes `{class id: name}` from the image.
`gbox/pso_class_registry.py` is the pinned table: address `0x805D3138`, 240 slots, 148 named, plus the vtable census
and the `family` grouping the editor uses.

CP0 (2026-11-10) folded the branch's table address and its 148-name list in as this cross-check instead of keeping two
independent claims: the anchor name and slot are the same on both sides, and the pinned list is the one the reader would
decode (the reader's own `table_offset` is checked on the owned disc by `tools/verify_pso_classes.py`)."""
import pytest


def test_the_anchor_class_is_the_same_on_both_sides():
    from gbox import pso_class_registry as pinned
    from gbox import pso_classes as reader
    assert reader.ANCHOR_NAME == "TObjCityDoor_Shop"
    assert reader.ANCHOR_SLOT == 0x46
    assert pinned.name(reader.ANCHOR_SLOT) == reader.ANCHOR_NAME
    assert pinned.index_of(reader.ANCHOR_NAME) == reader.ANCHOR_SLOT


def test_the_pinned_table_is_the_240_slot_148_name_list_the_branch_measured():
    from gbox import pso_class_registry as pinned
    assert pinned.TABLE_ADDRESS == 0x805D3138
    assert len(pinned.CLASS_NAMES) == 240, "4 bytes a slot, 240 slots"
    assert sum(1 for name in pinned.CLASS_NAMES if name) == 148, "148 named in this build"
    assert pinned.name(0x47) == "TObjCityDoor_Guild" and pinned.name(0x48) == "TObjCityDoor_Warp"
    assert pinned.name(0x49) == "TObjCityDoor_Med"
    assert all(pinned.name(i) is None for i in (0x05, 0x06, 0x13)), "this build's real holes stay holes"


def test_a_placement_kind_masks_to_its_class_on_both_sides():
    from gbox import pso_class_registry as pinned
    from gbox import pso_classes as reader
    assert pinned.class_index(0x80000046) == 0x46 == reader.ANCHOR_SLOT
    assert pinned.label(0x80000046) == "TObjCityDoor_Shop"
    assert pinned.name(240) is None and pinned.label(240).startswith("class_0x"), "past the table: unnamed, no crash"
