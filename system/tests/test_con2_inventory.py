"""Naruto: Clash of Ninja 2 (GC, GNUEDA) inventory: FPK index, PRS codec, HSD header and roster table."""
import hashlib
import os
import struct
from pathlib import Path

import pytest

from gbox import con2_inventory as ci

ISO = Path(os.environ.get("GBOX_CON2_ISO", Path.home() / "gbox-cache/modbase/68913550d6c4eae8"
                          / "Naruto - Clash of Ninja 2 (USA).iso"))


class _Bits:
    """PRS writer in decode order: flag bytes are reserved where the decoder will read them."""

    def __init__(self):
        self.out, self.flag_at, self.left = bytearray(), 0, 0

    def bit(self, b):
        if self.left == 0:
            self.flag_at, self.left = len(self.out), 8
            self.out.append(0)
        self.left -= 1
        self.out[self.flag_at] |= b << self.left

    def byte(self, v):
        self.out.append(v)


def _stream():
    w = _Bits()
    for c in b"abc":                                    # literals
        w.bit(1); w.byte(c)
    w.bit(0); w.bit(0); w.bit(1); w.bit(1); w.byte(0x100 - 3)            # short copy len 5, back 3
    v = ((0x2000 - 3) << 3) | 1                         # long copy len 3, back 3
    w.bit(0); w.bit(1); w.byte(v >> 8); w.byte(v & 0xFF)
    v = (0x2000 - 1) << 3                               # long copy, length byte (+1) = 10, back 1
    w.bit(0); w.bit(1); w.byte(v >> 8); w.byte(v & 0xFF); w.byte(9)
    w.bit(1); w.byte(ord("X"))
    return bytes(w.out), b"abcabcabcab" + b"b" * 10 + b"X"


def test_prs_literals_short_long_and_length_byte():
    blob, want = _stream()
    assert ci.prs_decompress(blob, len(want)) == want
    with pytest.raises(ValueError):
        ci.prs_decompress(blob, len(want) + 4)        # stream ends early -> refused, not zero padded
    with pytest.raises(ValueError):
        ci.prs_decompress(blob[:-1], len(want))


def test_prs_backref_before_start_reads_zero_window():
    w = _Bits()
    w.bit(0); w.bit(0); w.bit(1); w.bit(0); w.byte(0x100 - 2)            # short copy len 4 at o=0
    w.bit(1); w.byte(ord("Z"))
    assert ci.prs_decompress(bytes(w.out), 5) == b"\0\0\0\0Z"


def _fpk(entries):
    table = 0x10
    data_at = table + 0x20 * len(entries)
    body, rows = bytearray(), bytearray()
    for name, stored, size in entries:
        rows += name.encode()[-15:].ljust(0x10, b"\0") + struct.pack(">4I", 0, data_at + len(body), len(stored), size)
        body += stored
    total = data_at + len(body)
    return struct.pack(">4I", 0, len(entries), table, total) + bytes(rows) + bytes(body)


def test_fpk_index_names_are_cut_to_last_15_chars_and_payloads_decode():
    blob, want = _stream()
    pack = _fpk([("chr/ali/0000.dat", blob, len(want)), ("chr/ali/3000.h", b"//\r\n", 4)])
    idx = ci.fpk_index(pack)
    assert [e["name"] for e in idx] == ["hr/ali/0000.dat", "chr/ali/3000.h"]
    assert [e["compressed"] for e in idx] == [True, False]
    assert [b for _, b in ci.fpk_files(pack)] == [want, b"//\r\n"]
    with pytest.raises(ValueError):
        ci.fpk_index(pack[:-1])                        # header file size must match


def _hsd(reloc_at=0):
    data = bytes(16)
    strs = b"scene_data\0"
    body = data + struct.pack(">I", reloc_at) + struct.pack(">II", 0, 0) + strs
    return struct.pack(">5I12x", 0x20 + len(body), len(data), 1, 1, 0) + body


def test_hsd_header_checks_relocations():
    h = ci.hsd_header(_hsd())
    assert h["roots"] == ["scene_data"] and h["relocations"] == 1 and h["data_size"] == 16
    with pytest.raises(ValueError):
        ci.hsd_header(_hsd(reloc_at=14))


def test_code_table_finds_longest_pointer_run():
    text = b"ali\0bak\0zzz\0bus\0"
    base = 0x80010000
    tbl = struct.pack(">4I", base + 0, base + 4, base + 12, 0) + struct.pack(">I", base + 8)
    sec = text + tbl
    hdr = bytearray(0x100)
    struct.pack_into(">I", hdr, 0, 0x100)
    struct.pack_into(">I", hdr, 0x48, base)
    struct.pack_into(">I", hdr, 0x90, len(sec))
    at, codes = ci.code_table(bytes(hdr) + sec, {"ali", "bak", "bus"})
    assert codes == ["ali", "bak", "bus"] and at == 0x100 + len(text)


ORDER = ["ali", "bak", "bus", "mar", "she", "stu", "uli", "yug", "chr", "fan", "ino", "sik", "nej", "hin",
         "gai", "kan", "kar", "kib", "dog", "gar", "sa2", "oro", "obo", "miz"]


@pytest.mark.skipif(not ISO.exists(), reason="owned CoN2 ISO not unpacked (GBOX_CON2_ISO)")
def test_owned_disc_inventory():
    m = ci.inventory(ISO)
    assert m["image"]["disc_id"] == "GNUEDA" and m["image"]["region_bi2"] == 1
    assert m["main_dol"]["sha256"] == "7214908913b0a4711babdc3d1940d38a9b63e655961df33603a088a0ceef69b3"
    assert m["fst_files"] == 341 and len(m["packs"]) == 209
    assert m["stats"]["entries"] == 1410 and m["stats"]["hsd"] == 332 and m["stats"]["compressed"] == 1355
    assert m["roster_codes"] == ORDER and m["main_dol"]["code_table_offset"] == "0x18e3fc"
    ch = m["characters"]
    assert set(ORDER) <= set(ch) and len(ch) == 26
    assert len(ch["uli"]["costumes"]) == 4 and len(ch["obo"]["costumes"]) == 1
    assert all(ch[c]["motion_bytes"] for c in ORDER)
    ali = ch["ali"]["costumes"][0]
    assert ali["model_bytes"] == 363195 and ali["relocations"] > 0
