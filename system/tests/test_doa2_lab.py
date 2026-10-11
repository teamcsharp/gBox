from pathlib import Path

import pytest

from gbox import doa2_lab as L


def listing():
    return {f"DOA2/{stem}.{extension}": (1, 8)
            for stem in ("KAS00", "KAS01", "AYA00", "KTE02") for extension in ("CHR", "BIN", "SUP")}


def test_selects_actual_costumes_and_named_fighters():
    assert L.selected_costumes(listing(), "all", "all") == [("KAS", "00"), ("KAS", "01"), ("AYA", "00"), ("KTE", "02")]
    assert L.selected_costumes(listing(), "Ein", "all") == [("KTE", "02")]
    assert L.selected_costumes(listing(), "Kasumi:1", "00") == [("KAS", "01")]


def test_missing_costume_and_incomplete_archive_triplet_rejected():
    with pytest.raises(ValueError, match="absent"):
        L.selected_costumes(listing(), "Ein", "00")
    files = listing()
    del files["DOA2/KTE02.SUP"]
    with pytest.raises(ValueError, match="absent"):
        L.selected_costumes(files, "Ein", "02")


def test_profile_path_remains_inside_game_rig_directory(tmp_path):
    root = tmp_path / "rigs"
    root.mkdir()
    (root / "verified.json").write_text("{}")
    (tmp_path / "other.json").write_text("{}")
    assert L.profile_file(root, "verified.json") == root / "verified.json"
    for path in ("../other.json", "missing.json", ""):
        with pytest.raises(ValueError):
            L.profile_file(root, path)
