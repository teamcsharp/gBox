"""The gated body swap: a donor that would crash is refused before any file is written."""
import pathlib

import pytest

from gbox import pso_gc, pso_gc_paths, pso_player as P

DISC = pathlib.Path(r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved"
                    r"\Phantasy Star Online Episode I & II Plus (USA).iso")


@pytest.fixture(scope="module")
def disc():
    from gbox import gcdisc
    if not DISC.is_file():
        pytest.skip("the disc is not on this machine")
    return gcdisc.GCDisc(str(DISC))


def test_a_matching_bucket_donor_is_allowed_and_reports_the_deform(disc):
    result = P.body_swap(disc, "A", "C", platform="gc")
    assert result["refused"] is False and result["deforms"] is True
    assert "vertices" in result["why"]
    assert set(result["files"]) == {"plAbdy00.nj", "plAnj.bml"}
    donor = pso_gc_paths.read_part(disc, pso_gc_paths.gc_path("PSO/PLCBDY00.NJ"))
    assert result["files"]["plAbdy00.nj"] == donor
    entries = {row["name"].split(b"\0")[0].decode("latin-1"): row
               for row in P.bml_files(result["files"]["plAnj.bml"], ">")}
    # the entry is PRS-compressed by the BML builder; fields[2] is its decompressed size, i.e. the donor body's length
    assert entries["plAbdy00.nj"]["fields"][2] == len(donor)
    assert entries["plAbdy00.nj"]["fields"][0] < len(donor)


def test_a_bucket_mismatch_is_refused_with_no_files(disc):
    result = P.body_swap(disc, "A", "B", platform="gc")
    assert result["refused"] is True and result["files"] == {}
    assert "texture buckets differ" in result["why"]


def test_the_same_class_and_a_bad_letter_are_refused_up_front(disc):
    with pytest.raises(ValueError, match="same class"):
        P.body_swap(disc, "A", "A")
    with pytest.raises(ValueError, match="unknown PSO class letter"):
        P.body_swap(disc, "A", "Z")
