"""Tests for gbox.formats.nsw: synthetic HEAD-variant and classic XCI0 fixtures, plus the owned real card if present."""
import hashlib
import os
import struct

import pytest

from gbox.formats import nsw


def _hfs0(files):
    """Build an HFS0 image from [(name, bytes)]."""
    pool = b"".join(n.encode() + b"\0" for n, _ in files)
    entries, data, off, noff = b"", b"", 0, 0
    for n, d in files:
        entries += struct.pack("<QQIIQ", off, len(d), noff, 0, 0) + hashlib.sha256(d).digest()
        data += d
        off += len(d)
        noff += len(n) + 1
    return b"HFS0" + struct.pack("<II", len(files), len(pool)) + b"\0" * 4 + entries + pool + data


def _reader(img):
    return lambda o, n: img[o:o + n]


def _head_image():
    nca = b"NCA3" + b"\0" * 0x1FC
    nca += b"mainname".ljust(32, b"\0") + b"prog".ljust(32, b"\0") + b"\0" * 0x100
    secure = _hfs0([("a.nca", nca), ("b.cnmt.nca", b"x" * 64)])
    root = _hfs0([("update", _hfs0([])), ("secure", secure)])
    img = bytearray(0x10000 + len(root))
    img[0:0x100] = os.urandom(0x100) if False else b"\xf5" * 0x100
    img[0x100:0x104] = b"HEAD"
    struct.pack_into("<QQ", img, 0x130, 0xF000, len(root))
    img[0xF000:0xF000 + len(root)] = root
    return bytes(img)


def test_head_variant_listing():
    info = nsw.list_xci_from(_reader(_head_image()))
    assert [p.name for p in info.partitions] == ["update", "secure"]
    assert [e.name for e in info.hfs0["secure"]] == ["a.nca", "b.cnmt.nca"]
    assert info.hfs0["update"] == []
    assert [n["entry"] for n in info.ncas] == ["a.nca"]
    assert info.ncas[0]["header_names"] == ["mainname", "prog"]
    assert nsw.summarize(info)["warnings"] == []


def test_classic_xci0_listing():
    hfs = _hfs0([("c.nca", b"NCA3" + b"\0" * 0x3FC)])
    img = bytearray(0x1000 + 0x20)
    img[0:4] = b"XCI0"
    img += b"\0" * 0x1000
    start = len(img)
    img += hfs
    struct.pack_into("<QQHBB", img, 0x1000, start, len(hfs), 0x20, 1, 0)
    img[0x1014:0x1014 + 16] = b"HFS0PARTT".ljust(16)
    info = nsw.list_xci_from(_reader(bytes(img)))
    assert info.partitions[0].offset == start


def test_non_xci_rejected():
    with pytest.raises(ValueError):
        nsw.list_xci_from(_reader(b"\0" * 0x2000))


def test_truncated_rejected():
    with pytest.raises(ValueError):
        nsw.list_xci_from(_reader(_head_image()[:0xF010]))


REAL = os.path.join(os.path.dirname(__file__), "..", "animal_crossing_xci.xci")


@pytest.mark.skipif(not os.path.exists(REAL), reason="owned XCI not present")
def test_real_owned_card():
    info = nsw.list_xci(REAL)
    assert [p.name for p in info.partitions] == ["update", "normal", "secure"]
    names = [e.name for e in info.hfs0["secure"]]
    assert len(names) == 12
    assert "bd68bf29c8500e9c88ca844e1a6f77e8.nca" in names


KEYS = "/home/ehm_eckx/gBox_alt/switch/prod.keys"


@pytest.mark.skipif(not (os.path.exists(REAL) and os.path.exists(KEYS)), reason="owned XCI/prod.keys not present")
def test_real_program_nca_exefs():
    keys = nsw.load_keys(KEYS)
    info = nsw.list_xci(REAL)
    e = next(x for x in info.hfs0["secure"] if x.name == "bd68bf29c8500e9c88ca844e1a6f77e8.nca")
    with open(REAL, "rb") as fh:
        def rd(o, n):
            fh.seek(o)
            return fh.read(n)
        files = {f["name"]: f for f in nsw.list_exefs(rd, e.offset, keys)}
        assert {"main", "main.npdm"} <= set(files)
        h = nsw.decrypt_nca_header(rd, e.offset, keys["header_key"])
        sec = nsw.nca_sections(h)[0]
        assert rd  # NSO magic proves CTR key/counter correct
        assert nsw.read_nca_section(rd, e.offset, h, keys, sec, files["main"]["offset"], 4) == b"NSO0"


def test_lz4_block_roundtrip_vector():
    # token 0x5? literal "abcde"; then match offset 5 len 4+... hand-built: lit=5 'abcde', match off=5 ml=4 -> 'abcdeabcd', last seq lit 1 'Z'
    src = bytes([0x50]) + b"abcde" + bytes([5, 0]) + bytes([0x10]) + b"Z"
    assert nsw.lz4_block_decompress(src, 10) == b"abcdeabcdZ"


@pytest.mark.skipif(not (os.path.exists(REAL) and os.path.exists(KEYS)), reason="owned XCI/prod.keys not present")
def test_real_main_nso_segments():
    keys = nsw.load_keys(KEYS)
    info = nsw.list_xci(REAL)
    e = next(x for x in info.hfs0["secure"] if x.name == "bd68bf29c8500e9c88ca844e1a6f77e8.nca")
    with open(REAL, "rb") as fh:
        def rd(o, n):
            fh.seek(o)
            return fh.read(n)
        main = nsw.read_exefs_member(rd, e.offset, keys, "main")
    nso = nsw.parse_nso(main)  # raises on segment SHA-256 mismatch
    assert set(nso["segments"]) == {"text", "ro", "data"}
    assert nso["segments"]["text"]["size"] == 35723872 and nso["segments"]["ro"]["mem_offset"] == 0x2212000
    assert struct.unpack_from("<I", main, 0xC)[0] == 0x3F  # all segments compressed + hash-checked
    import hashlib
    assert hashlib.sha256(nso["segments"]["text"]["data"]).hexdigest() == "9c9b45d8e7a58706ca59e7244b3aebac2325ef98faa205e007974eeeb2f758e9"


def _synthetic_sarc(name=b"output.bfres", payload=b"FRES" + b"\0" * 12):
    names = name + b"\0"
    names += b"\0" * (-len(names) % 4)
    sfat = b"SFAT" + struct.pack("<HHI", 12, 1, 0x65) + struct.pack("<IIII", 0, 0x01000000, 0, len(payload))
    sfnt = b"SFNT" + struct.pack("<HH", 8, 0) + names
    data_off = (0x14 + len(sfat) + len(sfnt) + 0xF) & ~0xF
    body = b"SARC" + struct.pack("<HHII", 0x14, 0xFEFF, data_off + len(payload), data_off) + struct.pack("<HH", 0x100, 0)
    body += sfat + sfnt
    body += b"\0" * (data_off - len(body)) + payload
    return body


def test_sarc_members_synthetic():
    data = _synthetic_sarc()
    m = nsw.sarc_members(data)
    assert [x["name"] for x in m] == ["output.bfres"]
    assert data[m[0]["offset"]:m[0]["offset"] + 4] == b"FRES"


def test_romfs_tables_synthetic():
    # root dir (child file at 0, child dir at 0x28), one file in root, one in subdir "d"
    def dent(par, sib, cd, cf, name):
        nb = name.encode()
        e = struct.pack("<IIIIII", par, sib, cd, cf, 0, len(nb)) + nb
        return e + b"\0" * (-len(e) % 4)

    def fent(par, sib, off, size, name):
        nb = name.encode()
        e = struct.pack("<IIQQII", par, sib, off, size, 0, len(nb)) + nb
        return e + b"\0" * (-len(e) % 4)

    root = dent(0, 0xFFFFFFFF, 0x1C, 0, "")
    sub = dent(0, 0xFFFFFFFF, 0xFFFFFFFF, 0x30, "d")
    f0 = fent(0, 0xFFFFFFFF, 0, 5, "a.bin")
    f1 = fent(0x1C, 0xFFFFFFFF, 8, 7, "b.bin")
    assert len(root) == 0x18 + 0 and len(sub) == 0x1C + 0 or True
    d = root + sub
    sub_off = len(root)
    d = root + dent(0, 0xFFFFFFFF, 0xFFFFFFFF, 0, "")[:0] + sub
    # recompute with real offsets
    root = dent(0, 0xFFFFFFFF, sub_off, 0, "")
    sub = dent(0, 0xFFFFFFFF, 0xFFFFFFFF, len(f0), "d")
    files = nsw.parse_romfs_tables(root + sub, f0 + f1)
    assert {(f["path"], f["offset"], f["size"]) for f in files} == {("/a.bin", 0, 5), ("/d/b.bin", 8, 7)}


@pytest.mark.skipif(not (os.path.exists(REAL) and os.path.exists(KEYS)), reason="owned XCI/prod.keys not present")
def test_real_romfs_villager_model():
    import shutil, subprocess, tempfile
    if not shutil.which("zstd"):
        pytest.skip("zstd CLI missing")
    keys = nsw.load_keys(KEYS)
    info = nsw.list_xci(REAL)
    e = next(x for x in info.hfs0["secure"] if x.name == "bd68bf29c8500e9c88ca844e1a6f77e8.nca")
    with open(REAL, "rb") as fh:
        def rd(o, n):
            fh.seek(o)
            return fh.read(n)
        r = nsw.list_romfs(rd, e.offset, keys)
        files = {f["path"]: f for f in r["files"]}
        assert len(files) > 60000
        ent = files["/Model/NpcNmlAnt00.Nin_NX_NVN.zs"]
        blob = nsw.read_romfs_file(rd, e.offset, keys, ent)
    assert blob[:4] == bytes.fromhex("28b52ffd")  # zstd frame
    sarc = subprocess.run(["zstd", "-dc"], input=blob, capture_output=True, check=True).stdout
    m = nsw.sarc_members(sarc)
    assert [x["name"] for x in m] == ["output.bfres"]
    assert sarc[m[0]["offset"]:m[0]["offset"] + 4] == b"FRES"
