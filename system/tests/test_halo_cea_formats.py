"""Focused tests for gbox.halo_cea_formats: XDVDFS dirent walking, classic
.map chunk tables and Saber3D .s3dpak entry tables.  Synthetic fixtures mirror
bytes observed on the owned disc; set GBOX_HALO_CEA_ISO to also verify against
the real image."""
import os
import struct

import pytest

from gbox import halo_cea_formats as fmt


def _dirent(name: str, sector: int, size: int, flags: int) -> bytes:
    b = struct.pack("<HHII", 0, 0, sector, size) + bytes([flags, len(name)]) + name.encode()
    return b + b"\x00" * ((-len(b)) % 4)


def _table(*entries) -> bytes:
    return b"".join(entries)


# ------------------------------------------------------------- XDVDFS ----

def test_dirent_flags_and_layout():
    buf = _dirent("default.xex", 14639, 22265856, fmt.FILE_FLAG)
    e = fmt.read_dir_table(buf)[0]
    assert e["name"] == "default.xex" and e["sector"] == 14639
    assert e["size"] == 22265856 and not e["is_dir"]


def test_walk_recurses_directories():
    fdir = _dirent("maps_original", 66958, 732, fmt.DIR_FLAG)
    file1 = _dirent("a30.map", 90013, 17130728, fmt.FILE_FLAG)
    class Fake:
        def __init__(self): self.pos = None
        def seek(self, p): self.pos = p
        def read(self, n):
            src = _table(fdir) if self.pos == 264 * 2048 else _table(file1)
            return src + b"\x00" * (n - len(src))
    out = fmt.walk_xdvd(Fake(), 264, len(_table(fdir)))
    assert out == [("/maps_original/a30.map", 90013, 17130728)]


def test_terminator_stops_table():
    assert fmt.read_dir_table(b"\x00" * 32) == []


# --------------------------------------------------------- classic .map ----

def test_map_chunk_table_parses_xmem_headers():
    offsets = [0x40000, 0x41974, 0x46F1A]
    body = bytearray(offsets[-1] + 8)
    struct.pack_into("<I", body, 0, 3)
    for i, o in enumerate(offsets):
        struct.pack_into("<I", body, 4 + 4 * i, o)
    for i, o in enumerate(offsets):
        declared = (6506, 21916, 27496)[i]
        body[o:o + 5] = b"\xff\x80\x00" + struct.pack(">H", declared)
    t = fmt.map_chunk_table(bytes(body))
    assert t["chunk_count"] == 3
    assert [c["offset"] for c in t["chunks"]] == offsets
    assert [c["declared_uncompressed"] for c in t["chunks"]] == [6506, 21916, 27496]
    assert t["chunks"][0]["stored_size"] == offsets[1] - offsets[0]


def test_map_chunk_table_rejects_bad_magic():
    bad = bytearray(0x40010)
    struct.pack_into("<I", bad, 0, 2)
    struct.pack_into("<II", bad, 4, 0x40000, 0x40008)
    bad[0x40000:0x40005] = b"head\x00"
    with pytest.raises(ValueError):
        fmt.map_chunk_table(bytes(bad))


# ------------------------------------------------------------- s3dpak ----

def test_s3dpak_table_offsets_and_sizes():
    # mirrors initial_sounddata.s3dpak: count 2, offsets 0x40000 and file end
    size = 0x41326 + 510
    buf = bytearray(0x40)
    struct.pack_into("<III", buf, 0, 2, 0x40000, 0x41326)
    t = fmt.s3dpak_table(bytes(buf) + b"\x00" * (size - 0x40))
    assert t["entry_count"] == 2
    assert t["offsets"] == [0x40000, 0x41326]
    assert t["sizes"][0] == 0x41326 - 0x40000
    assert t["header_region"] == 0x40000


def test_s3dpak_rejects_unsorted():
    buf = bytearray(16)
    struct.pack_into("<III", buf, 0, 2, 0x80000, 0x40000)
    with pytest.raises(ValueError):
        fmt.s3dpak_table(bytes(buf))


# ------------------------------------------------------- owned-disc e2e ----

@pytest.mark.skipif(not os.environ.get("GBOX_HALO_CEA_ISO"), reason="owned disc path not set")
def test_real_disc_probes():
    iso = os.environ["GBOX_HALO_CEA_ISO"]
    import hashlib
    with open(iso, "rb") as f:
        f.seek(32 * 2048)
        vd = f.read(2048)
    assert vd[:0x14] == b"MICROSOFT*XBOX*MEDIA"
    rs, rz = struct.unpack_from("<II", vd, 0x14)
    listing = dict((p, (s, z)) for p, s, z in fmt.walk_xdvd(open(iso, "rb"), rs, rz))
    assert listing["/default.xex"][1] == 22265856
    xex = fmt.extract_file(iso, *listing["/default.xex"])
    assert hashlib.sha256(xex).hexdigest() == \
        "1412845884eba9eb61cdc00213ca3777be19c71f6196faea69e435a350fd3f19"
    a30 = fmt.extract_file(iso, *listing["/maps_original/a30.map"])
    t = fmt.map_chunk_table(a30)
    assert t["chunk_count"] == 1163
    pak = fmt.extract_file(iso, *listing["/paks360/initial_sounddata.s3dpak"])
    st = fmt.s3dpak_table(pak)
    assert st["entry_count"] == 2 and st["header_region"] == 0x40000


# ------------------------------------------- decoded classic map index ----

def _synthetic_map():
    io, bias_ptr = 0x1000, 0x500
    img = bytearray(0x2000)
    struct.pack_into(">6I", img, 0, 0x68656164, 7, len(img), 0, io, 0x100)
    img[0x20:0x23] = b"a10"
    img[0x7FC:0x800] = b"foot"
    struct.pack_into(">4I", img, io, bias_ptr, 0, 0, 2)
    names = io + 0x200
    img[names:names + 9] = b"hero\\bipd\0"[:9]
    img[names + 16:names + 25] = b"hero\\mod2"
    bias = io + 0x28 - bias_ptr
    bd, md = 0x1800, 0x1900
    struct.pack_into(">4s4s4s5I", img, io + 0x28, b"bipd", b"\0" * 4, b"\0" * 4, 0xAA, names - bias, bd - bias, 0, 0)
    struct.pack_into(">4s4s4s5I", img, io + 0x28 + 32, b"mod2", b"\0" * 4, b"\0" * 4, 0xBB, names + 16 - bias, md - bias, 0, 0)
    img[names + 25] = 0
    img[bd + 4:bd + 8] = b"mod2"
    struct.pack_into(">I", img, bd + 16, 0xBB)
    return bytes(img)


def test_map_header_and_tag_index_and_bipd_model_ref():
    img = _synthetic_map()
    h = fmt.map_header(img)
    assert (h["magic"], h["version"], h["name"]) == ("head", 7, "a10")
    idx = fmt.map_tag_index(img)
    assert idx["count"] == 2
    bipd = idx["by_id"][0xAA]
    assert bipd["data_offset"] == 0x1800 and bipd["path"].endswith("bipd")
    assert fmt.bipd_model_ref(img, idx, bipd)["id"] == 0xBB


@pytest.mark.skipif(not os.environ.get("GBOX_HALO_CEA_ISO"), reason="owned disc path not set")
def test_real_a10_decompress_and_character_roster():
    iso = os.environ["GBOX_HALO_CEA_ISO"]
    with open(iso, "rb") as f:
        f.seek(32 * 2048)
        rs, rz = struct.unpack_from("<II", f.read(2048), 0x14)
        listing = dict((p, (s, z)) for p, s, z in fmt.walk_xdvd(f, rs, rz))
    img = fmt.map_decompress(fmt.extract_file(iso, *listing["/maps_original/a10.map"]))
    assert len(img) == 96304160
    assert fmt.map_header(img)["build"] == "01.00.01.0563"
    idx = fmt.map_tag_index(img)
    assert idx["count"] == 3726
    chief = next(t for t in idx["tags"] if t["path"] == "characters\\cyborg\\cyborg_unarmed" and t["class"] == "bipd")
    assert fmt.bipd_model_ref(img, idx, chief)["path"] == "characters\\cyborg\\cyborg"
