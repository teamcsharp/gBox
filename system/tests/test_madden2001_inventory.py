"""Madden NFL 2001 (USA) N64 inventory (#1508): EA bit-LZ codec on a hand-built stream, pack parsing on a
synthetic ROM, and the owned build when its cached ROM is present."""
import hashlib
import os
import struct
from pathlib import Path

import pytest

from gbox import madden2001_inventory as m


class _W:
    def __init__(self):
        self.bits = []

    def put(self, v, n):
        self.bits += [(v >> (n - 1 - i)) & 1 for i in range(n)]

    def data(self):
        b = self.bits + [0] * (-len(self.bits) % 32)
        return bytes(int("".join(map(str, b[i:i + 8])), 2) for i in range(0, len(b), 8))


def _stream():
    w = _W()
    for byte in (3, 0, 0, 0, 0):                       # 5-byte header, first byte 3
        w.put(byte, 8)
    w.put(1, 1); w.put(4, 7)                           # 4 literals
    for c in b"ABCD":
        w.put(c, 8)
    # match at out 4: width grows to nb=3, range [0,4] -> unused 3; d=4 => 2 bits '11' + extra '1'
    w.put(0, 1); w.put(1, 1); w.put(3, 2); w.put(1, 1)  # unary g=0 -> length 3, distance 4
    return w.data()


def test_codec_literals_and_match():
    assert m.decompress(_stream(), 7) == b"ABCDABC"


def test_codec_rejects_bad_magic():
    with pytest.raises(ValueError):
        m.decompress(b"\x04" + _stream()[1:], 7)


def _long_stream():
    w = _W()
    for byte in (3, 0, 0, 0, 0):
        w.put(byte, 8)
    w.put(1, 1); w.put(4, 7)
    for c in b"ABCD":
        w.put(c, 8)
    w.put(0, 1); w.put(1, 5); w.put(15, 4); w.put(3, 2); w.put(1, 1)  # g=4 -> length 33, distance 4
    return w.data()


def test_codec_long_overlapping_match():
    assert m.decompress(_long_stream(), 37) == b"ABCD" * 9 + b"A"


def test_entries_stored_and_compressed():
    comp = _long_stream()
    body = b"RAW!" + comp
    pack = struct.pack(">3I3I", 24, 4, 0, 28, 37, 0x80000000 | len(comp)) + body
    rom = bytearray(0x2000)
    rom[0x100:0x100 + len(pack)] = pack
    es = m.entries(bytes(rom), 0x100)
    assert [e["method"] for e in es] == ["stored", "ea_lz"]
    assert m.unpack(bytes(rom), es[0]) == b"RAW!" and m.unpack(bytes(rom), es[1]) == b"ABCD" * 9 + b"A"


def test_rosters_and_teams():
    rec = b"\0BEARS".ljust(m.TEAM_STRIDE, b"\0") + b"\0BENGALS".ljust(m.TEAM_STRIDE, b"\0")
    assert m.teams(rec) == ["BEARS", "BENGALS"]
    r = b"C.MCNOWN".ljust(m.PLAYER_STRIDE, b"\0") + b"C.ENIS".ljust(m.PLAYER_STRIDE, b"\0")
    assert m.roster(r) == ["C.MCNOWN", "C.ENIS"] and m.roster(r[:-1]) == []


def test_wrong_build_refused():
    with pytest.raises(ValueError):
        m.check_build(bytes(0x2000))


ROM = Path(os.environ.get("GBOX_MADDEN2001_ROM", Path.home() / "gbox-cache/9b4aa1ef62e4ff07/rom.z64"))


@pytest.mark.skipif(not ROM.exists(), reason="owned Madden NFL 2001 ROM not cached")
def test_owned_build_inventory():
    rom = ROM.read_bytes()
    assert hashlib.sha256(rom).hexdigest() == "f9dc0e73a76ac936b176475bdbb0bc260054223112a32b30ed2f8ee32b4c7a49"
    inv = m.inventory(rom)
    assert len(inv["packs"]) == 23 and inv["entry_count"] == 3609
    assert inv["boot"]["code_size"] == m.CODE_SIZE
    assert inv["boot"]["code_sha256"] == "3ca488c5e900ac5748c11ef50a1178305b116e6a70bf22b7826d0c39bf4683a3"
    kinds = {p["pack"]: p["kinds"] for p in inv["packs"]}
    assert kinds[4]["nmf1_model"] == 57 and kinds[5]["tnmf_display_list_model"] == 34
    assert kinds[8]["audio_bank"] == 495
    assert inv["teams"][:2] == ["BEARS", "BENGALS"] and len(inv["teams"]) == 73
    assert len(inv["rosters"]) == 67 and inv["players"] == 3382


def test_truncated_inputs_raise_valueerror():
    comp = _long_stream()
    pack = struct.pack(">3I3I", 24, 4, 0, 28, 37, 0x80000000 | len(comp)) + b"RAW!" + comp
    for n in range(len(pack)):
        with pytest.raises(ValueError):
            m.entries(pack[:n], 0)
    with pytest.raises(ValueError):
        m.packs(b"\xb0\x00\x10\x00" * 2)
    for n in (0, 0x40, 0xFFF):
        with pytest.raises(ValueError):
            m.check_build(bytes(n))
    for n in range(len(comp) - 4):
        try:
            m.decompress(comp[:n], 37)
        except ValueError:
            pass
