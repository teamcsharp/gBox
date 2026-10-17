"""Metal Gear Solid 2 Substance (PS2): disc layers, STAGE archives (cipher, pages), kms / texture packs, the reader,
the cast writer, pick-whip slot mapping and registrations - on synthetic data (tests/mgs2_synth.py); the owned-disc
checks skip without the catalog's CHD / ISO."""
import inspect
import json
import os
import struct
import zlib
from pathlib import Path

import numpy as np
import pytest

from gbox import mgs2_inventory as inv
from gbox import mgs2_models as M
from gbox import mgs2_swap as S
from gbox import ps2_gs as G
from mgs2_synth import (BONES, FAKE_ELF, checker, humanoid_kms, make_dvd, palette, stage_blob, stage_dat,
                        texture_pack)

SNA, SNA_MT, BDN = inv.name_hash("sna_def"), inv.name_hash("sna_def_mt"), inv.name_hash("sna_mugen_bdn1")
OTHER, OTHER_TEX = 0x123456, 0x654321


# ---------------------------------------------------------------- hash + cipher
def test_name_hash():
    assert inv.name_hash("w00a") == 0x3C4661 and inv.name_hash("sna_def") == 0x413AA8
    assert inv.name_hash("") == 1 and all(inv.name_hash(n) < 1 << 24 for n in ("a" * 40, "rai_def", "gbs_def"))


def _ref(k, step, data):
    n = len(data) // 4
    w = list(struct.unpack_from(f"<{n}I", data))
    for i in range(n):
        w[i] ^= k
        k = (k * 0x02E90EDD + step) & 0xFFFFFFFF
    return struct.pack(f"<{n}I", *w) + data[4 * n:], k


def test_cipher_matches_the_loop_and_carries_state():
    data = os.urandom(4 * 3001 + 3)
    c = inv.Cipher(0x9ABCDEF0, 0x13579BDF)
    out = c.run(data[:4 * 1000]) + c.run(data[4 * 1000:])
    ref, k = _ref(0x9ABCDEF0, 0x13579BDF, data)
    assert out == ref and c.k == k
    assert inv.Cipher(5, 7).run(inv.Cipher(5, 7).run(data)) == data
    assert inv.Cipher(1, 2).run(b"\0" * 8) == struct.pack("<2I", 1, 0x02E90EDD + 2)


def test_page_round_trip_and_the_fixed_header():
    data = bytes(range(256)) * 300
    for seed in (0, 0x5A5A, 0xFFFF):
        raw = inv.encode_page(data, seed)
        assert struct.unpack_from("<H", raw, 0)[0] == seed
        assert inv.decode_page(raw, len(data)) == data
        plain = inv.Cipher.for_page(seed).run(raw)
        assert struct.unpack_from("<H", plain, 0)[0] == 0x9385      # 78 9c - 0x8f3
    with pytest.raises(inv.FormatError):
        inv.decode_page(inv.encode_page(data), len(data) + 1)
    with pytest.raises(inv.FormatError):
        inv.decode_page(b"\x01\x02\x03\x04" * 8)


# ---------------------------------------------------------------- GS memory
def test_gs_tables_and_round_trips():
    # the derived PSMT8 in-page table equals the published columnTable8 / blockTable8 (first block + block order)
    assert G.P8[0, :8].tolist() == [0, 4, 16, 20, 32, 36, 48, 52] and G.P8[2, :4].tolist() == [33, 37, 49, 53]
    assert (G.P8[:64:16, :128:16] // 256).tolist() == G.BT32.tolist()
    assert sorted(G.CT4.reshape(-1).tolist()) == list(range(512))
    m = G.GSMemory(1 << 20)
    i8 = np.random.default_rng(1).integers(0, 256, (128, 256)).astype(np.uint8)
    m.write8(i8, 16, 4)
    assert (m.read8(16, 4, 256, 128) == i8).all()
    i4 = np.random.default_rng(2).integers(0, 16, (256, 128)).astype(np.uint8)
    m.write4(i4, 512, 2)
    assert (m.read4(512, 2, 128, 256) == i4).all()
    raw = os.urandom(64 * 4 * 64)
    m.load_linear(raw, 0)
    assert m.dump_linear(0, len(raw) // 256) == raw
    p = np.random.default_rng(3).integers(0, 256, (256, 4)).astype(np.uint8)
    assert (G.csm1(G.csm1(p)) == p).all()


# ---------------------------------------------------------------- kms + texture packs
def test_kms_parse_strips_weights_and_roles():
    b = humanoid_kms(SNA_MT, 0xAAAA01)
    k = M.parse_kms(b)
    assert len(k["meshes"]) == len(BONES) and k["tex"] == SNA_MT
    assert M.triangles(k) == 12 * len(BONES)
    g = M.assemble(k)[0xAAAA01]
    assert len(g["tris"]) == 12 * len(BONES)
    # strips settled to the normals: every face points outward from its bone
    P, T = g["pos"], g["tris"]
    fn = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
    c = (P[T[:, 0]] + P[T[:, 1]] + P[T[:, 2]]) / 3
    bone = g["joints"][T[:, 0], 0]
    centre = k["world"][bone]
    assert ((fn * (c - centre)).sum(1) > 0).all()
    w = g["weights"]
    assert np.allclose(w.sum(1), 1) and (w[:, 1] > 0).any()
    roles = M.roles_of(k["parents"], k["world"])
    assert roles["hip"] == 0 and roles["head"] == 12 and roles["r_hand"] == 6 and roles["l_foot"] == 19
    assert roles["r_thigh"] == 13 and k["world"][roles["r_thigh"]][0] < 0
    assert M.strip_triangles(np.array([True, True, False, False, True, True, False])) == [(0, 1, 2), (1, 2, 3), (4, 5, 6)]
    with pytest.raises(M.FormatError):
        M.parse_kms(b[:0x80])


def _pack(entries=None):
    return texture_pack(entries or [
        {"hash": 0xAAAA01, "rect": (0, 0, 64, 64), "index": checker(), "palette": palette(1), "tbp": 0x10, "tbw": 8,
         "cbp": 0},
        {"hash": OTHER_TEX, "rect": (384, 0, 448, 64), "index": checker(a=9, b=99), "palette": palette(2),
         "tbp": 0x10, "tbw": 8, "cbp": 4}])


def test_texture_pack_decodes_each_entry():
    tp = M.TexturePack(_pack())
    img = tp.image(0xAAAA01)
    pal = palette(1)
    assert img.shape[:2] == (63, 63) or img.shape[:2] == (64, 64)
    assert (img[:8, :8, :3] == pal[3, :3]).all() and (img[:8, 8:16, :3] == pal[200, :3]).all()
    other = tp.image(OTHER_TEX)
    assert (other[:8, :8, :3] == palette(2)[9, :3]).all()
    assert tp.image(0xDEAD) is None


def test_glb_carries_skeleton_weights_textures_and_roles(tmp_path):
    r = M.extract_bytes(humanoid_kms(SNA_MT, 0xAAAA01), [_pack()], tmp_path / "m.glb", "m")
    assert r["verified"] and r["bones"] == len(BONES) and r["textures"] == 1 and not r["missing_textures"]
    from gbox.sm64_swap import load_rig
    rig = load_rig(tmp_path / "m.glb", r["roles"])
    assert len(rig["roles"]) == 18 and abs(rig["joints"][:, 1].min()) < 1.5


# ---------------------------------------------------------------- disc + archive
def _disc_files(extra_stage=b""):
    sna = humanoid_kms(SNA_MT, 0xAAAA01, extra=20000)
    other = humanoid_kms(OTHER_TEX, OTHER_TEX, radius=20)
    bdn = humanoid_kms(SNA_MT, 0xAAAA01, radius=10)
    st1 = stage_blob("r_sna_b", 0x3DB7B4DA, [(0x7F010000, [(0x01, inv.name_hash("r_sna_b"), b"\0" * 2048)]),
                                             (0x7F000002, [(0x13, SNA_MT, _pack()), (0x0A, SNA, sna),
                                                           (0x0A, BDN, bdn), (0x0A, OTHER, other)])])
    st2 = stage_blob("w00a", 0x3DB7B4DA, [(0x7F000002, [(0x0A, OTHER, other), (0x0C, 0x777777, b"motion" * 50)])])
    st4 = stage_blob("r_tnk0", 0x3DB7B4DA, [(0x7F000002, [(0x13, SNA_MT, _pack()), (0x0A, SNA, sna)])])
    dat = stage_dat([("r_sna_b", st1), ("w00a", st2), ("r_tnk0", st4)], slack=6)
    st3 = stage_blob("w51a", 0x3DB7B7DB, [(0x7F000002, [(0x0A, OTHER, other)])])
    dat2 = stage_dat([("w51a", st3)], key=0x3DB7B7DB)
    l0 = {"SYSTEM.CNF": b"BOOT2 = cdrom0:\\SLUS_205.54;1\r\nVER = 1.00\r\nVMODE = NTSC\r\n", "SLUS_205.54": FAKE_ELF,
          "MGS2/STAGE2.DAT": dat2}
    l1 = {"MGS2/STAGE.DAT": dat}
    return make_dvd(l0, l1)


@pytest.fixture()
def dvd(tmp_path, monkeypatch):
    import hashlib
    monkeypatch.setattr(inv, "ELF_SHA256", hashlib.sha256(FAKE_ELF).hexdigest())
    p = tmp_path / "mgs2.iso"
    p.write_bytes(_disc_files())
    return p


def test_two_layers_and_identity(dvd):
    d = inv.Disc(dvd)
    assert d.layer1_start is not None and d.layer1_start == d.layer0 - 16
    lba, size = d.files["MGS2/STAGE.DAT"]
    assert lba > d.layer0 and d.read("MGS2/STAGE.DAT", 0, 4) == struct.pack("<I", 0x3DB7B4DA)
    assert "MGS2/STAGE2.DAT" in d.files and d.files["MGS2/STAGE2.DAT"][0] < d.layer0
    ident = inv.identify(d)
    assert ident["exact_build"] and ident["platform"] == "ps2"
    d.close()


def test_archive_toc_stages_pages_and_rebuild(dvd):
    d = inv.Disc(dvd)
    a = inv.StageArchive(d)
    assert a.names() == ["r_sna_b", "w00a", "r_tnk0"] and a.count == 3
    st = a.stage("r_sna_b")
    assert [p.marker for p in st.pages] == [0x7F010000, 0x7F000002]
    assert {(f[0], f[1]) for f in st.pages[1].files} == {(0x13, SNA_MT), (0x0A, SNA), (0x0A, BDN), (0x0A, OTHER)}
    kms = a.file(st, 0x0A, SNA)
    assert M.parse_kms(kms)["tex"] == SNA_MT
    raw = {k: a.page_raw(st, k) for k in range(2)}
    page = bytearray(a.page(st, 1))
    blob = inv.rebuild_stage(st, a.key, {1: bytes(page)}, raw)
    assert len(blob) == st.sectors * inv.SECTOR
    big = bytes(os.urandom(st.sectors * inv.SECTOR))          # incompressible: can't fit the span
    with pytest.raises(inv.FormatError):
        inv.rebuild_stage(st, a.key, {1: big}, raw)
    inv_ = inv.inventory(dvd)
    assert inv_["archives"]["MGS2/STAGE.DAT"]["stages"] == 3
    d.close()


# ---------------------------------------------------------------- writer pieces
@pytest.fixture(scope="module")
def donor(tmp_path_factory):
    d = tmp_path_factory.mktemp("donor")
    tex = texture_pack([{"hash": 0xD0D0D0, "rect": (0, 0, 64, 64), "index": checker(a=50, b=150),
                         "palette": palette(7), "tbp": 0x10, "tbw": 8, "cbp": 0}])
    r = M.extract_bytes(humanoid_kms(0xD0D0D1, 0xD0D0D0, radius=55), [tex], d / "donor.glb", "donor")
    (d / "meta.json").write_text(json.dumps({"slug": "donor", "name": "Donor", "model": "donor.glb",
                                             "rig": {"roles": r["roles"]}}))
    return d / "donor.glb", r["roles"]


def test_strips_keep_the_game_parity():
    tris = [(0, 1, 2), (2, 1, 3), (2, 3, 4), (4, 3, 5)]          # a CCW quad strip
    s = S.strips(tris)
    assert len(s) == 1 and len(s[0]) == 6
    got = set()
    for k in range(len(s[0]) - 2):
        a, b, c = s[0][k:k + 3]
        got.add((a, b, c) if k % 2 == 0 else (b, a, c))
    norm = lambda t: min(t[i:] + t[:i] for i in range(3))      # noqa: E731
    assert {norm(t) for t in got} == {norm(t) for t in tris}


def test_fit_encode_degenerate_and_atlas(donor):
    glb, roles = donor
    tmpl = humanoid_kms(SNA_MT, 0xAAAA01, extra=20000)
    k = M.parse_kms(tmpl)
    tgt = S.target(k)
    pack = M.TexturePack(_pack())
    plan = S.plan_atlas(pack, S._textures(k), S._usage(k))
    assert plan["hijack"] == 0xAAAA01 and plan["A"] == 256 and plan["clut"] == 0   # OTHER_TEX keeps x >= 384
    fitted = S.fit(glb, roles, tgt)
    tri = S.triangles(fitted, plan["A"])
    r = S.fit_kms(tmpl, fitted, plan["hijack"], tgt, tri)
    assert len(r["data"]) == len(tmpl) and r["triangles"] >= len(tri["pos"]) * 0.9
    k2 = M.parse_kms(r["data"])
    assert k2["parents"] == k["parents"] and {p["tex"][0] for m in k2["meshes"] for p in m["parts"]} <= {plan["hijack"]}
    assert all(len(p["pos"]) <= S.MAX_PART for m in k2["meshes"] for p in m["parts"])
    small = S.fit_kms(tmpl, fitted, plan["hijack"], tgt, tri, budget=r["size"] - 1)
    assert small["cluster"] > 0 and small["size"] < r["size"] and len(small["data"]) == len(tmpl)
    with pytest.raises(S.SwapError):
        S.fit_kms(tmpl, fitted, plan["hijack"], tgt, tri, budget=600)
    deg = S.degenerate_kms(tmpl)
    assert M.triangles(M.parse_kms(deg)) == len(BONES) and len(deg) <= len(tmpl)
    for g in M.assemble(M.parse_kms(deg)).values():                    # zero-area: nothing to see
        P, T = g["pos"], g["tris"]
        assert np.allclose(np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]]), 0)
    newpack = S.write_atlas(_pack(), plan, tri["index"], tri["palette"])
    tp2 = M.TexturePack(newpack)
    assert len(newpack) == len(_pack())
    img = tp2.image(plan["hijack"])
    assert img.shape[0] >= 254 and (tp2.image(OTHER_TEX) == pack.image(OTHER_TEX)).all()
    pal = tri["palette"]
    assert (img[10, 10, :3] == pal[tri["index"][10, 10], :3]).all()


def test_build_disc_rewrites_only_the_slot_stage(dvd, tmp_path, donor):
    glb, roles = donor
    out = tmp_path / "out.iso"
    r = S.build_disc(dvd, out, [{"slot": "snake", "model": glb, "roles": roles, "name": "Donor"},
                                {"slot": "raiden", "model": glb, "roles": {}, "name": "No roles"}])
    reps = {x["slot"]: x for x in r["reports"]}
    assert reps["snake"]["status"] == "built" and reps["raiden"]["status"] == "failed"
    built = [m for m in reps["snake"]["models"] if m["status"] == "built"]
    hidden = [m for m in reps["snake"]["models"] if m["status"] == "hidden"]
    assert len(built) == 2 and len(hidden) == 1 and built[0]["read_back"]
    a0, a1 = inv.Disc(dvd), inv.Disc(out)
    s0, s1 = inv.StageArchive(a0), inv.StageArchive(a1)
    st0, st1 = s0.stage("r_sna_b"), s1.stage("r_sna_b")
    assert s1.file(st1, 0x0A, OTHER) == s0.file(st0, 0x0A, OTHER)                  # other models untouched
    assert s1.file(st1, 0x0A, SNA) != s0.file(st0, 0x0A, SNA)
    assert M.triangles(M.parse_kms(s1.file(st1, 0x0A, BDN))) == len(BONES)           # accessory collapsed
    w0, w1 = s0.stage("w00a"), s1.stage("w00a")
    assert s1.page_raw(w1, 0) == s0.page_raw(w0, 0)                                  # other stages byte-identical
    # every stage that carries the model got its own atlas: the model's texture is the atlas in both
    for name in ("r_sna_b", "r_tnk0"):
        st_ = s1.stage(name)
        k_ = M.parse_kms(s1.file(st_, 0x0A, SNA))
        t_ = {p["tex"][0] for m in k_["meshes"] for p in m["parts"]}
        assert len(t_) == 1
        img = M.TexturePack(s1.file(st_, 0x13, SNA_MT)).image(t_.pop())
        assert img.shape[0] >= 254 and img.shape[1] >= 254
    # everything outside STAGE.DAT's r_sna_b and r_tnk0 spans is byte-identical
    b0, b1 = Path(dvd).read_bytes(), out.read_bytes()
    spans = []
    for name in ("r_sna_b", "r_tnk0"):
        st_ = s0.stage(name)
        lba = a0.files["MGS2/STAGE.DAT"][0] + st_.sector
        spans.append((lba * 2048, (lba + st_.sectors) * 2048))
    spans.sort()
    cut0, cut1, pos = bytearray(), bytearray(), 0
    for lo, hi in spans:
        cut0 += b0[pos:lo]
        cut1 += b1[pos:lo]
        pos = hi
    assert bytes(cut0) + b0[pos:] == bytes(cut1) + b1[pos:] and b0 != b1
    a0.close()
    a1.close()
    assert Path(dvd).read_bytes() == b0                                               # the source untouched


def test_build_cast_reports_per_slot(dvd, tmp_path, donor, monkeypatch):
    glb, roles = donor
    from gbox import filemods

    class Cfg:
        cache = tmp_path / "cache"
    monkeypatch.setattr(filemods, "base_dir", lambda cfg, gid: tmp_path / "base")
    monkeypatch.setattr(S, "base_iso", lambda cfg, game, src, progress=None: Path(src))
    lib = tmp_path / "lib"
    (lib / "donor").mkdir(parents=True)
    (lib / "donor" / "donor.glb").write_bytes(Path(glb).read_bytes())
    meta = {"slug": "donor", "name": "Donor", "model": "donor.glb", "rig": {"roles": roles}}
    # build_mod reads the catalog disc through characters._rom: hand it the synthetic image instead
    monkeypatch.setattr(M, "source_disc", lambda ctx, game: Path(dvd))
    res = S.build_cast(Cfg, {"game_id": inv.GAME_ID}, [("snake", meta), ("olga", meta)], "cast_test", root=lib)
    assert res["mod"] == "cast_test" and res["slots"]["snake"]["status"] == "built"
    assert res["slots"]["olga"]["status"] == "failed"                    # olga's models are not on the synthetic disc
    mj = json.loads((tmp_path / "cache" / "mods" / inv.GAME_ID / "cast_test" / ".gbox-mod.json").read_text())
    assert mj["writer"] == "gbox.mgs2_swap" and mj["image"].endswith(".iso")


# ---------------------------------------------------------------- slots, pick whip, registrations
def test_slots_and_pick_whip_names():
    rows = {r["slot"]: r for r in S.cast_slots()}
    assert rows["player"]["aggregate"] and rows["soldiers"]["aggregate"]
    assert {"snake", "raiden", "soldier_tanker", "soldier_plant", "olga", "ocelot"} <= set(rows)
    assert S.resolve_slot("player") == ["snake", "raiden"] and S.resolve_slot("Solid Snake") == ["snake"]
    assert set(S.resolve_slot("soldiers")) >= {"soldier_tanker", "soldier_plant", "soldier_hightech"}
    assert S.slot_for_name("a soldier in grey camo", "w12a") == "soldier_plant"
    assert S.slot_for_name("the guard", "w00a") == "soldier_tanker"
    assert S.slot_for_name("heavy armored soldier", "w01b") == "soldier_tanker_heavy"
    assert S.slot_for_name("man with a ponytail", None, kind="player") == "snake"
    assert S.slot_for_name("", "w20a", kind="player") == "raiden"
    assert S.slot_for_name("Revolver Ocelot") == "ocelot" and S.slot_for_name("Iroquois Pliskin") == "pliskin"
    with pytest.raises(S.SwapError):
        S.resolve_slot("dog")
    assert S.STAGE_NAMES()[inv.name_hash("w00a")] == "w00a" and len(S.STAGE_LIST) > 250


def test_pick_whip_live_use_builds_the_whipped_slot_and_swaps_the_session(tmp_path, monkeypatch):
    """live_use from the pick whip: the stage is read from EE RAM, the target name picks the slot, the mod is built
    and launched into the session (session_swap keeps the moment)."""
    from gbox import characters as C
    calls = []
    ram = {S.STAGE_STATE_PTR: struct.pack("<I", 0x00400000), 0x00400000 + 0x3C: struct.pack("<I", inv.name_hash("w00a"))}

    def api(ctx, method, path, **kw):
        calls.append((method, path, kw.get("json")))
        if path.endswith("/rpc"):
            a = kw["json"]["args"]
            return ram[a["address"]].hex()
        if path == "/api/jobs":
            return {"id": "job1"}
        return {}
    monkeypatch.setattr(C, "_api", api)
    monkeypatch.setattr(C, "library_root", lambda cfg=None: tmp_path)
    built = []
    monkeypatch.setattr(S, "build_mod", lambda cfg, game, pairs, progress=None, title=None, **kw:
                        built.append(pairs) or {"mod": "m", "image": "x.iso", "reports": []})

    class Inp:
        op, character, session_id, slot, rebuild, launch = "live_use", "sonic", "w1-abc", "player", False, True
        x, y, target, pairs, title = 0.4, 0.5, "a soldier with a rifle", None, None

    class Ctx:
        class config:
            cache = tmp_path

        @staticmethod
        def progress(p, m):
            pass
    meta = {"slug": "sonic", "name": "Sonic"}
    r = S.use(Ctx, meta, {"game_id": inv.GAME_ID}, Inp)
    assert r["stage"] == "w00a" and r["slot"] == "soldier_tanker" and r["picked"] == "soldier_tanker"
    assert built and built[0][0][1] == "soldier_tanker" and r["status"] == "launching"
    launch = [c for c in calls if c[1] == "/api/jobs"][-1][2]
    assert launch["tool"] == "@launch" and launch["input"]["session_id"] == "w1-abc"
    # no name, no stage -> the player slot of the Tanker (Snake)
    ram.clear()
    Inp.target = ""
    built.clear()
    r = S.use(Ctx, meta, {"game_id": inv.GAME_ID}, Inp)
    assert r["slot"] == "snake" and r["stage"] is None


def test_registrations_and_platform():
    from gbox import cast_swap, char_coverage, characters as C, systems
    game = {"game_id": inv.GAME_ID, "title": "Metal Gear Solid 2: Substance (USA)", "platform": "windows_native"}
    for plat in ("windows_native", "ps2"):
        name, ros = char_coverage.extractor_for(game | {"platform": plat})
        assert name == "mgs2" and {"mgs2_snake", "mgs2_raiden", "mgs2_gurlukovich_soldier"} <= {r["slug"] for r in ros}
    w = char_coverage.writer_for(game)
    assert w["writer"] == "gbox.mgs2_swap" and w["routed"]
    assert {"player", "snake", "soldiers"} <= {s["slot"] for s in char_coverage.cast_slots(game)}
    assert cast_swap.strategy("gbox.mgs2_swap")[0] == "pairs" and "gbox.mgs2_swap" in cast_swap.BUILDERS
    src = inspect.getsource(C.characters_tool)
    assert "mgs2_swap.use(" in src and "mgs2_swap.GAME_IDS" in src
    assert "target" in C.CharIn.model_fields
    # HyperSpin's "Microsoft XBOX" emulator lists the PS2 rom folder: those discs are PS2 games
    assert systems.classify("Microsoft XBOX", "Microsoft XBOX", "collections/Sony Playstation 2/roms/USA")[:2] == \
        ("ps2", "pcsx2")
    assert systems.classify("Microsoft XBOX", "Microsoft XBOX", "collections/Microsoft XBOX/roms")[0] == "xbox"
    assert systems.classify("PC Games", "PC Games", "collections/PC Games/roms")[0] == "windows_native"


def test_attract_scan_files_the_ps2_disc_under_ps2(tmp_path):
    from gbox import catalog
    root = tmp_path / "Arcade"
    (root / "emulators").mkdir(parents=True)
    (root / "romlists").mkdir()
    ps2 = root / "collections" / "Sony Playstation 2" / "roms" / "USA"
    ps2.mkdir(parents=True)
    (ps2 / "Metal Gear Solid 2 - Substance (USA).chd").write_bytes(b"MComprHD")
    (root / "emulators" / "Microsoft XBOX.cfg").write_text(
        "executable x\nrompath collections\\Microsoft XBOX\\roms;collections\\Sony Playstation 2\\roms\\USA\n"
        "romext .iso;.chd\nsystem Microsoft XBOX\n")
    (root / "emulators" / "Sony PlayStation 2.cfg").write_text(
        "executable x\nrompath collections\\Sony PlayStation 2\\roms\\USA\nromext .chd\nsystem Sony PlayStation 2\n")
    (root / "romlists" / "Microsoft XBOX.txt").write_text(
        "#Name;Title;Emulator;CloneOf;Year;Manufacturer;Category\n"
        "Metal Gear Solid 2 - Substance (USA);Metal Gear Solid 2: Substance (USA);Microsoft XBOX;;2002;Konami;Action\n")
    games, _problems, _stats = catalog.scan_attract(root, "hyperspin")
    g = next(e for e in games if "Metal Gear" in e.title)
    assert g.platform == "ps2" and g.core == "pcsx2"


# ---------------------------------------------------------------- owned disc (skipped without it)
OWNED = [Path(p) for p in (os.environ.get("GBOX_MGS2_PS2_DISC") or "",
                           "D:/gBox/cache/modbase/cb7aae71edb10cd3/Metal Gear Solid 2 - Substance (USA).iso",
                           "//10.89.1.125/HyperSpin Attraction/Arcade/" + inv.CATALOG_REL) if p]


def _owned():
    for p in OWNED:
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None


@pytest.mark.skipif(_owned() is None, reason="the owned MGS2 disc is not reachable")
def test_owned_disc_archives_and_snake(tmp_path):
    d = inv.Disc(_owned())
    ident = inv.identify(d)
    assert ident["exact_build"] and ident["layer1_start"] == inv.LAYER0_SECTORS - 16
    a1, a2 = inv.StageArchive(d, "MGS2/STAGE.DAT"), inv.StageArchive(d, "MGS2/STAGE2.DAT")
    assert a1.count == 129 and a2.count == 165 and "r_sna_b" in a1.names()
    st = a1.stage("r_sna_b")
    kms = a1.file(st, inv.T_KMS, SNA)
    pack = a1.file(st, inv.T_TEX, M.parse_kms(kms)["tex"])
    r = M.extract_bytes(kms, [pack], tmp_path / "snake.glb", "snake")
    assert r["verified"] and len(r["roles"]) == 18 and 1.7 < r["height_m"] < 2.1 and not r["missing_textures"]
    d.close()
