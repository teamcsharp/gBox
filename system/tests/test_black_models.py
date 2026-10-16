"""Focused tests for gbox.black_models (Black PS2 cast reconnaissance, request #1965).

The disc and ELF fixtures are the operator's owned files on the Spark; tests skip
without them. GRDLNCHR.WDO is embedded (211 bytes) so the WDO parser is always tested.
"""
import hashlib
import struct
from pathlib import Path

import pytest

from gbox import black_models as bm
from gbox.black_models import DISC, ELF, CAST_WEAPONS, LOADER_SITES, FormatError, elf_loader_sites

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
