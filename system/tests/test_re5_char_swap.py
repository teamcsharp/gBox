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


def test_uem11_donor_swap_also_plans_its_required_class_rebind(tmp_path):
    from gbox import mt_arc, re5_ips
    from tests.test_re5_ips_class_rebind import supported_main
    donor = mt_arc.build(mt_arc.Arc(7, [mt_arc.Entry("em1000", 0, 0, 3, 0, b"arc")]))
    romfs = make_romfs(tmp_path, {"uEm10.arc": donor, "uEm11.arc": b"old"})
    main = supported_main()
    with pytest.raises(S.SwapError, match="verified decompressed NSO"):
        S.plan_changes(romfs, [("uEm10.arc", "uEm11.arc")])
    report, changes = S.plan_changes(romfs, [("uEm10.arc", "uEm11.arc")], main=main)
    assert report.pairs[0]["class_rebind"] == "uEm11->uEm10"
    assert changes == re5_ips.rebind_changes(donor, main=main)
    cfg = type("Config", (), {"cache": str(tmp_path / "cache")})()
    with pytest.raises(S.SwapError, match="only measured for RE5"):
        S.build(cfg, romfs, "game", "OTHER-TITLE", [("uEm10.arc", "uEm11.arc")], write=False)
    with pytest.raises(S.SwapError, match="existing verified"):
        S.build(cfg, romfs, "game", re5_ips.TITLE_ID, [("uEm10.arc", "uEm11.arc")], write=False)
    path = tmp_path / "cache" / "exefs" / re5_ips.TITLE_ID / "main.bin"
    path.parent.mkdir(parents=True)
    path.write_bytes(main)
    report = S.build(cfg, romfs, "game", re5_ips.TITLE_ID, [("uEm10.arc", "uEm11.arc")], write=False)
    assert "exefs/main.ips" in report.written


@pytest.mark.parametrize("name", ["../uEm10.arc", "..\\uEm10.arc", "C:uEm10.arc"])
def test_pair_names_cannot_escape_the_archive_folder(tmp_path, name):
    romfs = make_romfs(tmp_path, {"uEm11.arc": b"old"})
    with pytest.raises(S.SwapError, match="basenames"):
        S.plan_changes(romfs, [(name, "uEm11.arc")])


def test_build_stages_changes_when_a_session_uses_the_overlay(tmp_path, monkeypatch):
    from gbox import switch_mods
    romfs = make_romfs(tmp_path, {"uPl00ChrisNormal.arc": b"c", "uPl02JillCos1.arc": b"j"})
    calls = []
    monkeypatch.setattr(switch_mods, "running_users", lambda gid, name: ["live-session"])
    def write(*args, **kwargs):
        calls.append(kwargs)
        return {"pending": kwargs["in_use"], "files": list(args[3])}
    monkeypatch.setattr(switch_mods, "write_files", write)
    report = S.build(object(), romfs, "game", "title", [("uPl02JillCos1.arc", "uPl00ChrisNormal.arc")])
    assert calls[0]["in_use"] is True
    assert report.as_dict()["pending_restart"] is True


def test_rebind_main_can_verify_an_existing_eden_dump(tmp_path, monkeypatch):
    from gbox import provision, re5_ips, re_switch
    from tests.test_re5_ips_class_rebind import supported_main
    monkeypatch.setattr(provision, "switch_linux_dir", lambda cfg: tmp_path / "eden")
    path = tmp_path / "eden" / "dump" / re5_ips.TITLE_ID / "nso" / f"main-{re_switch.RE5_MAIN_BUILD_ID}.nso"
    path.parent.mkdir(parents=True)
    path.write_bytes(supported_main())
    cfg = type("Config", (), {"cache": tmp_path / "cache"})()
    assert S.rebind_main(cfg) == path.read_bytes()
