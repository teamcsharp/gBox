"""RE6 body-archive swapping: the RE5 route applied to nativeNXx64/arc/NX."""
import pytest

from gbox import re6_char_swap as S


def make_romfs(tmp_path, files: dict[str, bytes] | None = None):
    root = tmp_path / "romfs" / "01002A000CD48000" / "nativeNXx64" / "arc" / "NX"
    root.mkdir(parents=True)
    for name, data in (files or {}).items():
        (root / name).write_bytes(data)
    return tmp_path / "romfs" / "01002A000CD48000"


def test_the_re6_tree_is_required(tmp_path):
    with pytest.raises(S.SwapError):
        S.archive_root(tmp_path)


def test_the_catalogue_reads_the_arc_nx_body_archives(tmp_path):
    romfs = make_romfs(tmp_path, {"uPl00LeonUsa.arc": b"l", "uPl01HelenaUsa.arc": b"h",
                                  "uEm5200.arc": b"z", "uPl00HeadLeonUsa.arc": b"head"})
    out = S.catalogue(romfs)
    assert out["characters"] == ["uPl00HeadLeonUsa.arc", "uPl00LeonUsa.arc", "uPl01HelenaUsa.arc"]
    assert out["enemies"] == ["uEm5200.arc"]


def test_a_missing_donor_is_skipped_with_its_reason(tmp_path):
    romfs = make_romfs(tmp_path, {"uPl00LeonUsa.arc": b"l"})
    report = S.plan(romfs, [("uPl01HelenaUsa.arc", "uPl00LeonUsa.arc")])
    assert report.pairs == []
    assert "missing uPl01HelenaUsa.arc" in report.skipped[0]["reason"]


def test_a_complete_pair_names_the_body_archive(tmp_path):
    romfs = make_romfs(tmp_path, {"uPl00LeonUsa.arc": b"l" * 8, "uPl01HelenaUsa.arc": b"h" * 3})
    report = S.plan(romfs, [("uPl01HelenaUsa.arc", "uPl00LeonUsa.arc")])
    assert report.pairs[0]["target"] == "uPl00LeonUsa.arc"
    assert report.pairs[0]["donor_bytes"] == 3


def test_the_overlay_path_is_the_arc_nx_path(tmp_path):
    romfs = make_romfs(tmp_path, {"uPl00LeonUsa.arc": b"l", "uPl01HelenaUsa.arc": b"h"})
    config = type("Config", (), {"cache": str(tmp_path / "cache")})()
    report = S.build(config, romfs, [("uPl01HelenaUsa.arc", "uPl00LeonUsa.arc")], write=False)
    assert report.written == ["romfs/nativeNXx64/arc/NX/uPl00LeonUsa.arc"]
