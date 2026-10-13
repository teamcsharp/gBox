"""Tests for gbox.auf_ngc (007: Agent Under Fire GC .ngc packages / .gcm models).

The synthetic tests pin the formats as read from Bond.elf; the disc test runs
only where the owned GCZ is cached (GBOX_AUF_GCZ or the default cache path).
"""
import os
import struct

import pytest

from gbox import auf_ngc


def test_chunk_id_matches_chunkidtostr():
    # First header of maps/dm1.ngc on the owned disc.
    raw = bytes.fromhex("00626c615f646e73")
    assert auf_ngc.chunk_id(raw) == "snd_alb"
    for name in ("restable", "restxtrs", "shaders", "bspfile", "sndbank", "shockprf"):
        assert auf_ngc.chunk_id(auf_ngc.encode_chunk_id(name)) == name


def test_boa_literals_and_backrefs():
    # flags 0b11110111 LSB first: 3 literals, 1 back-ref, 4 literals
    # back-ref b0=0x31 (len 1+2=3, dist low nibble 3), b1=0 -> dist 3: copies "abc"
    src = bytes([0xF7]) + b"abc" + bytes([0x31, 0x00]) + b"defg"
    out, used = auf_ngc.boa_expand(src, 10)
    assert out == b"abcabcdefg"
    assert used == len(src)


def test_boa_overlapping_run_and_noop_token():
    # literal 'x', no-op token (length nibble 0), run copy dist 1 len 15+2
    src = bytes([0b00000001, ord("x"), 0x00, 0x00, 0x1F, 0x00])
    out, _ = auf_ngc.boa_expand(src, 18)
    assert out == b"x" * 18


def test_boa_rejects_reference_before_start():
    with pytest.raises(ValueError):
        auf_ngc.boa_expand(bytes([0x00, 0x51, 0x00]), 4)


def test_boa_store_roundtrip():
    data = bytes(range(256)) * 3 + b"tail"
    assert auf_ngc.boa_expand(auf_ngc.boa_store(data), len(data))[0] == data


def _chunk(name, payload, compress):
    size = len(payload)
    mem = (size + 31) & ~31
    body = auf_ngc.boa_store(payload) if compress else payload
    hdr = auf_ngc.encode_chunk_id(name) + struct.pack(">IfIIII", size, 1.0, int(compress),
                                                      0xCDCDCDCD, len(body), mem)
    blob = hdr + body
    return blob + b"\0" * (-len(blob) % 32)


def _restable(files):
    n = len(files)
    names = b""
    name_offs = []
    base = 0x10 + 16 * n
    for name, _ in files:
        name_offs.append(base + len(names))
        names += name.encode() + b"\0"
    data_base = (base + len(names) + 15) & ~15
    body = b""
    recs = b""
    for (name, blob), no in zip(files, name_offs):
        recs += struct.pack(">4I", no, data_base + len(body), len(blob), 0x1234)
        body += blob + b"\0" * (-len(blob) % 16)
    head = struct.pack(">4I", n, 0, 0, 0) + recs + names
    return head + b"\0" * (data_base - len(head)) + body


def _gcm():
    """Minimal object: header (byte7=8 -> body at 0x10), NGC block at 0x100."""
    g = bytearray(0x400)
    struct.pack_into(">II", g, 0, 0x48400001, 0x00000008)
    struct.pack_into(">I", g, 0x10 + 0x0C, len(g))
    struct.pack_into(">I", g, 0x10 + 0x80, 0x100)
    struct.pack_into(">II", g, 0x100, 0x3ED, 0x00292008)  # byte7 = 8 -> body 0x110
    body = 0x110
    counts = {"vtx_pos": 3, "vtx_normal": 3, "vtx_st": 3, "ent_vtx": 3, "u16_list": 4,
              "u8_list": 5, "tri_strip": 1, "mtx_map": 1, "geom_group": 1, "geom_section": 1}
    off = 0xA0
    for field, name, esize in auf_ngc.NGC_ARRAYS:
        if name not in counts or esize is None:
            continue
        struct.pack_into(">II", g, body + field, off, counts[name])
        if name == "vtx_pos":
            for i in range(3):
                struct.pack_into(">hhh", g, body + off + 6 * i, i, -i, 100 * i)
        off += counts[name] * esize
        off = (off + 3) & ~3
    return bytes(g)


def test_package_walk_restable_and_gcm_tiling():
    gcm = _gcm()
    table = _restable([("models/actors/bond/bond_test_l.gcm", gcm),
                       ("models/anims/idle.gca", b"anim")])
    data = (_chunk("snd_alb", b"\x01" * 40, True) + _chunk("bspfile", b"\x02" * 64, False)
            + _chunk("restable", table, True))
    pkg = auf_ngc.NgcPackage(data)
    assert [c.id for c in pkg.chunks] == ["snd_alb", "bspfile", "restable"]
    assert pkg.chunks[-1].end == len(data)
    assert [r.name for r in pkg.resources()] == ["models/actors/bond/bond_test_l.gcm",
                                                 "models/anims/idle.gca"]
    assert pkg.read("models/anims/idle.gca") == b"anim"
    got = pkg.read("models/actors/bond/bond_test_l.gcm")
    info = auf_ngc.gcm_info(got)
    assert info["ngc_body"] == 0x110
    assert auf_ngc.tile_check(info) == []
    assert auf_ngc.positions(got, info) == [(0, 0, 0), (1, -1, 100), (2, -2, 200)]
    rows = auf_ngc.characters(pkg)
    assert len(rows) == 1 and rows[0]["vtx_pos"] == 3 and rows[0]["tile_problems"] == []


def test_gcm_rejects_non_object():
    with pytest.raises(ValueError):
        auf_ngc.gcm_info(b"\x12\x34" + b"\0" * 0x200)


GCZ = os.environ.get("GBOX_AUF_GCZ",
                     os.path.expanduser("~/gbox-cache/gc/65b7187589166b26/source.gcz"))


@pytest.mark.skipif(not os.path.exists(GCZ), reason="owned AUF GCZ not cached")
def test_owned_disc_dm1_character_models(tmp_path):
    from gbox import au_inventory
    au_inventory.extract(GCZ, ["dm1.ngc"], str(tmp_path))
    data = (tmp_path / "dm1.ngc").read_bytes()
    pkg = auf_ngc.NgcPackage(data)
    assert [c.id for c in pkg.chunks] == ["snd_alb", "sndbank", "restxtrs", "shaders",
                                          "bspfile", "shockprf", "restable"]
    assert pkg.chunks[-1].data_offset + pkg.chunks[-1].disk_size == len(data)
    assert len(pkg.resources()) == 880
    rows = {r["name"]: r for r in auf_ngc.characters(pkg)}
    assert len(rows) == 31
    assert all(not r.get("error") and r["tile_problems"] == [] for r in rows.values())
    bond = rows["models/actors/bond/bond_combat_l.gcm"]
    assert (bond["size"], bond["vtx_pos"], bond["ent_vtx"], bond["tri_strips"],
            bond["sections"], bond["mtx_map"]) == (13824, 263, 387, 204, 3, 67)
