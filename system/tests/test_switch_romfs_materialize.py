"""gbox.switch_romfs_materialize: the arc list a swap targets and the destination rule."""
import struct
from types import SimpleNamespace

import pytest

from gbox import skin_swap, switch_romfs_materialize as M


def container(tmp_path, names=("a.nca", "b.tik")):
    table = b"".join(n.encode() + b"\x00" for n in names)
    entries = b""
    offset = 0
    name_at = 0
    data = b""
    for name in names:
        body = b"AAAA"
        entries += struct.pack("<QQII", offset, len(body), name_at, 0)
        offset += len(body)
        name_at += len(name) + 1
        data += body
    path = tmp_path / "game.nsp"
    path.write_bytes(struct.pack("<4sIII", b"PFS0", len(names), len(table), 0) + entries + table + data)
    return path


def test_re6_wanted_paths_cover_cast_and_enemies():
    paths = M.wanted("01002a000cd48000")
    assert any(p.endswith("uPl00LeonUsa.arc") for p in paths)
    assert any("uEm5200.arc" in p for p in paths)
    assert any("uEm1000.arc" in p for p in paths)
    assert len(paths) == len(set(paths))          # deduplicated (the majini arc is also an enemy arc)


def test_an_unmapped_title_wants_nothing():
    assert M.wanted("0100000000000000") == []


def test_dest_is_required_without_an_extracted_tree(monkeypatch):
    monkeypatch.setattr(skin_swap, "romfs_root", lambda tid: None)
    with pytest.raises(FileNotFoundError):
        M.materialize("x.nsp", "a.nca", "prod.keys", "01002A000CD48000")


def test_a_missing_container_fails_before_any_write(tmp_path):
    with pytest.raises(FileNotFoundError):
        M.materialize(tmp_path / "nope.nsp", "a.nca", tmp_path / "prod.keys", "01002A000CD48000",
                      dest=tmp_path / "out")


def test_print_mode_lists_the_paths(tmp_path, capsys):
    assert M.main(["--print", "--title", "01002A000CD48000", "--keys", "k", "--dest", str(tmp_path), "c.nsp", "a.nca"]) == 0
    out = capsys.readouterr().out
    assert "uPl00LeonUsa.arc" in out and "uEm5200.arc" in out

def test_select_adds_include_prefixes_after_the_wanted_paths():
    by_path = {
        "nativeNXx64/arc/NX/uPl00LeonUsa.arc": {},
        "nativeNXx64/arc/NX/uPlTex0000_0.arc": {},
        "nativeNXx64/arc/NX/uPlTex0010_1.arc": {},
        "nativeNXx64/arc/NX/uEm5200.arc": {},
    }
    plain = M.select(by_path, "01002A000CD48000")
    assert all("uPlTex" not in p for p in plain)
    with_tex = M.select(by_path, "01002A000CD48000", ("uPlTex",))
    assert len(with_tex) == len(plain) + 2
    assert with_tex[-2:] == sorted(p for p in by_path if "uPlTex" in p)
