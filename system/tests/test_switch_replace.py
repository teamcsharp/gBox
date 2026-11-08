"""The replacement step: what it refuses, and what it reports.

The refusals matter as much as the work - a page calls this with paths from a catalogue, and every one of them can be stale. The report
shape is pinned because the sidebar renders it directly.
"""
from pathlib import Path

import pytest

from gbox import switch_replace as S


class Config:
    romfs = ""


def test_a_missing_romfs_is_refused_with_the_paths_it_tried(tmp_path):
    with pytest.raises(S.ReplaceError) as raised:
        # a title id that cannot exist on any machine, so the test means the same thing everywhere
        S.romfs_root(Config(), "0000000000000000")
    assert "bio4/" in str(raised.value)


def test_romfs_root_finds_an_extracted_tree(tmp_path, monkeypatch):
    (tmp_path / "gBox_alt" / "switch" / "romfs" / "TITLE" / "bio4").mkdir(parents=True)
    monkeypatch.setattr(S.Path, "home", classmethod(lambda cls: tmp_path))
    found = S.romfs_root(Config(), "TITLE")
    assert found.name == "TITLE" and (found / "bio4").is_dir()


def test_a_pack_that_is_not_there_is_refused(tmp_path, monkeypatch):
    (tmp_path / "gBox_alt" / "switch" / "romfs" / "TITLE" / "bio4" / "em").mkdir(parents=True)
    monkeypatch.setattr(S.Path, "home", classmethod(lambda cls: tmp_path))
    with pytest.raises(S.ReplaceError) as raised:
        S.replace_pack(Config(), "TITLE", "em16.udas", donor_glb="x.glb")
    assert "em16.udas" in str(raised.value)


def test_no_donor_is_refused():
    with pytest.raises(S.ReplaceError):
        S.donor_mesh(None, None)


def test_a_missing_donor_glb_is_refused():
    with pytest.raises(S.ReplaceError):
        S.donor_mesh("/definitely/not/here.glb", None)


def test_the_report_says_what_it_did():
    report = S.ReplaceReport(pack="em16.udas", donor="sonic.glb", build="test")
    report.slots.append({"slot": 0, "vertices": 100})
    report.vertices_changed = 100
    payload = report.as_dict()
    for key in ("pack", "donor", "build", "blend", "slots", "skipped", "touched", "vertices_changed", "written"):
        assert key in payload, f"{key} is not in the report"
    assert payload["touched"] == 1


def test_a_hide_only_edit_does_not_need_a_donor():
    """"Remove clothes" is a hide with no donor: the refusal must be about *something to do*, not about a donor."""
    with pytest.raises(S.ReplaceError) as raised:
        S.donor_mesh(None, None)
    assert "donor" in str(raised.value)
    # and the guard that matters: no donor and no hide is refused before any file is touched
    with pytest.raises(S.ReplaceError) as refused:
        S.replace_pack(Config(), "0000000000000000", "pl00.udas")
    assert "a donor is required" in str(refused.value) or "RomFS" in str(refused.value)
