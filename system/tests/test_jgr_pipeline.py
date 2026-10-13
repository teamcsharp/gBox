"""Jet Grind Radio pipeline: #1396 (the extracted character arrived wrapped in other geometry and wrongly textured)
and the jgr_swap writer (#1151 / #1153 / #1156).

The synthetic PLAYER.AFS below has the owned disc's structure: a PLAY binding record naming six draw groups (gameplay
body, its low-detail copy, the spray-can bodies, a vertex-only shadow volume and a separate head), each body node
carrying a lit textured strip plus a cel-shading outline (an ignore-light strip on a reversed hull 0.1 unit outside),
and a PTEX binding record whose per-group texlists put the body atlas at PTEX texture 1 (texture 0 is a face sheet,
like Gum's) and at texture id 1 in the spray-can groups (id 0 = the shared can texture, like Yo-Yo's). Owned-disc
checks skip when the extracted GD-ROM is absent (JGR_GDI overrides the default Spark path)."""
import json
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from gbox import jgr, jgr_swap, ninja

GDI = Path(os.environ.get("JGR_GDI", "/home/ehm_eckx/gbox-cache/dc/4187aeab4d67638c/disc.gdi"))

PARENTS_HEAD = [-1, 0, 1, 2]
HULL = 0.1


# ------------------------------------------------------------------ synthetic PLAY / PTEX builders
def _nodes(parents, step=0.5):
    nodes = [{"flags": 0, "trs": struct.pack("<3f3i3f", 0, step if p >= 0 else 0, 0, 0, 0, 0, 1, 1, 1),
              "parent": None if p < 0 else p, "child": None, "sibling": None} for p in parents]
    for parent in range(len(nodes)):
        kids = [i for i, n in enumerate(nodes) if n["parent"] == parent]
        if kids:
            nodes[parent]["child"] = kids[0]
        for a, b in zip(kids, kids[1:]):
            nodes[a]["sibling"] = b
    return nodes


def _vlist(points, normals, base):
    vb = b"".join(struct.pack("<6f", *p, *n) for p, n in zip(points, normals))
    return struct.pack("<IHH", 0x29 | ((1 + 6 * len(points)) << 16), base, len(points)) + vb + struct.pack("<I", 0xFF)


def _material(rgba):
    r, g, b, a = rgba
    return struct.pack("<HH4B", 0x11, 2, b, g, r, a)


def _strip(typ, flags, idx, uvs=None):
    body = bytearray(struct.pack("<Hh", 1, len(idx)))
    for k, i in enumerate(idx):
        body += struct.pack("<H", i)
        if uvs is not None:
            body += struct.pack("<hh", *uvs[k])
    if len(body) % 4:
        body += bytes(2)
    return struct.pack("<HH", typ | (flags << 8), len(body) // 2) + bytes(body)


def _model(j, base, tex=None, can=None):
    """Node j: one lit textured triangle (texture id `tex`) + its outline hull (+ a can triangle with id `can`)."""
    tri = [[j, 0, 0], [j + 0.5, 0, 0], [j, 0.5, 0]]
    nrm = [[0, 0, 1]] * 3
    hull = [[x, y, z + HULL] for x, y, z in tri]
    pts, nrms = tri + hull, nrm + [[0, 0, -1]] * 3
    if can is not None:
        pts, nrms = pts + [[j, 0, 1], [j + 0.2, 0, 1], [j, 0.2, 1]], nrms + nrm
    pl = _material((255, 255, 255, 255))
    if tex is not None:
        pl += struct.pack("<HH", 8 | (0x34 << 8), tex | 0x4000)
        pl += _strip(0x41, 0x02, [base, base + 1, base + 2], [(0, 0), (255, 0), (0, 255)])
    if can is not None:
        pl += struct.pack("<HH", 8 | (0x34 << 8), can | 0x4000)
        pl += _strip(0x41, 0x02, [base + 6, base + 7, base + 8], [(0, 0), (255, 0), (0, 255)])
    pl += _material((34, 0, 2, 255)) + _strip(0x40, 0x03, [base + 5, base + 4, base + 3])   # reversed: faces inward
    pl += struct.pack("<H", 0xFF) + bytes(2)
    return _vlist(pts, nrms, base), pl, [j, 0, 0], 1.0


def _gbix(gbix, size, rgb):
    img = np.zeros((size, size, 3)) + np.array(rgb, float)
    return b"GBIX" + struct.pack("<II", 8, gbix) + bytes(4) + ninja.pvr_twiddled(img)


# PTEX order: 0 face sheet (8x8), 1 body atlas (16x16), 2 shared spray can (GBIX 760), 3 shadow
TEXTURES = [(39, 8, (230, 120, 0)), (35, 16, (150, 210, 0)), (760, 8, (200, 0, 0)), (38, 8, (90, 90, 90))]
TEXLISTS = [[1], [1], [2, 1], [2, 1], [3], [0]]
BODY_TEX, SPRAY_TEX = 0, 1          # texture id of the atlas in the gameplay / spray-can groups


def _play(native_id):
    # container header: "PLAY", N, then (value, kind) records: the binding record, then the model roots
    # (kind 1 bodies, 2 shadow, 3 head, as on the disc)
    rec = 8 + 8 * 7
    out = bytearray(b"PLAY" + struct.pack("<III", 7, rec, 1) + bytes(8 * 6))
    out += struct.pack("<i", native_id) + bytes(96) + struct.pack("<i", -1)
    out += bytes((-len(out)) % 4)
    roots = []

    def tree(parents, models):
        base = len(out)
        blob, root, _ = ninja.write_tree(_nodes(parents), models, base)
        out.extend(blob)
        roots.append(root)
    body = {j: _model(j, 10 * j, BODY_TEX) for j in range(1, 20)}
    spray = {j: _model(j, 10 * j, SPRAY_TEX, 0 if j == 15 else None) for j in range(1, 20)}
    shadow = {j: (_vlist([[j, 0, 0]], [[0, 1, 0]], j), b"", [j, 0, 0], 1.0) for j in range(1, 20)}
    head = {j: _model(j, 10 * j, 0) for j in range(1, 4)}
    for parents, models in ((jgr.BODY_PARENTS, body), (jgr.BODY_PARENTS, body), (jgr.BODY_PARENTS, spray),
                            (jgr.BODY_PARENTS, spray), (jgr.BODY_PARENTS, shadow), (PARENTS_HEAD, head)):
        tree(parents, models)
    for k, r in enumerate(roots):
        struct.pack_into("<4I", out, rec + 4 + 16 * k, r, r, r, r)
        struct.pack_into("<II", out, 16 + 8 * k, r, (1, 1, 1, 1, 2, 3)[k])
    return bytes(out), roots


def _ptex(native_id):
    out = bytearray(b"PTEX" + struct.pack("<II", 0, 12))
    out += struct.pack("<i", native_id) + bytes(96) + struct.pack("<i", -1)
    tex_at = 0x400
    offsets, o = [], tex_at
    blobs = [_gbix(*t) for t in TEXTURES]
    for b in blobs:
        offsets.append(o)
        o = (o + len(b) + 3) & ~3
    lists = []
    for tl in TEXLISTS:
        names = len(out)
        out += bytes(12 * len(tl))
        lists.append(len(out))
        out += struct.pack("<II", names, len(tl)) + b"".join(struct.pack("<I", offsets[i]) for i in tl)
    for k, p in enumerate(lists):
        struct.pack_into("<4I", out, 12 + 4 + 16 * k, p, p, p, p)
    assert len(out) <= tex_at
    out += bytes(tex_at - len(out))
    for off, b in zip(offsets, blobs):
        out += bytes(off - len(out)) + b
    return bytes(out + bytes((-len(out)) % 4))


def _afs():
    entries, names = [], []
    for i, name in enumerate(jgr.ARCHIVE_NAMES):
        entries += [_play(jgr.USA_NATIVE_IDS[i])[0], _ptex(jgr.USA_NATIVE_IDS[i])]
        names += [name + "dat.bin", name + "txr.bin"]
    n = len(entries)
    offs, o = [], 0x800
    for e in entries:
        offs.append(o)
        o = (o + len(e) + 0x7FF) & ~0x7FF
    directory = b"".join(nm.encode().ljust(44, b"\0") + struct.pack("<I", len(e)) for nm, e in zip(names, entries))
    out = bytearray(o + len(directory))
    out[:8] = b"AFS\0" + struct.pack("<I", n)
    for i, (off, e) in enumerate(zip(offs, entries)):
        struct.pack_into("<II", out, 8 + 8 * i, off, len(e))
        out[off:off + len(e)] = e
    struct.pack_into("<II", out, 8 + 8 * n, o, len(directory))
    out[o:] = directory
    return bytes(out)


@pytest.fixture(scope="module")
def afs():
    return _afs()


def _glb_json(path):
    raw = Path(path).read_bytes()
    return json.loads(raw[20:20 + struct.unpack_from("<I", raw, 12)[0]])


def _glb_triangles(path):
    g = _glb_json(path)
    return sum(g["accessors"][p["indices"]]["count"] // 3 for m in g["meshes"] for p in m["primitives"])


def _manifest_tris(m):
    return sum(len(mesh["indices"]) // 3 for mesh in m["meshes"])


# ------------------------------------------------------------------ #1396: the extracted character, alone
def test_binding_records_name_the_draw_groups_and_their_texlists(afs):
    play, ptex = jgr.character_pair(afs, 15)
    _, roots = _play(jgr.USA_NATIVE_IDS[15])
    assert jgr.play_groups(afs, play) == roots
    assert jgr.ptex_texlists(afs, ptex) == TEXLISTS
    assert jgr.atlas_texture(afs, ptex) == 1                  # the largest texture of the body's texlist, not PTEX 0


def test_outline_hull_is_its_own_strip_class(afs):
    play, _ = jgr.character_pair(afs, 4)
    buf = jgr.play_bytes(afs, play)
    body = jgr.play_groups(afs, play)[0]
    plain = jgr.play_model(buf, body)                          # the shared parser files the hull under texture 0
    assert {k: len(v) for k, v in plain.tris.items()} == {BODY_TEX: 38}
    split = jgr.play_model(buf, body, materials=True)
    assert split.materials == [{"outline": True, "texture": None, "colour": (34, 0, 2, 255)}]
    assert {k: len(v) for k, v in split.tris.items()} == {BODY_TEX: 19, jgr.FLAT_BASE: 19}


def test_legacy_selection_carried_the_can_and_the_hull(afs):
    # What the operator saw: the largest-triangle tree is the spray-can body, and every strip of it (hull included)
    # was bound to PTEX textures in file order, so the body drew the face sheet (PTEX 0 = orange) inside a dark shell.
    play, _ = jgr.character_pair(afs, 15)
    groups = jgr.play_groups(afs, play)
    assert jgr.body_root(afs, play) == groups[2]
    legacy = jgr.play_model(jgr.play_bytes(afs, play), groups[2])
    # body, can and hull, all under ids bound in PTEX order (id 1 -> PTEX 1, id 0 -> the face sheet)
    assert sorted(legacy.tris) == [0, 1] and sum(len(v) for v in legacy.tris.values()) == 39


def test_export_character_writes_the_body_alone_with_extras_as_parts(afs, tmp_path):
    x = jgr.export_character(afs, 15, str(tmp_path), "jgr_char15")
    play, _ = jgr.character_pair(afs, 15)
    groups = jgr.play_groups(afs, play)
    assert x["root"] == groups[0] and x["triangles"] == 19
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert _manifest_tris(m) == 19 == _glb_triangles(x["glb"])
    # bound through group 0's texlist: texture id 0 -> PTEX 1, the atlas (not the face sheet in PTEX slot 0)
    assert [mat["texture"] for mat in m["materials"]] == ["textures/jgr_char15_tex01_gbix35.png"]
    assert m["materials"][0]["source"] == {"strip_class": "textured", "ninja_texture_id": 0, "ptex_index": 1}
    # nothing around the character: every vertex lies on the body plane (the hull sits 0.1 in front of it)
    zs = {round(p[2], 4) for mesh in m["meshes"] for p in mesh["positions"]}
    assert len(zs) == 1
    parts = {p["role"]: p for p in x["parts"]}
    assert list(parts) == ["outline", "body_lod", "body_spray", "body_spray_lod", "shadow", "head"]
    assert parts["outline"]["triangles"] == 19 and _glb_triangles(tmp_path / parts["outline"]["file"]) == 19
    assert parts["body_spray"]["triangles"] == 39                       # body + can + hull, kept together
    assert parts["head"]["triangles"] == 6 and parts["head"]["nodes"] == 4
    assert parts["shadow"]["triangles"] == 0 and "file" not in parts["shadow"]
    spray = _glb_json(tmp_path / parts["body_spray"]["file"])
    names = sorted(mat.get("name", "") for mat in spray["materials"])
    assert len(names) == 3 and sum("outline" in n for n in names) == 1     # atlas, can, outline


def test_spray_can_group_binds_ids_through_its_own_texlist(afs, tmp_path):
    play, ptex = jgr.character_pair(afs, 15)
    groups = jgr.play_groups(afs, play)
    files = [f"textures/t{i}.png" for i in range(len(TEXTURES))]
    m, _nj, n = jgr.group_manifest(afs, play, groups[2], TEXLISTS[2], "spray", files, {}, outline=False)
    by_id = {mat.source["ninja_texture_id"]: mat.texture for mat in m.materials}
    assert by_id == {0: "textures/t2.png", 1: "textures/t1.png"}           # id 0 = can (760), id 1 = atlas
    assert n == 20


def test_collection_entries_of_the_old_reader_are_refreshed():
    assert jgr.needs_refresh({"extraction_tool": "gbox.jgr + gbox.ninja"})
    assert not jgr.needs_refresh({"extraction_tool": "gbox.jgr + gbox.ninja", "jgr_reader": jgr.READER_VERSION})
    assert not jgr.needs_refresh({"extraction_tool": "gbox.sa2_chars + gbox.ninja"})


def test_extract_run_reports_parts_and_reader_version(afs, tmp_path, monkeypatch):
    from gbox import characters, gdrom
    monkeypatch.setattr(characters, "_dc_gdi", lambda ctx, game: "fixture.gdi")
    monkeypatch.setattr(gdrom, "GDRom", lambda path: SimpleNamespace(read=lambda name: afs))
    ctx = SimpleNamespace(progress=lambda *a: None)
    r = jgr.extract_run(ctx, {"game_id": "4187aeab4d67638c"}, {"key": "04", "slug": "jgr_char04"}, tmp_path)
    assert r["extra"]["jgr_reader"] == jgr.READER_VERSION
    assert [p["role"] for p in r["extra"]["parts"]][:1] == ["outline"]
    assert tmp_path / "parts" in r["files"]
    assert r.get("roles") == jgr.BODY_ROLES or "Rig roles not derived" in r["notes"]


# ------------------------------------------------------------------ writer: per-group atlas ids
def test_group_texture_ids_follow_each_texlist(afs):
    play, ptex = jgr.character_pair(afs, 15)
    groups = jgr.play_groups(afs, play)
    atlas, ids = jgr.group_texture_ids(afs, play, ptex, groups[:4])
    assert atlas == 1
    assert ids == {groups[0]: 0, groups[1]: 0, groups[2]: 1, groups[3]: 1}
    with pytest.raises(ValueError, match="no texture id for the body atlas"):
        jgr.group_texture_ids(afs, play, ptex, [groups[5]])          # the head's texlist lacks the atlas
    with pytest.raises(ValueError, match="not a draw group"):
        jgr.group_texture_ids(afs, play, ptex, [groups[0] + 52])


def test_writer_gives_a_twin_with_another_atlas_id_its_own_strips(monkeypatch, tmp_path):
    from test_jgr_twins import _binary_groups, _patched_writer
    original, roots = _binary_groups()
    triangle = [((0, 1, 2), ((0, 0), (1, 0), (0, 1)))]
    geo = {i: ([[0, 0, 0], [0.25, 0, 0], [0, 0.25, 0]], [[0, 0, 1]] * 3, triangle) for i in range(1, 20)}
    _patched_writer(monkeypatch, original, roots, geo)
    monkeypatch.setattr(jgr, "group_texture_ids",
                        lambda data, play, ptex, rs: (0, {r: (1 if r == roots[1] else 0) for r in rs}))
    result = jgr.build_swap("fixture.gdi", tmp_path / "fixture.glb", {"hip": "x"}, tmp_path, "Donor", 4)
    rewritten = result["files"][jgr.PLAYER_AFS][0]
    assert set(jgr.play_model(rewritten, roots[0]).tris) == {0}
    assert set(jgr.play_model(rewritten, roots[1]).tris) == {1}      # its texlist's id for the atlas
    assert set(jgr.play_model(rewritten, roots[2]).tris) == {0}
    models = [[n["model"] for n in ninja.tree_nodes(rewritten, r)] for r in roots[:3]]
    assert models[0] == models[2] and all(a != b for a, b in zip(models[0][1:], models[1][1:]))
    assert result["report"]["texture_ids"] == {hex(roots[0]): 0, hex(roots[1]): 1, hex(roots[2]): 0}
    assert result["report"]["atlas_texture"] == 0


def test_cache_schema_moves_past_the_texture_order_builds():
    assert jgr.CACHE_VERSION >= 6


# ------------------------------------------------------------------ jgr_swap: slots, roster, routing
@pytest.mark.parametrize("slot, archive, assumed", [
    ("player", 4, True), ("character:beat", 4, False), ("character:Yo-Yo", 15, False), ("character:pench", 8, False),
    ("character:rival_pjam", 13, False), ("beat", 4, False), ("15", 15, False), ("jgr_char02", 2, False)])
def test_slots_resolve_without_the_disc(slot, archive, assumed):
    r = jgr_swap.resolve_slot(slot)
    assert (r["archive"], r["assumed"]) == (archive, assumed)
    assert r["native_id"] == jgr.USA_NATIVE_IDS[archive]


def test_slots_resolve_against_the_archive(afs):
    assert jgr_swap.resolve_slot("player", afs)["archive"] == 4
    assert jgr_swap.resolve_slot("player", afs, active_id=8) == {"archive": 15, "native_id": 8, "name": "Yo-Yo",
                                                                 "slot": "character:yoyo", "assumed": False}
    assert jgr_swap.resolve_slot("id:1", afs)["slot"] == "character:gum"
    assert jgr_swap.resolve_slot("character:gum", lambda: afs)["archive"] == 6


@pytest.mark.parametrize("slot", ["character:", "character:nobody", "char:99", "id:x"])
def test_bad_slots_are_refused(slot):
    with pytest.raises(ValueError):
        jgr_swap.resolve_slot(slot, _afs if slot == "id:x" else None)


def test_cast_menu_lists_player_and_all_sixteen():
    rows = jgr_swap.cast_slots()
    assert rows[0]["slot"] == "player" and rows[0]["native_id"] == 0
    slots = [r["slot"] for r in rows[1:]]
    assert len(slots) == len(set(slots)) == 16
    assert {"character:beat", "character:gum", "character:yoyo", "character:plug", "character:rival_snpjam"} <= set(slots)
    for row in rows[1:]:
        assert jgr_swap.resolve_slot(row["slot"])["archive"] == row["archive"]


def test_writer_is_registered_and_routed():
    from gbox import char_coverage
    game = {"game_id": "4187aeab4d67638c", "title": "Jet Grind Radio (USA)", "platform": "dreamcast"}
    w = char_coverage.writer_for(game)
    assert w["writer"] == "gbox.jgr_swap" and w["routed"]
    assert w["slots"][:2] == ["player", "character:<name>"] and "unverified" in w["replaces"]
    menu = char_coverage.cast_slots(game)
    assert menu[0]["slot"] == "player" and len(menu) == 17
    assert all(m["writer"] == "gbox.jgr_swap" for m in menu)


def test_use_builds_the_resolved_archive_and_says_when_player_was_assumed(afs, monkeypatch):
    from gbox import characters, gdrom
    monkeypatch.setattr(characters, "_dc_gdi", lambda ctx, game: "fixture.gdi")
    monkeypatch.setattr(gdrom, "GDRom", lambda path: SimpleNamespace(read=lambda name: afs))
    seen = []
    monkeypatch.setattr(jgr, "use", lambda ctx, meta, game, inp: seen.append(inp) or {"mod": f"jgr_x_{inp.slot}"})
    game = {"game_id": "4187aeab4d67638c"}
    out = jgr_swap.use(None, {"slug": "sa2_amy_rose"}, game, SimpleNamespace(slot="player", launch=False))
    assert seen[-1].slot == "04" and seen[-1].launch is False and seen[-1].active_id is None
    assert out["replaced"]["name"] == "Beat" and "player_assumed" in out
    out = jgr_swap.use(None, {"slug": "sa2_amy_rose"}, game,
                       SimpleNamespace(slot="character:yoyo", launch=True, rebuild=True))
    assert seen[-1].slot == "15" and seen[-1].launch and seen[-1].rebuild and "player_assumed" not in out
    with pytest.raises(ValueError, match="covers"):
        jgr_swap.use(None, {"slug": "x"}, {"game_id": "other"}, SimpleNamespace(slot="player"))


# ------------------------------------------------------------------ owned disc (skip when absent)
def _owned():
    if not GDI.is_file():
        pytest.skip("JGR disc not present")
    from gbox.gdrom import GDRom
    return GDRom(str(GDI)).read(jgr.PLAYER_AFS)


@pytest.fixture(scope="module")
def owned():
    return _owned()


def test_owned_groups_texlists_and_atlases(owned):
    expected_atlas = {6: 1, 7: 1, 13: 1, 14: 1}                    # Gum, Nuts and the Poison Jam leaders
    for i in range(jgr.CHARACTER_COUNT):
        play, ptex = jgr.character_pair(owned, i)
        groups, lists = jgr.play_groups(owned, play), jgr.ptex_texlists(owned, ptex)
        assert len(groups) == len(lists) == 6 and all(groups[:5])
        texs = jgr.ptex_textures(owned, ptex)
        atlas = jgr.atlas_texture(owned, ptex, lists)
        assert atlas == expected_atlas.get(i, 0)
        assert (texs[atlas]["width"], texs[atlas]["height"]) == (256, 256)
        _, ids = jgr.group_texture_ids(owned, play, ptex, groups[:4])
        assert ids[groups[0]] == lists[0].index(atlas)
    play, ptex = jgr.character_pair(owned, 15)                      # Yo-Yo: spray-can bodies draw the atlas as id 1
    _, ids = jgr.group_texture_ids(owned, play, ptex, jgr.play_groups(owned, play)[:4])
    assert list(ids.values()) == [0, 0, 1, 1]


def test_owned_outline_is_a_reversed_hull_on_every_body(owned):
    for i in range(jgr.CHARACTER_COUNT):
        play, _ = jgr.character_pair(owned, i)
        nj = jgr.play_model(jgr.play_bytes(owned, play), jgr.play_groups(owned, play)[0], materials=True)
        hull = [c[2] for k, v in nj.tris.items() if k >= jgr.FLAT_BASE and nj.materials[k - jgr.FLAT_BASE]["outline"]
                for t in v for c in t]
        body = [c[2] for k, v in nj.tris.items() if k < jgr.FLAT_BASE for t in v for c in t]
        assert len(hull) > len(body) / 3                            # roughly one hull triangle per body triangle
        H = np.array([v["pos"] for v in hull])
        B = np.array([v["pos"] for v in body])
        HN = np.array([v["nrm"] for v in hull])
        BN = np.array([v["nrm"] for v in body])
        near = np.sqrt(((H[:, None, :] - B[None, :, :]) ** 2).sum(-1)).argmin(1)
        dot = (HN * BN[near]).sum(1) / (np.linalg.norm(HN, axis=1) * np.linalg.norm(BN[near], axis=1) + 1e-9)
        assert np.median(dot) < -0.9                                # normals reversed: an inverted hull


def test_owned_export_of_yoyo_is_the_body_alone(owned, tmp_path):
    x = jgr.export_character(owned, 15, str(tmp_path), "jgr_char15")
    m = json.loads((tmp_path / "manifest.json").read_text())
    textured = [mat["texture"] for mat in m["materials"] if mat["source"].get("strip_class") == "textured"]
    assert textured == ["textures/jgr_char15_tex00_gbix35.png"]     # the 256x256 atlas, not the face sheet
    assert x["triangles"] == 759
    parts = {p["role"]: p for p in x["parts"]}
    assert parts["outline"]["triangles"] == 699 and parts["shadow"]["triangles"] == 0
    assert parts["body_spray"]["triangles"] == 1666 and parts["head"]["nodes"] == 4
