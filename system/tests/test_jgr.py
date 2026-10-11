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


# ---- swap-writer helpers (offline: synthetic AFS) ----
def _afs(entries):
    import struct as _s
    n = len(entries)
    offs, o = [], 0x800
    for e in entries:
        offs.append(o)
        o = (o + len(e) + 0x7FF) & ~0x7FF
    out = bytearray(o)
    out[:8] = b"AFS\0" + _s.pack("<I", n)
    for i, (off, e) in enumerate(zip(offs, entries)):
        _s.pack_into("<II", out, 8 + 8 * i, off, len(e))
        out[off:off + len(e)] = e
    return bytes(out), offs


USA_NATIVE_IDS = [7, 4, 3, 2, 0, 13, 1, 5, 9, 14, 6, 11, 12, 10, 15, 8]   # archive 00..15 (1ST_READ 0x8c0c7f74 review)


def test_swap_index_slots(monkeypatch):
    from gbox import jgr
    import pytest
    assert jgr.swap_index("07") == 7 and jgr.swap_index("jgr_char12") == 12 and jgr.swap_index("char:3") == 3
    assert jgr.swap_index("00") == 0                                   # explicit archive index still works
    with pytest.raises(ValueError):
        jgr.swap_index("16")
    with pytest.raises(ValueError):
        jgr.swap_index("enemy")
    # 'player' is never guessed as archive 00: without a known active native ID it fails with guidance
    for s in (None, "player"):
        with pytest.raises(ValueError, match="active native character ID is unknown"):
            jgr.swap_index(s)
    monkeypatch.setattr(jgr, "native_ids", lambda data: list(USA_NATIVE_IDS))
    loads = []
    assert jgr.swap_index("id:0", lambda: loads.append(1) or b"afs") == 4 and loads == [1]   # lazy PLAYER.AFS read
    assert jgr.swap_index("id:7", b"afs") == 0 and jgr.swap_index("native:15", b"afs") == 14
    assert jgr.swap_index("player", b"afs", active_id=0) == 4
    assert jgr.swap_index("07", lambda: 1 / 0) == 7                    # archive indexes never read the disc
    with pytest.raises(ValueError, match="needs the PLAYER.AFS data"):
        jgr.swap_index("id:0")
    with pytest.raises(ValueError, match="not bound"):
        jgr.swap_index("id:16", b"afs")


def test_native_id_checks():
    from gbox import jgr
    import pytest
    with pytest.raises(ValueError):
        jgr.native_id_for_archive(b"", 16)


def test_native_ids_on_owned_disc():
    from gbox import jgr
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    data = _player_afs(gdi)
    assert jgr.native_ids(data) == USA_NATIVE_IDS
    assert jgr.native_id_for_archive(data, 0) == 7 and jgr.archive_index_for_native_id(data, 0) == 4


def test_swap_index_by_character_name(monkeypatch):
    from gbox import jgr
    import pytest
    # without disc data the USA constants resolve names; beat = 1ST_READ "BEAT(EREKI)" = archive 04 = native ID 0
    assert jgr.swap_index("beat") == 4 and jgr.swap_index("Ereki") == 4 and jgr.swap_index(jgr.NEW_GAME_PLAYER) == 4
    assert jgr.swap_index("bis") == 0 and jgr.swap_index("gum") == 6 and jgr.swap_index("combo") == 2
    assert jgr.swap_index("conpo") == 2 and jgr.swap_index("nuts") == 7 and jgr.swap_index("pench") == 8
    assert jgr.swap_index("yo_yo") == 15 and jgr.swap_index("rival_pjam") == 13 and jgr.swap_index("Rival-NTank") == 12
    with pytest.raises(ValueError, match="no JGR character has that name"):
        jgr.swap_index("sonic")
    with pytest.raises(ValueError, match="use slot 'beat'"):
        jgr.swap_index("player")
    # with disc data the archive's own directory names are used (a reordered disc resolves by its names)
    names = list(reversed(jgr.ARCHIVE_NAMES))
    monkeypatch.setattr(jgr, "character_names", lambda data: names)
    monkeypatch.setattr(jgr, "native_ids", lambda data: list(reversed(USA_NATIVE_IDS)))
    assert jgr.swap_index("ereki", b"afs") == 11 and jgr.swap_index("beat", lambda: b"afs") == 11


def test_roster_names_every_character_from_the_disc_tables():
    from gbox import jgr
    ros = jgr.roster()
    assert [r["slug"] for r in ros] == [f"jgr_char{i:02d}" for i in range(16)]     # collection slugs unchanged
    assert ros[4]["name"] == "Beat (JGR ereki, ID 0)" and ros[4]["native_id"] == 0
    assert ros[0]["name"] == "Bis (JGR bis, ID 7)" and "BIS" in ros[0]["aliases"] and "JGR character 0" in ros[0]["aliases"]
    assert ros[13]["name"].startswith("Rival Pjam") and ros[15]["name"].startswith("Yo-Yo")


def test_afs_names_rejects_a_directory_that_disagrees_with_the_table():
    import struct
    import pytest
    from gbox import jgr
    blob = bytearray(0x1000)
    blob[:4] = b"AFS\0"
    struct.pack_into("<III", blob, 4, 1, 0x800, 4)                 # one entry at 0x800, 4 bytes
    struct.pack_into("<II", blob, 0x800 - 8, 0xc00, 48)            # directory pair before the first entry
    blob[0xc00:0xc08] = b"abcdat.b"
    struct.pack_into("<I", blob, 0xc00 + 44, 4)
    assert jgr.afs_names(bytes(blob)) == ["abcdat.b"]
    struct.pack_into("<I", blob, 0xc00 + 44, 5)                    # size mismatch: not a real directory
    with pytest.raises(ValueError, match="no file-name directory"):
        jgr.afs_names(bytes(blob))


def test_character_names_agree_with_native_ids_and_1st_read_on_owned_disc():
    import struct
    from gbox import jgr
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    disc = GDRom(str(gdi))
    data = disc.read("JETRADIO/PLAYER.AFS")
    names = jgr.character_names(data)
    assert names == jgr.ARCHIVE_NAMES
    assert jgr.afs_names(data)[16:18] == ["player_effect_dat.bin", "player_effect_txr.bin"]
    ids = jgr.native_ids(data)
    # 1ST_READ's debug pointer table (0x8c10df40) lists the names in native-ID order
    exe, base = disc.read("1ST_READ.BIN"), 0x8c010000
    labels = []
    for k in range(15):
        ptr = struct.unpack_from("<I", exe, 0x8c10df40 - base + 4 * k)[0]
        labels.append(exe[ptr - base:exe.index(b"\0", ptr - base)].decode())
    assert labels[:10] + labels[13:] == [n for n in jgr.NATIVE_DEBUG_NAMES if n]
    for i, n in enumerate(names):                   # each archive file name matches its native ID's debug label
        label = jgr.NATIVE_DEBUG_NAMES[ids[i]]
        if label:
            assert {"ereki": "BEAT(EREKI)", "conpo": "COMBO", "nat": "NUTS", "plug": "PLUG(PENCH)",
                    "yoyo": "YO_YO"}.get(n, n.upper()) == label
    assert jgr.swap_index("beat", data) == 4 and ids[4] == 0


def test_mipmapped_vq_encodes_and_decodes_like_the_old_texture():
    import struct
    import numpy as np
    from PIL import Image
    from gbox.ninja import pvr_vq, pvr_like, pvr_decode
    w = 64
    yy, xx = np.mgrid[0:w, 0:w]
    img = np.stack([xx * 4, yy * 4, np.full_like(xx, 128)], -1).astype(np.uint8)
    new = pvr_vq(img, pix=1, mips=True)
    q = new.find(b"PVRT")
    assert new[q + 9] == 4 and len(new) - q - 16 == 2048 + 1 + sum((s // 2) ** 2 for s in (2, 4, 8, 16, 32)) + (w // 2) ** 2
    dw, dh, rgba, _ = pvr_decode(new)
    out = np.frombuffer(rgba, np.uint8).reshape(w, w, 4)[..., :3].astype(int)
    assert (dw, dh) == (w, w) and np.abs(out - img).mean() < 12            # full-size level decodes to the image
    old = new[:q + 16] + bytes(len(new) - q - 16) + b"\xaa" * 40         # an old fmt-4 texture with tail padding
    like = pvr_like(old, Image.fromarray(img))
    assert len(like) == len(old) and like[:q + 16] == old[:q + 16] and like.endswith(b"\xaa" * 40)
    assert np.abs(np.frombuffer(pvr_decode(like)[2], np.uint8).reshape(w, w, 4)[..., :3].astype(int) - img).mean() < 12


def test_beat_texture_0_is_mipmapped_vq_and_re_encodes_on_owned_disc():
    import numpy as np
    from PIL import Image
    from gbox import jgr
    from gbox.ninja import pvr_like, pvr_decode
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    data = _player_afs(gdi)
    _, ptex = jgr.character_pair(data, jgr.swap_index("beat", data))
    t0 = jgr.ptex_textures(data, ptex)[jgr.ATLAS_TEXTURE]
    q = t0["bytes"].find(b"PVRT")
    assert t0["bytes"][q + 9] == 4                                   # Beat's body texture: VQ with mipmaps
    w, h, rgba, _ = pvr_decode(t0["bytes"])
    img = Image.frombytes("RGBA", (w, h), rgba)
    new = pvr_like(t0["bytes"], img)
    assert len(new) == len(t0["bytes"])
    back = np.frombuffer(pvr_decode(new)[2], np.uint8).reshape(h, w, 4)[..., :3].astype(int)
    assert np.abs(back - np.asarray(img)[..., :3].astype(int)).mean() < 16   # re-encoding Beat's own texture keeps it


def test_replace_entries_in_place_keeps_length_and_other_entries():
    import pytest
    from gbox import jgr
    data, offs = _afs([b"PLAY" + b"a" * 100, b"PTEX" + b"b" * 3000, b"main" + b"c" * 10])
    assert jgr.entry_room(data, offs[0]) == 0x800 and jgr.entry_room(data, offs[1]) == 0x1000
    new = jgr.replace_entries(data, {offs[1]: b"PTEX" + b"z" * 4000})
    assert len(new) == len(data)
    _, o2, s2 = jgr.afs_entries(new)
    assert o2 == offs and s2 == [104, 4004, 14]
    assert new[offs[0]:offs[0] + 104] == data[offs[0]:offs[0] + 104]
    assert new[offs[2]:] == data[offs[2]:]
    assert new[offs[1] + 4004:offs[2]] == bytes(offs[2] - offs[1] - 4004)
    with pytest.raises(ValueError):
        jgr.replace_entries(data, {offs[0]: b"PLAY" + b"x" * 0x800})


def test_pack_blobs_places_without_overlap_and_prefers_home():
    from gbox import jgr
    holes = [(0x100, 0x200), (0x400, 0x480), (0x800, 0x900)]
    sizes = {("v", 1): 0xF0, ("p", 1): 0x30, ("v", 2): 0x7E, ("m", 1): 24, ("m", 2): 24}
    at = jgr.pack_blobs(holes, sizes, {("v", 2): 0x400})
    assert at[("v", 2)] == 0x400                          # back in the hole its old list held
    spans = sorted((at[k], at[k] + ((s + 3) & ~3)) for k, s in sizes.items())
    for a, b in spans:
        assert any(h0 <= a and b <= h1 for h0, h1 in holes)
    for (_, b), (c, _) in zip(spans, spans[1:]):
        assert b <= c                                      # no two blobs share bytes


def test_pack_blobs_reports_stranded_list():
    # JGR character 00 at 300 triangles: five lists over 2.8 KB, four holes big enough, and the two smallest of
    # them overshoot the biggest hole by 28 bytes. The error names the stranded list and both totals (#1155).
    import pytest
    from gbox import jgr
    holes, o = [], 0
    for n in (5652, 5296, 4256, 4244, 2788):
        holes.append((o, o + n))
        o += n + 0x34                                      # a node struct between every hole
    sizes = {("v", 15): 4340, ("v", 10): 3500, ("v", 11): 3396, ("v", 4): 2852, ("v", 7): 2828}
    with pytest.raises(ValueError, match=r"found no hole") as e:
        jgr.pack_blobs(holes, sizes, tries=500)
    assert "16916 bytes of lists need placing, 22236 bytes are free" in str(e.value)
    sizes[("v", 7)] = 2800                                 # two fewer vertices: 2852 + 2800 fits the 5652 hole
    at = jgr.pack_blobs(holes, sizes, tries=500)
    assert len(at) == 5
