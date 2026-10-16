"""Focused tests for gbox.doa3_cast: XPR0 walk, CAT sections, slot inventory
and the AFS patch path. Fixtures mirror the byte layout observed in the owned
USA build (kas00.xpr / kas00.cat, loadfile.afs)."""
import struct

import pytest

from gbox import doa3_cast
from gbox.doa3_inventory import afs_table, entry_rooms, read_afs


# ----------------------------------------------------------------- fixtures

def make_xpr(mdl_size: int = 64, words: list[int] | None = None,
             total: int | None = None) -> bytes:
    """An XPR0 shaped like kas00: user-data MDL pair at 0x0C, second pair at
    0x18, descriptor count at 0x20, raw descriptor words, then the MDL payload
    and an unparsed trailing region."""
    words = words if words is not None else [0x48, 0x14C, 0x16BC, 0x3F54, 0x4190]
    hsize = 0x24 + 4 * len(words)
    mdl_end = hsize + mdl_size
    if total is None:
        total = mdl_end + 16
    out = bytearray(total)
    struct.pack_into("<4sII", out, 0, b"XPR0", total, hsize)
    struct.pack_into("<II", out, 12, 0x80000000, mdl_size)
    out[20:24] = b"MDL\x00"
    struct.pack_into("<II", out, 0x18, 0x48, 87)
    struct.pack_into("<I", out, 0x20, len(words))
    for i, w in enumerate(words):
        struct.pack_into("<I", out, 0x24 + 4 * i, w)
    out[hsize:hsize + mdl_size] = bytes((i * 7) & 0xFF for i in range(mdl_size))
    return bytes(out)


def make_cat(header: tuple[int, ...] | None = None) -> bytes:
    """A CAT companion shaped like kas00: 8 header words and a LNK marker."""
    header = header or (1, 0x14, 0x5C0, 0x9A40, 0x4F5C0, 0x100, 1, 0x18)
    body = bytearray(0x9A40 + 4)
    struct.pack_into("<8I", body, 0, *header)
    body[0x9A40:0x9A44] = b"LNK\x00"
    return bytes(body)


def make_afs(entries: list[bytes]) -> bytes:
    """Minimal AFS without a CRI name directory: header, offset/size table, data."""
    n = len(entries)
    head_len = 16 + 8 * n
    offsets, sizes, cur = [], [], head_len
    for blob in entries:
        offsets.append(cur)
        sizes.append(len(blob))
        cur += len(blob)
    out = bytearray(cur)
    struct.pack_into("<4sI", out, 0, b"AFS\x00", n)
    for i, (o, s) in enumerate(zip(offsets, sizes)):
        struct.pack_into("<II", out, 8 + 8 * i, o, s)
    for blob, o in zip(entries, offsets):
        out[o:o + len(blob)] = blob
    return bytes(out)


def make_manifest() -> dict:
    """Two complete families, one family with a missing cat, one costume-less."""
    return {"game_id": "b8edf7040116f3aa", "title": "Dead or Alive 3 (USA)",
            "roster_expected": doa3_cast.ROSTER,
            "fighter_families": [
                {"nick": "kasumi", "code": "kas", "mot": ["kasumi.mot", "m_kasumi.mot"],
                 "costumes": {"kas00": {"xpr": 1, "cat": 2}, "kas01": {"xpr": 3, "cat": 4}},
                 "complete_costumes": ["kas00", "kas01"]},
                {"nick": "tina", "code": "tin", "mot": ["tina.mot"],
                 "costumes": {"tin00": {"xpr": 5, "cat": 6}, "tin01": {"xpr": 7}},
                 "complete_costumes": ["tin00"]},
                {"nick": "tengu", "code": None, "mot": [], "costumes": {},
                 "complete_costumes": []},
            ]}


# ----------------------------------------------------------------- XPR0

def test_xpr_resources_mirrors_observed_layout():
    blob = make_xpr()
    res = doa3_cast.xpr_resources(blob)
    assert res["magic"] == "XPR0"
    assert res["header_size"] == 0x38
    assert res["mdl"] == {"type": 0x80000000, "size": 64, "tag": "MDL",
                          "offset": 0x38, "end": 0x78}
    assert res["second_pair"] == {"type": 0x48, "size": 87}
    assert res["descriptor_count"] == 5
    assert res["descriptor_words"] == [0x48, 0x14C, 0x16BC, 0x3F54, 0x4190]
    assert res["trailing_size"] == 16
    assert doa3_cast.xpr_mdl(blob)[0] == 0 and len(doa3_cast.xpr_mdl(blob)) == 64


def test_xpr_resources_rejects_non_xpr():
    with pytest.raises(ValueError, match="not an XPR0"):
        doa3_cast.xpr_resources(b"\x00" * 0x30)


def test_xpr_resources_rejects_mdl_outside_resource():
    blob = make_xpr(mdl_size=64, total=0x60)   # mdl_end 0x78 > total 0x60
    with pytest.raises(ValueError, match="outside the resource"):
        doa3_cast.xpr_resources(blob)


def test_xpr_resources_rejects_non_mdl_tag():
    blob = bytearray(make_xpr())
    blob[20:24] = b"ZZZZ"
    with pytest.raises(ValueError, match="tag"):
        doa3_cast.xpr_resources(bytes(blob))


def test_xpr_resources_caps_descriptor_words():
    blob = make_xpr(words=[0] * 5000)  # header larger than the descriptor window
    res = doa3_cast.xpr_resources(blob)
    assert res["descriptor_count"] == 5000
    assert len(res["descriptor_words"]) == doa3_cast.MAX_HEADER_WORDS


# ----------------------------------------------------------------- CAT

def test_cat_sections_mirrors_observed_header_and_marker():
    res = doa3_cast.cat_sections(make_cat())
    assert res["version"] == 1
    assert res["header"][0] == 0x14
    assert res["header"][1] == 0x5C0
    assert res["lnk_markers"] == [0x9A40]


def test_cat_sections_rejects_wrong_version():
    with pytest.raises(ValueError, match="version"):
        doa3_cast.cat_sections(make_cat(header=(2, 0x14, 1, 1, 1, 1, 1, 1)))


def test_cat_sections_without_markers():
    body = bytearray(0x30)
    struct.pack_into("<8I", body, 0, 1, 0x14, 1, 0x20, 1, 1, 1, 1)
    res = doa3_cast.cat_sections(bytes(body))
    assert res["lnk_markers"] == []


# ----------------------------------------------------------------- slots

def test_slot_inventory_counts_and_gaps():
    inv = doa3_cast.slot_inventory(make_manifest())
    assert inv["slot_count"] == 3
    assert inv["costume_total"] == 3
    by_nick = {s["nick"]: s for s in inv["slots"]}
    assert by_nick["kasumi"]["costume_count"] == 2
    assert by_nick["tina"]["costume_count"] == 1
    assert by_nick["tengu"]["costume_count"] == 0 and by_nick["tengu"]["hidden"]
    gaps = {(g["slot"], g["kind"]) for g in inv["coverage_gaps"]}
    assert ("tina", "no_complete_costumes") not in gaps  # tin00 is complete
    assert ("tengu", "no_complete_costumes") in gaps
    assert ("tengu", "display_name_pending") in gaps
    assert inv["display_mapping"] == "pending"
    assert inv["unlock_all"] == "pending"


def test_cast_writer_status_is_honest():
    st = doa3_cast.cast_writer_status()
    assert st["xpr0_parser"] and st["cat_parser"] and st["afs_patch_path"]
    assert not st["mdl_geometry_decode"] and not st["playable"]


# ----------------------------------------------------------------- AFS patch

def test_afs_patch_entry_roundtrip(tmp_path):
    afs = tmp_path / "loadfile.afs"
    afs.write_bytes(make_afs([b"A" * 16, b"B" * 32, b"C" * 16]))
    before = afs.read_bytes()
    doa3_cast.afs_patch_entry(afs, 1, b"X" * 20)
    after = afs.read_bytes()
    assert len(after) == len(before)                       # in place, same layout
    table = afs_table(after, len(after))
    assert table["sizes"][1] == 20
    assert after[table["offsets"][1]:table["offsets"][1] + 20] == b"X" * 20
    # zero padding fills the rest of the room; neighbours are untouched
    assert after[table["offsets"][0]:table["offsets"][0] + 16] == b"A" * 16
    assert after[table["offsets"][2]:table["offsets"][2] + 16] == b"C" * 16
    rooms = entry_rooms(table["offsets"], table["sizes"], len(after))
    assert after[table["offsets"][1] + 20:table["offsets"][1] + rooms[1]] == b"\x00" * (rooms[1] - 20)


def test_afs_patch_entry_refuses_oversize_and_leaves_file(tmp_path):
    afs = tmp_path / "loadfile.afs"
    afs.write_bytes(make_afs([b"A" * 16, b"B" * 16]))
    before = afs.read_bytes()
    with pytest.raises(ValueError, match="exceeds the entry room"):
        doa3_cast.afs_patch_entry(afs, 0, b"X" * 64)
    assert afs.read_bytes() == before


def test_afs_patch_entry_refuses_empty_slot(tmp_path):
    afs = tmp_path / "loadfile.afs"
    afs.write_bytes(make_afs([b"", b"B" * 16]))
    with pytest.raises(ValueError, match="empty"):
        doa3_cast.afs_patch_entry(afs, 0, b"X")


def test_read_afs_roundtrip_sees_patched_entry(tmp_path):
    afs = tmp_path / "loadfile.afs"
    afs.write_bytes(make_afs([b"A" * 16, b"B" * 32]))
    doa3_cast.afs_patch_entry(afs, 1, b"Y" * 24)
    parsed = read_afs(afs)
    assert parsed["count"] == 2
    assert parsed["entries"][1]["size"] == 24
    assert parsed["entries"][1]["magic"].startswith("Y")
