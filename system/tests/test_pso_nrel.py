"""CP6.2: the n.rel index runs and the triangle count against c.rel's footprint."""
import pathlib

import pytest

from gbox import pso_nrel as N

DISC = pathlib.Path(r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved"
                    r"\Phantasy Star Online Episode I & II Plus (USA).iso")


@pytest.fixture(scope="module")
def disc():
    from gbox import gcdisc
    if not DISC.is_file():
        pytest.skip("the disc is not on this machine")
    return gcdisc.GCDisc(str(DISC))


def test_index_runs_are_found_and_fit_the_vertex_bound(disc):
    data = disc.read("Scene/map_aancient01_00n.rel")
    runs = N.index_runs(data)
    assert len(runs) == 167
    assert all(len(r["values"]) >= N.MIN_RUN for r in runs)
    assert all(max(r["values"]) < 1112 for r in runs)
    assert sum(len(r["values"]) for r in runs) == 38689


def test_the_triangle_count_is_within_the_collision_footprint_order(disc):
    nrel = disc.read("Scene/map_aancient01_00n.rel")
    crel = disc.read("Scene/map_aancient01_00c.rel")
    summary = N.describe(nrel, crel)
    assert summary["triangles"] == 12896
    assert summary["collision_triangles"] == 11549
    assert 1.0 <= summary["ratio"] <= 1.2          # render mesh slightly denser than collision, as expected


def test_a_synthetic_index_array_is_counted(disc):
    # three consecutive triangles = 9 values, all below the bound; out-of-range words bound the run
    payload = b"".join(int(v).to_bytes(2, "big") for v in (0, 1, 2, 2, 1, 3, 4, 5, 6))
    data = b"\xff\xff" * 8 + payload + b"\xff\xff" * (N.MIN_RUN + 8)
    runs = N.index_runs(data, max_index=1112, min_run=3)
    assert runs and sum(len(r["values"]) for r in runs) == 9
    assert N.triangles(data, min_run=3) == 3


def test_a_run_with_values_above_the_bound_is_not_index_data():
    data = b"\xff\xff" * 100
    assert N.index_runs(data) == []


def test_the_structural_round_trip_reproduces_the_file_byte_for_byte(disc):
    """Every region is re-emitted from its parsed form: indices from u16 values, floats from floats, raw as-is."""
    data = disc.read("Scene/map_aancient01_00n.rel")
    rebuilt, totals = N.roundtrip(data)
    assert rebuilt == data
    assert sum(totals.values()) == len(data)
    assert totals["indices"] > 40000 and totals["floats"] > 100000   # the measured split, roughly 3:7


def test_the_region_kinds_are_contiguous_and_cover_the_file(disc):
    data = disc.read("Scene/map_aancient01_00n.rel")
    regs = N.regions(data)
    assert regs[0]["offset"] == 0
    assert all(a["offset"] + a["length"] == b["offset"] for a, b in zip(regs, regs[1:]))
    assert regs[-1]["offset"] + regs[-1]["length"] == len(data)
    kinds = {r["kind"] for r in regs}
    assert kinds <= {"indices", "floats", "raw"}
