"""Tests for gbox.auf_ngc_writer (007: Agent Under Fire GC .ngc package writer).

Synthetic tests pin the layout rules read from Bond.elf (ReadChunkData,
FS_FindResource, HashString); the disc tests run only where the owned GCZ is
cached (GBOX_AUF_GCZ or the default cache path).
"""
import hashlib
import os
import random
import struct

import pytest

from gbox import auf_ngc, auf_ngc_writer as W

GCZ = os.environ.get("GBOX_AUF_GCZ",
                     os.path.expanduser("~/gbox-cache/gc/65b7187589166b26/source.gcz"))


def test_hash_string_matches_owned_restable_records():
    # first two records of maps/dm1.ngc's restable (sorted by hash)
    assert W.hash_string("models/mp_fx_rocket_explosion.men") == 5565736
    assert W.hash_string("models/anims/4_m_s_w2_jump_land.gca") == 8255050
    assert W.hash_string("MODELS/ANIMS/D17_FIRE_1.GCA") == 11815974


def test_boa_compress_roundtrip_and_inplace():
    rnd = random.Random(7)
    data = (b"abcabcabc" * 50 + bytes(rnd.randrange(256) for _ in range(3000))
            + b"\0" * 5000 + bytes(range(256)) * 4)
    s = W.boa_compress(data)
    assert len(s) < len(data)
    assert auf_ngc.boa_expand(s, len(data))[0] == data
    assert W.inplace_ok(s, len(data), len(data))


def test_inplace_ok_rejects_incompressible_literal_stream():
    rnd = random.Random(1)
    data = bytes(rnd.randrange(256) for _ in range(4096))
    lit = auf_ngc.boa_store(data)          # 9/8 expansion: overruns mem+0x40
    assert not W.inplace_ok(lit, len(data), len(data))
    # encode_chunk then falls back to an uncompressed chunk
    c = W.encode_chunk("restable", data)
    pkg = auf_ngc.NgcPackage(c)
    assert pkg.chunks[0].compressed == 0 and pkg.payload("restable") == data


def _files():
    return [("models/props/test_prop.gcm", b"G" * 37),
            ("models/anims/idle.gca", b"anim"),
            ("global/mp_player_male.anm", bytes(range(50)))]


def test_build_restable_layout_sorted_aligned_and_readable():
    t = W.build_restable(_files())
    assert len(t) % 32 == 0
    res = auf_ngc.parse_restable(t)
    hs = [r.hash for r in res]
    assert hs == sorted(hs) and all(W.hash_string(r.name) == r.hash for r in res)
    assert all(r.offset % 16 == 0 for r in res)
    assert res[0].offset == 0x10 + 16 * len(res)
    by = {r.name: t[r.offset:r.offset + r.size] for r in res}
    assert by == dict(_files())
    names = [struct.unpack_from(">I", t, 0x10 + 16 * i)[0] for i in range(len(res))]
    assert names == sorted(names) and names[0] % 16 == 0 and names[0] >= max(r.offset + r.size for r in res)
    assert W.build_restable(W.restable_entries(t)) == t


def test_write_package_noop_and_resource_replace():
    t = W.build_restable(_files())
    data = W.encode_chunk("snd_alb", b"\1" * 40) + W.encode_chunk("bspfile", b"\2" * 64, 2.5, False) \
        + W.encode_chunk("restable", t)
    pkg = auf_ngc.NgcPackage(data)
    assert W.write_package(pkg) == data
    out = W.replace_resources(pkg, {"models/anims/idle.gca": b"new animation bytes"})
    q = auf_ngc.NgcPackage(out)
    assert q.read("models/anims/idle.gca") == b"new animation bytes"
    assert q.read("global/mp_player_male.anm") == bytes(range(50))
    assert out[:q.chunk("restable").offset] == data[:pkg.chunk("restable").offset]
    assert W.check_package(out)["problems"] == []
    with pytest.raises(KeyError):
        W.replace_resources(pkg, {"models/nope.gcm": b""})


def _dm1(tmp_path):
    from gbox import au_inventory
    au_inventory.extract(GCZ, ["dm1.ngc"], str(tmp_path))
    return (tmp_path / "dm1.ngc").read_bytes()


@pytest.mark.skipif(not os.path.exists(GCZ), reason="owned AUF GCZ not cached")
def test_owned_dm1_noop_roundtrip_is_byte_identical(tmp_path):
    data = _dm1(tmp_path)
    pkg = auf_ngc.NgcPackage(data)
    assert W.write_package(pkg) == data
    assert W.build_restable(W.restable_entries(pkg.table)) == pkg.table
    # re-encoding the table with our compressor decodes identically and is in-place safe
    out = W.write_package(pkg, {"restable": pkg.table})
    q = auf_ngc.NgcPackage(out)
    assert q.table == pkg.table
    assert q.chunk("restable").disk_size <= pkg.chunk("restable").disk_size
    assert W.check_package(out)["problems"] == []


@pytest.mark.skipif(not os.path.exists(GCZ), reason="owned AUF GCZ not cached")
def test_owned_dm1_bondcombat_slot_takes_uwb_thug(tmp_path):
    data = _dm1(tmp_path)
    pkg = auf_ngc.NgcPackage(data)
    out, info = W.swap_models(pkg, W.DEFAULT_PAIRS)
    assert [i["bones"] for i in info] == [35, 34]
    q = auf_ngc.NgcPackage(out)
    body, head = (p[0] for p in W.DEFAULT_PAIRS)
    assert q.read(body) == pkg.read(W.DEFAULT_PAIRS[0][1])
    assert q.read(head) == pkg.read(W.DEFAULT_PAIRS[1][1])
    changed = [r.name for r in pkg.resources() if q.read(r.name) != pkg.read(r.name)]
    assert sorted(changed) == sorted([body, head])
    for a, b in zip(pkg.chunks, q.chunks):
        if a.id != "restable":
            assert data[a.offset:a.end] == out[b.offset:b.end]
    assert W.check_package(out)["problems"] == []
    m = auf_ngc.mesh(q.read(body))
    assert len(m["faces"]) == 425 and auf_ngc.bbox_error(q.read(body), m)[0] < 0.5
    assert all(t is not None for t in auf_ngc.section_textures(q, m))
    # a donor with bones the slot never animates is refused
    with pytest.raises(ValueError):
        W.swap_models(pkg, [(head, "models/actors/actorheads/griffin_head_l.gcm")])
    assert hashlib.sha256(out).hexdigest() == "7e9e72489cb7f192378b7184e0006887489c455c9a8cf1a0acec8723c78f2561"

def _skinned_gcm():
    """Two bones (root at z=10, child +5 z and turned 90 deg about z), a 0.5-scale
    dequant matrix, one strip whose last two vertices use the child's matrix slot."""
    g = bytearray(0x600)
    struct.pack_into(">II", g, 0, 0x48400001, 0x00000008)
    h = 0x10
    struct.pack_into(">I", g, h + 0x0C, len(g))
    struct.pack_into(">3f", g, h + 0x20, 0.5, 1.0, 12.5)      # bbox centre
    struct.pack_into(">3f", g, h + 0x30, 1.5, 1.0, 2.5)       # half extents
    struct.pack_into(">H", g, h + 0x50, 2)                    # bones
    struct.pack_into(">H", g, h + 0x54, 2)                    # palette records
    for field, at in ((0x74, 0x200), (0x78, 0x220), (0x7C, 0x280), (0x80, 0x300)):
        struct.pack_into(">I", g, h + field, at)
        _block(g, at)
    struct.pack_into(">iIiI", g, 0x210, 0, 0x13C6700F, 0, 0x02489002)
    s = 0.5 ** 0.5
    struct.pack_into(">8f", g, 0x230, 0, 0, 10, 0, 0, 0, 0, 1)
    struct.pack_into(">8f", g, 0x250, 0, 0, 5, 0, 0, 0, s, s)
    struct.pack_into(">hhfhhf", g, 0x290, 0, -2, 1.0, 1, -2, 1.0)
    body = 0x310
    struct.pack_into(">12f", g, body, 0.5, 0, 0, 1.0, 0, 0.5, 0, 0, 0, 0, 0.5, 0)
    data = {
        "vtx_pos": struct.pack(">12h", 0, 0, 0, 2, 0, 0, 0, 2, 0, 2, 2, 0),
        "vtx_normal": struct.pack(">3b", 0, 0, 64),
        "vtx_st": struct.pack(">2h", 2048, 1024),
        "ent_vtx": struct.pack(">12H", 0, 0, 0, 1, 0, 0, 2, 0, 0, 3, 0, 0),
        "u16_list": struct.pack(">4H", 0, 1, 2, 3),
        "u8_list": bytes([0, 0, 3, 3]),
        "tri_strip": struct.pack(">HHHBB", 0, 4, 0, 0, 0xFF),
        "mtx_map": bytes([0, 0, 1, 3]),
        "geom_group": struct.pack(">4H", 0, 2, 0, 1),
        "geom_section": struct.pack(">IIHHI", 0, 0xABCD1234, 0, 1, 0),
    }
    off = 0xA0
    for field, name, esize in auf_ngc.NGC_ARRAYS:
        if name not in data:
            continue
        raw = data[name]
        struct.pack_into(">II", g, body + field, off, len(raw) // esize)
        g[body + off:body + off + len(raw)] = raw
        off = (off + len(raw) + 3) & ~3
    return bytes(g)
