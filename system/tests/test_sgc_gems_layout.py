"""Tests for the verified Sonic Gems Collection state layout.

The fixture is SYNTHETIC: it reproduces the shape of a shipped state save
(0x00-0x7F header with game code / title / comment fields, then the 34 leading
unset object records) without committing any bytes copied from the disc - the
repo is public.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gbox import sgc_gems_layout as L


def _fixture() -> bytes:
    head = bytearray(L.RECORD_TABLE_OFFSET)
    head[0:6] = b"G2XE8P"
    head[0x08:0x08 + 13] = b"TESTBANNER_01"
    head[0x40:0x40 + 21] = b"SONIC GEMS COLLECTION"
    head[0x60:0x60 + 13] = b" 8: VECTORMAN"
    return bytes(head) + bytes((0x81, L.UNSET_BYTE)) * L.LEADING_UNSET_RECORDS


FIXTURE = _fixture()


def test_vm_map_is_linear_and_roundtrips():
    assert L.vm_to_file_offset(0x80005600) == 0x2600
    assert L.file_offset_to_vm(0x2600) == 0x80005600
    for vm in (0x801E4C00, 0x801CDF88, 0x801E4C88, 0x80010810):
        assert L.file_offset_to_vm(L.vm_to_file_offset(vm)) == vm


def test_known_state_filenames():
    us = L.state_filenames("US")
    assert us[0] == "STATE_US\\MUSEUM01.STM"
    assert us[-1] == "STATE_US\\MUSEUM10.STM"
    assert len(us) == 10
    stg = L.stg_filenames("US")
    assert stg[0] == "STATE_US\\MUSEUM01.STG"
    assert len(stg) == 6
    try:
        L.state_filenames("XX")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown region must raise")


def test_decode_records_splits_class_and_sub():
    recs = L.decode_records(FIXTURE)
    assert len(recs) == 34
    for off, oid, cls, sub in recs:
        assert off >= 0x80
        assert oid == 0x81
        assert cls == L.UNSET_CLASS
        assert sub == L.UNSET_SUB
    assert all(0 <= c <= 7 for _o, _i, c, _s in recs)
    assert all(0 <= s <= 0x1F for _o, _i, _c, s in recs)


def test_class_encoding_roundtrip():
    for value in L.CLASS_BYTE_VALUES:
        cls = (value & L.CLASS_MASK) >> L.CLASS_SHIFT
        sub = value & L.SUB_MASK
        assert (cls << L.CLASS_SHIFT) | sub == value
    assert L.CLASS_BYTE_VALUES == tuple(
        (c << L.CLASS_SHIFT) | 0x1F for c in range(8))
    assert len(set(L.CLASS_BYTE_VALUES)) == 8


def test_summarise_reads_header_fields():
    s = L.summarise(FIXTURE)
    assert s["gamecode"] == "G2XE8P"
    assert s["title"] == "SONIC GEMS COLLECTION"
    assert s["comment"] == " 8: VECTORMAN"
    assert s["record_count"] == 34
    assert s["leading_unset"] == L.LEADING_UNSET_RECORDS == 34
    assert s["class_counts"] == {3: 34}


def test_unset_marker_constants_agree():
    assert L.UNSET_BYTE == 0x7F
    assert (L.UNSET_CLASS << L.CLASS_SHIFT) | L.UNSET_SUB == L.UNSET_BYTE


def test_content_inventory_counts():
    assert len(L.MUSEUM_MEDIA) == 12
    assert len(L.GS_OBJECT_TITLES) == 16
    assert len(L.GS_SELECT_SCREENS) == 16
    assert len(L.MS_SELECT_ENTRIES) == 4
    assert len(L.MUSEUM_GAMES) == 12


def test_category_status_is_honest():
    # 'unknown' means "not yet mapped", never "content absent".
    for name, value in L.CATEGORY_STATUS.items():
        assert value in ("unknown", "partial", "mapped")
    assert L.CATEGORY_STATUS["modes"] == "partial"
    assert L.CATEGORY_STATUS["characters"] == "unknown"
    assert set(L.CATEGORY_STATUS) == {
        "characters", "hidden_characters", "modes", "levels", "stages",
        "costumes", "items", "extras"}
