import struct, pytest
from gbox.blitz_pro_inventory import pak_header, pak_entries, part_names, FormatError, sha256_stream


def _pak():
    b = bytearray(0x200)
    b[:4] = b"PAK "
    struct.pack_into(">5I", b, 4, 0x200, 0x1000, 0x200, 3, 0x200000)
    for off, i in ((0x40, b"1000"), (0x100, b"1002")):
        b[off:off + 4] = i
    b[0x180:0x187] = b"c0130_1"
    return bytes(b)


def test_header_big_endian():
    h = pak_header(_pak())
    assert h["version"] == 0x200 and h["field_14"] == 0x200000


def test_entries_and_parts():
    p = _pak()
    assert [e["id"] for e in pak_entries(p)] == ["1000", "1002"]
    assert part_names(p, len(p)) == ["c0130_1"]


def test_rejects():
    with pytest.raises(FormatError):
        pak_header(b"PAK ")
    with pytest.raises(FormatError):
        pak_header(b"XXXX" + b"\0" * 32)


def test_sha(tmp_path):
    f = tmp_path / "x"; f.write_bytes(b"abc")
    assert sha256_stream(f) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
