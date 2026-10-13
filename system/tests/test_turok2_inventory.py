"""Turok 2 (N64, Europe NT2P) inventory tests.

The synthetic tests always run.  The owned-ROM test runs only when the
owned zip (GBOX_TUROK2_SOURCE or the gbox cache copy) is present.
"""
import hashlib
import os
import struct
from pathlib import Path

import pytest

from gbox import turok2_inventory as t2

OWNED_ZIP_SHA256 = "424730aea5572e0d30aa4165346b586e552cb46d956b7180686a3d57e696f7a1"
ROM_SHA256 = "6c8ec2083adeb6eb7bc0aad865384f77a8f89a98ff21b74a630dd85e8256ebf8"
SRC = Path(os.environ.get(
    "GBOX_TUROK2_SOURCE",
    Path.home() / "gbox-cache" / "96c6d766ba6202ca" / "source.zip"))


def _set(blocks: list[bytes]) -> bytes:
    n = len(blocks)
    hdr = 4 + 4 * (n + 1)
    hdr = (hdr + 15) & ~15
    offs, cur = [], hdr
    for b in blocks:
        offs.append(cur)
        cur += len(b)
    offs.append(cur)
    head = struct.pack(f">I{n + 1}I", n, *offs)
    return head.ljust(hdr, b"\0") + b"".join(blocks)


def test_find_cart_root_synthetic():
    obj = _set([b"\0" * 8, b"\1" * 8, b"\2" * 8, b"\3" * 8])
    go = _set([obj, obj])
    root = _set([go] + [b"\x55" * 16 for _ in range(20)])
    rom = b"\xAA" * 0x40 + root
    assert t2.find_cart_root(rom) == 0x40


def test_find_cart_root_rejects_wrong_shape():
    obj3 = _set([b"\0" * 8, b"\1" * 8, b"\2" * 8])
    root = _set([_set([obj3])] + [b"\x55" * 16 for _ in range(20)])
    assert t2.find_cart_root(b"\0" * 16 + root) is None


def test_header_requires_z64():
    with pytest.raises(ValueError):
        t2.header(b"\x37\x80\x40\x12" + b"\0" * 0x1000)


def test_inventory_rejects_object_types_overrun():
    obj = _set([b"\0" * 8, b"\1" * 8, b"\2" * 8, b"\3" * 8])
    go = _set([obj])
    bad_types = struct.pack(">II", 2, 0x7FFF)               # claims 32767 entries in an 8-byte block
    root = _set([go, b"\x55" * 16, bad_types] + [b"\x55" * 16 for _ in range(18)])
    with pytest.raises(ValueError, match="ObjectTypes"):
        t2.inventory(b"\xAA" * 0x40 + root + b"RNC")



@pytest.mark.skipif(not SRC.exists(), reason="owned Turok 2 EU zip not cached")
def test_owned_rom_inventory():
    from gbox import n64_rom
    assert hashlib.sha256(SRC.read_bytes()).hexdigest() == OWNED_ZIP_SHA256
    rom = n64_rom.read(SRC)
    assert hashlib.sha256(rom).hexdigest() == ROM_SHA256
    h = t2.header(rom)
    assert h["serial"] == "NT2P" and h["version"] == 0
    assert h["ipl3_crc32"] == "90bb6cb5"  # CIC 6102
    assert t2.find_cart_root(rom, 0xFC0000) == t2.CART_ROOT_OFFSET
    inv = t2.inventory(rom)
    go = inv["graphic_objects"]
    assert go["total"] == go["valid"] == 2705
    assert go["geometry_rnc_ok"] == 2705 and not go["geometry_rnc_fail"]
    assert inv["object_types"]["n"] == 2705
    assert inv["texture_sets"]["total"] == 1840
    assert inv["texture_sets"]["rnc_ok"] == 1840 and not inv["texture_sets"]["rnc_fail"]
    assert inv["levels"] == {"total": 165, "blocks_per_level": {9: 165}}
    hits = inv["mp_characters"]["rom_offsets"]
    assert all(len(hits[n]) == 2 for n in t2.MP_CHARACTERS)
    assert hits["Purr Lin"] == [0xB821F, 0x1351FF]
