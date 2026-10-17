"""Synthetic-GC-disc test for gbox.pso_gc_inventory: header/executable/character/animation classification."""
import hashlib
import struct

import pytest

from gbox.pso_gc_inventory import inventory

ALIGN = 0x8000


def _fst_entry(is_dir, name_off, a, b):
    return struct.pack(">III", (is_dir << 24) | name_off, a, b)


def _put(buf: bytearray, off: int, data: bytes | bytearray):
    """Write at an absolute offset; explicit zero-pad because bytearray slice-assign beyond len clamps to the end."""
    if off + len(data) > len(buf):
        buf.extend(b"\x00" * (off + len(data) - len(buf)))
    buf[off:off + len(data)] = data


def make_disc(tmp_path, names: list[str], payloads: dict[str, bytes]):
    """Write a minimal GameCube ISO: header, one text section, a real DOL, an FST, then the file data."""
    files = sorted(set(names))
    dol = bytearray(0x100 + 0x40)
    struct.pack_into(">7I", dol, 0, *([0x100] + [0] * 6))
    struct.pack_into(">7I", dol, 0x1C, *([0x80003100] + [0] * 6))
    struct.pack_into(">18I", dol, 0x90, *([len(dol) - 0x100] + [0] * 17))
    struct.pack_into(">II", dol, 0xD8, 0x80006000, 0x20)
    struct.pack_into(">I", dol, 0xE8, 0x80003100)
    files = ["boot.dol"] + files

    fst_names = b"\x00".join(n.encode() for n in files) + b"\x00"
    n = len(files) + 1
    fst = bytearray(_fst_entry(1, 0, 0, n))  # entry 0 = root dir; its size field is the FST count
    name_off = 0
    fst_entries = bytearray()
    for f in files:
        fst_entries += _fst_entry(0, name_off, 0, 0)  # offsets filled in below
        name_off += len(f) + 1
    fst += fst_entries + fst_names
    while len(fst) % 4:
        fst += b"\x00"

    fst_off = ALIGN + len(dol)
    data_off = (fst_off + len(fst) + 0x1F) & ~0x1F
    pos = data_off
    for i, f in enumerate(files):
        data = payloads.get(f, dol if f == "boot.dol" else b"\x00" * 32)
        off, size = pos, len(data)
        struct.pack_into(">II", fst, 12 * (i + 1) + 4, off, size)
        pos += (size + 0x1F) & ~0x1F

    header = bytearray(0x440)
    header[0:6] = b"GPOE8P"
    header[6:8] = b"\x00\x02"
    header[0x1C:0x20] = bytes.fromhex("c2339f3d")
    header[0x20:0x20 + len(b"PHANTASY STAR ONLINE EPISODE I&II")] = b"PHANTASY STAR ONLINE EPISODE I&II"
    struct.pack_into(">I", header, 0x420, ALIGN)          # DOL offset
    struct.pack_into(">II", header, 0x424, fst_off, len(fst))

    iso = bytearray(0)
    _put(iso, 0, header)
    _put(iso, ALIGN, dol)
    _put(iso, fst_off, fst)
    for i, f in enumerate(files):
        data = payloads.get(f, dol if f == "boot.dol" else b"\x00" * 32)
        off, size = struct.unpack_from(">II", fst, 12 * (i + 1) + 4)
        _put(iso, off, data)
    iso_path = tmp_path / "disc.iso"
    iso_path.write_bytes(bytes(iso))
    return iso_path


def _mini_dol() -> bytes:
    dol = bytearray(0x100 + 0x40)
    struct.pack_into(">7I", dol, 0, *([0x100] + [0] * 6))
    struct.pack_into(">7I", dol, 0x1C, *([0x80003100] + [0] * 6))
    struct.pack_into(">18I", dol, 0x90, *([len(dol) - 0x100] + [0] * 17))
    struct.pack_into(">II", dol, 0xD8, 0x80006000, 0x20)
    struct.pack_into(">I", dol, 0xE8, 0x80003100)
    return bytes(dol)


def test_inventory_classifies_psos(tmp_path):
    disc = make_disc(tmp_path, ["PsoV3.dol", "plAbdy00.nj", "plAhed00.nj", "plAtex.afs", "plAnj.bml",
                                "PlyMotionData.rlc", "map_forest01d.dat", "boss.adx"],
                     {"PsoV3.dol": _mini_dol(),
                      "plAbdy00.nj": b"NJCM" + b"\x00" * 28,
                      "plAtex.afs": b"AFS\x00\x89\x00\x00\x00" + b"\x00" * 64})
    m = inventory(str(disc), source_sha256="a" * 64, source_path="quickswap2/test.iso")
    assert m["game_id"] == "GPOE8P"
    assert m["platform"] == "gamecube"
    assert m["title"].startswith("PHANTASY STAR ONLINE")
    assert m["source_sha256"] == "a" * 64
    exe = [e for e in m["executables"] if e["name"] == "PsoV3.dol"]
    assert len(exe) == 1 and exe[0]["dol"]["entry"] == 0x80003100
    a = m["characters"]["A"]
    assert a["class"] == "HUmar"
    assert len(a["files"]["bodies"]) == 1 and len(a["files"]["heads"]) == 1
    assert len(a["files"]["bml"]) == 1 and len(a["files"]["tex_afs"]) == 1
    assert a["files"]["bodies"][0]["sha256"] == hashlib.sha256(b"NJCM" + b"\x00" * 28).hexdigest()
    anim = m["assets"]["animation"]
    assert [f["name"] for f in anim] == ["PlyMotionData.rlc"]
    assert m["assets"]["stage"][0]["name"] == "map_forest01d.dat"
    assert m["assets"]["audio"][0]["name"] == "boss.adx"


def test_inventory_rejects_non_gc(tmp_path):
    p = tmp_path / "notgc.iso"
    p.write_bytes(b"\x00" * 0x440)
    with pytest.raises(ValueError, match="not a GameCube disc"):
        inventory(str(p))
