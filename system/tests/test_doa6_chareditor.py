import struct
import zlib

import pytest

from gbox import doa6_chareditor as ce
from gbox import doa6_inventory as inv


def _g1m():
    def ch(tag, body):
        return tag[::-1].encode() + b"7300" + struct.pack("<I", 12 + len(body)) + body
    body = ch("G1MF", b"\0" * 8) + ch("G1MG", b"\1" * 20)
    total = 24 + len(body)
    return b"_M1G7300" + struct.pack("<4I", total, 24, 0, 2) + body


def test_parse_entry_name():
    r = ce.parse_entry_name("32300da0@2a87c3#1&0")
    assert r == {"bin": "CharacterEditor.rdb.bin1_0", "offset": 0x32300da0, "crc": 0x2a87c3}
    assert ce.parse_entry_name("133f9a0@aaaf")["bin"] == "CharacterEditor.rdb.bin"
    with pytest.raises(ValueError):
        ce.parse_entry_name("")


def test_g1m_chunks():
    info = ce.g1m_chunks(_g1m())
    assert [c["tag"] for c in info["chunks"]] == ["G1MF", "G1MG"]
    assert info["consistent"]
    with pytest.raises(ValueError):
        ce.g1m_chunks(b"x" * 40)


def test_g1t_header():
    b = b"GT1G1600" + struct.pack("<III", 99, 32, 1)
    assert ce.g1t_header(b)["textures"] == 1
    with pytest.raises(ValueError):
        ce.g1t_header(b"nope")


def test_read_multichunk_entry(tmp_path):
    """Regression: payloads spanning several zlib chunks must fully decode."""
    raw = bytes(range(256)) * 400  # 102400 bytes -> 7 chunks of 0x4000
    payload = b""
    for i in range(0, len(raw), inv.CHUNK_SIZE):
        z = zlib.compress(raw[i:i + inv.CHUNK_SIZE])
        payload += struct.pack("<I", len(z)) + z
    hdr = bytearray(56)
    hdr[:8] = inv.IDRK_MAGIC
    struct.pack_into("<Q", hdr, 8, 56 + len(payload))
    struct.pack_into("<Q", hdr, 24, len(raw))
    (tmp_path / "CharacterEditor.rdb.bin").write_bytes(b"\0" * 16 + bytes(hdr) + payload)
    assert ce.read_entry(tmp_path, "10@1") == raw
    assert inv.read_bin_entry(tmp_path / "CharacterEditor.rdb.bin", 16, limit=100) == raw[:100]
