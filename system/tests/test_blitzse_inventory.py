import hashlib
import os
from pathlib import Path
import struct

import pytest

from gbox import blitzse_inventory as bi

SOURCE = Path(os.environ.get("GBOX_BLITZSE_SOURCE",
                             Path.home() / "gBox_alt/gbox-cache" / bi.GAME_ID / "source.zip"))


def _fs(files, base=0x40, size=None):
    """Build a synthetic Midway fs image: [(name, payload, method, unpacked)]."""
    data = bytearray()
    recs = []
    pos = bi.FS_HEADER.size
    for name, payload, method, unpacked in sorted(files, key=lambda f: f[0]):
        recs.append((name, unpacked, pos, method, len(payload)))
        data += payload
        pos += len(payload)
        pad = (-pos) % 8
        data += b"\0" * pad
        pos += pad
    table = pos
    body = bi.FS_HEADER.pack(bi.FS_MAGIC, 0, table, len(recs)) + bytes(data)
    for name, unpacked, off, method, stored in recs:
        body += bi.FS_ENTRY.pack(name.encode().ljust(24, b"\0"), unpacked, off, method, stored)
    rom = bytearray(base) + body
    return bytes(rom), base


def test_parse_synthetic_fs_chains_align8():
    rom, base = _fs([("b.wms", b"\x19abc", 4, 40),
                     ("a.wbk", b"N64 WaveTables  x", 5, 17),
                     ("hel_1a.wms", b"z" * 9, 4, 99)])
    ents = bi.parse_fs(rom, base)
    assert [e["name"] for e in ents] == ["a.wbk", "b.wms", "hel_1a.wms"]
    assert ents[0]["offset"] == 0x10 and ents[1]["offset"] == 0x28
    assert bi.file_bytes(rom, ents[0]).startswith(b"N64 WaveTables")
    assert bi.family("hel_1a.wms") == "helmet" and bi.family("hed_skull.wms") == "secret_head"
    assert bi.family("a.wbk") is None


def test_parse_rejects_bad_magic_and_broken_chain():
    rom, base = _fs([("a.wms", b"abc", 4, 9)])
    bad = bytearray(rom)
    bad[base] = ord("x")
    with pytest.raises(bi.FsError):
        bi.parse_fs(bytes(bad), base)
    # corrupt the offset of the only record -> chain/range failure
    bad = bytearray(rom)
    table = base + struct.unpack_from(">I", rom, base + 8)[0]
    struct.pack_into(">I", bad, table + 28, 0x18)
    with pytest.raises(bi.FsError):
        bi.parse_fs(bytes(bad), base)


def test_stored_method_requires_equal_sizes():
    rom, base = _fs([("x.wbk", b"abcd", 5, 8)])
    with pytest.raises(bi.FsError):
        bi.parse_fs(rom, base)


@pytest.mark.skipif(not SOURCE.exists(), reason="owned NFL Blitz SE zip not cached")
def test_owned_rom_inventory(monkeypatch, tmp_path):
    monkeypatch.setenv("GBOX_N64_ROM_CACHE", str(tmp_path))
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == bi.KNOWN["source_zip_sha256"]
    rom = bi.n64_rom.read(SOURCE)
    man = bi.inventory(rom)
    ident = man["identity"]
    assert ident["z64_sha256"] == bi.KNOWN["z64_sha256"]
    assert ident["cic"] == "6102" and ident["header_crc_ok"]
    assert man["layout"]["fs_count"] == 1889
    assert man["layout"]["fs_table"] == 0xFD3398
    assert man["extensions"] == {"wms": 1745, "bfx": 40, "ptr": 44, "wbk": 44, "bin": 15, "ani": 1}
    assert man["methods"] == {"4": 1844, "5": 45}
    assert man["wave_banks"]["wavetable_magic"] == 44
    assert len(man["character_textures"]["helmet"]) == 114
    assert len(man["character_textures"]["jersey"]) == 20
    assert man["secret_heads"] == ["brain", "hat", "lashun", "raiden", "rob", "sal",
                                   "shinok", "skull", "thug"]
    assert man["animation_banks"][0]["sha256"].startswith("ad59d9aa")
    with pytest.raises(ValueError):
        bi.identify(rom[:0x2000] + bytes([rom[0x2000] ^ 0xFF]) + rom[0x2001:])
