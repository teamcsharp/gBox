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
                     os.path.expanduser("~/gBox_alt/gbox-cache/gc/65b7187589166b26/source.gcz"))


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


def test_visual_rebuild_rejects_missing_or_changed_gadgets_and_mission_scripts():
    entries = [("models/actors/bond.gcm", b"body"),
               ("models/qclaw_pickup.men", b"qclaw definition"),
               ("models/gadget_qlaser.men", b"qlaser definition"),
               ("maps/orc_1.scr", b"grant the mission gadgets"),
               ("script_dictionary", b"unchanged dictionary")]
    def package(files, bsp=b"unchanged bsp"):
        return auf_ngc.NgcPackage(W.encode_chunk("bspfile", bsp)
                                 + W.encode_chunk("restable", W.build_restable(files)))
    before = package(entries)
    visual = [(n, b"replacement body" if n.endswith(".gcm") else b) for n, b in entries]
    assert W.check_preserved(before, package(visual), ["models/actors/bond.gcm"]) == []
    for resource in ("models/qclaw_pickup.men", "models/gadget_qlaser.men", "maps/orc_1.scr", "script_dictionary"):
        broken = [(n, b"changed" if n == resource else b) for n, b in visual]
        assert W.check_preserved(before, package(broken), ["models/actors/bond.gcm"]) == [
            "unrequested resource changed: " + resource]
    missing = [(n, b) for n, b in visual if n != "models/qclaw_pickup.men"]
    assert "resource names changed during a visual-only rebuild" in W.check_preserved(
        before, package(missing), ["models/actors/bond.gcm"])
    assert W.check_preserved(before, package(visual, b"changed collision"), ["models/actors/bond.gcm"]) == [
        "unrequested chunk changed: bspfile"]


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
