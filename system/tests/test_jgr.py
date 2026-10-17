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


# ---- Public native targeting and immutable cache identity (no native execution) ----
def _binding_afs(ids=USA_NATIVE_IDS):
    entries = []
    for native in ids:
        play = bytearray(0xa0)
        struct.pack_into("<4sII", play, 0, b"PLAY", 1, 0x10)
        struct.pack_into("<i", play, 0x10, native)
        entries += [bytes(play), b"PTEX" + bytes(12)]
    return _afs(entries)


def test_native_ids_validate_actual_binding_records_without_monkeypatch():
    data, _ = _binding_afs()
    assert jgr.native_ids(data) == USA_NATIVE_IDS
    assert jgr.swap_index("player", data, active_id=0) == 4
    assert jgr.swap_index("id:7", data) == 0


@pytest.mark.parametrize("failure", ["duplicate", "negative", "misaligned", "record_overrun", "short_entry", "afs_overrun"])
def test_native_ids_reject_invalid_or_truncated_records(failure):
    data, offsets = _binding_afs()
    data = bytearray(data)
    if failure == "duplicate":
        struct.pack_into("<i", data, offsets[0] + 0x10, USA_NATIVE_IDS[1])
    elif failure == "negative":
        struct.pack_into("<i", data, offsets[0] + 0x10, -1)
    elif failure == "misaligned":
        struct.pack_into("<I", data, offsets[0] + 8, 0x11)
    elif failure == "record_overrun":
        struct.pack_into("<I", data, offsets[0] + 8, 0x18)
    elif failure == "short_entry":
        struct.pack_into("<I", data, 12, 8)
    else:
        struct.pack_into("<I", data, 12, len(data))
    with pytest.raises(ValueError):
        jgr.native_ids(bytes(data))


@pytest.mark.parametrize("native", [0, 7, 15, None])
def test_public_active_id_schema_keeps_bounded_ids_and_existing_character_guards(native):
    from gbox.characters import CharIn
    inp = CharIn(op="use", character="sa2_amy_rose", active_id=native, launch=False)
    assert inp.active_id == native and "active_id" in inp.model_dump()
    with pytest.raises(ValueError):
        CharIn(op="use", active_id=native)
    assert "rig_roles" in CharIn.model_fields


@pytest.mark.parametrize("native", [-1, 16, True, "0", 1.5])
def test_public_active_id_rejects_invalid_or_coerced_ids(native):
    from gbox.characters import CharIn
    with pytest.raises(ValueError):
        CharIn(op="use", character="sa2_amy_rose", active_id=native)
    with pytest.raises(ValueError):
        jgr.swap_index("player", b"not read", active_id=native)


@pytest.fixture
def cache_case(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from gbox import characters as C, gdrom
    root = tmp_path / "characters"
    donor = root / "amy"
    donor.mkdir(parents=True)
    model = donor / "model.gltf"
    model.write_text(json.dumps({"asset": {"version": "2.0"}, "nodes": [], "buffers": [],
                                 "images": [{"uri": "texture.bin"}]}))
    (donor / "texture.bin").write_bytes(b"original texture resource")
    meta = {"slug": "amy", "name": "Amy", "model": model.name, "rig": {"roles": {"hip": "hip"}}}
    game = {"game_id": "4187aeab4d67638c", "title": "Jet Grind Radio (USA)", "platform": "dreamcast"}
    data, _ = _binding_afs()
    calls = {"read": [], "build": [], "posted": []}
    monkeypatch.setattr(C, "library_root", lambda cfg: root)
    monkeypatch.setattr(C, "_dc_gdi", lambda ctx, g: calls["read"].append("source") or tmp_path/"original.gdi")
    monkeypatch.setattr(jgr, "body_root", lambda blob, play: 0x100)
    monkeypatch.setattr(gdrom, "GDRom", lambda path: SimpleNamespace(read=lambda name: data))
    monkeypatch.setattr(C, "_api", lambda ctx, method, path, **kw: calls["posted"].append((method, path, kw)))
    monkeypatch.setattr(C, "_launch", lambda *args: pytest.fail("No emulator launch is permitted in this test"))
    ctx = SimpleNamespace(config=SimpleNamespace(cache=str(tmp_path/"cache")), progress=lambda *args: None)
    identity = jgr.cache_identity(data, model, meta, game, 4)
    real_build_mod = jgr.build_mod
    def build(cfg, m, g, gdi, index, progress, **kwargs):
        calls["build"].append({"index": index, **kwargs})
        return {"mod": kwargs["name"], "report": {"triangles": 21}}
    monkeypatch.setattr(jgr, "build_mod", build)
    return SimpleNamespace(root=root, model=model, meta=meta, game=game, data=data, calls=calls,
                           ctx=ctx, identity=identity, donor=donor, real_build_mod=real_build_mod)


def _cached(case, *, identity=None, name=None):
    import json
    from gbox import filemods
    name = name or jgr._mod_name(case.meta, 4, case.identity)
    folder = filemods.mod_dir(case.ctx.config, case.game["game_id"], name)
    folder.mkdir(parents=True)
    (folder / "owned.gdi").write_bytes(b"untouched owned image")
    manifest = {"name": name, "game_id": case.game["game_id"], "image": "owned.gdi",
                "character": case.meta["slug"], "cache_identity": case.identity if identity is None else identity}
    (folder / ".gbox-mod.json").write_text(json.dumps(manifest))
    return folder


def test_donor_cache_fingerprint_covers_external_resources_and_retarget_settings(cache_case):
    case = cache_case
    first = jgr.donor_fingerprint(case.model, case.meta["rig"]["roles"])
    (case.donor / "texture.bin").write_bytes(b"changed external texture")
    changed = jgr.donor_fingerprint(case.model, case.meta["rig"]["roles"])
    assert changed != first
    assert jgr.donor_fingerprint(case.model, {"hip": "different_joint"}) != changed
    assert jgr.donor_fingerprint(case.model, case.meta["rig"]["roles"], {"head": 2}) != changed
    (case.donor / "texture.bin").unlink()
    with pytest.raises(OSError):
        jgr.donor_fingerprint(case.model, case.meta["rig"]["roles"])


@pytest.mark.parametrize("field", ["donor_slug", "donor_sha256", "source_afs_sha256", "archive_index", "native_id", "body_root"])
def test_use_refuses_mismatched_cached_identity_without_altering_files(cache_case, field):
    from gbox.characters import CharIn
    case = cache_case
    bad = dict(case.identity)
    bad[field] = "different" if isinstance(bad[field], str) else 7
    folder = _cached(case, identity=bad)
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    with pytest.raises(ValueError, match="files were preserved"):
        jgr.use(case.ctx, case.meta, case.game, CharIn(op="use", character="amy", slot="id:0", launch=False))
    assert before == {p.name: p.read_bytes() for p in folder.iterdir()}
    assert not case.calls["build"] and not case.calls["posted"]


def test_use_reuses_only_matching_cache_and_exposes_unverified_runtime(cache_case):
    from gbox.characters import CharIn
    case = cache_case
    folder = _cached(case)
    result = jgr.use(case.ctx, case.meta, case.game,
                     CharIn(op="use", character="amy", slot="player", active_id=0, launch=False))
    assert result["mod"] == folder.name and result["status"] == "ready"
    assert result["target"]["native_id"] == 0 and result["target"]["archive_index"] == 4
    assert result["target"]["body_selection"] == "max_triangles_unverified"
    assert result["runtime_verified"] is False
    assert not case.calls["build"] and not case.calls["posted"]


def test_unknown_player_refuses_before_read_build_or_launch(cache_case):
    from gbox.characters import CharIn
    case = cache_case
    with pytest.raises(ValueError, match="active native character ID is unknown"):
        jgr.use(case.ctx, case.meta, case.game, CharIn(op="use", character="amy", launch=False))
    assert not any(case.calls.values())


def test_legacy_cache_requires_separate_rebuild_and_preserves_original(cache_case):
    from gbox.characters import CharIn
    case = cache_case
    folder = _cached(case, identity={}, name=jgr._mod_name(case.meta, 4))
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    with pytest.raises(ValueError, match="rebuild=true"):
        jgr.use(case.ctx, case.meta, case.game, CharIn(op="use", character="amy", slot="id:0", launch=False))
    result = jgr.use(case.ctx, case.meta, case.game,
                     CharIn(op="use", character="amy", slot="id:0", rebuild=True, launch=False))
    assert result["mod"] != folder.name and result["status"] == "built"
    assert case.calls["build"][0]["identity"] == case.identity
    assert before == {p.name: p.read_bytes() for p in folder.iterdir()}


def test_explicit_rebuild_of_checked_cache_uses_new_directory(cache_case):
    from gbox.characters import CharIn
    case = cache_case
    folder = _cached(case)
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    result = jgr.use(case.ctx, case.meta, case.game,
                     CharIn(op="use", character="amy", slot="id:0", rebuild=True, launch=False))
    assert result["mod"].startswith(folder.name + "_") and result["mod"] != folder.name
    assert before == {p.name: p.read_bytes() for p in folder.iterdir()}


def test_changed_source_target_or_root_has_a_distinct_cache_name(cache_case, monkeypatch):
    case = cache_case
    name = jgr._mod_name(case.meta, 4, case.identity)
    modified = bytearray(case.data)
    modified[-1] ^= 1
    changed_source = jgr.cache_identity(bytes(modified), case.model, case.meta, case.game, 4)
    assert changed_source["source_afs_sha256"] != case.identity["source_afs_sha256"]
    assert jgr._mod_name(case.meta, 4, changed_source) != name
    changed_actor = jgr.cache_identity(case.data, case.model, case.meta, case.game, 0)
    assert changed_actor["native_id"] == 7 and changed_actor["archive_index"] == 0
    assert jgr._mod_name(case.meta, 0, changed_actor) != name
    monkeypatch.setattr(jgr, "body_root", lambda blob, play: 0x200)
    changed_root = jgr.cache_identity(case.data, case.model, case.meta, case.game, 4)
    assert changed_root["body_root"] == "0x200"
    assert jgr._mod_name(case.meta, 4, changed_root) != name


@pytest.mark.parametrize("destination", ["mod", "targets"])
def test_build_mod_refuses_existing_output_instead_of_overwriting_user_files(cache_case, destination):
    from gbox import filemods
    case = cache_case
    name = jgr._mod_name(case.meta, 4, case.identity)
    directory = (filemods.mod_dir(case.ctx.config, case.game["game_id"], name) if destination == "mod"
                 else case.donor / "targets" / name)
    directory.mkdir(parents=True)
    marker = directory / "user-file.txt"
    marker.write_bytes(b"preserve this user content")
    with pytest.raises(ValueError, match="already exists"):
        case.real_build_mod(case.ctx.config, case.meta, case.game, "original.gdi", 4,
                            root=case.root, identity=case.identity)
    assert marker.read_bytes() == b"preserve this user content"
    assert list(directory.iterdir()) == [marker]


def test_build_mod_refuses_changed_identity_before_creating_output(cache_case):
    from gbox import filemods
    case = cache_case
    changed = dict(case.identity, body_root="0x200")
    with pytest.raises(ValueError, match="identity changed before building"):
        case.real_build_mod(case.ctx.config, case.meta, case.game, "original.gdi", 4,
                            root=case.root, identity=changed)
    assert not filemods.mod_dir(case.ctx.config, case.game["game_id"], jgr._mod_name(case.meta, 4, changed)).exists()


def test_new_build_persists_identity_in_exclusive_paths_without_replacing_prior_assets(cache_case, monkeypatch):
    import json
    from types import SimpleNamespace
    from gbox import characters as C, filemods, gdrom
    case = cache_case
    old = case.donor / "targets" / "jgr_preview.png"
    old.parent.mkdir()
    old.write_bytes(b"earlier user preview")
    monkeypatch.setattr(C, "_blender", lambda cfg: None)
    def build_swap(gdi, model, roles, work, name, *args):
        rigged = work / "rigged.gltf"
        rigged.write_bytes(b"synthetic retarget result")
        report = {key: case.identity[key] for key in ("archive_index", "native_id", "source_afs_sha256", "body_root")}
        report.update(triangles=21, runtime_verified=False)
        return {"report": report, "rigged": rigged, "files": {jgr.PLAYER_AFS: b"synthetic changed archive"},
                "atlas": SimpleNamespace(save=lambda path: Path(path).write_bytes(b"synthetic atlas"))}
    def patch(gdi, directory, name, files, progress):
        image = directory / (name + ".gdi")
        with image.open("xb") as output:
            output.write(b"synthetic image")
        return image
    monkeypatch.setattr(jgr, "build_swap", build_swap)
    monkeypatch.setattr(gdrom, "patch_gdi", patch)
    monkeypatch.setattr(C, "render_preview", lambda model, output: output.write_bytes(b"synthetic preview"))
    result = case.real_build_mod(case.ctx.config, case.meta, case.game, "original.gdi", 4,
                                 root=case.root, identity=case.identity)
    directory = filemods.mod_dir(case.ctx.config, case.game["game_id"], result["mod"])
    manifest = json.loads((directory / ".gbox-mod.json").read_text())
    assert manifest["cache_identity"] == case.identity
    assert jgr.validate_cached_mod(directory, case.identity, case.meta) == manifest
    assert manifest["report"]["runtime_verified"] is False
    assert Path(result["rigged"]).parent == case.donor / "targets" / result["mod"]
    assert old.read_bytes() == b"earlier user preview"
    assert not any((Path(case.ctx.config.cache) / "characters_build").iterdir())


@pytest.mark.parametrize("image", ["missing.gdi", "../outside.gdi", "other.chd"])
def test_cached_image_must_exist_inside_the_mod_directory(cache_case, image):
    import json
    case = cache_case
    folder = _cached(case)
    manifest_path = folder / ".gbox-mod.json"
    record = json.loads(manifest_path.read_text())
    record["image"] = image
    manifest_path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="local GDI"):
        jgr.validate_cached_mod(folder, case.identity, case.meta)


def test_jgr_coverage_advertises_explicit_ids_and_native_verification_limit():
    from gbox import char_coverage
    writer = char_coverage.writer_for({"game_id": "4187aeab4d67638c", "title": "Jet Grind Radio (USA)",
                                      "platform": "dreamcast"})
    assert writer["routed"] and "id:<N>" in writer["slots"]
    assert "unverified" in writer["replaces"]


def _named_afs(names=None):
    data, _ = _binding_afs()
    blob = bytearray(data)
    count, offsets, sizes = jgr.afs_entries(blob)
    directory = len(blob)
    blob.extend(bytes(count * 48))
    struct.pack_into("<II", blob, min(offsets) - 8, directory, count * 48)
    names = names or [name + suffix for name in jgr.ARCHIVE_NAMES for suffix in ("dat.bin", "txr.bin")]
    for index, (name, size) in enumerate(zip(names, sizes)):
        raw = name.encode("ascii")
        blob[directory + 48 * index:directory + 48 * index + len(raw)] = raw
        struct.pack_into("<I", blob, directory + 48 * index + 44, size)
    return blob, directory


def test_names_resolve_verified_resources_and_reordered_archive(monkeypatch):
    for name, index in {"beat": 4, "ereki": 4, "erekidat.bin": 4, "bis": 0, "gum": 6, "combo": 2,
                        "conpo": 2, "nuts": 7, "pench": 8, "yo_yo": 15, "Rival-NTank": 12}.items():
        assert jgr.swap_index(name) == index
    data, _ = _named_afs()
    assert jgr.character_names(data) == jgr.ARCHIVE_NAMES
    assert jgr.swap_index("beat", data) == 4
    monkeypatch.setattr(jgr, "character_names", lambda data: list(reversed(jgr.ARCHIVE_NAMES)))
    monkeypatch.setattr(jgr, "native_ids", lambda data: list(reversed(USA_NATIVE_IDS)))
    loads = []
    assert jgr.swap_index("beat", lambda: loads.append(1) or data) == 11 and loads == [1]


def test_named_roster_preserves_slugs_without_claiming_active_player():
    rows = jgr.roster()
    assert [row["slug"] for row in rows] == [f"jgr_char{i:02d}" for i in range(16)]
    assert rows[4]["name"] == "Beat (JGR ereki, ID 0)" and rows[4]["native_id"] == 0
    assert "JGR character 0" in rows[0]["aliases"] and "BIS" in rows[0]["aliases"]
    with pytest.raises(ValueError, match="active native character ID is unknown"):
        jgr.swap_index("player", lambda: pytest.fail("Unknown player must not read the archive"))
    with pytest.raises(ValueError, match="no JGR character has that name"):
        jgr.swap_index("sonic")


@pytest.mark.parametrize("failure", ["size", "extent", "non_ascii", "truncated_entry", "bad_filename", "duplicate"])
def test_named_archive_rejects_invalid_or_ambiguous_directory(failure):
    data, directory = _named_afs()
    _, offsets, _ = jgr.afs_entries(data)
    if failure == "size":
        struct.pack_into("<I", data, directory + 44, 1)
    elif failure == "extent":
        struct.pack_into("<I", data, min(offsets) - 4, len(data) + 1)
    elif failure == "non_ascii":
        data[directory] = 0xff
    elif failure == "truncated_entry":
        struct.pack_into("<I", data, 12, len(data) + 1)
    elif failure == "bad_filename":
        data[directory:directory + 32] = b"../../bisdat.bin".ljust(32, b"\0")
    elif failure == "duplicate":
        data[directory + 2 * 48:directory + 2 * 48 + 32] = b"bisdat.bin".ljust(32, b"\0")
    with pytest.raises(ValueError):
        jgr.swap_index("beat", data)


def test_names_reject_conflicting_native_alias_and_invalid_id_map():
    names = list(jgr.ARCHIVE_NAMES)
    names[4] = "gum"  # Native Beat label would otherwise silently mask another entry's resource name.
    with pytest.raises(ValueError, match="ambiguous"):
        jgr.character_aliases(names, USA_NATIVE_IDS)
    with pytest.raises(ValueError, match="permutation"):
        jgr.character_aliases(jgr.ARCHIVE_NAMES, [True] + USA_NATIVE_IDS[1:])


def test_owned_directory_names_match_native_executable_debug_table():
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    disc = GDRom(str(gdi))
    data = disc.read(jgr.PLAYER_AFS)
    assert jgr.character_names(data) == jgr.ARCHIVE_NAMES
    assert jgr.native_ids(data) == jgr.USA_NATIVE_IDS
    exe, base = disc.read("1ST_READ.BIN"), 0x8c010000
    labels = []
    for index in range(15):
        ptr = struct.unpack_from("<I", exe, 0x8c10df40 - base + 4 * index)[0] - base
        labels.append(exe[ptr:exe.index(b"\0", ptr)].decode("ascii"))
    assert labels[:10] + labels[13:] == [name for name in jgr.NATIVE_DEBUG_NAMES if name]
    assert jgr.swap_index("beat", data) == 4 and jgr.swap_index("gum", data) == 6


def test_owned_beat_mipmapped_body_texture_reencodes_inside_its_extent():
    import numpy as np
    from PIL import Image
    from gbox.ninja import pvr_like, pvr_decode
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    data = _player_afs(gdi)
    _, ptex = jgr.character_pair(data, jgr.swap_index("beat", data))
    texture = jgr.ptex_textures(data, ptex)[jgr.ATLAS_TEXTURE]["bytes"]
    q = texture.find(b"PVRT")
    assert texture[q + 9] == 4
    width, height, rgba, _ = pvr_decode(texture)
    image = Image.frombytes("RGBA", (width, height), rgba)
    encoded = pvr_like(texture, image)
    assert len(encoded) == len(texture) and encoded[:q + 16] == texture[:q + 16]
    end = q + 8 + struct.unpack_from("<I", texture, q + 4)[0]
    assert encoded[end:] == texture[end:]
    decoded = np.frombuffer(pvr_decode(encoded)[2], np.uint8).reshape(height, width, 4)
    assert np.abs(decoded[..., :3].astype(int) - np.asarray(image)[..., :3].astype(int)).mean() < 16


def test_single_root_writer_cache_builds_a_new_identity_and_keeps_old_files(cache_case):
    from gbox.characters import CharIn
    case = cache_case
    previous = dict(case.identity, schema=2)
    old_name = jgr._mod_name(case.meta, 4, previous)
    folder = _cached(case, identity=previous, name=old_name)
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    result = jgr.use(case.ctx, case.meta, case.game,
                     CharIn(op="use", character="amy", slot="id:0", launch=False))
    assert result["mod"] != old_name and result["status"] == "built"
    assert case.calls["build"][0]["identity"]["schema"] == jgr.CACHE_VERSION
    assert before == {p.name: p.read_bytes() for p in folder.iterdir()}
    assert result["runtime_verified"] is False
