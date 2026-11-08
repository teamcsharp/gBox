"""Swapping RE5 character archives: what it refuses, what it plans, and what it writes.

The behaviour that matters is the planning half - a target must exist because it is the slot the game loads, and a pair with a
missing side is skipped with a reason rather than written blind. The writing half is one overlay file per target, which is the
route measured to render Jill in Chris's slot.
"""
import pytest

from gbox import re5_char_swap as S


def make_romfs(tmp_path, files: dict[str, bytes] | None = None):
    root = tmp_path / "romfs" / "010018100CD46000" / "nativeNXx64" / "ImgNX" / "Archive"
    root.mkdir(parents=True)
    for name, data in (files or {}).items():
        (root / name).write_bytes(data)
    return tmp_path / "romfs" / "010018100CD46000"


def test_a_tree_without_the_archive_folder_is_refused(tmp_path):
    with pytest.raises(S.SwapError):
        S.archive_root(tmp_path)


def test_the_catalogue_separates_characters_from_enemies(tmp_path):
    romfs = make_romfs(tmp_path, {"uPl00ChrisNormal.arc": b"c", "uPl02JillCos1.arc": b"j",
                                  "uEm6c.arc": b"e", "uEm71.arc": b"f", "README.txt": b"x"})
    out = S.catalogue(romfs)
    assert out["characters"] == ["uPl00ChrisNormal.arc", "uPl02JillCos1.arc"]
    assert out["enemies"] == ["uEm6c.arc", "uEm71.arc"]
    assert out["counts"] == {"characters": 2, "enemies": 2}


def test_a_missing_side_is_skipped_with_the_reason(tmp_path):
    romfs = make_romfs(tmp_path, {"uPl00ChrisNormal.arc": b"c"})
    report = S.plan(romfs, [("uPl02JillCos1.arc", "uPl00ChrisNormal.arc")])
    assert report.pairs == []
    assert "missing" in report.skipped[0]["reason"]


def test_a_complete_pair_is_planned_with_its_kind(tmp_path):
    romfs = make_romfs(tmp_path, {"uPl00ChrisNormal.arc": b"c", "uEm6c.arc": b"e" * 10})
    report = S.plan(romfs, [("uEm6c.arc", "uPl00ChrisNormal.arc")])
    assert report.pairs[0]["kind"] == "character"
    assert report.pairs[0]["donor_bytes"] == 10


def test_building_without_a_usable_pair_is_refused(tmp_path):
    romfs = make_romfs(tmp_path, {})
    config = type("Config", (), {"cache": str(tmp_path / "cache")})()
    with pytest.raises(S.SwapError):
        S.build(config, romfs, "game", "title", [("uPl02JillCos1.arc", "uPl00ChrisNormal.arc")])


def test_a_dry_run_lists_the_files_it_would_write(tmp_path):
    romfs = make_romfs(tmp_path, {"uPl00ChrisNormal.arc": b"c", "uPl02JillCos1.arc": b"j"})
    config = type("Config", (), {"cache": str(tmp_path / "cache")})()
    report = S.build(config, romfs, "game", "title", [("uPl02JillCos1.arc", "uPl00ChrisNormal.arc")], write=False)
    assert report.written == ["romfs/nativeNXx64/ImgNX/Archive/uPl00ChrisNormal.arc"]
    assert report.as_dict()["effective"].startswith("the title's next boot")
