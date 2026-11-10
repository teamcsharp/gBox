"""gbox.tools.switch_decrypt: the dispatchable client-side decryption job (validation and the key-free `info` path)."""
import struct
from types import SimpleNamespace

import pytest

from gbox import tools
from gbox.config import Config
from gbox.registry import ToolUnavailable


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


def ctx(tmp_path):
    return SimpleNamespace(config=Config(data_dir=tmp_path / "data"))


def test_info_needs_only_the_container(tmp_path, monkeypatch):
    from gbox import hactool
    monkeypatch.setattr(hactool, "keys_path", lambda: None)
    out = tools.switch_decrypt(tools.SwitchDecryptIn(op="info", container=str(container(tmp_path))), ctx(tmp_path))
    assert [m["name"] for m in out["result"]["members"]] == ["a.nca", "b.tik"]


def test_a_missing_container_is_unavailable(tmp_path):
    with pytest.raises(ToolUnavailable, match="not a file"):
        tools.switch_decrypt(tools.SwitchDecryptIn(op="info", container=str(tmp_path / "nope.nsp")), ctx(tmp_path))


def test_an_unknown_op_is_refused(tmp_path):
    with pytest.raises(ValueError, match="unknown op"):
        tools.switch_decrypt(tools.SwitchDecryptIn(op="format-c", container=str(container(tmp_path))),
                             ctx(tmp_path))


def test_no_keys_is_unavailable_before_any_decryption(tmp_path, monkeypatch):
    from gbox import hactool
    monkeypatch.setattr(hactool, "keys_path", lambda: None)
    with pytest.raises(ToolUnavailable, match="prod.keys"):
        tools.switch_decrypt(tools.SwitchDecryptIn(op="romfs-list", container=str(container(tmp_path)), nca="a.nca"),
                             ctx(tmp_path))


def test_out_is_required_for_file_ops(tmp_path, monkeypatch):
    from gbox import hactool
    monkeypatch.setattr(hactool, "keys_path", lambda: str(tmp_path / "prod.keys"))
    with pytest.raises(ValueError, match="needs out"):
        tools.switch_decrypt(tools.SwitchDecryptIn(op="exefs", container=str(container(tmp_path)), nca="a.nca"),
                             ctx(tmp_path))
