"""gbox.skin_swap's whole-model fallback: the path RE6 player arcs take (model payload, not BM/MM/NM map groups)."""
import pytest

from gbox import mt_arc, skin_swap


def test_model_swap_arc_refuses_a_non_arc(tmp_path):
    target = tmp_path / "target.arc"
    donor = tmp_path / "donor.arc"
    target.write_bytes(b"NOT AN ARC")
    donor.write_bytes(b"NOT AN ARC EITHER")
    data, slot, donor_name = skin_swap.model_swap_arc(target, donor)
    assert data is None and slot == "" and donor_name == ""


def test_model_swap_arc_logs_the_failure(tmp_path):
    target = tmp_path / "t.arc"
    donor = tmp_path / "d.arc"
    target.write_bytes(b"NOPE")
    donor.write_bytes(b"NOPE")
    seen = []
    skin_swap.model_swap_arc(target, donor, log=lambda *a, **k: seen.append((a, k)))
    assert seen and seen[0][0][0] == "model_swap_failed"


def test_swap_arc_still_refuses_re6_style_names():
    # a body whose model entries are all named the same has no BM/MM/NM groups, which is what the fallback is for
    assert skin_swap.body_group({}) is None
    with pytest.raises(mt_arc.ArcError):
        mt_arc.parse(b"not an archive")
