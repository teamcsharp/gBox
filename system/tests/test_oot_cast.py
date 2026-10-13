"""OoT whole cast (gbox.oot_cast + gbox.oot_swap.build_cast) on a synthetic retail-layout ROM: the catalogue, limb-tree
roles, the reclaimable bytes (lists, vertices, textures), the per-room object-space plan, one rebuilt ROM with grown
objects relocated (DMA table, gObjectTable, CRC), refusals with reasons, and the cast swap's planning / builder for
OoT. Owned-ROM checks at the end skip unless the operator's ROM is cached."""
import json
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from gbox import cast_swap as CS, characters as C, oot_cast as OC, oot_swap as SW, oot_writer as OW

OOT = {"game_id": "446e8e442d726e31", "title": "Legend of Zelda, The: Ocarina of Time (USA)", "platform": "n64"}
DMA = 0x7430                                              # ntsc-1.0 dmadata
SA, DEKU, TA, FIELD_KEEP = 0xBC, 0x4A, 0x88, 0x02

# a 15-limb humanoid in the usual OoT NPC layout: root -> 2 legs + torso -> 2 arms + head
LIMBS = [((0, 0, 0), 1, 0xFF), ((60, 0, 0), 2, 4), ((0, -200, 0), 3, 0xFF), ((0, -180, 0), 0xFF, 0xFF),
         ((-60, 0, 0), 5, 7), ((0, -200, 0), 6, 0xFF), ((0, -180, 0), 0xFF, 0xFF),
         ((0, 50, 0), 8, 0xFF), ((100, 250, 0), 9, 11), ((120, 0, 0), 10, 0xFF), ((100, 0, 0), 0xFF, 0xFF),
         ((-100, 250, 0), 12, 14), ((-120, 0, 0), 13, 0xFF), ((-100, 0, 0), 0xFF, 0xFF), ((0, 300, 0), 0xFF, 0xFF)]


def _vtx(x, y, z, n=(0, 127, 0)):
    return struct.pack(">hhhHhh4B", x, y, z, 0, 0, 0, n[0] & 255, n[1] & 255, n[2] & 255, 255)


def _box_dl(base_vtx: int, tex: int | None = None) -> bytes:
    cmds = [(0xE7000000, 0), (0xFC127E24, 0xFFFFF9FC)]
    if tex is not None:                                   # a 16x16 RGBA16 texture loaded with LoadBlock
        cmds += [(0xD7000002, 0xFFFFFFFF), (0xFD100000, tex), (0xF5100000, 0x07000000), (0xE6000000, 0),
                 (0xF3000000, 0x070FF100), (0xF5101000, 0), (0xF2000000, 0x0003C03C)]
    cmds += [(0x01000000 | (8 << 12) | (8 << 1), base_vtx), (0x06000204, 0x00060406), (0x0608060A, 0x000A0C0E),
             (0xDF000000, 0)]
    return b"".join(struct.pack(">II", *c) for c in cmds)


def humanoid_object(skel_at: int, size: int, flex: bool = True, textured: bool = False) -> bytes:
    """An object with LIMBS as a (Flex)Skeleton at skel_at, one box list per limb but the root, an AnimationHeader
    (one frame, every rotation 0) and, if textured, one texture the lists load."""
    d = bytearray(0x40)
    tex = None
    if textured:
        tex = len(d)
        d += bytes(range(256)) * 2                       # 512 bytes: 16x16 RGBA16
    dls = []
    for i, (pos, _c, _s) in enumerate(LIMBS):
        if i == 0:
            dls.append(0)
            continue
        nxt = next((LIMBS[j][0] for j in range(len(LIMBS)) if LIMBS[i][1] == j), (0, 60, 0))
        vat = len(d)
        w = 20
        for (x, y, z) in ((-w, 0, 0), (w, 0, 0), (nxt[0] + w, nxt[1], nxt[2]), (nxt[0] - w, nxt[1], nxt[2]),
                          (0, 0, -w), (0, 0, w), (nxt[0], nxt[1], nxt[2] + w), (nxt[0], nxt[1], nxt[2] - w)):
            d += _vtx(x, y, z)
        dl = len(d)
        d += _box_dl(0x06000000 | vat, None if tex is None else 0x06000000 | tex)
        dls.append(0x06000000 | dl)
    fd = len(d)
    d += bytes(8)                                         # frame data: zeros
    ji = len(d)
    d += bytes(6 * (len(LIMBS) + 1))                      # joint indices: all -> 0
    d += bytes((-len(d)) % 4)
    d += struct.pack(">hhIIH2x", 1, 0, 0x06000000 | fd, 0x06000000 | ji, 1)
    limb_at = []
    for i, (pos, ch, sb) in enumerate(LIMBS):
        limb_at.append(len(d))
        d += struct.pack(">hhhBBI", *pos, ch, sb, dls[i])
    table = len(d)
    for a in limb_at:
        d += struct.pack(">I", 0x06000000 | a)
    assert len(d) <= skel_at, "skeleton offset too low for the test object"
    d += bytes(skel_at - len(d))
    d += struct.pack(">IB3x", 0x06000000 | table, len(LIMBS))
    if flex:
        d += struct.pack(">B3x", len(LIMBS) - 1)
    d += bytes(max(0, size - len(d)))
    return bytes(d)


def synthetic_rom(objects: dict[int, bytes], keep_size: int = 0xD0000, kf_objects=(SA, DEKU)) -> bytes:
    """A big-endian ROM in the NTSC 1.0 layout gbox.oot_writer reads: dmadata at 0x7430, `code` (index 27) holding
    gObjectTable and gSceneTable, gameplay_keep at index 498, the given objects, and 101 scenes of which Kokiri Forest
    (0x55) has one room loading kf_objects."""
    files: list[bytes] = [b""] * 3
    for i in range(3, 498):
        files.append(b"F" * 16)
    files.append(bytes(keep_size))                        # 498 gameplay_keep
    ids = {1: 498}
    for oid, data in sorted({FIELD_KEEP: bytes(0x100), 0x14: bytes(0x2000), 0x15: bytes(0x2000), **objects}.items()):
        ids[oid] = len(files)
        files.append(data)
    room = struct.pack(">BBHI", 0x0B, len(kf_objects), 0, 0x03000010) + struct.pack(">BBHI", 0x14, 0, 0, 0)
    room += struct.pack(f">{len(kf_objects)}h", *kf_objects)
    room_i = len(files)
    files.append(room)
    scenes = []
    for s in range(101):
        if s == 0x55:
            sc = struct.pack(">BBHI", 0x04, 1, 0, 0x02000018) + struct.pack(">BBHI", 0x07, 0, 0, FIELD_KEEP) + \
                struct.pack(">BBHI", 0x14, 0, 0, 0) + b"ROOMROOM"            # room list entry patched below
        else:
            sc = struct.pack(">BBHI", 0x14, 0, 0, 0) + struct.pack(">I", s)
        scenes.append(len(files))
        files.append(sc)
    files.append(b"")                                     # code placeholder index fix-up below
    order = list(range(len(files)))
    code_i = 27
    # VROM layout: every file stored uncompressed at vrom == rom
    vrom, at = [], 0x10000
    sizes = [len(f) if i not in (0, 1, 2, code_i) else 0 for i, f in enumerate(files)]
    code = bytearray(0x4000)
    sizes[code_i] = len(code)
    for i in order:
        if i == 0:
            vrom.append((0, 0x1060))
        elif i == 1:
            vrom.append((0x1060, DMA))
        elif i == 2:
            vrom.append((DMA, DMA + 16 * (len(files) + 1)))
        else:
            n = (max(sizes[i], 16) + 15) & ~15
            vrom.append((at, at + n))
            at += n
    room_v = vrom[room_i]
    kf = files[scenes[0x55]]
    files[scenes[0x55]] = kf[:0x18] + struct.pack(">II", *room_v)
    obj_tbl = 0x100
    for oid, fi in ids.items():
        struct.pack_into(">II", code, obj_tbl + 8 * oid, *vrom[fi])
    scene_tbl = 0x1000
    for s, fi in enumerate(scenes):
        struct.pack_into(">II", code, scene_tbl + 0x14 * s, *vrom[fi])
    files[code_i] = bytes(code)
    rom = bytearray(max(at, 0x101000) + 0x10)
    rom[:4] = b"\x80\x37\x12\x40"
    rom[0x20:0x34] = b"THE LEGEND OF ZELDA "
    rom[0x3B:0x3F] = b"CZLE"
    for i, f in enumerate(files):
        if i in (0, 1, 2):
            continue
        rom[vrom[i][0]:vrom[i][0] + len(f)] = f
    for k, (vs, ve) in enumerate(vrom):
        struct.pack_into(">4I", rom, DMA + 16 * k, vs, ve, vs, 0)
    return bytes(rom)


@pytest.fixture(scope="module")
def rom_bytes():
    return synthetic_rom({SA: humanoid_object(0xB1A0, 0xB1B0, textured=True),
                          DEKU: humanoid_object(0x3268, 0x3278, flex=False),
                          TA: humanoid_object(0xB7B8, 0xB7C8)})


# ---------------------------------------------------------------- the catalogue

def test_catalogue_slots_are_unique_and_name_real_objects():
    slots = [c["slot"] for c in OC.CAST]
    assert len(slots) == len(set(slots)) and slots[0] == "player"
    assert {"saria", "mido", "kokiri_boy", "zelda_child", "impa", "malon_child", "talon", "ganondorf", "darunia",
            "goron", "zora", "ruto_child", "nabooru", "sheik", "koume", "kotake", "stalfos", "moblin_spear",
            "deku_scrub", "skulltula", "lizalfos", "iron_knuckle", "epona", "navi"} <= set(slots)
    for c in OC.CAST:
        if c["object"] != "gameplay_keep":
            assert OC.object_id(c["object"]) is not None, c["object"]
        assert all(OC.actor_id(a) is not None for a in c["actors"]), c["actors"]
        assert c.get("type") in ("flex", "normal", None) and c.get("limb_type") in ("standard", "lod", "skin", None)
    assert OC.object_id("object_md") == 0xFB                          # the real Mido object, not the empty duplicate


def test_cast_slots_report_refusals_with_reasons():
    rows = {r["slot"]: r for r in OC.cast_slots()}
    assert rows["epona"]["status"] == "not_working" and "skinned" in rows["epona"]["reason"]
    assert rows["navi"]["status"] == "not_working" and "gameplay_keep" in rows["navi"]["reason"]
    assert rows["saria"].get("status") is None and rows["player"]["kind"] == "player"
    assert SW.cast_slots() == OC.cast_slots()


def test_snapshot_matches_the_catalogue():
    snap = OC.load_snapshot()
    assert snap["rom"]["version"].startswith("ntsc")
    for c in OC.CAST:
        row = snap["slots"][c["slot"]]
        if c.get("refuse"):
            assert row["mapping"]["mode"] is None
            continue
        assert row["mapping"]["mode"] in ("retarget", "rigid"), (c["slot"], row["mapping"])
        if c["kind"] != "player":
            f = row["skeleton_facts"]
            assert f["offset"] == c["skel"] and f["type"] == c["type"], c["slot"]
            assert f["lod"] == (c["limb_type"] == "lod")
            if c["slot"] in OC.CREATURES:
                assert row["mapping"]["mode"] == "rigid"
    assert sum(r["mapping"]["mode"] == "retarget" for r in snap["slots"].values()) >= 60


# ---------------------------------------------------------------- skeletons -> roles

def _skel(obj, off):
    return OW.skeleton(obj, off)


def test_limb_tree_roles_find_arms_legs_and_head():
    obj = humanoid_object(0xB1A0, 0xB1B0)
    sk = _skel(obj, 0xB1A0)
    W = OW.pose(sk, None)
    roles = SW.topo_roles(sk, np.array([w[:3, 3] for w in W]))
    assert roles == {"chest": 7, "head": 14, "l_upper": 8, "l_fore": 9, "l_hand": 10, "r_upper": 11, "r_fore": 12,
                     "r_hand": 13, "l_thigh": 1, "l_shin": 2, "l_foot": 3, "r_thigh": 4, "r_shin": 5, "r_foot": 6,
                     "hip": 0}


def test_limb_tree_roles_without_legs_and_refusal():
    # robe NPC: root -> two arms + head (the Happy Mask Salesman / shooting gallery layout)
    limbs = [{"pos": (0, 0, 0), "child": 1, "sibling": 0xFF, "dls": [1]},
             {"pos": (50, 10, 0), "child": 2, "sibling": 4, "dls": [1]}, {"pos": (60, 0, 0), "child": 3, "sibling": 0xFF, "dls": [1]},
             {"pos": (60, 0, 0), "child": 0xFF, "sibling": 0xFF, "dls": [1]},
             {"pos": (-50, 10, 0), "child": 5, "sibling": 7, "dls": [1]}, {"pos": (-60, 0, 0), "child": 6, "sibling": 0xFF, "dls": [1]},
             {"pos": (-60, 0, 0), "child": 0xFF, "sibling": 0xFF, "dls": [1]},
             {"pos": (0, 80, 0), "child": 0xFF, "sibling": 0xFF, "dls": [1]}]
    sk = {"limbs": limbs, "count": 8}
    P = np.array([w[:3, 3] for w in OW.pose(sk, None)])
    r = SW.topo_roles(sk, P)
    assert r["hip"] == 0 and r["head"] == 7 and r["l_upper"] == 1 and r["r_upper"] == 4 and "l_thigh" not in r
    worm = {"limbs": [{"pos": (0, 10 * i, 0), "child": i + 1 if i < 4 else 0xFF, "sibling": 0xFF, "dls": [1]}
                      for i in range(5)], "count": 5}
    with pytest.raises(ValueError, match="not a humanoid"):
        SW.topo_roles(worm, np.array([w[:3, 3] for w in OW.pose(worm, None)]))


def test_skeleton_facts_tell_flex_from_normal():
    assert OC.skeleton_facts(humanoid_object(0x1000, 0x1010), 0x1000)["type"] == "flex"
    f = OC.skeleton_facts(humanoid_object(0x1000, 0x1010, flex=False), 0x1000)
    assert f["type"] == "normal" and f["limbs"] == 15 and f["limbs_with_dl"] == 14 and not f["lod"]


def test_texture_ranges_and_reclaim_include_the_body_texture():
    obj = humanoid_object(0x2000, 0x2010, textured=True)
    sk = _skel(obj, 0x2000)
    body = [lb["dls"][0] for lb in sk["limbs"] if lb["dls"][0]]
    assert OW._merge(OC.texture_ranges(obj, body)) == [[0x40, 0x240]]
    out = OC._subtract([(0, 100), (200, 300)], [(50, 250)])
    assert out == [(0, 50), (250, 300)]


# ---------------------------------------------------------------- the synthetic ROM

def test_synthetic_rom_reads_like_retail(rom_bytes):
    rom = OW.Rom(rom_bytes)
    assert rom.version == "ntsc-1.0" and rom.object(SA)[0xB1A4] == 15
    assert OC.scene_table(rom) == (0x1000, 101)
    kf = [c for c in OC.contexts(rom) if c["scene"] == 0x55]
    assert len(kf) == 1 and kf[0]["name"] == "Kokiri Forest" and kf[0]["age"] == "child"
    assert set(kf[0]["objects"]) == {SA, DEKU, OW.OBJECT_LINK_CHILD}
    used = 0xD0000 + 0x100 + 0x2000 + ((0xB1B0 + 15) & ~15) + ((0x3278 + 15) & ~15)
    assert kf[0]["free"] == OC.SPACE - used
    assert OC.where(rom, SA) == ["Kokiri Forest"]


def test_growth_plan_shares_a_full_room_and_frees_the_rest(rom_bytes):
    rom = OW.Rom(rom_bytes)
    room = OC.contexts(rom)[0]["free"] - OC.RESERVE
    plan = OC.growth_plan(rom, {SA: 0x9000, DEKU: 0x9000, TA: 0x9000, OW.OBJECT_LINK_CHILD: 0xA000})
    a = plan["allow"]
    assert a[TA] == 0x9000                                           # in no room of this ROM: its cap
    assert abs(a[SA] + a[DEKU] + a[OW.OBJECT_LINK_CHILD] - room) < 0x40 and a[SA] == a[DEKU]
    assert plan["tight"] and plan["tight"][0]["scene"] == "Kokiri Forest"
    assert OC.space_report(rom, {SA: room, DEKU: 0x10}) == [
        {"scene": "Kokiri Forest", "layer": 0, "room": 0, "over": 0x10 - OC.RESERVE, "cutscene": False}] or \
        OC.space_report(rom, {SA: room, DEKU: 0x10}) == []
    assert OC.space_report(rom, {SA: room + OC.RESERVE + 0x100})[0]["over"] == 0x100


def test_slot_spec_and_refusals(rom_bytes):
    rom = OW.Rom(rom_bytes)
    sp = OC.slot_spec(rom, "saria")
    assert sp["object"] == SA and sp["group"]["skel"] == (SA, 0xB1A0) and sp["facts"]["type"] == "flex"
    assert sp["reclaim"]["lists"] > 0 and sp["reclaim"]["textures"] == 0x200      # the box lists + the one texture
    with pytest.raises(ValueError, match="skinned"):
        OC.slot_spec(rom, "epona")
    with pytest.raises(ValueError, match="no skeleton at"):
        OC.slot_spec(rom, "mido")                                     # object_md isn't in this ROM's table -> tiny
    with pytest.raises(LookupError):
        OC.slot_spec(rom, "nobody")
    t = SW.slot_target(rom, OC.slot_spec(rom, "deku_scrub"))
    assert t["mode"] == "rigid" and t["rigid_limb"] in range(1, 15)
    t = SW.slot_target(rom, sp)
    assert t["mode"] == "retarget" and t["roles"]["head"] == 14


def _donor(tmp_path, rom_bytes) -> dict:
    """A collection entry made from the synthetic humanoid itself (as op=extract would)."""
    rom = OW.Rom(rom_bytes)
    obj = rom.object(SA)
    sk = OW.skeleton(obj, 0xB1A0)
    W = OW.pose(sk, None)
    mesh = OW.object_mesh(obj, sk, W, {4: rom.object(1)})
    d = tmp_path / "lib" / "donor"
    d.mkdir(parents=True)
    OW.write_gltf(mesh, sk, W, d / "donor.gltf", "Donor")
    roles = SW.topo_roles(sk, np.array([w[:3, 3] for w in W]))
    meta = {"slug": "donor", "name": "Donor", "kind": "character", "model": "donor.gltf",
            "rig": {"roles": {r: f"l{j:02d}" for r, j in roles.items()}}}
    (d / "meta.json").write_text(json.dumps(meta))
    return meta


def test_build_cast_one_rom_relocates_grown_objects_and_fixes_the_crc(tmp_path, rom_bytes, monkeypatch):
    monkeypatch.setattr(C, "_blender", lambda cfg: None)
    meta = _donor(tmp_path, rom_bytes)
    cfg = SimpleNamespace(cache=tmp_path / "cache")
    msgs = []
    r = SW.build_cast(cfg, OOT, [("saria", meta), ("deku_scrub", meta), ("epona", meta), ("talon", meta)],
                      "cast_test", lambda p, m: msgs.append(m), root=tmp_path / "lib", rom_data=rom_bytes)
    s = r["slots"]
    assert r["mod"] == "cast_test", r
    assert s["saria"]["status"] == "built" and s["saria"]["mode"] == "retarget", s["saria"]
    assert s["deku_scrub"]["status"] == "built" and s["deku_scrub"]["mode"] == "rigid" and "rides" in s["deku_scrub"]["note"]
    assert s["epona"]["status"] == "failed" and "skinned" in s["epona"]["reason"]
    assert s["talon"]["status"] == "built"
    img = tmp_path / "cache" / "mods" / OOT["game_id"] / "cast_test"
    rec = json.loads((img / ".gbox-mod.json").read_text())
    out = (img / rec["image"]).read_bytes()
    assert struct.unpack_from(">II", out, 0x10) == OW.crc6105(out)
    old, new = OW.Rom(rom_bytes), OW.Rom(out)
    end = max(e[1] for e in old.dma)
    for oid, off in ((SA, 0xB1A0), (DEKU, 0x3268), (TA, 0xB7B8)):
        o0, o1 = old.object(oid), new.object(oid)
        vs, ve = struct.unpack_from(">II", new.file(27), new.obj_table + 8 * oid)
        if len(o1) > len(o0):                                         # grew: a fresh VROM range past every file
            assert vs >= end and new.dma[new.object_index(oid)][:2] == [vs, ve]
        assert OW.skeleton(o1, off)["count"] == 15
        assert OC.check_object(o1, off) == []
        assert o1[off + 8] == o0[off + 8]                             # the Flex dListCount is untouched
        new_dls = {lb["dls"][0] for lb in OW.skeleton(o1, off)["limbs"]} - {0}
        assert new_dls and new_dls != {lb["dls"][0] for lb in OW.skeleton(o0, off)["limbs"]} - {0}
    assert new.file(498) == old.file(498)                             # everything else as it was
    assert r["detail"]["over_budget_rooms"] == [] and set(r["detail"]["grew"]) >= {"object_sa", "object_dekunuts"}
    kf = OC.contexts(OW.Rom(rom_bytes))[0]
    assert sum(r["detail"]["grew"].get(n, 0) for n in ("object_sa", "object_dekunuts")) <= kf["free"]
    assert any("Rebuilding the ROM" in m for m in msgs)


def test_build_cast_refuses_what_does_not_fit_and_keeps_the_rest(tmp_path, rom_bytes, monkeypatch):
    monkeypatch.setattr(C, "_blender", lambda cfg: None)
    meta = _donor(tmp_path, rom_bytes)
    full = synthetic_rom({SA: humanoid_object(0xB1A0, 0xB1B0), DEKU: humanoid_object(0x3268, 0x3278, flex=False),
                          TA: humanoid_object(0xB7B8, 0xB7C8)}, keep_size=OC.SPACE - 0x2100 - 0xB1B0 - 0x3280)
    r = SW.build_cast(SimpleNamespace(cache=tmp_path / "cache"), OOT, [("saria", meta), ("talon", meta)],
                      "cast_full", root=tmp_path / "lib", rom_data=full)
    assert r["slots"]["talon"]["status"] == "built"              # not in Kokiri Forest's room: its own cap
    sar = r["slots"]["saria"]
    assert sar["status"] == "built" and sar["grew"] <= 0x200 or sar["status"] == "failed" and \
        "doesn't fit" in sar["reason"], sar


def test_fit_budget_flattens_then_refuses():
    tri = ((np.zeros(3), np.array([0, 1.0, 0]), (0.0, 0.0)), (np.array([10.0, 0, 0]), np.array([0, 1.0, 0]), (1.0, 0.0)),
           (np.array([0, 10.0, 0]), np.array([0, 1.0, 0]), (0.0, 1.0)))
    parts = {1: [(0, tri)] * 40}
    mats = [{"color": (255, 255, 255), "tex": np.full((64, 64, 4), 200, np.uint8)}]
    fitted, rep = SW.fit_budget(parts, mats, [40], 0x4000)
    assert rep["bytes"] <= 0x4000 and rep["max_texels"] <= 2048
    with pytest.raises(ValueError, match="untextured"):
        SW.fit_budget(parts, mats, [40], 0x100)


# ---------------------------------------------------------------- the cast swap on OoT

ROLES = {"hip": "j0", "chest": "j1", "head": "j2"}
SA2 = [{"slug": f"sa2_{n}", "name": n, "kind": "character", "model": "m.glb", "aliases": [], "rig": {"roles": ROLES},
        "stats": {"triangles": 100, "textures": 1},
        "source": {"game_title": "Sonic Adventure 2 (USA)", "game_id": "d95ed7ed1e40552a", "platform": "dreamcast"}}
       for n in ("Sonic", "Shadow", "Knuckles", "Rouge", "Tails", "Eggman", "Amy")]


def test_cast_swap_plans_the_whole_oot_cast_as_pairs():
    rows = CS.slot_rows(OOT)
    slots = [r["slot"] for r in rows]
    assert slots[0] == "player" and len(slots) == len(set(slots)) == len(OC.CAST)
    assert not any(" " in s for s in slots)                          # no descriptive coverage strings as slots
    assert {r["slot"] for r in CS.filter_slots(rows, "enemies")} >= {"stalfos", "moblin_spear", "skulltula"}
    assert {r["slot"] for r in CS.filter_slots(rows, "bosses")} >= {"ganondorf", "ganon"}
    assert "saria" in {r["slot"] for r in CS.filter_slots(rows, "main")}
    p = CS.plan(OOT, SA2, "SA2", seed="kf")
    assert p["status"] == "planned" and p["strategy"] == "pairs" and p["writer"] == "gbox.oot_swap"
    planned = {a["slot"] for a in p["assignments"]}
    skipped = {s["slot"]: s["reason"] for s in p["skipped"]}
    assert {"epona", "navi", "like_like", "hylian_townsfolk"} == set(skipped) and "skinned" in skipped["epona"]
    assert planned == set(slots) - set(skipped) and "player" in planned
    assert p == CS.plan(OOT, SA2, "SA2", seed="kf")                  # deterministic


def test_cast_swap_builds_oot_through_build_cast(tmp_path, monkeypatch):
    from gbox import filemods, oot_swap
    seen = {}

    def build_cast(cfg, game, pairs, name, progress=None, strict_cutscenes=False, **kw):
        seen.update(pairs=[(s, m["slug"]) for s, m in pairs], strict=strict_cutscenes)
        d = filemods.mod_dir(cfg, game["game_id"], name)
        d.mkdir(parents=True)
        (d / ".gbox-mod.json").write_text(json.dumps({"name": name, "game_id": game["game_id"]}))
        return {"mod": name, "slots": {s: ({"status": "built"} if s != "kokiri_girl" else
                                           {"status": "failed", "reason": "doesn't fit"}) for s, _m in pairs}}
    monkeypatch.setattr(oot_swap, "build_cast", build_cast)
    monkeypatch.setattr(C, "get", lambda root, slug: next(m for m in SA2 if m["slug"] == slug))
    monkeypatch.setattr(C, "_api", lambda *a, **k: {})
    p = CS.plan(OOT, SA2, "SA2", slots="player,kokiri_boy,kokiri_girl,saria")
    ctx = SimpleNamespace(config=SimpleNamespace(cache=tmp_path / "cache"), progress=lambda *a: None, job_id="j")
    r = CS.build(ctx, OOT, p, SA2, tmp_path, SimpleNamespace(rebuild=False, strict_cutscenes=True))
    assert [s for s, _ in seen["pairs"]] == ["player", "kokiri_boy", "kokiri_girl", "saria"] and seen["strict"]
    assert r["status"] == "partial" and r["mod"] == p["mod"]
    girl = next(x for x in r["report"] if x["slot"] == "kokiri_girl")
    assert girl["status"] == "failed" and girl["reason"] == "doesn't fit"


# ---------------------------------------------------------------- the operator's ROM (skipped when not cached)

OWNED = [Path(os.environ["GBOX_OOT_ROM"])] if os.environ.get("GBOX_OOT_ROM") else [
    Path.home() / "gbox-cache/446e8e442d726e31/rom.z64", Path.home() / "gbox-cache/1aa2e4bb5797493f/source.zip"]


@pytest.fixture(scope="module")
def owned():
    p = next((p for p in OWNED if p.exists()), None)
    if p is None:
        pytest.skip("the operator's OoT ROM isn't cached (set GBOX_OOT_ROM)")
    from gbox import n64_rom
    return OW.Rom(n64_rom.read(p))


def test_owned_rom_has_every_catalogued_skeleton(owned):
    snap = OC.load_snapshot()["slots"]
    for c in OC.CAST:
        if c.get("refuse") or c["kind"] == "player":
            continue
        obj = owned.object(OC.object_id(c["object"]))
        f = OC.skeleton_facts(obj, c["skel"])
        assert f["limbs"] == snap[c["slot"]]["skeleton_facts"]["limbs"], c["slot"]
        assert f["type"] == c["type"], c["slot"]


def test_owned_rom_kokiri_forest_object_space(owned):
    kf = [c for c in OC.contexts(owned) if c["name"] == "Kokiri Forest" and c["layer"] == 0 and c["room"] == 0][0]
    assert 120 * 1024 < kf["free"] < 140 * 1024                     # docs/model_swaps.md: ~130 KB free as child
    assert {OC.object_id(n) for n in ("object_km1", "object_kw1", "object_sa", "object_md", "object_fa")} <= set(kf["objects"])
    sp = OC.slot_spec(owned, "kokiri_girl")
    assert sp["objects"] == [0xFD, 0x13D] and sp["group"]["extra_heads"] == [(0x13D, 0x2940)]
