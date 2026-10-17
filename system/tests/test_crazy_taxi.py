import hashlib
import os
import struct
from pathlib import Path

import pytest

from gbox import crazy_taxi as ct

ISO = Path(os.environ.get("GBOX_CT_ISO", "/home/ehm_eckx/gbox-cache/modbase/bc02bb68790ce2e7/Crazy Taxi (USA).iso"))

CUBE = [(x, y, z) for z in (-1, 1) for y in (-1, 1) for x in (-1, 1)]
FACES = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]


def _cube_shp() -> bytes:
    """A minimal .shp laid out like the disc's loose ct/cube0.shp (radius sqrt3, scale radius/512, s16 +-18918)."""
    radius = 3 ** 0.5
    b = bytearray(0x2A0)
    struct.pack_into(">ff", b, 0, 1.0, radius)
    struct.pack_into(">3f", b, 0x2C, *(radius / 512,) * 3)
    struct.pack_into(">I", b, 0xCC, 0x120)            # POS
    struct.pack_into(">I", b, 0xDC, 0x160)            # TEX0
    struct.pack_into(">4I", b, 0x110, 0x180, 0x120, 0x1C0, 0x260)
    for i, v in enumerate(CUBE):
        struct.pack_into(">3h", b, 0x120 + 6 * i, *(c * 18918 for c in v))
    for i, uv in enumerate([(1, 1), (254, 1), (254, 254), (1, 254)]):
        struct.pack_into(">2h", b, 0x160 + 4 * i, *uv)
    struct.pack_into(">I", b, 0x180, 0x38)
    struct.pack_into(">II", b, 0x1A4, 0x1C0, 0xA0)
    dl = bytearray(b"\x90" + struct.pack(">H", 36))
    for a, bb, c, d in FACES:
        for p, t in ((a, 0), (bb, 1), (c, 2), (a, 0), (c, 2), (d, 3)):
            dl += struct.pack(">HH", p, t)
    b[0x1C0:0x1C0 + len(dl)] = dl
    b[0x260:0x269] = b"white.tex"
    return bytes(b)


def test_cube_shape_decodes_like_the_disc_oracle():
    s = ct.read_shape(_cube_shp(), "cube0")
    assert s.lists == [(0x1C0, 0xA0)]
    assert len(s.tris) == 12
    assert s.frac() == 6
    pts = s.positions()
    assert all(abs(abs(c) - 1.0) < 1e-3 for p in pts[:8] for c in p)
    assert s.uv[2] == (254 / 256, 254 / 256)
    assert s.textures == ["white.tex"]
    obj = ct.to_obj(s)
    assert obj.count("\nf ") == 12 and obj.count("\nv ") == len(s.pos)


def test_strip_and_fan_primitives():
    corner = lambda i: struct.pack(">H", i)
    strip = b"\x98" + struct.pack(">H", 4) + b"".join(corner(i) for i in range(4))
    fan = b"\xa0" + struct.pack(">H", 4) + b"".join(corner(i) for i in range(4))
    t = ct.decode_dl(strip + b"\0\0" + fan, ["pos"])
    as_idx = [tuple(c["pos"] for c in tri) for tri in t]
    assert as_idx == [(0, 1, 2), (2, 1, 3), (0, 1, 2), (0, 2, 3)]
    with pytest.raises(ValueError):
        ct.decode_dl(b"\x55\x00\x01", ["pos"])


def test_bank_round_trip_and_size_check():
    blobs = [("a.shp", b"\1" * 0x20), ("MP_YH_plyrA_atama.shp", _cube_shp())]
    data = ct.write_bank(blobs)
    entries = ct.read_bank(data)
    assert [(n, s) for n, _, s in entries] == [(n, len(b)) for n, b in blobs]
    assert ct.write_bank([(n, data[o:o + s]) for n, o, s in entries]) == data
    with pytest.raises(ValueError):
        ct.read_bank(data + b"\0" * 0x20)
    assert ct.driver_parts(entries, "A") == {"atama": entries[1][1:]}


@pytest.mark.skipif(not ISO.exists(), reason="owned Crazy Taxi GC disc not present")
def test_owned_disc_driver_inventory():
    from gbox.gcdisc import GCDisc
    disc = GCDisc(ISO)
    assert disc.game_id == ct.DISC_ID
    bank = disc.read(ct.BANK)
    assert hashlib.sha256(bank).hexdigest().startswith("a5171e43e8458a2e")
    entries = ct.read_bank(bank)
    assert len(entries) == 1586
    # main.dol's shape enum (0x80190a9c) gives MP_YH_plyrA_koshi id 0x48a; its bank position is 26 lower.
    assert [n for n, _, _ in entries].index("MP_YH_plyrA_koshi.shp") == 0x48A - 26
    assert ct.write_bank([(n, bank[o:o + s]) for n, o, s in entries]) == bank
    inv = ct.inventory(bank)
    assert set(inv["drivers"]) == {"axel", "bd_joe", "gena", "gus"}
    for d in inv["drivers"].values():
        assert set(d["parts"]) == set(ct.PARTS)
    # 393 with the head's fifth material list (0x9e0, before the fourth record's 0xa20), which the ascending-order
    # scan skipped (389, and a stale pointer in the written head: the driver-select FIFO hang)
    assert inv["drivers"]["axel"]["tris"] == 393
    head = inv["drivers"]["axel"]["parts"]["atama"]
    assert (head["verts"], head["tris"]) == (64, 77)
    o, s = ct.driver_parts(entries, "A")["atama"]
    assert ct.read_shape(bank[o:o + s]).frac() == 8


def test_car_part_names_and_roster():
    assert ct.car_part_name("CZ_CADI", "shp") == "CZ_CADI.shp"
    assert ct.car_part_name("CZ_CADI", "stop_ON") == "CZ_CADIstop_ON.shp"
    assert ct.car_part_name("CZ_CADI", "flw") == "CZ_CADI_flw.shp"
    entries = [("CZ_CADI.shp", b"\1" * 0x40), ("CZ_CADIstop_ON.shp", b"\2" * 0x20)]
    data = ct.write_bank(entries)
    parts = ct.car_parts(ct.read_bank(data), "CZ_CADI")
    assert set(parts) == {"shp", "stop_ON"}
    roster = ct.roster()
    assert any(e["slug"] == "crazy_taxi_yellow" and e["kind"] == "vehicle" for e in roster)


@pytest.mark.skipif(not ISO.exists(), reason="owned Crazy Taxi GC disc not present")
def test_owned_disc_yellow_taxi_glb():
    """Request #459: the yellow taxi (CZ_CADI) assembles into a posed GLB + OBJ from the owned disc."""
    import json
    from gbox.gcdisc import GCDisc
    disc = GCDisc(ISO)
    bank = disc.read(ct.BANK)
    entries = ct.read_bank(bank)
    parts = ct.car_parts(entries, "CZ_CADI")
    assert set(parts) >= {"shp", "flw", "frw", "rlw", "rrw", "taxiON", "stop_OFF"}
    glb, stats = ct.car_glb(bank, "CZ_CADI")
    assert glb[:4] == b"glTF" and stats["tris"] > 2000 and stats["verts"] > 1100
    jl = struct.unpack("<I", glb[12:16])[0]
    gl = json.loads(glb[20:20 + jl])
    nodes = {n["name"]: n for n in gl["nodes"]}
    assert "translation" not in nodes["shp"]
    hubs = {}
    for w in ("flw", "frw", "rlw", "rrw"):
        t = nodes[w]["translation"]
        sw = ct.read_shape(bank[parts[w][0]:parts[w][0] + parts[w][1]], w)
        hub = (sw.centre[0] + t[0], sw.centre[1] + t[1], sw.centre[2] + t[2])
        hubs[w] = hub
        assert abs(abs(hub[0]) - 1.025) < 1e-3, w       # track width carried by the header centre
        assert hub[1] > 2.0                              # hub above the ground plane
    assert hubs["flw"][2] < 0 < hubs["rlw"][2]           # front wheels ahead of the rear ones
    obj, ostats = ct.car_obj(bank, "CZ_CADI")
    assert sum(v["tris"] for v in ostats.values()) == stats["tris"]
    # the TAXI sign sits inside the body's bounding box (on the roof), in one car space
    body = ct.read_shape(bank[parts["shp"][0]:parts["shp"][0] + parts["shp"][1]], "body")
    sign = ct.read_shape(bank[parts["taxiON"][0]:parts["taxiON"][0] + parts["taxiON"][1]], "sign")
    bys = [p[1] for p in body.positions()]
    sys_ = [p[1] for p in sign.positions()]
    assert min(sys_) > (min(bys) + max(bys)) / 2 and max(sys_) <= max(bys) + 1e-3
    # posed wheels reach the ground and stay inside the body's height
    for w, hub in hubs.items():
        wheel = ct.read_shape(bank[parts[w][0]:parts[w][0] + parts[w][1]], w)
        wys = [p[1] + hub[1] for p in wheel.positions()]
        assert min(wys) >= -0.1 and max(wys) < max(bys)


# --- request #1369: registered reader for the session observer, exact build, skeleton/animation findings ---

def test_roster_collects_only_posed_cabs_and_no_bone_local_drivers():
    roster = ct.roster()
    assert {e["kind"] for e in roster} == {"vehicle"}
    assert [e["slug"] for e in roster if e.get("collect")] == ["crazy_taxi_yellow"]
    assert all(e["collect"] is (e["key"] in ct.WHEEL_POSE) for e in roster)


def _f(v: float) -> int:
    return struct.unpack(">I", struct.pack(">f", v))[0]


def _motion(frames: int, groups) -> bytes:
    """A motDC.bin motion: u32 frames + 17 group word offsets, then 3 channel tracks per group of
    u32 count + count x (u32 frame, value word, tangent-in word, tangent-out word)."""
    body, offs = b"", []
    for g in groups:
        offs.append(18 + len(body) // 4)
        for keys in g:
            body += struct.pack(">I", len(keys)) + b"".join(struct.pack(">4I", f, w, 0, 0) for f, w in keys)
    return struct.pack(">18I", frames, *offs) + body


def test_motion_bank_channel_groups_on_synthetic_bank():
    groups = []
    for g in range(1, 18):
        if g in ct.POSITION_GROUPS:
            groups.append([[(0, _f(-4.4)), (12, _f(-5.38))], [(0, _f(9.8))], [(0, _f(2.62)), (30, _f(0.0))]])
        else:
            groups.append([[(0, 0)], [(0, (-0xC000) & 0xFFFFFFFF), (30, 0x4000)], []])
    m0 = _motion(30, groups)                     # last key may sit on the frame count (looping motions)
    bad = struct.pack(">18I", 30, 18, *range(19, 35)) + struct.pack(">I", 2) + struct.pack(">4I", 5, 0, 0, 0) * 2
    got = ct.motion_bank(m0 + m0 + bad)
    assert len(got["motions"]) == 2 and got["end"] == 2 * len(m0)
    a = got["motions"][0]
    assert a.frames == 30 and a.size == len(m0) and got["motions"][1].offset == len(m0)
    assert max(abs(v - w) for v, w in zip(a.at_frame0(1), (-4.4, 9.8, 2.62))) < 1e-6
    assert a.at_frame0(2) == (0.0, -270.0, 0.0) and a.groups[1][1][1][1] == 90.0
    worse = list(groups)
    worse[1] = [[(0, _f(1.5))], [(0, 0)], []]    # a float word in an angle group breaks the layout
    assert ct.parse_motion(_motion(30, worse)) is None
    assert ct.motion_bank(m0[:-4])["motions"] == []


def test_dol_shape_names_reads_the_rig_order_list():
    names = [b"MP_YH_plyrA_koshi.shp", b"MP_YH_plyrA_momo_r.shp", b"MP_YH_Man_koshi.shp", b"not a shape"]
    data = b""
    for n in names:
        data += n + b"\0" * (4 - len(n) % 4)
    va = 0x80003100
    dol = bytearray(0x100)
    struct.pack_into(">I", dol, 0x1C, 0x100)            # data section 0: file offset, address, size
    struct.pack_into(">I", dol, 0x64, va)
    struct.pack_into(">I", dol, 0xAC, len(data))
    dol = bytes(dol) + data
    assert ct.dol_va_to_offset(dol, va + 4) == 0x104 and ct.dol_va_to_offset(dol, va - 4) is None
    assert ct.dol_shape_names(dol, va) == ["MP_YH_plyrA_koshi", "MP_YH_plyrA_momo_r", "MP_YH_Man_koshi"]
    assert ct.driver_bones_from_dol(dol[:0x100] + data, "A") == ()     # default VA is not in this fixture
    assert set(ct.PARTS) <= set(ct.DRIVER_BONES) and ct.DRIVER_BONES[0] == "koshi"


def test_collect_includes_opted_in_vehicle_without_rig(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from gbox import characters as C
    game = {"game_id": "fixture", "title": "Fixture", "platform": "test"}
    entries = [{"slug": "cab", "name": "cab", "aliases": [], "kind": "vehicle", "collect": True},
               {"slug": "unposed", "name": "unposed", "aliases": [], "kind": "vehicle", "collect": False}]
    monkeypatch.setattr(C, "DEDICATED", [("fixture", lambda t, p: True, lambda: entries, None)])
    monkeypatch.setattr(C, "_game", lambda ctx, inp: game)
    monkeypatch.setattr(C, "library_root", lambda cfg: tmp_path)
    called = []
    monkeypatch.setattr(C, "extract_dedicated", lambda ctx, g, slug, root, prep: called.append(slug) or
                        {"status": "extracted", "entry": {"slug": slug}})
    monkeypatch.setattr(C, "get", lambda root, slug: {"slug": slug, "name": slug, "rig": {}})
    monkeypatch.setattr(C, "verify_entry", lambda root, meta: {"ok": True})
    res = C.collect(SimpleNamespace(config=None, progress=lambda *a: None), C.CharIn(op="collect"))
    assert called == ["cab"] and res["status"] == "complete" and res["characters"] == 0
    assert res["entries"][0]["kind"] == "vehicle" and res["entries"][0]["retargetable"] is False


@pytest.mark.skipif(not ISO.exists(), reason="owned Crazy Taxi GC disc not present")
def test_owned_disc_build_identity_bone_local_drivers_and_motion_bank():
    """#1369: exact build, why the drivers are not collected yet, and the motDC.bin key-track layout."""
    from gbox.gcdisc import GCDisc
    disc = GCDisc(ISO)
    head = ISO.open("rb").read(0x40)
    assert head[:6] == b"GCTE51" and head[6] == 0 and head[7] == 0 and head[0x20:0x2a] == b"Crazy Taxi"
    assert hashlib.sha256(disc.dol()).hexdigest() == ct.DOL_SHA256
    bank = disc.read(ct.BANK)
    assert hashlib.sha256(bank).hexdigest() == ct.BANK_SHA256
    for letter in ct.DRIVERS:
        ext = ct.driver_part_extents(bank, letter)
        assert set(ext) == set(ct.PARTS)
        for p, (lo, hi) in ext.items():                  # every part sits at its own joint origin
            assert all(abs(lo[a] + hi[a]) / 2 < 3.0 for a in range(3)), (letter, p, lo, hi)
        for foot in ("kakato_l", "kakato_r"):            # head and feet overlap: unassembled bone-local parts
            (alo, ahi), (flo, fhi) = ext["atama"], ext[foot]
            assert all(alo[a] < fhi[a] and flo[a] < ahi[a] for a in range(3)), (letter, foot)
    mot = disc.read(ct.MOTION)
    assert hashlib.sha256(mot).hexdigest() == ct.MOTION_SHA256
    got = ct.motion_bank(mot)
    ms = got["motions"]
    assert len(ms) == 278 and got["end"] == 1525560 and ms[1].offset == 7556   # sequential walk; see findings
    m0 = ms[0]
    assert m0.frames == 91 and [len(c) for c in m0.groups[0]] == [10, 10, 10]
    assert [k[0] for k in m0.groups[0][0][:4]] == [0, 12, 21, 27]
    assert max(abs(v - w) for v, w in zip(m0.at_frame0(1), (-4.4, 9.8, 2.62))) < 1e-5
    assert m0.at_frame0(2) == (0.0, -270.0, 0.0)
    assert ms[6].offset == 0x8a18 and ms[6].frames == 61 and [k[0] for k in ms[6].groups[0][0]][-2:] == [75, 60]
    assert ct.driver_bones_from_dol(disc.dol()) == ct.DRIVER_BONES


@pytest.mark.skipif(not ISO.exists(), reason="owned Crazy Taxi GC disc not present")
def test_owned_disc_collect_registers_the_posed_yellow_cab(monkeypatch, tmp_path):
    """#1369: the registered reader's background collection yields a verified native model (the yellow cab)."""
    from types import SimpleNamespace
    from gbox import characters as C
    game = {"game_id": "bc02bb68790ce2e7", "title": "Crazy Taxi (USA)", "platform": "gamecube"}
    assert any(r[0] == "crazy_taxi" and r[1](game["title"].lower(), "gamecube") for r in C.DEDICATED)
    monkeypatch.setattr(C, "_game", lambda ctx, inp: game)
    monkeypatch.setattr(C, "library_root", lambda cfg: tmp_path / "lib")
    monkeypatch.setattr(C, "_gc_iso", lambda ctx, g: ISO)
    ctx = SimpleNamespace(config=SimpleNamespace(cache=str(tmp_path / "cache")), progress=lambda *a: None)
    res = C.collect(ctx, C.CharIn(op="collect"))
    assert res["status"] == "complete" and res["total"] == res["collected"] == 1 and res["characters"] == 0
    (entry,) = res["entries"]
    assert entry["slug"] == "crazy_taxi_yellow" and entry["kind"] == "vehicle" and entry["verified"]
    meta = C.get(tmp_path / "lib", "crazy_taxi_yellow")
    stats = C.model_stats(tmp_path / "lib" / "crazy_taxi_yellow" / meta["model"])
    assert stats["triangles"] > 2000 and meta.get("kind", "vehicle") == "vehicle"
