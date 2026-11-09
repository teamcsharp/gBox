"""gbox.switch_extract: the container member table and the CLI's non-keyed path (info); the keyed paths need real keys."""
import struct

import pytest

from gbox import switch_extract as X


def container(tmp_path, names=("a.nca", "b.tik"), payload=b""):
    table = b"".join(n.encode() + b"\x00" for n in names)
    entries = b""
    offset = 0
    name_at = 0
    data = b""
    for name, body in zip(names, [b"AAAA", b"BBBBBBBB"]):
        entries += struct.pack("<QQII", offset, len(body), name_at, 0)
        offset += len(body)
        name_at += len(name) + 1
        data += body
    path = tmp_path / "game.nsp"
    path.write_bytes(struct.pack("<4sIII", b"PFS0", len(names), len(table), 0) + entries + table + data)
    return path


def test_members_reports_offsets_relative_to_the_container(tmp_path):
    path = container(tmp_path)
    out = X.members(path)
    assert [m["name"] for m in out] == ["a.nca", "b.tik"]
    assert out[0]["size"] == 4 and out[1]["size"] == 8
    data_at = 0x10 + 2 * 0x18 + len(b"a.nca\x00b.tik\x00")
    assert out[0]["offset"] == data_at and out[1]["offset"] == data_at + 4


def test_main_info_prints_the_members_without_keys(tmp_path, capsys):
    path = container(tmp_path)
    assert X.main(["info", str(path)]) == 0
    out = capsys.readouterr().out
    assert "a.nca 4" in out and "b.tik 8" in out


def test_nca_refuses_a_missing_member(tmp_path):
    path = container(tmp_path)
    with pytest.raises(ValueError, match="not a member"):
        X.Nca(path, "nope.nca", {"header_key": "00" * 32})
