"""The HD model-pack replace step as an operation: `pack_slots` and `swap_pack`.

These are what the extraction tab needs to offer "inventory -> pick a slot -> replace": one lists a pack's slots with
the ones the decoder refuses named, the other performs the swap and reports per slot. Both take a root path, so a
temporary tree is enough to pin them without game data.
"""
import struct

import pytest

from gbox import decrypt_lab as L
from gbox import re4gc_inventory as I
from gbox import re4hd_models as M

from test_re4hd_models import make_bin, grid_mesh, pack_with


@pytest.fixture
def hd_tree(tmp_path):
    em = tmp_path / "bio4" / "em"
    em.mkdir(parents=True)
    small = M.bin_read(make_bin(n=6, bones=((0, 0xFF),), prims=((5, 6),)))
    big = M.bin_read(make_bin(n=60, bones=((0, 0xFF),), prims=((5, 60),)))
    (em / "em11.udas").write_bytes(pack_with(M.bin_from(small, pos=small.pos, tris=small.tris),
                                             M.bin_from(big, pos=big.pos, tris=big.tris)))
    donor_pos, donor_tris = grid_mesh(9)                   # 128 triangles: needs simplifying to fit
    donor = M.Bin(header=b"", info={})
    donor.pos, donor.tris, donor.uv, donor.colors = donor_pos, donor_tris, None, None
    (em / "em21.udas").write_bytes(pack_with(M.bin_from(big, pos=donor_pos, tris=donor_tris)))
    return tmp_path


def test_pack_slots_lists_what_a_swap_can_target(hd_tree):
    out = L.pack_slots(hd_tree, "em11.udas")
    assert out["pack"] == "bio4/em/em11.udas" and out["slots"] == 2 and out["decodable"] == 2
    for row in out["rows"]:
        assert row["status"] == "ok" and row["verts"] > 0 and row["bones"] == 1
    # the index the swap takes is `bin`, and it is what the rows are ordered by
    assert [r["bin"] for r in out["rows"]] == [0, 1]
    with pytest.raises(FileNotFoundError):
        L.pack_slots(hd_tree, "nope.udas")


def test_swap_pack_replaces_the_named_slot_and_reports_it(hd_tree):
    out = L.swap_pack(hd_tree, "em11.udas", "em21.udas", 0, slots=[1])
    assert out["changed"] and out["swapped"] == 1
    row = out["report"][0]
    assert row["bin"] == 1 and row["status"] == "swapped"
    assert row["bytes"] <= row["slot_bytes"]
    # the pack keeps its slot sizes: a replacement is in place, never a resize
    assert [s["size"] for s in I.bin_slots(out["data"], "<")] == [s["size"] for s in I.bin_slots(
        (hd_tree / "bio4" / "em" / "em11.udas").read_bytes(), "<")]
    assert len(out["data"]) == (hd_tree / "bio4" / "em" / "em11.udas").stat().st_size


def test_swap_pack_simplifies_a_donor_that_cannot_fit_as_given(hd_tree):
    out = L.swap_pack(hd_tree, "em11.udas", "em21.udas", 0, slots=[1])
    row = out["report"][0]
    assert row["status"] == "swapped" and row["simplified"] is True
    assert row["tris"] < out["donor_tris"]


def test_a_slot_too_small_for_any_simplification_is_reported_not_forced(hd_tree):
    """The tiny slot holds six vertices; no budget makes a 128-triangle donor fit it, and saying so is the answer."""
    out = L.swap_pack(hd_tree, "em11.udas", "em21.udas", 0, slots=[0])
    assert out["swapped"] == 0 and out["changed"] is False
    assert out["report"][0]["status"] == "too_big"


def test_swap_pack_refuses_a_donor_index_out_of_range_and_a_missing_pack(hd_tree):
    with pytest.raises(ValueError, match="out of range"):
        L.swap_pack(hd_tree, "em11.udas", "em21.udas", 9)
    with pytest.raises(FileNotFoundError):
        L.swap_pack(hd_tree, "nope.udas", "em21.udas", 0)


def test_a_tree_without_bio4_em_is_refused_by_the_route_helper(tmp_path):
    with pytest.raises(FileNotFoundError):
        L.pack_slots(tmp_path, "em11.udas")
