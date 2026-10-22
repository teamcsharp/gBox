import struct, pytest
from gbox.pop_sot_gc import parse_big_header, sha256_stream


def test_header():
    h = parse_big_header(b"BIG\x00" + struct.pack("<III", 0x25, 0x642, 5))
    assert h["version"] == 0x25 and h["field_8"] == 1602 and h["field_12"] == 5


def test_bad_magic():
    with pytest.raises(ValueError):
        parse_big_header(b"XXXX" + b"\0" * 12)


def test_sha():
    assert sha256_stream([b"a", b"bc"]) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
