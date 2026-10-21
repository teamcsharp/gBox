import json
import os
import struct
import zlib
from pathlib import Path

import pytest

from gbox import ctr_romfs, merc3d_inventory as mi

REAL = Path(os.path.expanduser(
    "~/gBox_alt/gbox-cache/3ds/0ed22ae742e1b56b/Resident Evil - The Mercenaries.3ds"))

# 'P' + backward-LZ stream for 'xyz'*6: three literals then a (disp 3, len 15) back-reference.
BLZ = b"P" + bytes([0x00, 0xC0]) + b"xyz" + bytes([0x10]) + struct.pack("<II", (8 << 24) | 14, 4)


def _pad(b, n):
    return b + b"\0" * (-len(b) % n)


def _utf16(s):
    return _pad(s.encode("utf-16le"), 4)


def _arc():
    mod = _pad(b"MOD\0" + struct.pack("<HHHHII", 229, 20, 46, 5, 100, 200), 0x40)
    body = zlib.compress(mod)
    name = b"model\\chara\\pl\\pl0000\\pl0000".ljust(64, b"\0")
    ent = name + struct.pack("<IIII", 0x58A15856, len(body), 0x40000000 | len(mod), 12 + 80)
    return b"ARC\0" + struct.pack("<HHI", 16, 1, 0) + ent + body, mod


def _romfs(fname, data):
    root = struct.pack("<6I", 0, 0xFFFFFFFF, 0x18, 0xFFFFFFFF, 0xFFFFFFFF, 0)
    dn = _utf16("archive")
    sub = struct.pack("<6I", 0, 0xFFFFFFFF, 0xFFFFFFFF, 0, 0xFFFFFFFF, len("archive") * 2) + dn
    dmeta = root + sub
    fn = _utf16(fname)
    fmeta = struct.pack("<IIQQII", 0x18, 0xFFFFFFFF, 0, len(data), 0xFFFFFFFF, len(fname) * 2) + fn
    dmo = 0x28
    fmo = dmo + len(dmeta)
    fdo = _pad(b"\0" * (fmo + len(fmeta)), 16).__len__()
    l3 = struct.pack("<10I", 0x28, 0, 0, dmo, len(dmeta), 0, 0, fmo, len(fmeta), fdo)
    l3 = _pad(l3 + dmeta + fmeta, 16) + data
    iv = bytearray(0x60)
    iv[:4] = b"IVFC"
    struct.pack_into("<I", iv, 0x08, 0x20)
    struct.pack_into("<I", iv, 0x4C, 12)
    return bytes(iv) + b"\0" * (0x1000 - 0x60) + l3


def _image(tmp_path):
    arc, mod = _arc()
    smdh = bytearray(0x36C0)
    smdh[:4] = b"SMDH"
    o = 8 + 0x200
    smdh[o:o + 8] = "MERC".encode("utf-16le")
    smdh[o + 0x80:o + 0x88] = "LONG".encode("utf-16le")
    struct.pack_into("<I", smdh, 0x2018, 0x0C)
    exefs = bytearray(0x200)
    struct.pack_into("<8sII", exefs, 0, b".code", 0, len(BLZ))
    struct.pack_into("<8sII", exefs, 16, b"icon", 0x200, len(smdh))
    exefs = _pad(bytes(exefs) + _pad(BLZ, 0x200) + bytes(smdh), 0x200)
    romfs = _pad(_romfs("uPl( Chris ).arc", arc), 0x200)
    exh = bytearray(0x400)
    exh[:8] = b"biomerce"
    exh[0xD] = 1
    ncch = bytearray(0x200)
    ncch[0x100:0x104] = b"NCCH"
    struct.pack_into("<Q", ncch, 0x108, 0x0004000000038B00)
    ncch[0x150:0x15A] = b"CTR-P-ABMP"
    struct.pack_into("<I", ncch, 0x180, 0x400)
    ex_u = 3
    rf_u = ex_u + len(exefs) // 0x200
    struct.pack_into("<II", ncch, 0x1A0, ex_u, len(exefs) // 0x200)
    struct.pack_into("<II", ncch, 0x1B0, rf_u, len(romfs) // 0x200)
    part = bytes(ncch) + bytes(exh) + exefs + romfs
    hdr = bytearray(0x200)
    hdr[0x100:0x104] = b"NCSD"
    struct.pack_into("<II", hdr, 0x120, 1, len(part) // 0x200)
    p = tmp_path / "t.3ds"
    p.write_bytes(bytes(hdr) + part)
    return p, mod


def test_blz_backreference():
    assert ctr_romfs.blz_decompress(BLZ) == b"P" + b"xyz" * 6


def test_blz_rejects_bad_footer():
    with pytest.raises(ctr_romfs.CtrError):
        ctr_romfs.blz_decompress(b"\0" * 4 + struct.pack("<II", (8 << 24) | 99, 4))


def test_synthetic_image_manifest(tmp_path):
    p, mod = _image(tmp_path)
    m = mi.manifest(p)
    assert m["decrypted"] and not m["ncch_nocrypto_flag"]
    assert m["region"] == {"product_code": "CTR-P-ABMP", "product_region": "EUR", "smdh_regions": ["EUR", "AUS"]}
    assert m["exheader"]["name"] == "biomerce" and m["exheader"]["code_compressed"]
    assert m["romfs_files"] == 1
    (row,) = m["roster"]
    assert row["name"] == "Chris" and row["kinds"] == {"mod": 1}
    (md,) = row["models"]
    assert (md["id"], md["version"], md["bones"], md["meshes"], md["materials"]) == ("pl0000", 229, 20, 46, 5)
    assert md["loose_copy"] is None
    json.dumps(m)


def test_arc_rejects_truncated():
    arc, _ = _arc()
    with pytest.raises(mi.ArcError):
        mi.Arc3ds(arc[:100])


@pytest.mark.skipif(not REAL.exists(), reason="owned dump not unpacked")
def test_owned_dump_inventory():
    m = mi.manifest(REAL)
    assert m["product_code"] == "CTR-P-ABMP" and m["region"]["smdh_regions"] == ["EUR", "AUS"]
    assert m["code_decompressed_sha256"] == "85a34c86eb62597d89f1dc48b2e75dc7f4b25fdfeed7def086f93e875e5821be"
    ids = {md["id"]: r["name"] for r in m["roster"] for md in r["models"]}
    assert len(ids) == 16 and ids["pl0000"] == "Chris" and ids["pl0170"] == "WeskerCos2"
    assert all(md["loose_identical"] for r in m["roster"] for md in r["models"])
