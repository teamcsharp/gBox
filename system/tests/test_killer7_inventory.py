"""Focused tests for gbox.killer7_inventory (hermetic — no disc mount needed)."""
import struct

from gbox.killer7_inventory import (
    chara_roster,
    classify_variant,
    is_hsd,
    hsd_roots,
    re_match_model_index,
)


def _synthetic_hsd(roots=("scene_data", "castsShadows")) -> bytes:
    """Build a minimal valid HSD archive with the given root names."""
    ds = 8
    nr = 0
    nroot = len(roots)
    nref = 0
    name_blob = bytearray()
    root_entries = bytearray()
    so = 0
    for name in roots:
        root_entries += struct.pack(">II", 0, so)
        name_blob += name.encode("latin-1") + b"\0"
        so = len(name_blob)
    data = bytearray(b"\x00" * ds)
    o = 0x20 + ds + 4 * nr
    strs = o + 8 * (nroot + nref)
    fs = strs + len(name_blob)
    hdr = struct.pack(">5I", fs, ds, nr, nroot, nref) + b"\x00" * 12  # 0x20 header
    return bytes(hdr) + bytes(data) + bytes(root_entries) + bytes(name_blob)


def test_is_hsd_accepts_valid_and_rejects_garbage():
    h = _synthetic_hsd()
    assert is_hsd(h)
    # first u32 must equal the byte length
    assert not is_hsd(h + b"\x00")
    assert not is_hsd(b"\x00" * 0x20)
    assert not is_hsd(b"")


def test_hsd_roots():
    assert hsd_roots(_synthetic_hsd()) == ["castsShadows", "scene_data"]
    assert hsd_roots(b"not an hsd") == []


def test_classify_variant_case_insensitive():
    assert classify_variant("Cyo", "CYO_M00") == "M"
    assert classify_variant("Gal", "GAL_M00") == "M"
    assert classify_variant("Dan", "Dan_M04") == "M"
    assert classify_variant("AKI", "AKI_B_M00") == "B"
    assert classify_variant("AKI", "AKI_R_M00") == "R"
    assert classify_variant("Msk", "Msk_face_00") == "other"


def test_re_match_model_index():
    assert re_match_model_index("DAN_M00", "Dan") == 0
    assert re_match_model_index("CYO_M04", "Cyo") == 4
    assert re_match_model_index("DAN_M0", "Dan") == 0
    assert re_match_model_index("DAN_M", "Dan") is None
    assert re_match_model_index("AKI_B_M00", "AKI") is None


def test_chara_roster_groups_and_counts():
    files = {
        "3Ddata/Model/Chara/Dan/Dan_M00.dat": (0, 1),
        "3Ddata/Model/Chara/Dan/Dan_M04.dat": (0, 1),
        "3Ddata/Model/Chara/AKI/AKI_M00.dat": (0, 1),
        "3Ddata/Model/Chara/AKI/AKI_B_M00.dat": (0, 1),
        "3Ddata/Model/Chara/AKI/AKI_R_M00.dat": (0, 1),
        "3Ddata/Model/Chara/Cyo/CYO_M03.dat": (0, 1),
        "3Ddata/Model/Stage/573/Stage573_M00.pte": (0, 1),   # not Chara -> ignored
    }
    roster = chara_roster(files)
    assert set(roster) == {"Dan", "AKI", "Cyo"}
    assert roster["Dan"]["total"] == 2
    assert roster["Dan"]["variants"]["M"] == 2
    assert roster["Dan"]["model_variants"] == [0, 4]
    assert roster["AKI"]["variants"] == {"M": 1, "B": 1, "R": 1}
    # case-insensitive code matching folds CYO under Cyo
    assert roster["Cyo"]["model_variants"] == [3]
