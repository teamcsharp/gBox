import hashlib
import os
import struct
from pathlib import Path

import pytest

from gbox import nightfire_analysis as na
from gbox import nightfire_edl as edl

ISO = Path(os.environ.get("GBOX_NIGHTFIRE_ISO", Path.home() / "gBox_alt/gbox-cache/modbase/744ba3bc797403bf/007 - Nightfire (USA).iso"))


class _W:
    def __init__(self):
        self.bits = []

    def put(self, v, n):  # LSB-first value
        self.bits += [(v >> i) & 1 for i in range(n)]

    def code(self, c, n):  # Huffman code, MSB first (stored reversed, like deflate)
        self.bits += [(c >> (n - 1 - i)) & 1 for i in range(n)]

    def words(self):
        b = self.bits + [0] * (-len(self.bits) % 32)
        return b"".join(struct.pack(">I", sum(b[i + k] << k for k in range(32))) for i in range(0, len(b), 32))


def _edl(body: bytes, unpacked: int, flag=0x81) -> bytes:
    return b"EDL" + bytes([flag]) + struct.pack(">II", 12 + len(body), unpacked) + body


def test_header_and_errors():
    h = edl.header(_edl(b"\0" * 8, 5))
    assert h == {"flag": 0x81, "method": 1, "big_endian": True, "size": 20, "unpacked": 5}
    with pytest.raises(edl.EDLError):
        edl.header(b"XDL\x81" + b"\0" * 12)
    with pytest.raises(edl.EDLError):
        edl.header(b"EDL\x83" + b"\0" * 12)
    with pytest.raises(edl.EDLError):
        edl.decompress(_edl(b"\0" * 8, 5)[:-4] + b"\0" * 8)  # size field mismatch


def test_method0_stored_copy():
    assert edl.decompress(_edl(b"hello", 5, flag=0x80)) == b"hello"


def test_method1_stored_block():
    w = _W()
    w.put(0, 1); w.put(3, 15)
    for c in b"abc":
        w.put(c, 8)
    w.put(1, 1)
    assert edl.decompress(_edl(w.words(), 3)) == b"abc"


def test_method1_huffman_block_with_overlapping_match():
    w = _W()
    w.put(1, 1)
    w.put(258, 9)                       # litlen table: 'A'=len1, 256 (EOB)=len2, 257 (len 3)=len2
    for sym in range(258):
        if sym == 65:
            w.put(1, 1); w.put(1, 4)
        elif sym == 66:
            w.put(1, 1); w.put(0, 4)
        elif sym == 256:
            w.put(1, 1); w.put(2, 4)
        else:
            w.put(0, 1)                 # repeat the running length
    w.put(1, 9); w.put(1, 1); w.put(1, 4)  # distance table: sym 0 = len1
    for _ in range(4):
        w.code(0, 1)                    # 'A'
    w.code(0b11, 2); w.code(0, 1)       # length 3, distance 1 (copy from out[-1])
    w.code(0b10, 2)                     # end of block
    w.put(1, 1)                         # last block
    assert edl.decompress(_edl(w.words(), 7)) == b"A" * 7


def test_method1_rejects_wrong_unpacked_size():
    w = _W()
    w.put(0, 1); w.put(1, 15); w.put(0x41, 8); w.put(1, 1)
    with pytest.raises(edl.EDLError):
        edl.decompress(_edl(w.words(), 2))


def test_method1_rejects_truncated_stream_and_overrun():
    w = _W()
    w.put(0, 1); w.put(3, 15); w.put(0x41, 8)              # stored block of 3 cut after one byte
    body = w.words()
    with pytest.raises(edl.EDLError):
        edl.decompress(_edl(body[:4], 3))
    w = _W()
    w.put(0, 1); w.put(0x7FFF, 15)                          # stored block far beyond the unpacked size
    with pytest.raises(edl.EDLError):
        edl.decompress(_edl(w.words(), 3))



def test_skin_header():
    p = struct.pack("<I3f", 0x05000007, 1.0, 1.0, 1.0) + bytes([1, 0, 0x16, 0x3C, 0])
    assert na.skin_header(p) == {"hash": "0x05000007", "scale": [1.0, 1.0, 1.0], "head": [1, 0, 0x16, 0x3C, 0]}


@pytest.mark.skipif(not ISO.exists(), reason="owned Nightfire disc image not cached")
def test_owned_disc_tables_and_levels():
    from gbox.gcdisc import GCDisc

    disc = GCDisc(ISO)
    elf = disc.read("Nightfire.elf")
    assert hashlib.sha256(elf).hexdigest() == edl.EXE_SHA256
    t = edl.elf_tables(elf)
    assert t["len_base"] == edl.LEN_BASE and t["len_extra"] == edl.LEN_EXTRA
    assert t["dist_base"] == edl.DIST_BASE and t["dist_extra"] == edl.DIST_EXTRA
    # EDL_ParseHeader compares 'E','D','L' at 0x80067c40.. and dispatches method 1 to 0x800668e4
    off = 0x360 + 0x80067C40 - 0x800072E0
    assert struct.unpack_from(">I", elf, off)[0] == 0x2C000045  # cmpwi r0, 0x45
    assert struct.unpack_from(">I", elf, 0x360 + 0x80044A70 - 0x800072E0)[0] == 0x60630007  # ori r3,r3,7
    levels = {}
    for name in ("gc/07000500.bin", "gc/07000048.bin", "gc/07000001.bin"):
        levels[name[3:11]] = na.level_index(disc.read(name))
    sha = {k: hashlib.sha256(v[0]).hexdigest() for k, v in levels.items()}
    assert sha["07000500"] == "c195b082459e5f75cc162a0d57eae941f9375df94de84e44f7eb432721c712a5"
    c = na.census(levels)
    assert set(c["bondcombat"]) == {"07000001"}
    b = c["bondcombat"]["07000001"]
    assert b["size"] == 4320 and b["hash"] == "0x05000007" and b["scale"] == [1.0, 1.0, 1.0]
    assert c["types"]["skin"] >= 28 and c["types"]["skeleton"] >= 45
