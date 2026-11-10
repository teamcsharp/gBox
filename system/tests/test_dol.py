import hashlib
import os
import struct

import pytest

from gbox.formats.dol import find_strings, parse_dol


def _mk():
    h = bytearray(0x100)
    struct.pack_into(">I", h, 0, 0x100)
    struct.pack_into(">I", h, 0x48, 0x80004000)
    struct.pack_into(">I", h, 0x90, 0x20)
    struct.pack_into(">I", h, 7 * 4, 0x120)
    struct.pack_into(">I", h, 0x48 + 28, 0x80006740)
    struct.pack_into(">I", h, 0x90 + 28, 0x10)
    struct.pack_into(">III", h, 0xD8, 0x80300000, 0x1000, 0x80004008)
    return bytes(h) + b"\0" * 0x20 + b"/rel/Release/game.rel\0" + b"\0" * 0x20


def test_parse_synthetic():
    d = parse_dol(_mk())
    assert d["entry"] == 0x80004008 and d["text"][0]["size"] == 0x20
    assert d["data"][0]["addr"] == 0x80006740 and d["size"] == 0x130


def test_bad_entry_and_range():
    b = bytearray(_mk())
    struct.pack_into(">I", b, 0xE0, 0x90000000)
    with pytest.raises(ValueError):
        parse_dol(bytes(b))
    with pytest.raises(ValueError):
        parse_dol(_mk()[:0x110])


def test_strings():
    assert find_strings(_mk()) == ["/rel/Release/game.rel"]


def test_real_main_dol_if_extracted():
    p = os.path.join(os.environ.get("TMPDIR", "/tmp"), "om", "main.dol")
    if not os.path.exists(p):
        pytest.skip("main.dol not extracted")
    b = open(p, "rb").read()
    assert hashlib.sha256(b).hexdigest() == "8aa8be89f491ddc70ba52efb42171140184c0ad25fe056b0e08e8eaa67841a22"
    d = parse_dol(b)
    assert d["entry"] == 0x80006310 and d["size"] == len(b)
    assert "/rel/Release/game.rel" in find_strings(b)
