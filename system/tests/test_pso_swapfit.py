"""gbox.pso_swapfit: the rule that predicts which raw model swaps render and which crash, checked against the disc."""
from pathlib import Path

import pytest

from gbox import pso_swapfit as F

DISC = Path(r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz")

HUMAR = {"bones": 64, "vertices": 269, "buckets": [0, 1, 2, 3, 4]}
HUCAST = {"bones": 64, "vertices": 311, "buckets": [0, 1, 2, 3, 4]}
HUNEWEARL = {"bones": 64, "vertices": 356, "buckets": [0, 1, 2, 3, 4, 5, 6, 7]}


def test_a_donor_with_more_materials_is_refused():
    """This is the crash: the renderer looks up a material the host does not have."""
    out = F.compare(HUMAR, HUNEWEARL)
    assert out["safe"] is False and "the donor references texture buckets the host does not have" in out["why"]


def test_a_donor_with_the_same_materials_but_other_proportions_is_allowed_but_flagged():
    out = F.compare(HUMAR, HUCAST)
    assert out["safe"] is True and out.get("deforms") is True
    assert "renders with the donor's proportions on the host's skeleton" in out["why"]


def test_an_identical_body_is_a_clean_copy():
    out = F.compare(HUMAR, HUMAR)
    assert out["safe"] is True and not out.get("deforms") and "all match" in out["why"]


def test_a_bone_count_difference_is_refused():
    out = F.compare(HUMAR, {"bones": 60, "vertices": 269, "buckets": [0, 1, 2, 3, 4]})
    assert out["safe"] is False and "bone count differs" in out["why"]


def test_an_empty_body_is_refused():
    assert F.compare({"bones": 0}, HUMAR)["safe"] is False


def test_the_report_spells_out_the_numbers():
    text = F.report(HUMAR, HUNEWEARL, host_name="HUmar", donor_name="HUnewearl")
    assert text.startswith("REFUSE: HUnewearl -> HUmar")
    assert "64 bones" in text and "8 texture buckets" in text


@pytest.mark.skipif(not DISC.is_file(), reason="the disc is not on this machine")
def test_the_real_bodies_predict_both_round_35_outcomes():
    """The rule must reproduce what the emulator did: HUcast renders (5 buckets), HUnewearl crashes (8 buckets)."""
    from gbox import gcdisc, pso_gc_paths

    d = gcdisc.GCDisc(str(DISC))
    sigs = {cls: F.signature_nj(pso_gc_paths.nj_part(d, f"PSO/PL{cls}BDY00.NJ")) for cls in ("A", "B", "C")}
    assert sigs["A"]["bones"] == sigs["C"]["bones"] == sigs["B"]["bones"] == 64
    assert F.compare(sigs["A"], sigs["C"])["safe"] is True, "HUcast must be the render-but-deform case"
    assert F.compare(sigs["A"], sigs["B"])["safe"] is False, "HUnewearl must be the refused case"
    assert len(sigs["A"]["buckets"]) == 5 and len(sigs["B"]["buckets"]) == 8


def test_a_donor_that_uses_a_subset_of_the_host_materials_is_safe():
    """A built GC swap emits the fitted mesh in one host material: fewer buckets, all of them the host's own."""
    host = {"bones": 64, "buckets": [0, 1, 2, 3, 4], "vertices": 311}
    donor = {"bones": 64, "buckets": [1], "vertices": 666}
    result = F.compare(host, donor)
    assert result["safe"] is True and result.get("subset") is True
    assert result.get("deforms") is True                 # different vertex count: the gate's own wording
# ---- CP7.1: the +0x8 field the crash address reads --------------------------------------------------------------------------

def _nj_bytes(centres):
    """A minimal NJCM with one model per centre tuple: 52-byte nodes and 24-byte model headers, big-endian."""
    import struct as _s
    nodes = len(centres)
    node_block = bytearray(52 * nodes)
    model_block = bytearray()
    model_base = 52 * nodes
    for i, centre in enumerate(centres):
        off = 52 * i
        mo = model_base + len(model_block)
        _s.pack_into(">II", node_block, off, 0x07, mo)
        child = 52 * (i + 1) if i + 1 < nodes else 0          # child/sibling are byte offsets, not indices
        _s.pack_into(">II", node_block, off + 44, child, 0)
        model_block += _s.pack(">II4f", 0, 0, *centre)
    payload = bytes(node_block) + bytes(model_block)
    return b"NJCM" + _s.pack("<I", len(payload)) + payload


def test_the_signature_carries_the_model_list_and_its_centres():
    from gbox import ninja
    nj = ninja.NJ(_nj_bytes([(1.0, 2.0, 3.0, 4.0)]), be=True)
    sig = F.signature_nj(nj)
    assert sig["models"] == 1 and sig["centre_ok"] is True


def test_a_non_finite_centre_is_refused_with_the_0x8028f508_reason():
    from gbox import ninja
    bad = ninja.NJ(_nj_bytes([(float("nan"), 0.0, 0.0, 1.0)]), be=True)
    good = ninja.NJ(_nj_bytes([(0.0, 0.0, 0.0, 1.0)]), be=True)
    verdict = F.compare(F.signature_nj(good), F.signature_nj(bad))
    assert verdict["safe"] is False and "0x8028f508" in verdict["why"]


def test_a_different_model_list_length_is_refused():
    from gbox import ninja
    host = F.signature_nj(ninja.NJ(_nj_bytes([(0.0, 0.0, 0.0, 1.0)]), be=True))
    donor = F.signature_nj(ninja.NJ(_nj_bytes([(0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0, 2.0)]), be=True))
    verdict = F.compare(host, donor)
    assert verdict["safe"] is False and "model list" in verdict["why"]


def test_the_real_bodies_have_the_measured_model_lists():
    import pathlib as _p
    from gbox import gcdisc, ninja, pso_gc_paths
    disc = _p.Path(r"D:\\gBox\\cache\\mods\\436e0bb84d5337d1\\pso_city_npc_moved"
                   r"\\Phantasy Star Online Episode I & II Plus (USA).iso")
    if not disc.is_file():
        pytest.skip("the disc is not on this machine")
    d = gcdisc.GCDisc(str(disc))
    for letter in ("A", "B", "C"):
        body = pso_gc_paths.read_part(d, pso_gc_paths.gc_path(f"PSO/PL{letter}BDY00.NJ"))
        sig = F.signature_nj(ninja.NJ(body, be=True))
        # measured: HUmar 18 model nodes, HUnewearl 20, HUcast 18 - the list the transform walk indexes
        assert sig["models"] == {"A": 18, "B": 20, "C": 18}[letter], letter
        assert sig["centre_ok"] is True, letter
