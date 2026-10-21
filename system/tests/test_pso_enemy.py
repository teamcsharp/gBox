"""PSO Ver.2 (DC) enemy writer (gbox.pso_enemy, #235): synthetic enemy packs (NJTL + NJCM bodies with their PVM, NJM
motions, PRS-packed BML) and a synthetic skinned donor, no disc, Blender or emulator; the owned-disc tests at the end
read the Booma pack off the operator's GDI when it is reachable (PSO_GDI or the Spark cache path) and skip otherwise."""
import json
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from gbox import char_coverage as CC, characters as C, ninja, pso_enemy as PE, pso_player
from gbox.gdrom import GDRom, patch_gdi

PACK = "PSO/BM_ENE_LAPPY_AP.BML"                      # a PACKS path: slot enemy:lappy enumerates this pack's bodies
#         0 root, 1 hip, 2 chest, 3-5 right arm (5 = claw tip marker), 6-8 left arm, 9 head, 10-12 left leg, 13-15 right leg
PARENTS = [-1, 0, 1, 2, 3, 4, 2, 6, 7, 2, 1, 10, 11, 1, 13, 14]
LOCAL = [(0, 0, 0), (0, 10, 0), (0, 4, 0), (-3, 0, 0), (0, -4, 0), (0, -4, 0), (3, 0, 0), (0, -4, 0), (0, -4, 0),
         (0, 3, 0), (1.5, 0, 0), (0, -5, 0), (0, -5, 0), (-1.5, 0, 0), (0, -5, 0), (0, -5, 0)]
MARKERS = {5, 8}
MESH = [i for i in range(16) if i not in MARKERS and i != 0]
ROLES = {"hip": 1, "chest": 2, "head": 9, "r_upper": 3, "r_fore": 4, "r_hand": 5, "l_upper": 6, "l_fore": 7, "l_hand": 8,
         "l_thigh": 10, "l_shin": 11, "l_foot": 12, "r_thigh": 13, "r_shin": 14, "r_foot": 15}
COLLAPSE = {5: 4, 8: 7}
DONOR_NAMES = ["hip", "chest", "head", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand", "l_thigh", "l_shin",
               "l_foot", "r_thigh", "r_shin", "r_foot"]
DONOR_PARENTS = [-1, 0, 1, 1, 3, 4, 1, 6, 7, 0, 9, 10, 0, 12, 13]
DONOR_POS = np.array([[0, 1, 0], [0, 1.4, 0], [0, 1.7, 0], [.25, 1.4, 0], [.25, 1.1, 0], [.25, .85, 0],
                      [-.25, 1.4, 0], [-.25, 1.1, 0], [-.25, .85, 0], [.1, 1, 0], [.1, .5, 0], [.1, 0, 0],
                      [-.1, 1, 0], [-.1, .5, 0], [-.1, 0, 0]])


# ---------------------------------------------------------------- synthetic enemy pack

def _nodes():
    nodes = [{"off": 52 * i, "flags": (0x1E if i in MARKERS else 0x0C if i == 0 else 0x04), "model": 0,
              "trs": struct.pack("<3f3i3f", *LOCAL[i], 0, 0, 0, 1, 1, 1), "parent": None if p < 0 else p,
              "child": None, "sibling": None} for i, p in enumerate(PARENTS)]
    for parent in range(len(nodes)):
        kids = [i for i, n in enumerate(nodes) if n["parent"] == parent]
        if kids:
            nodes[parent]["child"] = kids[0]
        for a, b in zip(kids, kids[1:]):
            nodes[a]["sibling"] = b
    return nodes


def _weighted_chunk(verts):
    """A 0x2C vertex chunk (position + normal + ninja flags: index | weight << 16), status start."""
    body = b"".join(struct.pack("<3f3fI", *p, 0, 1, 0, i | (255 << 16)) for i, p in enumerate(verts))
    return struct.pack("<IHH", 0x2C | ((1 + 7 * len(verts)) << 16), 0, len(verts)) + body


def _njtl(names):
    arr = struct.pack("<II", 8, len(names))
    table, blob, ptrs = b"", b"", []
    off = 8 + 12 * len(names)
    for n in names:
        ptrs.append(8 + len(table))
        table += struct.pack("<III", off + len(blob), 0, 0)
        blob += n.encode() + b"\0"
    d = arr + table + blob
    d += bytes((-len(d)) % 4)
    return b"NJTL" + struct.pack("<I", len(d)) + d + ninja.pof0([0] + ptrs)


def enemy_body(tex_names=("t_a", "t_b", "t_c")) -> bytes:
    """A body entry like the disc's: NJTL + POF0 + NJCM + POF0; every mesh node draws one triangle, the hip keeps a
    weighted (0x2C) vertex chunk in front of its rigid one, strips use textures 0..2 and a 0x13 material."""
    nodes = _nodes()
    mat = struct.pack("<HH", 0x13, 4) + bytes([0xB2, 0xB2, 0xB2, 0xFF, 0x7F, 0x7F, 0x7F, 0xFF])
    models = {}
    for j in MESH:
        tri = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0.5]], float) + [0.1 * j, 0, 0]
        keep = _weighted_chunk([(0, 0, 0), (0, 0.5, 0)]) if j == 1 else b""
        models[j] = ninja.cnk_model_lists(tri, np.tile([0, 0, 1.0], (3, 1)), [((0, 1, 2), ((0, 0), (1, 0), (0, 1)))],
                                          j % 3, mat, base=16 + 4 * j, keep_vlist=keep)
    for j in range(len(nodes)):
        nodes[j]["model"] = 1 if j in models else 0
    data, _root, ptrs = ninja.write_tree(nodes, models, 0)
    return _njtl(tex_names) + b"NJCM" + struct.pack("<I", len(data)) + data + ninja.pof0(ptrs)


def _tex(size, colour):
    """A noisy texture (solid colours would PRS-compress to nothing and make the pack's sectors unrealistic)."""
    rng = np.random.default_rng(size + colour[1])
    img = np.zeros((size, size, 4), np.uint8)
    img[..., :3] = np.clip(np.array(colour) + rng.integers(-40, 40, (size, size, 3)), 0, 255)
    img[..., 3] = 255
    return ninja.pvr_twiddled(img, 1)


def enemy_pvm(size=16, names=("t_a", "t_b", "t_c")) -> bytes:
    return PE.pvm_pack([(n, _tex(size, (200, 60 * k, 30)), 0x1B000 + k) for k, n in enumerate(names)])


def bml_pack(entries) -> bytes:
    """[(name, decompressed data, decompressed texture archive or None)] -> a BML like the disc's."""
    head = bytearray(0x800)
    struct.pack_into("<II", head, 4, len(entries), 0x150)
    body = bytearray()
    for i, (name, data, tex) in enumerate(entries):
        raw = ninja.prs_compress(data)
        ctex = ninja.prs_compress(tex) if tex is not None else b""
        head[0x40 + 0x40 * i:0x40 + 0x40 * i + 0x20] = name.encode().ljust(0x20, b"\0")
        struct.pack_into("<5I", head, 0x40 + 0x40 * i + 0x20, len(raw), 0, len(data), len(ctex), len(tex) if tex else 0)
        body += raw + bytes((-len(raw)) % 0x20)
        if tex is not None:
            body += ctex + bytes((-len(ctex)) % 0x20)
    return bytes(head + body)


def enemy_pack(bodies=("lappy_base.nj", "lappy_two.nj"), tex_size=16) -> bytes:
    rng = np.random.default_rng(1)
    ents = [(b, enemy_body(), enemy_pvm(tex_size)) for b in bodies]
    ents += [(f"{m}_re3_b_base.njm", b"NMDM" + struct.pack("<I", 64) + rng.bytes(64), None) for m in ("walk", "attack")]
    return bml_pack(ents)


def fake_disc(bml: bytes, spare_sectors: int = 8, path: str = PACK, room_sectors: int | None = None):
    """The pack at LBA 1000 with `spare_sectors` free ones before the next file (or exactly `room_sectors` in all)."""
    sectors = (len(bml) + 2047) // 2048 + spare_sectors if room_sectors is None else room_sectors
    return SimpleNamespace(files={path: (1000, len(bml)), "PSO/NEXT.BIN": (1000 + sectors, 100)},
                           read=lambda p, _b=bml: _b if p == path else b"\0" * 100)


def enemy(bml: bytes, key="lappy_base", entry="lappy_base.nj", roles=ROLES, collapse=COLLAPSE, head_nodes=(9,)):
    """An enemy like resolve_slot() gives: roles=None means inferred from the skeleton at build time."""
    return {"key": key, "name": key, "file": PACK, "entry": entry, "roles": roles,
            "collapse": collapse if roles is not None else None, "head_nodes": list(head_nodes) if roles is not None else None}


# ---------------------------------------------------------------- synthetic donor (a skinned glTF)

def donor_gltf(path: Path, names=DONOR_NAMES, parents=DONOR_PARENTS, pos=DONOR_POS) -> Path:
    from gbox.melee_models import write_gltf
    joints = []
    for p, q in zip(parents, pos):
        w = np.eye(4)
        w[:3, 3] = q
        joints.append({"parent": p, "world": w})
    P, J = [], []
    for k, q in enumerate(pos):
        P += [q + [0, 0, .05], q + [.05, 0, 0], q + [0, .05, .05]]
        J += [k, k, k]
    P = np.array(P, float)
    jj = np.zeros((len(P), 4), int)
    jj[:, 0] = J
    ww = np.zeros((len(P), 4))
    ww[:, 0] = 1
    tex = np.zeros((4, 4, 4), np.uint8)
    tex[..., :3], tex[..., 3] = (30, 120, 220), 255
    prims = [{"pos": P, "nrm": np.tile([0, 0, 1.0], (len(P), 1)), "uv": np.tile([.5, .5], (len(P), 1)),
              "tris": np.arange(len(P)).reshape(-1, 3), "J": jj, "W": ww, "tex": tex, "color": (255, 255, 255, 255),
              "wrap": (10497, 10497)}]
    return write_gltf(path, joints, prims, 1.0, "donor", list(names))


def _body_tree(raw: bytes):
    _prefix, data = PE._njcm(raw)
    return data, ninja.tree_nodes(data, 0)


# ---------------------------------------------------------------- slots, roster, coverage

def test_slot_parsing_without_the_disc():
    assert [e["key"] for e in PE.resolve_slot("enemy:booma")] == ["booma"]
    assert [e["key"] for e in PE.resolve_slot("enemy:Gigobooma")] == ["gigobooma"]
    assert [e["key"] for e in PE.resolve_slot("enemy:boomas")] == ["booma", "gobooma", "gigobooma"]
    assert [e["key"] for e in PE.resolve_slot("enemies")] == ["booma", "gobooma", "gigobooma"]
    assert [e["key"] for e in PE.resolve_slot("enemy:bm1f_s1_wala_body")] == ["gobooma"]
    for e in PE.resolve_slot("enemy:boomas"):
        assert e["file"] == PE.BOOMA_PACK and e["roles"]["hip"] == 2 and e["collapse"] == {13: 12, 8: 7}
    with pytest.raises(ValueError, match="unknown enemy"):
        PE.resolve_slot("enemy:rappy")
    with pytest.raises(ValueError, match="not an enemy slot"):
        PE.resolve_slot("player")
    assert PE.slot_name("enemy:Boomas") == "boomas" and PE.slot_name("enemies") == "enemies"
    assert pso_player.is_enemy_slot("enemy:booma") and pso_player.is_enemy_slot("enemies")
    assert not pso_player.is_enemy_slot("player") and not pso_player.is_enemy_slot("")


def test_slot_parsing_with_the_disc_enumerates_pack_bodies():
    disc = fake_disc(enemy_pack())
    bodies = PE.resolve_slot("enemy:lappy", disc)
    assert [b["entry"] for b in bodies] == ["lappy_base.nj", "lappy_two.nj"]
    assert all(b["roles"] is None and b["inferred"] and b["file"] == PACK for b in bodies)
    one = PE.resolve_slot("enemy:lappy_two", disc)
    assert len(one) == 1 and one[0]["entry"] == "lappy_two.nj"
    with pytest.raises(ValueError, match="no pack on the disc"):
        PE.resolve_slot("enemy:nothing_here", disc)


def test_roster_and_cast_slots_list_the_enemies():
    roster = C._pso_roster()
    enemies = [e for e in roster if e.get("kind") == "enemy"]
    assert [e["slug"] for e in enemies] == ["pso_booma", "pso_gobooma", "pso_gigobooma"]
    assert all(e["slot"] == e["key"] and e["slot"].startswith("enemy:") and e["file"] == PE.BOOMA_PACK for e in enemies)
    assert len([e for e in roster if e.get("kind") == "character"]) == 9       # the classes are still there
    s = PE.slots()
    by = {x["slot"]: x for x in s}
    assert by["enemy:booma"]["entry"] == "bm1_s_wala_body.nj" and by["enemy:booma"]["roles"] == "mapped"
    assert by["enemy:boomas"]["entries"] == ["bm1_s_wala_body.nj", "bm1f_s1_wala_body.nj", "bm1tl_s_wala_body.nj"]
    assert by["enemy:lappy"]["roles"] == "inferred" and "entries" not in by["enemy:lappy"]
    assert PE.slots(fake_disc(enemy_pack()))[[x["slot"] for x in s].index("enemy:lappy")]["entries"] == ["lappy_base.nj", "lappy_two.nj"]
    game = {"game_id": "daba7a3b195dcf6b", "title": "Phantasy Star Online Ver. 2 (USA)", "platform": "dreamcast"}
    cast = CC.cast_slots(game)
    slots = [x["slot"] for x in cast]
    assert slots[0] == "player" and "enemy:booma" in slots and "enemy:boomas" in slots and "enemies" in slots
    assert all(x["writer"] == "gbox.pso_player" for x in cast)
    row = next(r for r in CC.WRITERS if r[0] == "pso_player")
    assert "enemy:<name>" in row[1] and "enemies" in row[1]


def test_collect_reports_the_enemy_slots(monkeypatch, tmp_path):
    game = {"game_id": "daba7a3b195dcf6b", "title": "Phantasy Star Online Ver. 2 (USA)", "platform": "dreamcast"}
    monkeypatch.setattr(C, "_game", lambda ctx, inp: game)
    monkeypatch.setattr(C, "library_root", lambda cfg: tmp_path)
    monkeypatch.setattr(C, "dedicated_entries", lambda cfg, g, name, roster: [])
    ctx = SimpleNamespace(config=SimpleNamespace(cache=tmp_path), progress=lambda *a: None)
    res = C.collect(ctx, SimpleNamespace(game_id=game["game_id"], game="", session_id=""))
    assert res["extractor"] == "pso"
    assert [s["slot"] for s in res["slots"]][:5] == ["player", "enemy:booma", "enemy:gobooma", "enemy:gigobooma", "enemy:boomas"]


# ---------------------------------------------------------------- skeleton fit: roles, virtual joints, collapse

def test_infer_roles_on_the_synthetic_skeleton():
    raw = enemy_body()
    nj = ninja.NJ(raw)
    _data, nodes = _body_tree(raw)
    roles, collapse, heads = PE.infer_roles(nj, nodes)
    assert roles == ROLES and collapse == COLLAPSE and heads == [9]


def test_enemy_target_adds_virtual_limb_ends_and_grounds_on_the_feet():
    raw = enemy_body()
    nj = ninja.NJ(raw)
    tgt = PE.enemy_target(nj, ROLES, COLLAPSE, [9])
    assert tgt["joints"] == 16 and tgt["virtual"] == {} and tgt["collapse"] == COLLAPSE
    assert tgt["ground"] == pytest.approx(0.0, abs=1e-6)                  # the feet, not the lowest vertex
    assert tgt["T"][ROLES["l_fore"]].tolist() == pytest.approx([3, 10, 0])
    short = {r: j for r, j in ROLES.items() if r not in ("l_hand", "r_hand", "l_foot", "r_foot")}
    tgt2 = PE.enemy_target(nj, short, {}, [9])
    assert tgt2["joints"] == 20 and set(tgt2["virtual"]) == {"l_hand", "r_hand", "l_foot", "r_foot"}
    v = tgt2["virtual"]["l_hand"]
    assert tgt2["T"][v].tolist() == pytest.approx([3, 6, 0])              # the forearm segment carried on
    assert tgt2["collapse"][v] == ROLES["l_fore"] and tgt2["parent"][v] == ROLES["l_fore"]
    assert tgt2["collapse"][tgt2["virtual"]["r_foot"]] == ROLES["r_shin"]
    assert tgt2["roles"]["l_hand"] == v and tgt2["ground"] == pytest.approx(0.0, abs=1e-6)


def test_split_nodes_collapses_marker_geometry_onto_the_forearm():
    from gbox import ninja_swap as NS
    raw = enemy_body()
    tgt = PE.enemy_target(ninja.NJ(raw), ROLES, COLLAPSE, [9])
    P = np.array([[-3, 6, 0], [-2, 6, 0], [-3, 7, 0.0]])                  # at the right claw tip, fitted to marker 5
    J = np.zeros((3, 4), int)
    J[:, 0] = 5
    geo = NS.split_nodes([{"pos": P, "nrm": np.tile([0, 0, 1.0], (3, 1)), "uv": np.zeros((3, 2)),
                           "tris": np.array([[0, 1, 2]]), "J": J}], tgt)
    assert list(geo) == [4]                                                   # stored on the forearm node...
    pos = geo[4][0]
    assert pos[0].tolist() == pytest.approx([0, -4, 0])                      # ...in its space (the tip is 4 below it)


# ---------------------------------------------------------------- the body entry and its textures

def test_body_nj_keeps_the_tree_and_original_chunks_and_draws_texture_0():
    raw = enemy_body()
    data, nodes = _body_tree(raw)
    tri = (np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0.0]]), np.tile([0, 0, 1.0], (3, 1)),
           [((0, 1, 2), ((0, 0), (1, 0), (0, 1)))])
    out = PE.body_nj(raw, {2: tri, 4: tri})
    assert out.startswith(b"NJTL") and out[:raw.find(b"NJCM")] == raw[:raw.find(b"NJCM")]    # texture list kept
    d2, n2 = _body_tree(out)
    assert len(n2) == len(nodes) == 16
    for a, b in zip(nodes, n2):
        assert (a["trs"], a["parent"], a["child"], a["sibling"]) == (b["trs"], b["parent"], b["child"], b["sibling"])
        assert b["flags"] == a["flags"] & ~0x8 if b is n2[2] or b is n2[4] else b["flags"] == a["flags"]
    assert n2[5]["model"] == 0 and n2[8]["model"] == 0                      # markers stay empty
    vl = struct.unpack_from("<I", d2, n2[1]["model"])[0]
    assert d2[vl:vl + 8 + 2 * 28] == _weighted_chunk([(0, 0, 0), (0, 0.5, 0)])   # the hip's weighted chunk, first
    nj2 = ninja.NJ(out)
    assert set(nj2.tris) == {0} and len(nj2.tris[0]) == 2                     # only the donor strips, on texture 0
    world = sorted(tuple(round(x, 3) for x in c[2]["pos"]) for c in nj2.tris[0][0]) + \
        sorted(tuple(round(x, 3) for x in c[2]["pos"]) for c in nj2.tris[0][1])
    assert (0, 14, 0) in world and (-3, 10, 0) in world                      # chest + forearm triangles placed by their nodes
    assert nj2.tris[0][0][0][2]["joints"][0][0] in (2, 4)
    assert out.endswith(ninja.pof0(ninja.write_tree(n2, {}, 0)[2] or [0])[:4]) or b"POF0" in out[-200:]


def test_render_state_comes_from_the_body():
    raw = enemy_body()
    data, nodes = _body_tree(raw)
    mat, tiny_fl, tex_fl, strip_fl = PE._render_state(data, nodes)
    assert mat[:2] == struct.pack("<H", 0x13) and tiny_fl == 0x34 and tex_fl == 0x4000 and strip_fl & 0x10


def test_pvm_pack_round_trips_and_body_pvm_keeps_names_and_shrinks_only_the_rest():
    from PIL import Image
    pvm = enemy_pvm(16)
    flags, meta = PE.pvm_meta(pvm)
    assert flags == 0x11F and meta == [("t_a", 0x1B000), ("t_b", 0x1B001), ("t_c", 0x1B002)]
    assert [(n, ninja.pvr_decode(c)[:2]) for n, c in ninja.pvm(pvm)] == [("t_a", (16, 16)), ("t_b", (16, 16)), ("t_c", (16, 16))]
    atlas = Image.fromarray(np.full((32, 32, 3), (10, 200, 10), np.uint8), "RGB")
    full = PE.body_pvm(pvm, atlas, False)
    small = PE.body_pvm(pvm, atlas, True)
    assert PE.pvm_meta(full) == PE.pvm_meta(small) == (flags, meta)
    assert [ninja.pvr_decode(c)[:2] for _n, c in ninja.pvm(full)] == [(16, 16)] * 3
    assert [ninja.pvr_decode(c)[:2] for _n, c in ninja.pvm(small)] == [(16, 16), (8, 8), (8, 8)]
    assert len(small) < len(full) == len(pvm)
    w, h, rgba, _ = ninja.pvr_decode(ninja.pvm(full)[0][1])
    assert rgba[1] > 150 and rgba[0] < 40                                     # the atlas colour, in the old format


def test_bml_build_replaces_an_entry_and_its_textures_in_place():
    bml = enemy_pack()
    new_body, new_tex = enemy_body(("x", "y", "z")), enemy_pvm(8)
    b2 = pso_player.bml_build(bml, {"lappy_two.nj": new_body}, {"lappy_two.nj": new_tex})
    e_old, e_new = {e["name"]: e for e in pso_player.bml_files(bml)}, {e["name"]: e for e in pso_player.bml_files(b2)}
    assert list(e_old) == list(e_new)
    for nm in e_old:
        if nm.startswith(b"lappy_two"):
            assert PE._unpack(e_new[nm]) == (new_body, new_tex)
            assert e_new[nm]["fields"][2] == len(new_body) and e_new[nm]["fields"][4] == len(new_tex)
        else:
            assert (e_new[nm]["raw"], e_new[nm]["tex"], e_new[nm]["fields"]) == (e_old[nm]["raw"], e_old[nm]["tex"], e_old[nm]["fields"])


def test_room_bytes_is_the_gap_to_the_next_file():
    disc = fake_disc(enemy_pack(), spare_sectors=3)
    bml = disc.read(PACK)
    assert PE.room_bytes(disc, PACK) == ((len(bml) + 2047) // 2048 + 3) * 2048


# ---------------------------------------------------------------- the whole swap on a synthetic pack

def test_build_swap_fits_the_donor_on_the_enemy_motions(tmp_path):
    bml = enemy_pack()
    disc = fake_disc(bml, spare_sectors=8)
    donor = donor_gltf(tmp_path / "donor.gltf")
    r = PE.build_swap(disc, donor, {n: n for n in DONOR_NAMES}, tmp_path / "work", "Donor",
                      [enemy(bml), enemy(bml, "lappy_two", "lappy_two.nj", roles=None)])
    assert list(r["files"]) == [PACK]
    b2 = r["files"][PACK]
    assert len(b2) <= PE.room_bytes(disc, PACK)
    old, new = {e["name"]: e for e in pso_player.bml_files(bml)}, {e["name"]: e for e in pso_player.bml_files(b2)}
    assert list(old) == list(new)
    for nm in old:
        if b".njm" in nm:
            assert new[nm]["raw"] == old[nm]["raw"] and new[nm]["fields"] == old[nm]["fields"]      # motions untouched
    for key, entry in (("lappy_base", b"lappy_base.nj"), ("lappy_two", b"lappy_two.nj")):
        raw, pvm = PE._unpack(new[entry.ljust(0x20, b"\0")])
        _d, nodes = _body_tree(raw)
        _d0, nodes0 = _body_tree(PE._unpack(old[entry.ljust(0x20, b"\0")])[0])
        assert [(n["trs"], n["parent"], n["child"], n["sibling"]) for n in nodes] == \
            [(n["trs"], n["parent"], n["child"], n["sibling"]) for n in nodes0]
        assert nodes[5]["model"] == 0 and nodes[8]["model"] == 0            # nothing on the claw-tip markers
        nj = ninja.NJ(raw)
        assert set(nj.tris) == {0}
        drawn = {max(c[2]["joints"], key=lambda jw: jw[1])[0] for tris in nj.tris.values() for tri in tris for c in tri}
        assert drawn <= set(MESH) and {4, 7} <= drawn                         # hands collapsed onto the forearms
        assert len(PE.drawn_vertices(nj)) == 15 * 3                           # the donor's vertices, drawn per node
        assert PE.pvm_meta(pvm)[1] == [("t_a", 0x1B000), ("t_b", 0x1B001), ("t_c", 0x1B002)]
        rep = r["report"][key]
        assert rep["triangles"] == 15 and rep["entry"] == entry.decode() and rep["collapse"] == {5: 4, 8: 7}
        assert rep["roles"]["l_hand"] == 8 and rep["roles"]["head"] == 9 and rep["textures_small"] is False
        assert rep["pack_bytes"] == len(b2) and rep["pack_room"] == PE.room_bytes(disc, PACK)
        assert (tmp_path / "work" / key / "rigged.gltf").exists() and r["atlas"][key].size == (128, 128)
    assert r["report"]["lappy_base"]["roles_inferred"] is False and r["report"]["lappy_two"]["roles_inferred"] is True


def test_build_swap_shrinks_textures_when_the_pack_would_not_fit(tmp_path):
    bml = enemy_pack(bodies=("lappy_base.nj",), tex_size=64)                  # 3 x 8 KB twiddled textures: ~25 KB
    disc = fake_disc(bml, room_sectors=8)                                     # 16 KB: full-size textures can't fit
    donor = donor_gltf(tmp_path / "donor.gltf")
    r = PE.build_swap(disc, donor, {n: n for n in DONOR_NAMES}, tmp_path / "work", "Donor", [enemy(bml)])
    assert r["report"]["lappy_base"]["textures_small"] is True
    new = {e["name"]: e for e in pso_player.bml_files(r["files"][PACK])}
    pvm = PE._unpack(new[b"lappy_base.nj".ljust(0x20, b"\0")])[1]
    assert [ninja.pvr_decode(c)[:2] for _n, c in ninja.pvm(pvm)] == [(64, 64), (8, 8), (8, 8)]
    assert len(r["files"][PACK]) <= PE.room_bytes(disc, PACK) == 8 * 2048 < len(bml)


def test_build_swap_refuses_a_pack_that_cannot_fit(tmp_path):
    bml = enemy_pack(tex_size=64)
    disc = SimpleNamespace(files={PACK: (1000, len(bml)), "PSO/NEXT.BIN": (1001, 100)}, read=lambda p: bml)
    donor = donor_gltf(tmp_path / "donor.gltf")
    with pytest.raises(ValueError, match="bytes, 2048 available"):
        PE.build_swap(disc, donor, {n: n for n in DONOR_NAMES}, tmp_path / "work", "Donor", [enemy(bml)])


def test_build_swap_rejects_an_unmappable_skeleton(tmp_path):
    raw = enemy_body()
    bml = bml_pack([("blob.nj", raw, enemy_pvm(16))])
    disc = fake_disc(bml)
    monkeypatch_roles = {"hip": 1}                                            # no chest: not enough to fit a humanoid
    donor = donor_gltf(tmp_path / "donor.gltf")
    import gbox.pso_enemy as mod
    orig = mod.infer_roles
    mod.infer_roles = lambda nj, nodes: (monkeypatch_roles, {}, [])
    try:
        with pytest.raises(ValueError, match="can't infer body roles"):
            PE.build_swap(disc, donor, {n: n for n in DONOR_NAMES}, tmp_path / "work", "Donor",
                          [enemy(bml, "blob", "blob.nj", roles=None)])
    finally:
        mod.infer_roles = orig


# ---------------------------------------------------------------- the rebuilt disc layout (gbox.gdrom.patch_gdi)

def _dir_record(extent, size, flags, name):
    nb = name.encode()
    rec = bytearray(34 + len(nb))
    rec[0] = 34 + len(nb)
    struct.pack_into("<I", rec, 2, extent)
    struct.pack_into(">I", rec, 6, extent)
    struct.pack_into("<I", rec, 10, size)
    struct.pack_into(">I", rec, 14, size)
    rec[25] = flags
    rec[32] = len(nb)
    rec[33:33 + len(nb)] = nb
    return bytes(rec)


def make_gdi(tmp_path: Path, files: dict[str, bytes], spare: int = 2) -> Path:
    """A three-track GDI whose high-density track (2048-byte sectors at LBA 45000) holds PSO/<files>: 16 system
    sectors, PVD, terminator, root dir, the PSO dir, then the files each followed by `spare` free sectors."""
    start = 45000
    sectors: list[bytes] = [bytes(2048)] * 16
    pvd = bytearray(2048)
    pvd[0], pvd[1:6] = 1, b"CD001"
    rec = _dir_record(start + 18, 2048, 2, "\x00")
    pvd[156:156 + len(rec)] = rec
    term = bytearray(2048)
    term[0], term[1:6] = 0xFF, b"CD001"
    root = bytearray(2048)
    rec = _dir_record(start + 19, 2048, 2, "PSO")
    root[:len(rec)] = rec
    psodir = bytearray(2048)
    lba, o, blobs = start + 20, 0, []
    for name, data in files.items():
        rec = _dir_record(lba, len(data), 0, name + ";1")
        psodir[o:o + len(rec)] = rec
        o += len(rec)
        n = (len(data) + 2047) // 2048
        blobs += [data[i:i + 2048].ljust(2048, b"\0") for i in range(0, n * 2048, 2048)] + [bytes(2048)] * spare
        lba += n + spare
    sectors += [bytes(pvd), bytes(term), bytes(root), bytes(psodir)] + blobs
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "disc01.bin").write_bytes(bytes(2048 * 2))
    (tmp_path / "disc02.raw").write_bytes(bytes(2352 * 2))
    (tmp_path / "disc03.bin").write_bytes(b"".join(sectors))
    gdi = tmp_path / "disc.gdi"
    gdi.write_text("3\n1 0 4 2048 disc01.bin 0\n2 6795 0 2352 disc02.raw 0\n3 45000 4 2048 disc03.bin 0\n")
    return gdi


def test_patch_gdi_substitutes_the_pack_in_a_new_image(tmp_path):
    bml = enemy_pack()
    other = b"other file" * 300
    gdi = make_gdi(tmp_path / "src", {"BM_ENE_LAPPY_AP.BML": bml, "BM_ENE_OTHER_A.BML": other})
    disc = GDRom(gdi)
    assert disc.read(PACK) == bml and PE.room_bytes(disc, PACK) == ((len(bml) + 2047) // 2048 + 2) * 2048
    donor = donor_gltf(tmp_path / "donor.gltf")
    r = PE.build_swap(disc, donor, {n: n for n in DONOR_NAMES}, tmp_path / "work", "Donor", [enemy(bml)])
    before = (tmp_path / "src" / "disc03.bin").read_bytes()
    out = patch_gdi(gdi, tmp_path / "mod", "pso_donor_as_lappy", r["files"])
    assert (tmp_path / "src" / "disc03.bin").read_bytes() == before            # never in place
    mod = GDRom(out)
    assert mod.read(PACK) == r["files"][PACK] and mod.read("PSO/BM_ENE_OTHER_A.BML") == other
    assert mod.files[PACK][0] == disc.files[PACK][0]                          # rewritten in its own sectors
    assert sorted(mod.files) == sorted(disc.files)


def test_build_mod_writes_the_mod_dir_and_registers_the_report(tmp_path, monkeypatch):
    bml = enemy_pack()
    gdi = make_gdi(tmp_path / "src", {"BM_ENE_LAPPY_AP.BML": bml})
    lib = tmp_path / "library" / "donor"
    lib.mkdir(parents=True)
    donor_gltf(lib / "donor.gltf")
    cfg = SimpleNamespace(cache=tmp_path / "cache")
    monkeypatch.setattr(C, "library_root", lambda c: tmp_path / "library")
    monkeypatch.setattr(C, "_blender", lambda c: None)
    monkeypatch.setattr(C, "render_preview", lambda src, dst: dst.write_bytes(b"png"))
    meta = {"slug": "donor", "name": "Donor", "model": "donor.gltf", "rig": {"roles": {n: n for n in DONOR_NAMES}}}
    game = {"game_id": "daba7a3b195dcf6b", "title": "Phantasy Star Online Ver. 2 (USA)"}
    res = PE.build_mod(cfg, meta, game, gdi, [enemy(bml)], slot="enemy:lappy")
    assert res["mod"] == "pso_donor_as_lappy"
    d = tmp_path / "cache" / "mods" / game["game_id"] / "pso_donor_as_lappy"
    man = json.loads((d / ".gbox-mod.json").read_text())
    assert man["files"] == [PACK] and man["enemies"] == ["lappy_base"] and man["slot"] == "enemy:lappy"
    assert man["verified"] is False and man["report"]["lappy_base"]["triangles"] == 15
    assert (d / man["image"]).exists() and GDRom(d / man["image"]).read(PACK) != bml
    assert (lib / "targets" / "pso_lappy_base.gltf").exists() and (lib / "targets" / "pso_lappy_base_preview.png").exists()
    assert GDRom(gdi).read(PACK) == bml


def test_use_builds_once_registers_and_launches(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(C, "library_root", lambda c: tmp_path)
    monkeypatch.setattr(C, "_dc_gdi", lambda ctx, g: tmp_path / "disc.gdi")
    monkeypatch.setattr(C, "_api", lambda ctx, m, p, **kw: calls.append((m, p, kw.get("json"))))
    monkeypatch.setattr(C, "_launch", lambda ctx, gid, mod, node: {"job": "j1", "state": "queued", "node": node})
    monkeypatch.setattr(PE, "build_mod", lambda cfg, meta, game, gdi, enemies, progress, name=None, slot="":
                        calls.append(("build", name, [e["key"] for e in enemies], slot)) or
                        {"mod": name, "image": "x.gdi", "report": {e["key"]: {"triangles": 7} for e in enemies}})
    ctx = SimpleNamespace(config=SimpleNamespace(cache=tmp_path / "cache"), progress=lambda *a: None)
    meta = {"slug": "oot_link_adult", "name": "Link", "rig": {"roles": {"hip": "l01"}}}
    game = {"game_id": "daba7a3b195dcf6b", "title": "PSO"}
    r = PE.use(ctx, meta, game, SimpleNamespace(slot="enemy:boomas", rebuild=False, launch=True))
    assert r["status"] == "built+launched" and r["mod"] == "pso_oot_link_adult_as_boomas"
    assert r["replaces"] == ["Booma", "Gobooma", "Gigobooma"] and "unverified" in r["verification"]
    assert calls[0] == ("build", "pso_oot_link_adult_as_boomas", ["booma", "gobooma", "gigobooma"], "enemy:boomas")
    assert calls[1][1] == "/api/characters/oot_link_adult/targets" and calls[1][2]["slot"] == "enemy:boomas"
    r2 = pso_player.use(ctx, meta, game, SimpleNamespace(slot="enemy:booma", rebuild=False, launch=False))
    assert r2["status"] == "built" and r2["mod"] == "pso_oot_link_adult_as_booma"   # routed through the PSO writer
    with pytest.raises(ValueError, match="unknown enemy"):
        PE.use(ctx, meta, game, SimpleNamespace(slot="enemy:rappy", rebuild=False, launch=False))


# ---------------------------------------------------------------- the owned disc (skipped when it isn't reachable)

_DEFAULT_GDI = "/home/ehm_eckx/gBox_alt/gbox-cache/dc/daba7a3b195dcf6b/disc.gdi"


def _gdi():
    p = Path(os.environ.get("PSO_GDI", _DEFAULT_GDI))
    return p if p.is_file() else None


@pytest.fixture(scope="module")
def booma_pack():
    gdi = _gdi()
    if gdi is None:
        pytest.skip("PSO Ver.2 disc not present")
    disc = GDRom(str(gdi))
    return disc, disc.read(PE.BOOMA_PACK)


def test_owned_disc_booma_pack_layout(booma_pack):
    disc, bml = booma_pack
    assert disc.files[PE.BOOMA_PACK] == (189894, 163424) and PE.room_bytes(disc, PE.BOOMA_PACK) == 163840
    names = [e["name"].split(b"\0")[0].decode() for e in pso_player.bml_files(bml)]
    assert names[:3] == ["bm1f_s1_wala_body.nj", "bm1tl_s_wala_body.nj", "bm1_s_wala_body.nj"]
    assert len([n for n in names if n.endswith(".njm")]) == 12 and all(n.endswith("_bm1_s_wala_body.njm") for n in names[3:])
    for key in PE.FAMILIES["boomas"]:
        en = PE.ENEMIES[key]
        raw, pvm = PE._unpack(PE._entry(bml, en["entry"]))
        nj = ninja.NJ(raw)
        _d, nodes = _body_tree(raw)
        assert len(nodes) == len(nj.bones) == 51
        owners = PE.vertex_owners(nj)
        for role, j in en["roles"].items():
            if j in en["collapse"]:
                assert not owners.get(j) and nodes[j]["flags"] & 0x8, (key, role)      # a marker
            else:
                assert owners.get(j), (key, role, j)                                   # a mesh node
        assert [n for n, _c in ninja.pvm(pvm)] == ninja.njtl(raw) and len(ninja.pvm(pvm)) == 3
    sizes = {k: len(PE._unpack(PE._entry(bml, PE.ENEMIES[k]["entry"]))[0]) for k in PE.FAMILIES["boomas"]}
    assert sizes == {"booma": 13060, "gobooma": 13068, "gigobooma": 11784}


def test_owned_disc_inferred_roles_match_the_booma_tables(booma_pack):
    _disc, bml = booma_pack
    for key in PE.FAMILIES["boomas"]:
        en = PE.ENEMIES[key]
        raw, _pvm = PE._unpack(PE._entry(bml, en["entry"]))
        nj = ninja.NJ(raw)
        _d, nodes = _body_tree(raw)
        roles, collapse, heads = PE.infer_roles(nj, nodes)
        assert roles == en["roles"] and collapse == en["collapse"], key
        assert set(heads) <= set(en["head_nodes"])
        tgt = PE.enemy_target(nj, en["roles"], en["collapse"], en["head_nodes"])
        assert tgt["joints"] == 51 and tgt["virtual"] == {} and -0.5 < tgt["ground"] < 0.5
        assert tgt["T"][en["roles"]["l_upper"]][0] > 4 > -4 > tgt["T"][en["roles"]["r_upper"]][0]   # left at +X


def test_owned_disc_donor_fits_the_booma_family_in_its_sectors(booma_pack, tmp_path):
    disc, bml = booma_pack
    donor = donor_gltf(tmp_path / "donor.gltf")
    r = PE.build_swap(disc, donor, {n: n for n in DONOR_NAMES}, tmp_path / "work", "Donor", PE.resolve_slot("enemy:boomas"))
    b2 = r["files"][PE.BOOMA_PACK]
    assert len(b2) <= 163840
    old, new = {e["name"]: e for e in pso_player.bml_files(bml)}, {e["name"]: e for e in pso_player.bml_files(b2)}
    assert all(new[n]["raw"] == old[n]["raw"] for n in old if b".njm" in n)
    for key in PE.FAMILIES["boomas"]:
        raw, _pvm = PE._unpack(new[PE.ENEMIES[key]["entry"].encode().ljust(0x20, b"\0")])
        nj = ninja.NJ(raw)
        assert len(nj.bones) == 51 and set(nj.tris) == {0} and r["report"][key]["triangles"] == 15
        drawn = {max(c[2]["joints"], key=lambda jw: jw[1])[0] for tris in nj.tris.values() for tri in tris for c in tri}
        assert not drawn & {8, 13} and drawn <= set(PE.ENEMIES[key]["roles"].values())
