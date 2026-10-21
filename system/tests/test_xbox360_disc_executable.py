"""The xbox360 disc route must find default.xex (#2057: Armored Core V).

``XDVD.files`` is keyed by absolute disc paths ("/default.xex"), but
``gbox.re_lab_tool.extract_from_disc`` asked for "default.xex".  Every
xbox360 disc extraction therefore died with ``KeyError: 'default.xex'``
before a single byte of the executable was read, which looked like an
unreadable ROM on the worker.  The reader now accepts both spellings.
"""
import struct

import pytest

from gbox import re6
from gbox.re6 import XDVD


def _xiso(tmp_path, name="default.xex", payload=b"XEX2" + b"\0" * 60):
    """A minimal XDVDFS image holding one file, as the Xbox 360 discs are."""
    path = tmp_path / "game.iso"
    sector = 2048
    root_lba, root_size = 264, 88
    data_lba = 300
    with path.open("wb") as writer:
        writer.truncate(data_lba * sector + len(payload))
        # volume descriptor at LBA 32
        writer.seek(32 * sector)
        writer.write(b"MICROSOFT*XBOX*MEDIA" + struct.pack("<II", root_lba, root_size))
        # root directory: one file entry.  left/right are 4-byte offsets of the
        # tree children; 0 means "no child" (0xFFFF would mean "skip me").
        writer.seek(root_lba * sector)
        entry = struct.pack("<HHIIBB", 0, 0, data_lba, len(payload), 0x20, len(name))
        entry += name.encode("latin-1")
        entry += b"\0" * ((-len(entry)) % 4)
        writer.write(entry)
        writer.seek(data_lba * sector)
        writer.write(payload)
    return path


def test_read_accepts_absolute_and_bare_paths(tmp_path):
    path = _xiso(tmp_path)
    disc = XDVD(path)
    try:
        assert "/default.xex" in disc.files
        assert disc.read("/default.xex") == b"XEX2" + b"\0" * 60
        assert disc.read("default.xex") == b"XEX2" + b"\0" * 60
    finally:
        disc.close()


def test_read_unknown_file_still_raises_key_error(tmp_path):
    path = _xiso(tmp_path)
    disc = XDVD(path)
    try:
        with pytest.raises(KeyError):
            disc.read("missing.xex")
    finally:
        disc.close()


def test_xbox360_disc_route_extracts_the_executable(tmp_path, monkeypatch):
    """extract_from_disc must return the XEX bytes, not raise KeyError."""
    from gbox import re_lab_tool

    path = _xiso(tmp_path)
    game = {"platform": "xbox360", "title": "Armored Core V"}

    def fake_xex_image(xex):
        return {"image": b"PE-IMAGE", "base": 0x82000000, "entry": 0x82B90778, "size": 8}

    monkeypatch.setattr(re6, "xex_image", fake_xex_image)
    elf, raw, info = re_lab_tool.extract_from_disc(None, game, path)
    assert raw == b"XEX2" + b"\0" * 60
    assert info["source_file"] == "default.xex"
    assert info["format"] == "XEX2 -> PE image"
    assert info["base"] == 0x82000000
    assert elf[:4] == b"\x7fELF"
