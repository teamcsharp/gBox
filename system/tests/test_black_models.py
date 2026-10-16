"""Focused tests for gbox.black_models (Black PS2 cast reconnaissance, request #1965).

The disc and ELF fixtures are the operator's owned files on the Spark; tests skip
without them. GRDLNCHR.WDO is embedded (211 bytes) so the WDO parser is always tested.
"""
import hashlib
import struct
from pathlib import Path

import pytest

from gbox import black_models as bm
from gbox.black_models import (
    DISC, ELF, CAST_WEAPONS, LOADER_SITES, FormatError, elf_loader_sites,
    BONE_HEADER_FIXED, BONE_HEADER_PER, db_bone_records,
    WDD_STREAMS, WDD_ATTRS, wdd_type, wdd_type_census,
)

WDO_FIXTURE = bytes.fromhex(
    "0908000000000000d30000002c0000000000000000400000acc9eaaa38fc1749ae8164eadbc79353"
    "d3000000000000000000000000000000b8000000b8000000000000000000000460cd430008e04300"
    "00000000000000000000000000000000c800000000000000c0cd4300803e00000000000080180000"
    "040112000000000000000000008d1400803e00000000000080180000040112000000000000000000"
    "008d1400000000000000000000000000040000000000000038000000380000005c00000000000000"
    "4772644c6e6368724c4600"
)


def test_parse_wdo_fixture():
    w = bm.parse_wdo(WDO_FIXTURE)
    assert w["magic"] == 0x0809
    assert w["size"] == len(WDO_FIXTURE) == 211
    assert w["name"] == "GrdLnchrLF"                       # "GrdLnchr" + "LF" extension
    assert 0x43CD60 in w["ram_ptrs"] and 0x43E008 in w["ram_ptrs"]
    assert 0x120104 in w["ram_ptrs"] and 0x148D00 in w["ram_ptrs"]


def test_parse_wdo_rejects_bad_magic():
    with pytest.raises(FormatError):
        bm.parse_wdo(b"\x00" * 16)
    with pytest.raises(FormatError):                       # magic ok, size lies
        bm.parse_wdo(struct.pack("<3I", 0x0809, 0, 999) + b"\x00" * 200)


def test_wdd_census_rejects_wrong_size():
    with pytest.raises(FormatError):
        bm.wdd_census(b"\x07\x02\x11\x0f" + b"\x00" * 128)


@pytest.mark.skipif(not DISC.exists(), reason="owned Black disc not unpacked on this node")
def test_cast_roster_from_disc():
    cast = bm.list_cast()
    slots = sorted(k for k in cast if k.startswith("BG1_"))
    assert len(slots) == len(CAST_WEAPONS)
    for w in CAST_WEAPONS:
        assert f"BG1_{w}" in cast, f"missing cast slot BG1_{w}"
        assert cast[f"BG1_{w}"][".WDD"]["size"] == 65536
        assert 500_000 < cast[f"BG1_{w}"][".DB"]["size"] < 800_000
    # gun objects carry both their object table and geometry
    assert cast["GRDLNCHR.WDO"]["size"] == 211


@pytest.mark.skipif(not DISC.exists(), reason="owned Black disc not unpacked on this node")
def test_bg1_ak1_wdd_hash():
    cast = bm.list_cast()
    f = open(DISC, "rb")
    lba = cast["BG1_AK1"][".WDD"]["lba"]
    f.seek(lba * 2048)
    digest = hashlib.sha256(f.read(65536)).hexdigest()
    assert digest.startswith("e2c1cb3f")                    # pinned from the owned disc


@pytest.mark.skipif(not ELF.exists(), reason="owned SLUS_213.76 ELF not extracted on this node")
def test_elf_loader_sites():
    hits = elf_loader_sites()
    for saddr, (frag, sites) in LOADER_SITES.items():
        assert saddr in hits, f"no code site for {frag!r}"
        for site in sites:
            assert site in hits[saddr], f"expected site {site:#x} for {frag!r}"
    # no other code site may reference these strings (pins the table exactly)
    assert {a for lst in hits.values() for a in lst} == {s for lst in LOADER_SITES.values() for s in lst[1]}


def _db_bytes(slot: str) -> bytes:
    cast = bm.list_cast()
    f = open(DISC, "rb")
    lba = cast[slot][".DB"]["lba"]
    f.seek(lba * 2048)
    return f.read(cast[slot][".DB"]["size"])


@pytest.mark.skipif(not DISC.exists(), reason="owned Black disc not unpacked on this node")
def test_db_skeleton_ak1_pinned():
    """The BG1_AK1 DB skeleton is an FPS arms rig, pinned bone-for-bone."""
    bones = bm.db_skeleton(_db_bytes("BG1_AK1"))
    assert bones == [
        "World", "Extra", "Root",
        "Shoulder_lft", "Elbow_lft", "Joint_wrist_twist", "Wrist_lft",
        "Finger1_Top_lft", "Finger1_Mid_lft", "Finger1_Tip_lft",
        "Finger2_Top_lft", "Finger2_Mid_lft", "Finger2_Tip_lft",
        "Finger3_Top_lft", "Finger3_Mid_lft", "Finger3_Tip_lft",
        "Finger4_Top_lft", "Finger4_Mid_lft", "Finger4_Tip_lft",
        "Thumb_Top_lft", "Thumb_Mid_lft", "Thumb_Tip_lft",
        "Shoulder_rt", "Elbow_rt", "Wrist_rt",
        "AssualtRifle_Root", "AssualtRifle_Clip", "AssualtRifle_Magazine",
        "AssualtRifle_Slide", "Bullets",
        "Finger1_Top_rt", "Finger1_Mid_rt", "Finger1_Tip_rt",
        "Finger2_Top_rt", "Finger2_Mid_rt", "Finger2_Tip_rt",
        "Finger3_Top_rt", "Finger3_Mid_rt", "Finger3_Tip_rt",
        "Finger4_Top_rt", "Finger4_Mid_rt",
        "Thumb_Top_rt", "Thumb_Mid_rt", "Thumb_Tip_rt",
    ]


@pytest.mark.skipif(not DISC.exists(), reason="owned Black disc not unpacked on this node")
def test_db_skeleton_every_variant_anchors_and_bounds():
    """Every BG1_*.DB yields a bounded skeleton anchored at 'World'."""
    cast = bm.list_cast()
    for slot in sorted(k for k in cast if k.startswith("BG1_")):
        bones = bm.db_skeleton(_db_bytes(slot))
        assert bones[0] == "World", f"{slot} not anchored at World"
        assert 42 <= len(bones) <= 46, f"{slot} has {len(bones)} bones"
        # no leg/spine/neck/head bones anywhere: it is an FPS arms rig
        assert not any(b.startswith(("Leg", "Spine", "Neck", "Head", "Hip", "Thigh", "Knee", "Ankle")) for b in bones)


@pytest.mark.skipif(not DISC.exists(), reason="owned Black disc not unpacked on this node")
def test_db_weapon_bones_match_slot_family():
    """Weapon-specific bones track the weapon family of the slot (pistol/shotgun/heavy)."""
    fam = {
        "BG1_GK1": "Pistol", "BG1_GK5": "Pistol",
        "BG1_GRL": "Shotgun",
        "BG1_HV5": "Heavy", "BG1_HVY": "Heavy",
    }
    for slot, prefix in fam.items():
        wb = bm.db_weapon_bones(_db_bytes(slot))
        assert wb and all(b.startswith(prefix) or b == "Site" or b == "Small_Site" for b in wb), (slot, wb)
    # the grenade launcher variant carries grenade-specific bones alongside the rifle
    wb = bm.db_weapon_bones(_db_bytes("BG1_BNS"))
    assert "GrenadeShell" in wb and "BottomLead" in wb and "AssualtRifle_Root" in wb


def _wdd_bytes(slot: str) -> bytes:
    cast = bm.list_cast()
    f = open(DISC, "rb")
    lba = cast[slot][".WDD"]["lba"]
    f.seek(lba * 2048)
    return f.read(65536)


@pytest.mark.skipif(not DISC.exists(), reason="owned Black disc not unpacked on this node")
def test_wdd_records_framing():
    """Every BG1_*.WDD is 4096 16-byte [type][sub][payload] records."""
    cast = bm.list_cast()
    for slot in sorted(k for k in cast if k.startswith("BG1_")):
        recs = bm.wdd_records(_wdd_bytes(slot))
        assert len(recs) == 4096, f"{slot} has {len(recs)} records"
        for t, sub, payload in recs:
            assert len(payload) == 14
            assert sub in (0, 2, 3), f"{slot} record sub {sub:#x}"
            if sub == 0:                     # zero padding: type 0, all-zero payload
                assert t == 0 and payload == b"\x00" * 14, f"{slot} non-padding sub-0 record"
            else:
                assert t < 0x80, f"{slot} data record type {t:#x}"


@pytest.mark.skipif(not DISC.exists(), reason="owned Black disc not unpacked on this node")
def test_wdd_summary_padding_and_pointer_records():
    """The tail is zero padding (sub 0); a few sub 3 pointer records sit inside."""
    cast = bm.list_cast()
    for slot in sorted(k for k in cast if k.startswith("BG1_")):
        s = bm.wdd_summary(_wdd_bytes(slot))
        assert s["records"] == 4096
        assert s["zero_pad_records"] > 0, f"{slot} has no trailing padding"
        assert 0 < s["subs"].get(3, 0) <= 20, f"{slot} sub-3 count {s['subs'].get(3, 0)}"


@pytest.mark.skipif(not DISC.exists(), reason="owned Black disc not unpacked on this node")
def test_db_bone_offset_table_ak1_pinned():
    """BG1_AK1's offset table is one u32 per bone (44), stepping by 24, before 'World'."""
    tbl = bm.db_bone_offset_table(_db_bytes("BG1_AK1"))
    assert tbl["offsets"] == [0x0CD0 + i * 24 for i in range(44)]
    assert len(tbl["offsets"]) == len(bm.db_skeleton(_db_bytes("BG1_AK1"))) == 44
    assert tbl["anchor"] == tbl["table_offset"] + 4 * 44


@pytest.mark.skipif(not DISC.exists(), reason="owned Black disc not unpacked on this node")
def test_db_bone_offset_table_every_variant():
    """Every BG1_*.DB carries one offset per bone, ascending by 24, before its anchor."""
    cast = bm.list_cast()
    for slot in sorted(k for k in cast if k.startswith("BG1_")):
        db = _db_bytes(slot)
        tbl = bm.db_bone_offset_table(db)
        offs = tbl["offsets"]
        assert offs, f"{slot} has no offset table"
        assert offs == sorted(offs), f"{slot} offsets not ascending"
        for a, b in zip(offs, offs[1:]):
            assert b - a == 24, f"{slot} offset stride {b - a:#x}"
        assert tbl["anchor"] == tbl["table_offset"] + 4 * len(offs)
        assert len(offs) == len(bm.db_skeleton(db)), \
            f"{slot}: {len(offs)} offsets vs {len(bm.db_skeleton(db))} bones"


@pytest.mark.skipif(not DISC.exists(), reason="owned Black disc not unpacked on this node")
def test_db_bone_records_absolute_and_contiguous():
    """The offset table holds ABSOLUTE file offsets; the block sits right after the
    header whose size is 0x70 + 72*nBones (3 x 24-byte records per bone)."""
    cast = bm.list_cast()
    for slot in sorted(k for k in cast if k.startswith("BG1_")):
        db = _db_bytes(slot)
        bones = bm.db_skeleton(db)
        rec = db_bone_records(db)
        n = len(bones)
        assert rec["count"] == n, f"{slot} block count {rec['count']} vs {n} bones"
        # header = fixed + per-bone bytes; the block starts immediately after it
        assert rec["block_start"] == BONE_HEADER_FIXED + BONE_HEADER_PER * n, \
            f"{slot} block start {rec['block_start']:#x} != 0x{BONE_HEADER_FIXED + BONE_HEADER_PER * n:x}"
        assert rec["block_end"] == rec["block_start"] + 24 * n
        assert rec["block_end"] <= len(db), f"{slot} block runs past end of DB"
        assert all(len(r) == 24 for r in rec["records"]), f"{slot} record not 24 bytes"
        # the records are byte-for-byte the offsets' targets
        tbl = bm.db_bone_offset_table(db)
        for off, r in zip(tbl["offsets"], rec["records"]):
            assert db[off:off + 24] == r, f"{slot} record mismatch at {off:#x}"


def test_wdd_type_decodes_nibbles():
    """type = (stream<<4)|attr; bit 7 / stream >= 5 / attr >= 13 are all invalid."""
    assert wdd_type(0x00) == (0, 0)
    assert wdd_type(0x36) == (3, 6)
    assert wdd_type(0x4C) == (4, 12)
    for bad in (0x80, 0x5F, 0x0D, 0xFF):
        with pytest.raises(FormatError):
            wdd_type(bad)


@pytest.mark.skipif(not DISC.exists(), reason="owned Black disc not unpacked on this node")
def test_wdd_type_census_matches_records():
    """Every record type decomposes as stream 0..4 / attr 0..12, and the census
    tallies the same (stream, attr) kinds as a direct walk of wdd_records()."""
    cast = bm.list_cast()
    for slot in sorted(k for k in cast if k.startswith("BG1_")):
        data = _wdd_bytes(slot)
        c = bm.wdd_type_census(data)
        kinds: dict = {}
        n_data = 0
        n_pointer = 0
        for t, sub, _p in bm.wdd_records(data):
            s, a = wdd_type(t)                    # raises if the codec is violated
            assert 0 <= s < WDD_STREAMS and 0 <= a < WDD_ATTRS, f"{slot} type {t:#x}"
            if sub == 2:
                n_data += 1
                kinds[(s, a)] = kinds.get((s, a), 0) + 1
            elif sub == 3:
                n_pointer += 1
        assert c["records"] == 4096, slot
        assert c["data_records"] == n_data, slot
        assert c["kinds"] == kinds, slot
        assert set(c["streams"]) <= set(range(WDD_STREAMS)), slot
        assert set(c["attrs"]) <= set(range(WDD_ATTRS)), slot
        assert n_pointer == sum(sum(m.values()) for m in c["pointer"].values()), slot
        assert n_pointer > 0, slot                  # every variant carries pointer records
