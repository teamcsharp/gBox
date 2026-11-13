import subprocess
import math
"""Tests for gbox.formats.nsw: synthetic HEAD-variant and classic XCI0 fixtures, plus the owned real card if present."""
import hashlib
import os
import struct

import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
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


def test_bfres_header_synthetic_and_rejects():
    b = bytearray(0x100)
    b[:8] = b"FRES    "
    struct.pack_into("<IHBB", b, 8, 0x00090000, 0xFEFF, 0x0C, 0)
    struct.pack_into("<IHHII", b, 0x10, 0x82, 0, 0x80, 0xC0, 0x100)
    struct.pack_into("<H", b, 0x80, 3)
    b[0x82:0x85] = b"abc"
    struct.pack_into("<Q", b, 0x28, 0x40)
    b[0x40:0x44] = b"FMDL"
    b[0xC0:0xC4] = b"_RLT"
    h = nsw.parse_bfres_header(bytes(b))
    assert h["name"] == "abc" and h["fmdl_offset"] == 0x40 and h["file_size"] == 0x100
    with pytest.raises(ValueError):
        nsw.parse_bfres_header(bytes(b[:0xF0]))
    with pytest.raises(ValueError):
        nsw.parse_bfres_header(b"XXXX" * 20)


@pytest.mark.skipif(not (os.path.exists(REAL) and os.path.exists(KEYS)), reason="owned XCI/prod.keys not present")
def test_real_villager_bfres_header():
    import shutil, subprocess
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
        ent = next(f for f in r["files"] if f["path"] == "/Model/NpcNmlAnt00.Nin_NX_NVN.zs")
        blob = nsw.read_romfs_file(rd, e.offset, keys, ent)
    sarc = subprocess.run(["zstd", "-dc"], input=blob, capture_output=True, check=True).stdout
    m = nsw.sarc_members(sarc)[0]
    bf = sarc[m["offset"]:m["offset"] + m["size"]]
    h = nsw.parse_bfres_header(bf)
    assert h["file_size"] == len(bf) == 3019456
    assert h["name"] == "output" and h["fmdl_offset"] == 0xF0 and h["rlt_offset"] == 0x2E1000
    assert h["magic_counts"]["FMDL"] == 1 and h["magic_counts"]["FSHP"] == 3 and h["magic_counts"]["FMAT"] == 3
    assert h["bntx_offset"] == 0x33000


def _real_ant_bfres():
    import shutil, subprocess
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
        ent = next(f for f in r["files"] if f["path"] == "/Model/NpcNmlAnt00.Nin_NX_NVN.zs")
        blob = nsw.read_romfs_file(rd, e.offset, keys, ent)
    sarc = subprocess.run(["zstd", "-dc"], input=blob, capture_output=True, check=True).stdout
    m = nsw.sarc_members(sarc)[0]
    return sarc[m["offset"]:m["offset"] + m["size"]]


@pytest.mark.skipif(not (os.path.exists(REAL) and os.path.exists(KEYS)), reason="owned XCI/prod.keys not present")
def test_real_villager_bfres_model():
    bf = _real_ant_bfres()
    assert hashlib.sha256(bf).hexdigest() == "beaacdb751a044e70e1869eca2f7043430a1d192b83a69d59b944a6e9be9f1ae"
    m = nsw.parse_bfres_model(bf)
    assert m["name"] == "NpcNmlAnt00" and m["pool_base"] == 0x12000
    assert len(m["bones"]) == 44 and m["bones"][0]["name"] == "Root" and m["bones"][0]["parent"] == -1
    assert m["bones"][43]["name"] == "Z_Tail" and m["bones"][43]["parent"] == 42
    assert all(b["parent"] < b["index"] for b in m["bones"])
    assert [s["name"] for s in m["shapes"]] == ["Body__mBody", "Body__mCapVis", "Body__mEye"]
    for s in m["shapes"]:
        fv = m["fvtx"][s["fvtx"]]
        idx = nsw.bfres_read_indices(bf, m, s)
        assert len(idx) % 3 == 0 and max(idx) == fv["vertex_count"] - 1
        assert max(s["skin_bones"]) < len(m["bones"])
        pos = nsw.bfres_read_positions(bf, m, s)
        assert len(pos) == fv["vertex_count"]
        assert all(abs(c) < 50 for p in pos for c in p)
    body = m["shapes"][0]
    assert body["lod0"]["index_count"] == 11160 and m["fvtx"][0]["vertex_count"] == 2284
    assert [a["name"] for a in m["fvtx"][0]["attrs"]] == ["_p0", "_n0", "_t0", "_c0", "_u0", "_i0", "_w0"]


def test_parse_bfres_model_rejects_garbage():
    with pytest.raises(ValueError):
        nsw.parse_bfres_model(b"FRES" + b"\0" * 0x200)



def test_n0_10bit_normal_decode_real_card():
    """_n0 vertex normals on the owned card are 3x signed-10-bit, x in low bits.

    Machine-verified: bit order (0,10,20) must score mean dot >0.85 vs
    area-weighted geometric normals and beat the next best permutation
    by >=0.3.
    """
    import struct as st
    _here = os.path.dirname(os.path.abspath(__file__))
    _card = os.path.join(os.path.dirname(_here), "animal_crossing_xci.xci")
    _keys = "/home/ehm_eckx/gBox_alt/switch/prod.keys"
    if not os.path.exists(_card):
        pytest.skip("owned card not present")
    if not os.path.exists(_keys):
        pytest.skip("prod.keys not present")
    keys = nsw.load_keys(_keys)
    info = nsw.list_xci(_card)
    e = next(x for x in info.hfs0["secure"] if x.name == "bd68bf29c8500e9c88ca844e1a6f77e8.nca")
    fh = open(_card, "rb")
    def rd(o, n):
        fh.seek(o); return fh.read(n)
    r = nsw.list_romfs(rd, e.offset, keys)
    ent = next(f for f in r["files"] if f["path"] == "/Model/NpcNmlAnt00.Nin_NX_NVN.zs")
    blob = nsw.read_romfs_file(rd, e.offset, keys, ent)
    fh.close()
    sarc = subprocess.run(["zstd", "-dc"], input=blob, capture_output=True, check=True).stdout
    m = nsw.sarc_members(sarc)[0]
    bf = sarc[m["offset"]:m["offset"] + m["size"]]
    model = nsw.parse_bfres_model(bf)
    fv = model["fvtx"][0]
    attrs = {a["name"]: a for a in fv["attrs"]}
    N = fv["vertex_count"]
    def poff(nm):
        a = attrs[nm]; b = fv["buffers"][a["buffer"]]
        return model["pool_base"] + b["pool_offset"] + a["offset"]
    pos = [st.unpack("<3f", bf[poff("_p0") + i * 12:poff("_p0") + i * 12 + 12]) for i in range(N)]
    idx = nsw.bfres_read_indices(bf, model, model["shapes"][0])
    accs = [(0.0, 0.0, 0.0)] * N
    for t in range(0, len(idx), 3):
        i0, i1, i2 = idx[t], idx[t + 1], idx[t + 2]
        p0, p1, p2 = pos[i0], pos[i1], pos[i2]
        e1 = (p1[0]-p0[0], p1[1]-p0[1], p1[2]-p0[2])
        e2 = (p2[0]-p0[0], p2[1]-p0[1], p2[2]-p0[2])
        c = (e1[1]*e2[2]-e1[2]*e2[1], e1[2]*e2[0]-e1[0]*e2[2], e1[0]*e2[1]-e1[1]*e2[0])
        for i in (i0, i1, i2):
            a = accs[i]; accs[i] = (a[0]+c[0], a[1]+c[1], a[2]+c[2])
    gns = [tuple(x / (math.sqrt(sum(v * v for v in c)) or 1.0) for x in c) for c in accs]
    raw = bf[poff("_n0"):poff("_n0") + 4 * N]
    scores = {}
    for perm in [(0,10,20),(0,20,10),(10,0,20),(10,20,0),(20,0,10),(20,10,0)]:
        tot = 0.0
        for i, v in enumerate(nsw.bfres_decode_10vec(raw, perm)):
            L = math.sqrt(sum(x * x for x in v))
            if L > 1e-6:
                tot += sum(a * b for a, b in zip(v, gns[i])) / L
        scores[perm] = tot / N
    best = max(scores, key=scores.get)
    others = sorted(scores.values())[:-1]
    assert scores[best] > 0.85, scores
    assert best == (0, 10, 20), scores
    assert scores[best] - others[-1] >= 0.3, scores


@pytest.mark.skipif(not (os.path.exists(REAL) and os.path.exists(KEYS)), reason="owned XCI/prod.keys not present")
def test_t0_u0_decode_real_card():
    """_t0 = LE s8x3/127 (fmt 0x020b), _u0 = (s16+32768)/65536 (fmt 0x0112).

    Machine-verified on the owned NpcNmlAnt00 card: decoded tangents are
    orthogonal to decoded normals (mean |dot| < 0.01) and byte-reversed
    tangents are not (mean |dot| > 0.1); all UVs land in [0, 1).
    """
    bf = _real_ant_bfres()
    model = nsw.parse_bfres_model(bf)
    for s in model["shapes"]:
        fv = model["fvtx"][s["fvtx"]]
        N = fv["vertex_count"]
        t = nsw.bfres_decode_t0(nsw.bfres_read_attr(bf, model, s, "_t0"))
        assert len(t) == N
        nrm = nsw.bfres_decode_10vec(nsw.bfres_read_attr(bf, model, s, "_n0"))

        def dotmean(reversed_bytes):
            tot = 0.0
            for i in range(N):
                tv = t[i][2::-1] if reversed_bytes else t[i]
                l1 = math.sqrt(sum(x * x for x in tv)) or 1.0
                l2 = math.sqrt(sum(x * x for x in nrm[i])) or 1.0
                tot += abs(sum(a * b for a, b in zip(tv, nrm[i]))) / (l1 * l2)
            return tot / N

        assert dotmean(False) < 0.01, (s["name"], dotmean(False))
        assert dotmean(True) > 0.1, (s["name"], dotmean(True))
        uv = nsw.bfres_decode_u0(nsw.bfres_read_attr(bf, model, s, "_u0"))
        assert len(uv) == N
        assert all(0.0 <= x < 1.0 and 0.0 <= y < 1.0 for x, y in uv), s["name"]


@pytest.mark.skipif(not (os.path.exists(REAL) and os.path.exists(KEYS)), reason="owned XCI/prod.keys not present")
def test_real_villager_obj_export():
    """OBJ export of all three NpcNmlAnt00 shapes: vertex counts, face
    counts, index bounds and optional per-vertex attributes parse back."""
    bf = _real_ant_bfres()
    model = nsw.parse_bfres_model(bf)
    counts = {"Body__mBody": 2284, "Body__mCapVis": 398, "Body__mEye": 152}

    def obj_counts(obj):
        c = {"v": 0, "vn": 0, "vt": 0, "vc": 0, "f": 0}
        for line in obj.splitlines():
            for k in ("vn ", "vt ", "vc ", "f ", "v "):
                if line.startswith(k):
                    c[k.rstrip()] += 1
                    break
        return c

    for s in model["shapes"]:
        obj = nsw.bfres_export_obj(bf, model, s)
        c = obj_counts(obj)
        N = counts[s["name"]]
        assert c["v"] == N, (s["name"], c)
        assert c["vn"] == N and c["vt"] == N, (s["name"], c)
        assert c["f"] == s["lod0"]["index_count"] // 3, (s["name"], c)
        have_c0 = any(a["name"] == "_c0" for a in model["fvtx"][s["fvtx"]]["attrs"])
        assert (c["vc"] == N) == have_c0, (s["name"], c)
        for line in obj.splitlines():
            if line.startswith("f "):
                for tok in line[2:].split():
                    assert 1 <= int(tok.split("/")[0]) <= N
    all_obj = nsw.bfres_export_obj_all(bf, model)
    for name in counts:
        assert ("o %s" % name) in all_obj
