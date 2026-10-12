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
