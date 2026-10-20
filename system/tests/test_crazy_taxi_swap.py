"""gbox.crazy_taxi_swap: a collection character as a Crazy Taxi (GC) driver / pedestrians / fares in ct/polDC0.all.

Synthetic: hand-assembled .shp parts (two materials, POS/NRM/TEX0) in a hand-assembled bank, synthetic donor segments.
Owned disc: the GCTE51 ISO (GBOX_CT_ISO, else the Spark's modbase copy) and HUcast from the library; skipped without.
"""
import hashlib
import json
import math
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from gbox import crazy_taxi as ct
from gbox import crazy_taxi_swap as cs

ISO = Path(os.environ.get("GBOX_CT_ISO", "/home/ehm_eckx/gBox_alt/gbox-cache/modbase/bc02bb68790ce2e7/Crazy Taxi (USA).iso"))
BANK_FILE = os.environ.get("GBOX_CT_BANK", "")          # or a loose copy of the disc's ct/polDC0.all
LIB = Path(os.environ.get("GBOX_CHARACTERS", "/home/ehm_eckx/gBox_alt/gbox-cache/characters"))
GID = "bc02bb68790ce2e7"


def _exists(p) -> bool:
    try:
        return bool(p) and Path(p).is_file()
    except OSError:                                      # an unreachable share is "not present"
        return False


OWNED = _exists(BANK_FILE) or _exists(ISO)

BOX = [(x, y, z) for x in (0.0, 4.0) for y in (-1.0, 1.0) for z in (-1.0, 1.0)]       # bone-local: starts at the joint
QUADS = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
TRIS = [t for a, b, c, d in QUADS for t in ((a, b, c), (a, c, d))]


def _part(verts=BOX, tris=TRIS, centre=(2.0, 0.0, 0.0), cap=40, dl_room=0x400) -> bytes:
    """A driver-style .shp: header centre/scale (frac 8), POS + NRM s16 arrays and one TEX0 entry at 0x120, a material
    block of two 0x24-byte records (DL pointer pairs), two GX display lists (0x90 triangles; pos/nrm/tex u16 indices),
    white.tex. Vertices are given centre-included, as gbox.crazy_taxi decodes them."""
    local = np.asarray(verts, float) - centre
    radius = float(np.linalg.norm(local, axis=1).max())
    scale = radius * 256 / 32767
    first, mat = 0x120, 0x120 + ((12 * cap + 4 + 0x1F) & ~0x1F)
    dl_base = mat + 0x60
    tex_off = dl_base + dl_room
    b = bytearray(tex_off + 0x40)
    struct.pack_into(">ff", b, 0, 1.0, radius)
    struct.pack_into(">3f", b, 0x20, *centre)
    struct.pack_into(">3f", b, 0x2C, scale, scale, scale)
    struct.pack_into(">6I", b, 0x60, 0, 6, 6, 0, 0, 4)
    V = len(verts)
    pos_off, nrm_off, tex0 = first, first + 6 * V, first + 12 * V
    struct.pack_into(">I", b, 0xCC, pos_off)
    struct.pack_into(">I", b, 0xD0, nrm_off)
    struct.pack_into(">I", b, 0xDC, tex0)
    struct.pack_into(">4I", b, 0x110, mat, first, dl_base, tex_off)
    for i, p in enumerate(local):
        struct.pack_into(">3h", b, pos_off + 6 * i, *(int(round(c * 256 / scale)) for c in p))
        n = p / max(np.linalg.norm(p), 1e-9)
        struct.pack_into(">3h", b, nrm_off + 6 * i, *(int(round(c * 16384)) for c in n))
    struct.pack_into(">I", b, mat, 0x0C)                               # a game-side table index, like the disc's
    cur = dl_base
    half = len(tris) // 2
    for k, chunk in enumerate((tris[:half], tris[half:])):
        dl = bytearray(b"\x90" + struct.pack(">H", 3 * len(chunk)))
        for t in chunk:
            for i in t:
                dl += struct.pack(">3H", i, i, 0)
        dl += b"\0" * ((0x20 - len(dl) % 0x20) % 0x20)
        b[cur:cur + len(dl)] = dl
        struct.pack_into(">II", b, mat + 0x10 + 0x24 * k, cur, len(dl))
        cur += len(dl)
    b[tex_off:tex_off + 9] = b"white.tex"
    return bytes(b)


def _sphere(r=1.0, c=(0.0, 0.0, 0.0), n=8):
    """A UV sphere donor segment (pos, nrm, tris), dense enough to need clustering."""
    pos = [(0.0, r, 0.0)]
    for i in range(1, n):
        th = math.pi * i / n
        for j in range(2 * n):
            ph = 2 * math.pi * j / (2 * n)
            pos.append((r * math.sin(th) * math.cos(ph), r * math.cos(th), r * math.sin(th) * math.sin(ph)))
    pos.append((0.0, -r, 0.0))
    ring = lambda i, j: 1 + (i - 1) * 2 * n + j % (2 * n)
    tris = [(0, ring(1, j + 1), ring(1, j)) for j in range(2 * n)]
    for i in range(1, n - 1):
        for j in range(2 * n):
            tris += [(ring(i, j), ring(i, j + 1), ring(i + 1, j + 1)), (ring(i, j), ring(i + 1, j + 1), ring(i + 1, j))]
    last = len(pos) - 1
    tris += [(last, ring(n - 1, j), ring(n - 1, j + 1)) for j in range(2 * n)]
    P = np.asarray(pos) + c
    return P, (P - c) / r, tris


def _segs():
    return {p: _sphere(0.5 + 0.05 * i, (i * 3.0, 10.0, 0.0)) for i, p in enumerate(ct.PARTS)}


def _bank():
    part, small = _part(), _part(cap=8, dl_room=0x100)
    blobs = [("CZ_CADI.shp", b"\x11" * 0x20), ("MP_YH_plyrA_atama.shp", part), ("MP_YH_plyrA_atamaB.shp", part),
             ("MP_YH_plyrA_sl_atama.shp", small), ("MP_YH_plyrA_te_l_gu.shp", part), ("MP_YH_plyrB_atama.shp", part),
             ("MP_YH_pplMC_mune.shp", part), ("MP_YH_psgAA_koshi.shp", part), ("MP_YH_psgAO.shp", b"\x22" * 0x20)]
    return ct.write_bank(blobs), blobs


# ------------------------------------------------------------------------------------------- names and slots

def test_classify_part_names():
    assert cs.classify("MP_YH_plyrB_sl_atamaB.shp") == {"group": "plyrB", "part": "atama", "lod": True,
                                                         "accessory": True, "pose": ""}
    assert cs.classify("MP_YH_plyrA_te_r_ok.shp")["part"] == "te_r"
    assert cs.classify("MP_YH_plyrA_te_r_ok.shp")["pose"] == "ok"
    assert cs.classify("MP_YH_plyrA_kata_rB.shp")["accessory"] is True
    assert cs.classify("MP_YH_Man_momo_l.shp")["group"] == "Man"
    assert cs.classify("MP_YH_psgAO.shp") is None and cs.classify("CZ_CADI.shp") is None


def test_parse_slot_player_drivers_and_people():
    assert cs.parse_slot("player").slot == "driver:axel" and cs.parse_slot("player").suffix == ""
    assert cs.parse_slot("player", "gus").groups == ("plyrD",)
    for text in ("driver:bd_joe", "driver:B.D. Joe", "driver:joe", "driver:plyrB", "DRIVER:b"):
        s = cs.parse_slot(text)
        assert (s.slot, s.groups, s.suffix, s.label) == ("driver:bd_joe", ("plyrB",), "_bd_joe", "B.D. Joe")
    assert cs.parse_slot("drivers").groups == ("plyrA", "plyrB", "plyrC", "plyrD")
    assert cs.parse_slot("pedestrian:MC").groups == ("pplMC",) and cs.parse_slot("ped:pplmc").slot == "pedestrian:pplMC"
    assert cs.parse_slot("fare:AA").slot == "passenger:psgAA"
    assert len(cs.parse_slot("passengers").groups) == sum(1 for v in cs.PEOPLE.values() if v[0] == "passenger")
    assert "Man" in cs.parse_slot("pedestrians").groups
    for bad in ("driver:sonic", "pedestrian:zz", "enemy:booma"):
        with pytest.raises(ValueError):
            cs.parse_slot(bad)
    assert cs.is_slot("player") and cs.is_slot("driver:gena") and cs.is_slot("passengers")
    assert not cs.is_slot("enemy:booma") and not cs.is_slot("The Rock")
    assert cs.mod_name("hucast", cs.parse_slot("player")) == "ct_hucast"
    assert cs.mod_name("hucast", cs.parse_slot("driver:gena")) == "ct_hucast_gena"


def test_player_slot_follows_the_last_driver_target():
    meta = {"targets": {GID: [{"slot": "driver:gena"}, {"slot": "pedestrians"}, {"slot": "driver:gus"}]}}
    assert cs.default_driver(meta, GID) == "gus"
    assert cs.default_driver({"targets": {GID: [{"slot": "player"}]}}, GID) == "axel"
    assert cs.default_driver({}, GID) == "axel"


def test_roster_and_cast_slots_list_the_drivers_without_collecting():
    ros = cs.roster()
    keys = [r["key"] for r in ros]
    assert keys[:5] == ["driver:axel", "driver:bd_joe", "driver:gena", "driver:gus", "drivers"]
    assert {"pedestrians", "passengers", "pedestrian:pplMC", "passenger:psgAA"} <= set(keys)
    assert all(r["kind"] == "slot" and r["collect"] is False for r in ros)
    assert next(r for r in ros if r["key"] == "driver:bd_joe")["blobs"] == 54
    cast = cs.cast_slots()
    assert cast[0]["slot"] == "player" and {"driver:gena", "drivers"} <= {c["slot"] for c in cast}
    assert len({c["slot"] for c in cast}) == len(cast)
    bank, _ = _bank()
    live = {r["key"] for r in cs.roster(bank)}
    assert {"driver:axel", "driver:bd_joe", "pedestrian:pplMC", "passenger:psgAA"} <= live


def test_writer_is_registered_and_routed():
    from gbox import char_coverage as CC
    game = {"game_id": GID, "title": "Crazy Taxi (USA)", "platform": "gamecube"}
    w = CC.writer_for(game)
    assert w["writer"] == "gbox.crazy_taxi_swap" and w["routed"] is True
    assert "driver:<axel|bd_joe|gena|gus>" in w["slots"] and "player" in w["slots"]
    slots = CC.cast_slots(game)
    assert slots[0]["slot"] == "player" and any(s["slot"] == "driver:gus" for s in slots)
    assert len({s["slot"] for s in slots}) == len(slots)


# ------------------------------------------------------------------------------------------- fitting

def test_synthetic_part_decodes_like_the_disc():
    s = ct.read_shape(_part(), "MP_YH_plyrA_atama.shp")
    assert s.frac() == 8 and len(s.tris) == 12 and len(s.lists) == 2 and s.textures == ["white.tex"]
    pts = np.asarray(s.positions())
    assert np.allclose(pts, BOX, atol=1e-3)


def test_deal_materials_by_region_keeps_every_material_drawn():
    pos = np.asarray([(0, 0, 0), (1, 0, 0), (0, 1, 0), (10, 0, 0), (11, 0, 0), (10, 1, 0)], float)
    tris = [(0, 1, 2), (3, 4, 5)]
    assert cs.deal_materials(pos, tris, [np.array([10.0, 0, 0]), np.array([0.0, 0, 0])]) == [[(3, 4, 5)], [(0, 1, 2)]]
    got = cs.deal_materials(pos, tris, [np.array([0.0, 0, 0]), np.array([-50.0, 0, 0])])
    assert all(got) and sorted(t for c in got for t in c) == tris                       # the far material still draws
    assert cs.deal_materials(pos, tris, [np.zeros(3)]) == [tris]


def test_fit_blob_round_trip_keeps_size_header_and_frame():
    tpl = _part()
    seg = _sphere(0.7, (5.0, -3.0, 2.0), n=10)
    blob, st = cs.fit_blob(tpl, seg, "MP_YH_plyrA_atama.shp")
    assert len(blob) == len(tpl) and st["size"] == len(tpl) and st["tris"] > 0 and st["verts"] >= 3
    assert blob[:0xC8] == tpl[:0xC8]                                    # radius, centre, scale, format words
    assert blob[-0x40:] == tpl[-0x40:] and struct.unpack_from(">I", blob, 0x110) == struct.unpack_from(">I", tpl, 0x110)
    a, stock = ct.read_shape(blob, "new"), ct.read_shape(tpl, "stock")
    assert len(a.lists) == 2 and all(size > 0 for _, size in a.lists)
    assert len(a.tris) == st["tris"]
    pts = np.asarray(a.positions(stock.frac()))
    lo, hi = np.asarray(BOX).min(0), np.asarray(BOX).max(0)
    assert (pts.min(0) > lo - 0.5).all() and (pts.max(0) < hi + 0.5).all()           # fitted onto the part's cloud
    assert np.ptp(pts, 0).max() > 2.0                                                  # not collapsed
    local = pts - np.asarray(stock.centre)
    assert (np.abs(local).max(0) <= cs.representable(tpl, stock.frac()) + 1e-6).all()
    again, _ = cs.fit_blob(tpl, seg, "MP_YH_plyrA_atama.shp")
    assert again == blob                                                               # deterministic


def test_fit_blob_clusters_a_dense_donor_into_a_small_part():
    tpl = _part(cap=8, dl_room=0x80)
    blob, st = cs.fit_blob(tpl, _sphere(1.0, n=12), "MP_YH_plyrA_sl_atama.shp")
    vmax, _dl = ct.part_budgets(tpl, ["pos", "nrm", "tex"])
    assert vmax == 10 and len(blob) == len(tpl) and st["verts"] <= vmax and st["donor_tris"] > 200
    assert len(ct.read_shape(blob).tris) == st["tris"] > 0


def test_hidden_blob_draws_nothing_but_keeps_every_display_list():
    tpl = _part()
    blob = cs.hidden_blob(tpl, "MP_YH_plyrA_atamaB.shp")
    s = ct.read_shape(blob)
    assert len(blob) == len(tpl) and len(s.lists) == 2 and len(s.tris) == 2
    pts = s.positions()
    for t in s.tris:
        corners = {pts[c["pos"]] for c in t}
        assert len(corners) == 1                                                       # zero-area


def test_swap_people_replaces_only_the_slot_groups():
    bank, blobs = _bank()
    new, stats = cs.swap_people(bank, _segs(), ("plyrA",))
    old_e, new_e = ct.read_bank(bank), ct.read_bank(new)
    assert [(n, s) for n, _, s in new_e] == [(n, s) for n, _, s in old_e] and len(new) == len(bank)
    changed = {n for (n, o, s) in old_e if bank[o:o + s] != new[o:o + s]}
    assert changed == {"MP_YH_plyrA_atama.shp", "MP_YH_plyrA_atamaB.shp", "MP_YH_plyrA_sl_atama.shp",
                       "MP_YH_plyrA_te_l_gu.shp"}
    assert stats["MP_YH_plyrA_atamaB.shp"]["hidden"] is True
    assert stats["MP_YH_plyrA_te_l_gu.shp"]["part"] == "te_l" and stats["MP_YH_plyrA_te_l_gu.shp"]["pose"] == "gu"
    assert stats["MP_YH_plyrA_sl_atama.shp"]["lod"] is True
    for n, o, s in new_e:
        if n.endswith(".shp") and n.startswith("MP_YH_") and n != "MP_YH_psgAO.shp":
            ct.read_shape(new[o:o + s], n)                                             # every part still decodes
    with pytest.raises(ValueError):
        cs.swap_people(bank, _segs(), ("plyrC",))
    both, st2 = cs.swap_people(bank, _segs(), ("pplMC", "psgAA"))
    assert {v["group"] for v in st2.values()} == {"pplMC", "psgAA"}
    gone = dict(_segs())
    del gone["atama"]
    with pytest.raises(ValueError, match="atama"):
        cs.swap_people(bank, gone, ("plyrA",))


def test_use_builds_the_slot_mod_and_records_the_target(monkeypatch, tmp_path):
    from gbox import characters as C
    from gbox import filemods
    import gbox.gcdisc as gcdisc
    bank, _ = _bank()
    calls = {}

    class Disc:
        game_id = ct.DISC_ID

        def __init__(self, path):
            self.f = SimpleNamespace(close=lambda: None)

        def read(self, name):
            assert name == ct.BANK
            return bank

    def fake_build(cfg, game, iso, new_bank, name, image_name, progress=None):
        calls["bank"] = new_bank
        d = tmp_path / "mods" / name
        d.mkdir(parents=True)
        (d / ".gbox-mod.json").write_text(json.dumps({"name": name, "game_id": game["game_id"], "files": [ct.BANK]}))
        return {"mod": name, "dir": str(d), "image": str(d / image_name), "files": [ct.BANK]}

    monkeypatch.setattr(gcdisc, "GCDisc", Disc)
    monkeypatch.setattr(ct, "build_mod", fake_build)
    monkeypatch.setattr(cs, "donor_segments", lambda glb, roles: _segs())
    monkeypatch.setattr(C, "library_root", lambda cfg: tmp_path)
    monkeypatch.setattr(C, "_local_or_fetch", lambda ctx, meta, rel: tmp_path / rel)
    monkeypatch.setattr(C, "_gc_iso", lambda ctx, game: tmp_path / "ct.iso")
    monkeypatch.setattr(filemods, "list_mods", lambda cfg, gid: [])
    monkeypatch.setattr(C, "_api", lambda ctx, method, path, **kw: calls.setdefault("api", []).append((method, path, kw)))
    roles = {r: f"j_{r}" for names in ct.CT_ROLE.values() for r in names[:1]}
    meta = {"slug": "donor", "name": "Donor", "model": "donor.glb", "rig": {"roles": roles},
            "targets": {GID: [{"slot": "driver:bd_joe"}]}}
    ctx = SimpleNamespace(config=SimpleNamespace(cache=str(tmp_path)), progress=lambda *a: None)
    game = {"game_id": GID, "title": "Crazy Taxi (USA)", "platform": "gamecube"}
    inp = C.CharIn(op="use", character="donor", game_id=GID, slot="driver:axel", launch=False)
    r = cs.use(ctx, meta, game, inp)
    assert r["status"] == "built" and r["mod"] == "ct_donor" and r["slot"] == "driver:axel"
    assert r["build"]["report"]["blobs"] == 4 and r["build"]["report"]["hidden"] == 1
    marker = json.loads((tmp_path / "mods" / "ct_donor" / ".gbox-mod.json").read_text())
    assert marker["slot"] == "driver:axel" and marker["character"] == "donor" and "parts" not in marker["report"]
    (method, path, kw), = calls["api"]
    assert path == "/api/characters/donor/targets" and kw["json"]["slot"] == "driver:axel"
    assert kw["json"]["mod"] == "ct_donor"
    # slot=player follows the last driver target (B.D. Joe here); a missing body role fails before any disc work
    r2 = cs.use(ctx, meta, game, C.CharIn(op="use", character="donor", game_id=GID, slot="player", launch=False))
    assert (r2["mod"], r2["slot"], r2["build"]["report"]["blobs"]) == ("ct_donor_bd_joe", "driver:bd_joe", 1)
    new_e = ct.read_bank(calls["bank"])
    assert [n for (n, o, s), (_, oo, _s) in zip(ct.read_bank(bank), new_e)
            if bank[o:o + s] != calls["bank"][oo:oo + s]] == ["MP_YH_plyrB_atama.shp"]
    with pytest.raises(ValueError, match="role"):
        cs.use(ctx, dict(meta, rig={"roles": {"hip": "a"}}), game,
               C.CharIn(op="use", character="donor", game_id=GID, slot="driver:axel", launch=False, rebuild=True))


def test_characters_tool_routes_crazy_taxi_slots_to_the_writer():
    import inspect
    from gbox import characters as C
    src = inspect.getsource(C.characters_tool)
    assert "crazy_taxi_swap.is_slot(inp.slot)" in src and "crazy_taxi_swap.use(" in src


# ------------------------------------------------------------------------------------------- owned disc

def _owned_bank() -> bytes:
    if _exists(BANK_FILE):
        bank = Path(BANK_FILE).read_bytes()
    else:
        from gbox.gcdisc import GCDisc
        disc = GCDisc(ISO)
        assert disc.game_id == ct.DISC_ID
        bank = disc.read(ct.BANK)
        disc.f.close()
    assert hashlib.sha256(bank).hexdigest() == ct.BANK_SHA256
    return bank


@pytest.mark.skipif(not OWNED, reason="owned Crazy Taxi GC disc not present")
def test_owned_disc_people_match_the_snapshot():
    bank = _owned_bank()
    live = cs.people(ct.read_bank(bank))
    assert {g: (d["kind"], d["blobs"], d["missing"]) for g, d in live.items()} == \
        {g: tuple(v) for g, v in cs.PEOPLE.items()}


@pytest.mark.skipif(not OWNED, reason="owned Crazy Taxi GC disc not present")
def test_owned_disc_every_driver_takes_a_synthetic_donor():
    bank = _owned_bank()
    old = ct.read_bank(bank)
    segs = _segs()
    for slug, (letter, _name, _a) in cs.DRIVERS.items():
        group = f"plyr{letter}"
        new, stats = cs.swap_people(bank, segs, (group,))
        new_e = ct.read_bank(new)
        assert [(n, s) for n, _, s in new_e] == [(n, s) for n, _, s in old]
        changed = [n for (n, o, s) in old if bank[o:o + s] != new[o:o + s]]
        assert changed and all(cs.classify(n)["group"] == group for n in changed), slug
        assert len(stats) == cs.PEOPLE[group][1]
        hidden = [n for n, v in stats.items() if v.get("hidden")]
        assert hidden and all(cs.classify(n)["accessory"] for n in hidden)
        for n, o, s in new_e:
            if n in stats:
                assert len(ct.read_shape(new[o:o + s], n).tris) >= 1


@pytest.mark.skipif(not (OWNED and _exists(LIB / "hucast" / "meta.json")),
                    reason="owned Crazy Taxi GC disc or the HUcast library entry not present")
def test_owned_disc_hucast_as_gena(tmp_path):
    bank = _owned_bank()
    meta = json.loads((LIB / "hucast" / "meta.json").read_text())
    new, report = cs.swap_bank(bank, LIB / "hucast" / meta["model"], meta["rig"]["roles"], cs.parse_slot("driver:gena"))
    assert report["slot"] == "driver:gena" and report["blobs"] == 50 and report["fitted"] + report["hidden"] == 50
    assert report["triangles"] > 800 and report["source_bank"] == ct.BANK_SHA256[:16]
    assert len(new) == len(bank)
    old_e = ct.read_bank(bank)
    for n, o, s in old_e:
        c = cs.classify(n)
        if c and c["group"] == "plyrC" and not c["accessory"]:
            got = np.asarray(ct.read_shape(new[o:o + s], n).positions(ct.read_shape(bank[o:o + s]).frac()))
            ref = np.asarray(ct.read_shape(bank[o:o + s], n).positions())
            ext = np.ptp(ref, 0).max()
            assert np.abs(got.mean(0) - ref.mean(0)).max() < 0.35 * ext, n            # lands on its own bone
