"""Focused checks for the JGR Dreamcast reader foundation (gbox/jgr.py).

These gate on the owned disc, like the DOA2 suite: they run only when the extracted GD-ROM is
present (env JGR_GDI or the default cache path), otherwise they skip. They verify the archive and
container-header plumbing against the real PLAYER.AFS, not a synthetic stand-in.
"""
import os
import struct
from pathlib import Path

import pytest

from gbox import jgr
from gbox.gdrom import GDRom

_DEFAULT_GDI = "/home/ehm_eckx/gbox-cache/dc/4187aeab4d67638c/disc.gdi"


def _gdi():
    p = Path(os.environ.get("JGR_GDI", _DEFAULT_GDI))
    return p if p.is_file() else None


def _player_afs(gdi):
    return GDRom(str(gdi)).read("JETRADIO/PLAYER.AFS")


def test_afs_header_parses_owned_player_archive():
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    data = _player_afs(gdi)
    count, offsets, sizes = jgr.afs_entries(data)
    assert count == 34
    assert len(offsets) == 34 and len(sizes) == 34
    # Interleaved (offset, size) pairs: first entry is the first PLAY chunk, sizes are exact and
    # every entry ends before the next begins.
    assert data[offsets[0]:offsets[0] + 4] == b"PLAY"
    assert (offsets[0], sizes[0]) == (0x80000, 0xC6768)
    for (o, sz), nxt in zip(zip(offsets, sizes), offsets[1:]):
        assert o + sz <= nxt
    assert offsets[-1] + sizes[-1] <= len(data)


def test_chunks_finds_play_ptex_and_main():
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    data = _player_afs(gdi)
    found = jgr.chunks(data)
    kinds = [k for k, _ in found]
    # 16 characters, each a PLAY model followed by its PTEX texture set, plus main and EFTX.
    assert kinds.count("play") == 16
    assert kinds.count("ptex") == 16
    assert kinds.count("main") == 1
    assert kinds.count("eftx") == 1
    assert len(found) == 34


def test_play_container_header_decodes_record_table():
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    data = _player_afs(gdi)
    off = next(off for kind, off in jgr.chunks(data) if kind == "play")
    magic, recs = jgr.container_header(data, off)
    assert magic == b"PLAY"
    assert len(recs) == 12
    assert recs[0] == (108, 1)
    assert recs[-1] == (812880, 0)


def test_ptex_container_header_decodes():
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    data = _player_afs(gdi)
    off = next(off for kind, off in jgr.chunks(data) if kind == "ptex")
    magic, recs = jgr.container_header(data, off)
    assert magic == b"PTEX"
    assert len(recs) > 0


def test_inventory_lists_player_and_enemy_archives():
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    inv = jgr.inventory(str(gdi))
    assert "JETRADIO/PLAYER.AFS" in inv
    assert "JETRADIO/ENEMY.AFS" in inv
    assert len(inv["JETRADIO/PLAYER.AFS"]) == 34


def test_afs_entries_rejects_non_archive():
    with pytest.raises(ValueError):
        jgr.afs_entries(b"\x00" * 64)


def test_play_subobjects_record_table_sorted_by_address_and_contiguous():
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    data = _player_afs(gdi)
    count, offsets, sizes = jgr.afs_entries(data)
    play_off = next(off for kind, off in jgr.chunks(data) if kind == "play")
    afs_size = sizes[offsets.index(play_off)]
    subs = jgr.play_subobjects(data, play_off, afs_size=afs_size)
    by_rel = sorted(subs, key=lambda s: s["relative"])
    for a, b in zip(by_rel, by_rel[1:]):
        assert a["offset"] + a["length"] == b["offset"]


def test_decode_submesh_produces_indexed_triangle_list_for_small_record():
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    data = _player_afs(gdi)
    count, offsets, sizes = jgr.afs_entries(data)
    play_off = next(off for kind, off in jgr.chunks(data) if kind == "play")
    afs_size = sizes[offsets.index(play_off)]
    subs = jgr.play_subobjects(data, play_off, afs_size=afs_size)
    # Pick the kind==1 record at relative offset 0x1b8d4 (observed to be self-contained).
    mesh = next(s for s in subs if s["kind"] == 1 and s["relative"] == 0x1B8D4)
    indices, verts = jgr.decode_submesh(mesh["bytes"])
    assert indices
    assert verts
    assert max(indices) < len(verts)
    assert len(indices) % 3 == 0
    xs, ys, zs = zip(*verts)
    assert max(xs) - min(xs) < 2.0
    assert max(ys) - min(ys) < 3.0
    assert max(zs) - min(zs) < 2.0


def test_container_header_rejects_unknown_magic():
    with pytest.raises(ValueError):
        jgr.container_header(b"XXXX" + struct.pack("<I", 3) + b"\x00" * 24, 0)


def test_ptex_textures_walk_every_gbix_pvrt_to_the_entry_end():
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    data = _player_afs(gdi)
    off = next(off for kind, off in jgr.chunks(data) if kind == "ptex")
    size = jgr.entry_size(data, off)
    texs = jgr.ptex_textures(data, off)
    assert [(t["offset"], t["gbix"], t["pixfmt"], t["datafmt"], t["width"], t["height"]) for t in texs] == [
        (0x1000, 50, 1, 0x03, 256, 256),
        (0x5820, 54, 1, 0x04, 128, 128),
        (0x75A0, 760, 1, 0x10, 64, 64),
        (0x7DC0, 53, 2, 0x10, 64, 64),
    ]
    last = texs[-1]
    assert last["offset"] + len(last["bytes"]) <= size
    assert all(t["bytes"][:4] == b"GBIX" and t["bytes"][16:20] == b"PVRT" for t in texs)


def test_every_player_texture_decodes_to_rgba():
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    data = _player_afs(gdi)
    total = 0
    for kind, off in jgr.chunks(data):
        if kind not in ("ptex", "eftx"):
            continue
        texs = jgr.ptex_textures(data, off)
        assert texs, f"no textures in {kind} at {off:#x}"
        for t in texs:
            w, h, rgba = jgr.decode_texture(t)
            assert (w, h) == (t["width"], t["height"])
            assert len(rgba) == w * h * 4
            total += 1
    assert total == 89


def test_first_character_body_texture_is_not_flat_or_noise(tmp_path):
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    data = _player_afs(gdi)
    off = next(off for kind, off in jgr.chunks(data) if kind == "ptex")
    w, h, rgba = jgr.decode_texture(jgr.ptex_textures(data, off)[0])
    px = [tuple(rgba[i:i + 4]) for i in range(0, len(rgba), 4)]
    colours = set(px)
    # A real VQ atlas has many distinct colours but long runs of identical neighbours (flat UV
    # islands); random bytes decoded as VQ would give almost no equal neighbours.
    assert 64 < len(colours) < w * h // 2
    same = sum(1 for i in range(1, len(px)) if px[i] == px[i - 1])
    assert same > len(px) // 4
    paths = jgr.export_texture_set(data, off, str(tmp_path))
    assert len(paths) == 4
    assert all(open(p, "rb").read(8) == b"\x89PNG\r\n\x1a\n" for p in paths)


# ---------------------------------------------------------------- PLAY model trees
def _plays(data):
    return [o for k, o in jgr.chunks(data) if k == "play"]


def test_first_play_chunk_roots_and_counts_match_the_disc():
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    data = _player_afs(gdi)
    rows = jgr.play_summary(data, _plays(data)[0])
    got = [(r["root"], r["nodes"], r["vertices"], r["triangles"], r["texture_ids"]) for r in rows]
    assert got == [
        (0x9C7C, 20, 353, 1834, [0]),
        (0x22644, 20, 178, 947, [0]),
        (0x15450, 20, 386, 2054, [0, 1]),
        (0x1B8D4, 20, 195, 1057, [0, 1]),
        (0x1CAA4, 20, 11, 0, []),        # shadow volume: vertices, no strips
        (0xA990, 4, 28, 120, [1]),
    ]
    # The root table record and the motion/other kinds are not taken as objects.
    buf = jgr.play_bytes(data, _plays(data)[0])
    assert not jgr._is_object(buf, 0x6C)


def test_every_character_has_a_20_node_body_with_resolved_triangles():
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    data = _player_afs(gdi)
    plays = _plays(data)
    assert len(plays) == 16
    for off in plays:
        rows = jgr.play_summary(data, off)
        bodies = [r for r in rows if r["nodes"] == 20 and r["triangles"]]
        assert len(bodies) == 4, (hex(off), rows)
        best = max(r["triangles"] for r in bodies)
        assert 1300 < best < 2200, (hex(off), best)
        buf = jgr.play_bytes(data, off)
        nj = jgr.play_model(buf, max(bodies, key=lambda r: r["triangles"])["root"])
        # Every strip corner resolved to a cached vertex when it was drawn.
        assert all(c[2] is not None for tl in nj.tris.values() for t in tl for c in t)


def test_body_is_upright_humanoid_sized_and_exports_a_textured_skinned_glb(tmp_path):
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    import json
    data = _player_afs(gdi)
    ch = jgr.chunks(data)
    play = [o for k, o in ch if k == "play"][0]
    ptex = [o for k, o in ch if k == "ptex"][0]
    nj = jgr.play_model(jgr.play_bytes(data, play), 0x15450)
    pts = [c[2]["pos"] for tl in nj.tris.values() for t in tl for c in t]
    xs, ys, zs = zip(*pts)
    height, width, depth = max(ys) - min(ys), max(xs) - min(xs), max(zs) - min(zs)
    assert 15 < height < 20 and min(ys) > -0.5          # feet on the ground, Y up
    assert width < height / 2 and depth < height / 2      # standing figure, not exploded parts
    glb = Path(jgr.export_play_glb(data, play, 0x15450, str(tmp_path), "jgr_char00", ptex))
    raw = glb.read_bytes()
    assert raw[:4] == b"glTF"
    g = json.loads(raw[20:20 + struct.unpack_from("<I", raw, 12)[0]])
    assert len(g["skins"]) == 1 and len(g["skins"][0]["joints"]) == 20
    assert len(g["meshes"]) == 2 and len(g["images"]) == 2
    assert len(list((tmp_path / "textures").glob("*.png"))) == 4


# ---------------------------------------------------------------- native collection route
def test_characters_routes_jet_grind_radio_to_the_jgr_reader():
    from gbox import characters
    pick = lambda t, p: next((r[0] for r in characters.DEDICATED if r[1](t.lower(), p)), None)
    assert pick("Jet Grind Radio (USA)", "dreamcast") == "jgr"
    assert pick("Jet Set Radio (Europe)", "dreamcast") == "jgr"
    assert pick("Jet Set Radio Future", "xbox") is None
    ros = jgr.roster()
    assert len(ros) == 16 and len({r["slug"] for r in ros}) == 16
    assert all(r["kind"] == "character" for r in ros)


def test_collect_extracts_all_16_characters_verified_and_retargetable(tmp_path, monkeypatch):
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    from gbox import characters
    monkeypatch.setattr(characters, "_dc_gdi", lambda ctx, game: gdi)

    class Ctx:
        class config:
            cache = str(tmp_path / "cache")

        def progress(self, pct, msg):
            pass

    game = {"game_id": "4187aeab4d67638c", "title": "Jet Grind Radio (USA)", "platform": "dreamcast"}
    root = tmp_path / "lib"
    root.mkdir()
    ros = jgr.roster()
    for e in ros:
        res = characters.extract_dedicated(Ctx(), game, e["slug"], root, ("jgr", ros))
        assert res["status"] == "extracted", res
        meta = characters.get(root, e["slug"])
        assert characters.verify_entry(root, meta)["ok"], e["slug"]
        assert meta["rig"]["roles"] == jgr.BODY_ROLES, e["slug"]
        rig = characters.rig_from_gltf(root / e["slug"] / meta["model"], meta["rig"]["roles"])
        assert len(rig["roles"]) == 15 and len(rig["joints"]) == 20
        # Bind-pose sanity: feet below the pelvis, head above it (02 and 12 are bound with an arm raised).
        y = {r: rig["joints"][i][1] for r, i in rig["roles"].items()}
        assert y["l_foot"] < y["hip"] < y["head"] and y["r_foot"] < y["hip"]


def test_body_roles_rejects_a_foreign_skeleton(tmp_path):
    import json
    gl = {"asset": {"version": "2.0"}, "nodes": [{"name": f"node{i:03d}", "children": [i + 1] if i < 19 else []}
                                                 for i in range(20)], "skins": [{"joints": list(range(20))}]}
    js = json.dumps(gl).encode()
    js += b" " * (-len(js) % 4)
    p = tmp_path / "chain.glb"
    p.write_bytes(b"glTF" + struct.pack("<II", 2, 20 + len(js)) + struct.pack("<I", len(js)) + b"JSON" + js)
    with pytest.raises(ValueError):
        jgr.body_roles(p)
