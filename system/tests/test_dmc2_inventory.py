"""Focused tests for the DMC2 PS2 inventory parser (gbox/dmc2.py, request #1314)."""
import hashlib
import os
import struct
from pathlib import Path

import pytest

from gbox import dmc2


def _afs(entries, name_dir=None):
    n = len(entries)
    head = bytearray(b"AFS\x00" + struct.pack("<I", n))
    off, table, body = 0x800, [], b""
    for e in entries:
        table.append((off + len(body), len(e)))
        body += e + b"\0" * (-len(e) % 0x800)
    for o, z in table:
        head += struct.pack("<II", o, z)
    head += struct.pack("<II", *(name_dir or (0, 0)))
    return bytes(head.ljust(0x800, b"\0")) + body


def _momo(children):
    n = len(children)
    out, data, o = bytearray(b"MOMO" + struct.pack("<I", n)), b"", 8 + 8 * n
    for c in children:
        out += struct.pack("<II", o + len(data) if c else 0, len(c))
        data += c
    return bytes(out) + data


def _mesh(parts=3, b1=0x22, size=0x60):
    return bytes([9, b1, 5, 1]) + struct.pack("<II", parts, size) + b"\0" * (size - 12)


def test_afs_table_and_name_dir():
    blob = _afs([b"MOMO" + b"\0" * 12, b"TIM2" + b"\0" * 12], name_dir=(0x2000, 96))
    t = dmc2.afs_table(blob[:0x30], len(blob))
    assert t["count"] == 2 and t["sizes"] == [16, 16] and t["offsets"][0] == 0x800
    assert dmc2.afs_name_dir(t) == (0x2000, 96)
    with pytest.raises(ValueError):
        dmc2.afs_table(b"NOPE" + b"\0" * 12)
    with pytest.raises(ValueError):
        dmc2.afs_table(blob[:0x30], 0x810)  # second entry beyond the archive


def test_momo_walk_classifies_mesh_texbank_and_nested():
    texbank = struct.pack("<3I", 2, 0x21, 0x21) + b"\0" * 20
    inner = _momo([b"TIM2" + b"\0" * 28])
    pkg = _momo([_mesh(), texbank, b"", inner, bytes([1, 1, 1, 1]) + struct.pack("<II", 4, 0x40) + b"\0" * 52])
    rows = []
    dmc2.walk_package(pkg, "X:0", rows)
    kinds = {r["path"]: r["kind"] for r in rows}
    assert kinds == {"X:0": "momo", "X:0/0": "mesh", "X:0/1": "texbank", "X:0/3": "momo",
                     "X:0/3/0": "tim2", "X:0/4": "rec01"}
    mesh = next(r for r in rows if r["path"] == "X:0/0")
    assert mesh["model"] == {"tag": "09220501", "parts": 3, "size": 0x60}
    assert mesh["sha256"] == hashlib.sha256(_mesh()).hexdigest()


def test_bad_momo_and_compressed_markers():
    with pytest.raises(ValueError):
        dmc2.momo_children(b"MOMO" + struct.pack("<III", 1, 16, 0x1000))
    assert dmc2.classify(b"\x00\x00MOMO\x0b\x00") == "compressed_momo"
    assert dmc2.classify(b"A\x04TIM2\x04\x01") == "compressed_tim2"
    assert dmc2.classify(b"\x00\x00\x01\xba" + b"\0" * 12) == "mpeg_ps"
    assert dmc2.classify(_mesh(size=0x40)[:0x30]) == "unknown"  # header size larger than the child


def test_character_candidates_threshold():
    models = [{"sha256": "a", "path": f"X:{i}/0", "size": 10, "model": {"parts": 57, "tag": "09220501"}}
              for i in range(25)] + [{"sha256": "b", "path": "X:99/0", "size": 9, "model": {"parts": 5, "tag": "07220401"}}]
    uniq = {}
    for m in models:
        uniq.setdefault(m["sha256"], []).append(m["path"])
    c = dmc2.character_candidates(uniq, models)
    assert [x["sha256"] for x in c] == ["a"] and c[0]["copies"] == 25 and c[0]["parts"] == 57


ISO = Path(os.environ.get("GBOX_DMC2_ISO", Path.home() / "gbox-cache/ps2/01bb1fe7c84e8e79/disc.iso"))


@pytest.mark.skipif(not ISO.exists(), reason="owned DMC2 Disc 1 image not extracted on this host")
def test_owned_disc_inventory():
    inv = dmc2.inventory(ISO)
    assert inv["serial"] == "SLUS_204.84"
    assert inv["disc"]["SLUS_204.84"]["sha256"] == "09040e703963acd105a8f52e72f850dd8c179d5b57934dfca70e4db763f422f0"
    assert inv["archives"]["X_DATA.BIN"]["entries"] == 3488
    assert inv["archives"]["Z_DATA.BIN"]["kinds"] == {"mpeg_ps": 11}
    assert not inv["archives"]["X_DATA.BIN"]["name_dir_on_disc"]
    assert inv["unique_models"] == 7 and len(inv["character_candidates"]) >= 5


# --- mesh part-record / VIF probe ---------------------------------------------------------------


def _mesh_child(parts=5, declared=None, trailer=0x280, pad_after=0):
    """Synthetic mesh child: header, part records (kinds 1..5 round-robin), payloads, trailer."""
    table_end = 12 + 16 * parts
    payloads, offs = [], []
    o = table_end
    for k in range(parts):
        kind = (1, 2, 3, 4, 5)[k % 5]
        cnt = 8
        if kind == 2:
            data = struct.pack("<8H", *range(8))
        else:
            data = struct.pack("<8f", *([1.5 + k] * 8))
        flags, z2 = (1, 0x10) if kind in (3, 4) else (0, 0)
        offs.append(o)
        payloads.append((kind, cnt, flags, z2, data))
        o += len(data)
    body = b"".join(p[4] for p in payloads)
    size = declared if declared is not None else o
    table = b"".join(struct.pack("<HHIHH4x", p[0], p[1], offs[i], p[2], p[3]) for i, p in enumerate(payloads))
    child = bytes([9, 0x22, 4, 1]) + struct.pack("<II", parts, size) + table + body
    child += b"\xcd" * pad_after + b"\x00" * trailer
    return child


def _x_data_child(iso, entry, path):
    """Fetch a MOMO child from X_DATA.BIN on the owned disc image."""
    X_LBA = 1264649  # verified in the inventory stage
    with iso.open("rb") as f:
        f.seek(X_LBA * 2048)
        n = struct.unpack_from("<I", f.read(8)[4:])[0]
        f.seek(X_LBA * 2048)
        tab = dmc2.afs_table(f.read(8 + 8 * n), 1065326592)
        o, z = tab["offsets"][entry], tab["sizes"][entry]
        f.seek(X_LBA * 2048 + o)
        cur = f.read(z)
    for j in path:
        kids = dmc2.momo_children(cur)
        cur = cur[kids[j][0]: kids[j][0] + kids[j][1]]
    return cur


MESH_CANDIDATES = [(108, [10]), (1157, [10]), (108, [0]), (1157, [0]), (2036, [0]), (836, [10])]


def test_mesh_parts_synthetic_and_probe():
    child = _mesh_child(parts=5)
    header, parts = dmc2.mesh_parts(child)
    assert header["tag"] == "09220401" and header["declared_parts"] == 5
    assert header["trailer"] == 0x280
    assert [p["kind"] for p in parts] == [1, 2, 3, 4, 5]
    assert all(p["count"] == 8 for p in parts)
    probe = dmc2.mesh_probe(child)
    assert probe["floats"] == 32 and probe["u16s"] == 8 and probe["quads"] == 16
    assert probe["nan_count"] == 0 and probe["coverage"] >= 0.9
    assert len(probe["quad_flagged"]) == 2  # kinds 3 and 4 carry (1, 0x10)


def test_mesh_parts_rejects_non_mesh_and_bad_size():
    with pytest.raises(ValueError):
        dmc2.mesh_parts(b"\x09\x21\x04\x01" + b"\x00" * 32)  # b1 != 0x22
    with pytest.raises(ValueError):
        dmc2.mesh_parts(b"\x09\x22\x04\x01" + struct.pack("<II", 2, 0x100) + b"\x00" * 0x10)  # size > child


def test_mesh_parts_stops_at_padding():
    child = _mesh_child(parts=5)
    header, parts = dmc2.mesh_parts(child)
    assert len(parts) == 5
    padded = bytearray(_mesh_child(parts=5))
    padded[12 + 16 * 2: 12 + 16 * 2 + 2] = b"\xcd\xcd"  # 0xCDCD padding mid-table
    _, short = dmc2.mesh_parts(bytes(padded))
    assert len(short) == 2
    with pytest.raises(ValueError):
        dmc2.mesh_parts(_mesh_child(parts=5)[:0x40])  # truncated: declared size exceeds child


@pytest.mark.skipif(not ISO.exists(), reason="owned DMC2 Disc 1 image not extracted on this host")
def test_owned_disc_mesh_probe():
    for entry, path in MESH_CANDIDATES:
        child = _x_data_child(ISO, entry, path)
        probe = dmc2.mesh_probe(child)
        assert probe["trailer"] == 0x280, (entry, path, probe["trailer"])
        assert probe["records"] >= 1, (entry, path)
        assert probe["max_end"] <= probe["size"], (entry, path)
        assert probe["nan_count"] == 0, (entry, path, probe["nan_count"])
        # quad records (kinds 3/4) always carry the (1, 0x10) flags on the owned disc
        for p in probe["quad_flagged"]:
            assert p["kind"] in (3, 4) and (p["flags"], p["z2"]) == (1, 0x10)


# --- compressed entry probe ------------------------------------------------------------------


def _x_data_entry(iso, entry):
    """Raw bytes of one X_DATA.BIN AFS entry from the owned disc image."""
    X_LBA = 1264649
    with iso.open("rb") as f:
        f.seek(X_LBA * 2048)
        n = struct.unpack_from("<I", f.read(8)[4:])[0]
        f.seek(X_LBA * 2048)
        tab = dmc2.afs_table(f.read(8 + 8 * n), 1065326592)
        o, z = tab["offsets"][entry], tab["sizes"][entry]
        f.seek(X_LBA * 2048 + o)
        return f.read(z)


def _momo_entry(children):
    """Synthetic compressed MOMO entry: 2-byte flag 0x0000 + literal MOMO package."""
    return b"\x00\x00" + _momo(children)


def test_compressed_entry_probe_synthetic():
    p = dmc2.compressed_entry_probe(_momo_entry([b"TIM2" + b"\0" * 28]))
    assert p["flag"] == 0 and p["flag_hi"] == 0 and p["flag_lo"] == 0
    assert p["type"] == "momo" and p["magic"] == "MOMO"
    assert p["literal_prefix"] == 16  # MOMO + count + one table entry
    with pytest.raises(ValueError):
        dmc2.compressed_entry_probe(b"MOMO" + b"\0" * 8)  # uncompressed: magic at 0, not +2


@ pytest.mark.skipif(not ISO.exists(), reason="owned DMC2 Disc 1 image not extracted on this host")
def test_owned_disc_compressed_probe():
    # X:105/106 are compressed MOMO (flag 0x0000); X:2631 is a compressed TIM2 (flag 0x0440).
    p105 = dmc2.compressed_entry_probe(_x_data_entry(ISO, 105))
    assert p105["type"] == "momo" and p105["flag"] == 0x0000
    assert p105["literal_prefix"] == 32  # MOMO + count + 3 leading table entries on this entry
    p106 = dmc2.compressed_entry_probe(_x_data_entry(ISO, 106))
    assert p106["type"] == "momo" and p106["flag"] == 0x0000
    assert p106["literal_prefix"] == 32  # MOMO + count + full 3-entry table, all literal
    p2631 = dmc2.compressed_entry_probe(_x_data_entry(ISO, 2631))
    assert p2631["type"] == "tim2" and p2631["flag_hi"] == 0x04
    assert p2631["flag_lo"] in dmc2.TIM2_FLAGS
    assert p2631["literal_prefix"] >= 8


@pytest.mark.parametrize("magic", [b"MOMO", b"TIM2"])
@pytest.mark.parametrize("length", [8, 9])
def test_compressed_probe_rejects_truncated_headers(magic, length):
    blob = (b"\x00\x00" + magic + b"\x01\x00\x00\x00")[:length]
    with pytest.raises(ValueError):
        dmc2.compressed_entry_probe(blob)


def test_compressed_probe_stops_before_a_truncated_momo_record():
    blob = b"\x00\x00MOMO" + struct.pack("<I", 1) + b"\x01" * 7
    assert dmc2.compressed_entry_probe(blob)["literal_prefix"] == 8


def _lz_encode_literal(data: bytes) -> bytes:
    """Reference encoder: literal-only groups (control 0).  Pads to 2-byte units."""
    data += b"\0" * (len(data) % 2)
    out = b""
    for i in range(0, len(data), 32):
        out += b"\0\0" + data[i:i + 32]
    return out


def test_lz_decompress_synthetic_refs():
    # unit index 2 is a back-reference: dist=2*2=4 bytes, len=(2)*2=4 bytes, then literal "GH"
    stream = (b"\x00\x00" + b"ABCD" + b"EF")  # group 1 control word 0 + units
    assert dmc2.lz_decompress(stream) == b"ABCDEF"
    ctrl = 0b0010000000000000  # unit index 2 is a back-reference
    s2 = ctrl.to_bytes(2, "little") + b"AB" + b"CD" + bytes([2, 2 << 3]) + b"GH"
    assert dmc2.lz_decompress(s2) == b"ABCD" + b"ABCD" + b"GH"
    # long form: len bits 0 -> next u16 = units; overlap copy of last unit (dist 2) x 5 units
    s3 = (0b0010000000000000).to_bytes(2, "little") + b"AB" + b"XY" + bytes([1, 0]) + (5).to_bytes(2, "little")
    assert dmc2.lz_decompress(s3) == b"ABXY" + b"XY" * 5


def test_decompress_entry_literal_momo_and_bad():
    raw = b"MOMO" + struct.pack("<I", 1) + struct.pack("<II", 16, 4) + b"TIM2"
    assert dmc2.decompress_entry(_lz_encode_literal(raw)) == raw
    with pytest.raises(ValueError):
        dmc2.decompress_entry(raw)  # no leading control word
    bad = b"MOMO" + struct.pack("<I", 1) + struct.pack("<II", 16, 99999) + b"TIM2"
    with pytest.raises(ValueError):
        dmc2.decompress_entry(_lz_encode_literal(bad))


@pytest.mark.skipif(not ISO.exists(), reason="owned DMC2 Disc 1 image not extracted on this host")
def test_owned_disc_decompress():
    # X:2631 compressed TIM2 -> exactly 16 + totalsize bytes (header says 132144).
    t = dmc2.decompress_entry(_x_data_entry(ISO, 2631))
    assert t[:4] == b"TIM2" and len(t) == 16 + struct.unpack_from("<I", t, 16)[0] == 132160
    # X:106 compressed MOMO: 3 TIM2 children at 0x800/0x41000/0x49800, ends 0x69980.
    m = dmc2.decompress_entry(_x_data_entry(ISO, 106))
    assert [m[o:o + 4] for o in (0x800, 0x41000, 0x49800)] == [b"TIM2"] * 3
    assert struct.unpack_from("<II", m, 8 + 16) == (0x49800, 0x20180)
    # X:105: 11 TIM2 children
    m = dmc2.decompress_entry(_x_data_entry(ISO, 105))
    n = struct.unpack_from("<I", m, 4)[0]
    assert n == 11 and all(m[struct.unpack_from("<I", m, 8 + 8 * j)[0]:][:4] == b"TIM2" for j in range(n))


# --- TIM2 decode + character package export (reader stage) --------------------------------------


def _synthetic_tim2(w=4, h=2):
    """Minimal PSMT8 TIM2 with a 2-entry RGBA32 CLUT."""
    clut = bytes([255, 0, 0, 255, 0, 0, 255, 255])  # red, blue
    img = bytes([0, 1, 1, 0, 0, 0, 1, 1])
    total = 32 + len(clut) + len(img)
    blob = b"TIM2" + bytes([0x04, 0x00, 1, 0]) + struct.pack("<I", 16 + total)
    blob += struct.pack("<II", total, len(clut)) + struct.pack("<II", len(img), 0)
    blob += struct.pack("<HH", 2, 2) + bytes([0, 0, 3, 5]) + struct.pack("<HH", w, h)
    blob += b"\x00" * 8 + clut + img
    return blob


def test_tim2_rgba_synthetic():
    blob = _synthetic_tim2()
    pics = dmc2.tim2_rgba(blob)
    assert len(pics) == 1
    w, h, rgba = pics[0]
    assert (w, h) == (4, 2)
    px = [tuple(rgba[i:i + 4]) for i in range(0, len(rgba), 4)]
    assert px[0] == (255, 0, 0, 255) and px[1] == (0, 0, 255, 255)
    assert px == [px[0], px[1], px[1], px[0], px[0], px[0], px[1], px[1]]


def test_write_png_roundtrip(tmp_path):
    import zlib
    rgba = bytes([255, 0, 0, 255] * 2 + [0, 255, 0, 128] * 2)  # 2x2
    dmc2.write_png(tmp_path / "t.png", 2, 2, rgba)
    b = (tmp_path / "t.png").read_bytes()
    assert b[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", b[16:24]) == (2, 2)
    pos, idat = 8, b""
    while pos < len(b):
        ln = struct.unpack(">I", b[pos:pos + 4])[0]
        if b[pos + 4:pos + 8] == b"IDAT":
            idat += b[pos + 8:pos + 8 + ln]
        pos += 12 + ln
    raw = zlib.decompress(idat)
    assert raw == b"\x00" + rgba[:8] + b"\x00" + rgba[8:]


def test_texbank_tim2_offsets():
    blob = b"\x00" * 0x800 + _synthetic_tim2() + b"\x00" * 9 + b"\x00TIM2!"
    assert dmc2.texbank_tim2_offsets(blob) == [0x800, len(blob) - 5]


@pytest.mark.skipif(not ISO.exists(), reason="owned DMC2 Disc 1 image not extracted on this host")
def test_owned_disc_export_character_package(tmp_path):
    r = dmc2.export_character_package(ISO, 108, tmp_path)
    # mesh child 0: 178016 bytes, 8 parts, first float triple is model-space
    assert r["mesh"]["child"] == 0 and r["mesh"]["size"] == 178016
    lay = r["mesh"]["layout"]
    assert len(lay) == 9 and lay[4]["kind"] == 3 and lay[4]["count"] == 2157
    assert all(abs(v) < 500 for v in lay[4]["first_float_triple"])
    # textures: 16 TIM2s, all 256x256 PSMT8, PNG files on disk
    assert len(r["textures"]) == 16
    assert all(t["w"] == 256 and t["h"] == 256 for t in r["textures"])
    assert all(Path(t["path"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" for t in r["textures"])
    # texbanks live at children 1 (5 TIM2), 11 (4), 19 (1), 21 (1), 23 (3), 31 (2)
    from collections import Counter
    assert Counter(t["child"] for t in r["textures"]) == {1: 5, 11: 4, 19: 1, 21: 1, 23: 3, 31: 2}


def _vertex_part(counts):
    n = len(counts)
    tabs = bytearray()
    body = bytearray()
    base = 32 * n
    for c in counts:
        offs = []
        for size in (12, 12, 4, 4, 2):
            offs.append(base + len(body))
            body += b"\x00" * (size * c)
        t = struct.pack("<8I", c, *offs, 0, 0)
        tabs += t
    return bytes(tabs + body), offs


def test_mesh_blocks_and_decode_synthetic():
    data, _ = _vertex_part([3, 2])
    blocks = dmc2.mesh_blocks(data, 0)
    assert [b["count"] for b in blocks] == [3, 2]
    ba = bytearray(data)
    struct.pack_into("<3f", ba, blocks[0]["pos"] + 12, 1.0, 2.0, 3.0)
    struct.pack_into("<2H", ba, blocks[1]["uv"], 2048, 4096)
    v = dmc2.decode_mesh_part(bytes(ba), 0)["vertices"]
    assert len(v) == 5 and v[1]["pos"] == (1.0, 2.0, 3.0) and v[3]["uv"] == (0.5, 1.0)
    obj = dmc2.part_to_obj(bytes(ba), 0)
    assert obj.count("\nv ") == 5


def test_strip_triangles_restart_flag():
    vs = [{"idx": 0x8000 | 31}, {"idx": 31}, {"idx": 31}, {"idx": 31}, {"idx": 0x801F}, {"idx": 31}, {"idx": 31}]
    assert dmc2.strip_triangles(vs) == [(0, 1, 2), (2, 1, 3), (4, 5, 6)]


def test_mesh_blocks_rejects_garbage():
    with pytest.raises(ValueError):
        dmc2.mesh_blocks(struct.pack("<8I", 1, 0, 0, 0, 0, 0, 0, 0), 0)


@pytest.mark.skipif(not ISO.exists(), reason="owned DMC2 Disc 1 image not extracted on this host")
def test_owned_disc_x108_vertex_blocks():
    child = _x_data_child(ISO, 108, [0])
    _, parts = dmc2.mesh_parts(child)
    total = 0
    ymin, ymax, xmin, xmax = 1e9, -1e9, 1e9, -1e9
    for p in parts:
        d = dmc2.decode_mesh_part(child, p["offset"])
        assert len(d["vertices"]) == p["count"]
        total += p["count"]
        for v in d["vertices"]:
            ymin, ymax = min(ymin, v["pos"][1]), max(ymax, v["pos"][1])
            xmin, xmax = min(xmin, v["pos"][0]), max(xmax, v["pos"][0])
            assert abs(sum(c * c for c in v["nrm"]) - 1.0) < 0.01
    assert total == 5181
    assert 170 < ymax < 190 and -5 < ymin < 5 and xmax > 60 and xmin < -60
