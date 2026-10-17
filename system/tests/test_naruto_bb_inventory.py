"""Focused tests for gbox.naruto_bb_inventory -- synthetic fixtures only (no disc/SMB)."""
import struct

from gbox.naruto_bb_inventory import (
    XDVDFS_MAGIC,
    SECTOR,
    bf64_header,
    classify,
    parse_xex_header,
    xdvdfs_locate,
    xdvdfs_walk,
)


def _build_xdvdfs(files):
    """Return (blob, part, root_sector, root_size) for a tiny XDVDFS volume.

    XDVDFS directory entries are variable-length (14-byte head + name), 4-byte
    aligned; the u16 left/right tree links store the child entry's offset in
    4-byte units (byte_offset // 4), which is exactly what xdvdfs_walk expects.
    """
    part = 0
    root_sector = 40  # distinct from the descriptor sector (32)
    root_size = 512

    def entry(sector, size, name, attr=0x00, left=0xFFFF, right=0xFFFF):
        nb = name.encode("latin-1")
        return struct.pack("<HHIIBB", left, right, sector, size, attr, len(nb)) + nb

    # unit 0 = first entry; unit 7 = second (align4(25 bytes) == 28 == 7*4)
    f1 = entry(64, 100, "default.xex", right=7)
    f2 = entry(65, 200, "naruto.bf")
    records = [f1, f2]
    table = b""
    for rec in records:
        table += rec
        table += b"\x00" * ((-len(rec)) % 4)
    root = table + b"\x00" * (root_size - len(table))
    # file data sectors (sector 64/65) can be zero; only sizes matter for the walk
    blob = bytearray(66 * SECTOR)
    blob[32 * SECTOR:32 * SECTOR + 28] = XDVDFS_MAGIC + struct.pack("<II", root_sector, root_size)
    blob[root_sector * SECTOR:root_sector * SECTOR + root_size] = root
    return bytes(blob), part, root_sector, root_size


def test_xdvdfs_walk_counts_and_sizes(tmp_path):
    import io
    blob, part, rs, rz = _build_xdvdfs({})
    fh = io.BytesIO(blob)
    got = xdvdfs_walk(fh, part, rs, rz)
    assert set(got) == {"default.xex", "naruto.bf"}
    assert got["default.xex"] == (64, 100)
    assert got["naruto.bf"] == (65, 200)


def test_xdvdfs_locate():
    import io
    blob, part, rs, rz = _build_xdvdfs({})
    fh = io.BytesIO(blob)
    p, s, z = xdvdfs_locate(fh)
    assert p == part and s == rs and z == rz


def test_parse_xex_header():
    blob = bytearray(0x60)
    blob[:4] = b"XEX2"
    struct.pack_into(">I", blob, 4, 1)
    struct.pack_into(">I", blob, 8, len(blob))
    struct.pack_into(">I", blob, 20, 2)
    struct.pack_into(">II", blob, 0x18, 0x00010100, 0x82000000)
    struct.pack_into(">II", blob, 0x20, 0x00040006, 0x40)
    assert parse_xex_header(bytes(blob)) == {0x00010100: 0x82000000, 0x00040006: 0x40}


def test_bf64_header_real_observed_fields():
    # Real header words observed on the owned disc's naruto.bf (12:51 run).
    b = bytearray(0x44)
    b[:4] = b"BF64"
    struct.pack_into("<I", b, 4, 1)          # version
    struct.pack_into("<11I", b, 8, 42, 1780, 2, 0, 0xFFFFFFFF, 0xFFFFFFFF,
                     0xCC00008E, 12, 16, 121, 84)
    struct.pack_into("<QQ", b, 52, 752, 68)   # file/folder info offsets
    h = bf64_header(bytes(b))
    assert h["version"] == 1
    assert h["indices"] == 42
    assert h["parameters"] == 1780
    assert h["files"] == 2
    assert h["folders"] == 0
    assert h["file_info_offset"] == 752
    assert h["folder_info_offset"] == 68
    assert h["raw_words"] == [0xFFFFFFFF, 0xFFFFFFFF, 0xCC00008E, 12, 16, 121, 84]


def test_classify():
    assert classify(b"BF64\x01\x00\x00\x00") == "Ubisoft BigFile (BF64) -- game asset archive"
    assert classify(b"FRSA....") == "Ubisoft streaming archive (SRA)"
    assert classify(b"BIKi....") == "Bink video (Rad Game Tools)"
    assert classify(b"XUIZ\x00\x00\x00\x01") == "Xbox 360 XUI resource archive"
    assert classify(b"3BDS\x00\x04") == "Xenon compiled shader database"
    assert classify(b"XEX2\x00\x00") == "Xbox 360 executable"
    assert classify(b"\x00\x01\x02\x03") is None


def test_small_inventory_hash_is_json_serializable(tmp_path):
    import hashlib, json
    from gbox.naruto_bb_inventory import inventory
    blob, _, _, _ = _build_xdvdfs({})
    path = tmp_path / "small.iso"
    path.write_bytes(blob)
    result = inventory(str(path))
    assert result["source"]["sha256"] == hashlib.sha256(blob).hexdigest()
    json.dumps(result)


def test_binary_headers_reject_truncated_data():
    import pytest
    with pytest.raises(ValueError):
        parse_xex_header(b"XEX2" + bytes(16))
    with pytest.raises(ValueError):
        bf64_header(b"BF64" + bytes(8))
