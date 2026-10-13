"""#1639 builds on this PC: the download icon's worker op (build_local download = filemods.stage into this PC's cache, never
a launch; locate; export), the export format choice (the same container as the original by default: copy, GCZ / CSO
written here, N64 byte order, zip under the original name, chdman / dolphin-tool / wit when installed, else the plain
image and a notice), plain / patch / zip, and the server routes (GET /api/builds/local, .../formats, POST .../local).
Synthetic files only: no game data, nothing launched, no external program run."""
import json
import struct
import subprocess
import zipfile
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gbox import build_export as BX
from gbox import filemods
from gbox import romexport as RX
from gbox import tools as T
from gbox.registry import Ctx
from tests.test_builds import GID, fixture, get


# ------------------------------------------------------------------------------------------------- the format choice

@pytest.mark.parametrize("src,image,plat,kind,ext,tool", [
    ("Zelda (USA).iso", "game.iso", "gamecube", "copy", ".iso", None),
    ("Zelda (USA).gcm", "game.iso", "gamecube", "copy", ".iso", None),
    ("Zelda (USA).gcz", "Zelda (USA).iso", "gamecube", "gcz", ".gcz", None),
    ("Crazy Taxi (USA).gdi", "disc.gdi", "dreamcast", "copy", ".gdi", None),
    ("Crazy Taxi (USA).chd", "disc.gdi", "dreamcast", "chd", ".chd", "chdman"),
    ("FF7 (Disc 1).cue", "FF7 (Disc 1).cue", "psx", "copy", ".cue", None),
    ("FF7 (Disc 1).bin", "FF7 (Disc 1).cue", "psx", "copy", ".cue", None),
    ("Mario 64 (USA).n64", "Mario 64 (USA).n64", "n64", "copy", ".n64", None),
    ("Mario 64 (USA).v64", "Mario 64 (USA).z64", "n64", "byteswap", ".v64", None),
    ("Mario 64 (USA).zip", "Mario 64 (USA).z64", "n64", "zipimage", ".zip", None),
    ("Metroid (USA).rvz", "Metroid (USA).iso", "gamecube", "dolphin", ".rvz", "dolphin-tool"),
    ("Wii Sports (USA).wbfs", "Wii Sports (USA).iso", "wii", "wit", ".wbfs", "wit"),
    ("Patapon (USA).cso", "Patapon (USA).iso", "psp", "cso", ".cso", None),
    ("doapp.zip", "doapp.zip", "mame", "copy", ".zip", None),
])
def test_same_format_follows_the_original_container(src, image, plat, kind, ext, tool):
    p = BX.choose("same", src, image, plat)
    assert (p["kind"], p["ext"], p.get("tool")) == (kind, ext, tool)
    assert p["label"].startswith("Same format as the original (")


def test_chd_cd_or_dvd_folder_games_and_the_other_formats():
    assert BX.choose("same", "x.chd", "x.iso", "ps2")["chd"] == "createdvd", "a PS2 DVD image"
    assert BX.choose("same", "x.chd", "x.iso", "psx")["chd"] == "createcd", "a CD platform"
    assert BX.choose("same", "x.chd", "x.cue", "ps2")["chd"] == "createcd", "a cue sheet is a CD"
    assert BX.choose("same", "x.chd", "x.iso", "ps2", chd_cd=True)["chd"] == "createcd", "the original CHD's own tracks win"
    ps3 = BX.choose("same", "EBOOT.BIN", "", "ps3", folder=True)
    assert ps3["kind"] == "folder" and ps3["ext"] == "folder"
    x360 = BX.choose("same", "Halo 3.iso", "default.xex", "xbox360", folder=True)
    assert x360["kind"] == "folder" and "the original is .iso" in x360["label"]
    wii = BX.choose("same", "Smash (USA).wbfs", "", "wii", folder=True)
    assert wii["kind"] == "wii_tree" and wii["tool"] == "wit"
    odd = BX.choose("same", "game.7z", "game.iso", "ps2")
    assert odd["kind"] == "copy" and "no .7z writer" in odd["notice"]
    assert BX.choose("plain", "a.gcz", "a.iso", "gamecube") == {"format": "plain", "kind": "copy", "ext": ".iso", "tool": None,
                                                               "label": "Plain image (.iso)"}
    assert BX.choose("patch", "a.gcz", "a.iso")["kind"] == "patch" and BX.choose("patch", "", "", folder=True)["kind"] == "patch_kit"
    assert BX.choose("zip", "a.gcz", "a.iso")["ext"] == ".zip"
    with pytest.raises(ValueError):
        BX.choose("rar", "a.iso", "a.iso")
    opts = BX.options("Crazy Taxi (USA).chd", "disc.gdi", "dreamcast")
    assert [o["id"] for o in opts] == ["same", "plain", "patch", "zip"] and opts[0]["default"]
    assert opts[0]["needs"] == "chdman" and "without it the plain" in opts[0]["note"]
    assert opts[2]["disabled"].startswith("a patch needs a single-image build"), "tracks: no single-image patch"
    assert not BX.options("a.iso", "a.iso")[2].get("disabled")


# ------------------------------------------------------------------------------------------------- writers

def _disc(n=3 * BX.GCZ_BLOCK + 100, wii=False):
    data = bytearray(n)
    if wii:
        struct.pack_into(">I", data, 0x18, 0x5D1C9EA3)
    else:
        struct.pack_into(">I", data, 0x1C, 0xC2339F3D)
    data[BX.GCZ_BLOCK:BX.GCZ_BLOCK * 2] = bytes(range(256)) * (BX.GCZ_BLOCK // 256)   # one compressible block
    import random
    rnd = random.Random(7)
    data[2 * BX.GCZ_BLOCK:3 * BX.GCZ_BLOCK] = bytes(rnd.getrandbits(8) for _ in range(BX.GCZ_BLOCK))  # stored as is
    return bytes(data)


def test_gcz_round_trips_through_dolphins_layout(tmp_path):
    data = _disc()
    (tmp_path / "a.iso").write_bytes(data)
    BX.write_gcz(tmp_path / "a.iso", tmp_path / "a.gcz")
    raw = (tmp_path / "a.gcz").read_bytes()
    magic, sub, csize, dsize, bsize, n = struct.unpack_from("<IIQQII", raw)
    assert (magic, sub, dsize, bsize, n) == (0xB10BC001, 0, len(data), BX.GCZ_BLOCK, 4)
    ptrs = struct.unpack_from(f"<{n}Q", raw, 32)
    hashes = struct.unpack_from(f"<{n}I", raw, 32 + 8 * n)
    assert ptrs[2] >> 63 == 1 and ptrs[1] >> 63 == 0, "random data is stored, a pattern is compressed"
    base = 32 + 12 * n
    for i, p in enumerate(ptrs):
        start, end = p & ~(1 << 63), (ptrs[i + 1] & ~(1 << 63)) if i + 1 < n else csize
        assert zlib.adler32(raw[base + start:base + end]) == hashes[i], "Dolphin checks each block's Adler-32"
    assert len(raw) == base + csize
    filemods.gcz_to_iso(tmp_path / "a.gcz", tmp_path / "back.iso")
    assert (tmp_path / "back.iso").read_bytes() == data
    (tmp_path / "w.iso").write_bytes(_disc(wii=True))
    assert struct.unpack_from("<I", BX.write_gcz(tmp_path / "w.iso", tmp_path / "w.gcz").read_bytes(), 4)[0] == 1, "Wii sub type"


def test_cso_round_trip_and_n64_byte_orders(tmp_path):
    from gbox import cso
    data = _disc(5 * 2048 + 9)
    (tmp_path / "p.iso").write_bytes(data)
    BX.write_cso(tmp_path / "p.iso", tmp_path / "p.cso")
    cso.to_iso(tmp_path / "p.cso", tmp_path / "back.iso")
    assert (tmp_path / "back.iso").read_bytes() == data
    z = b"\x80\x37\x12\x40" + bytes(range(252))
    v, n = BX.n64_order(z, ".v64"), BX.n64_order(z, ".n64")
    assert v[:4] == b"\x37\x80\x40\x12" and n[:4] == b"\x40\x12\x37\x80"
    assert BX.n64_order(v, ".z64") == z == BX.n64_order(n, ".z64") and BX.n64_order(v, ".n64") == n


def test_companion_tracks_of_a_cue_and_a_gdi(tmp_path):
    (tmp_path / "Game (Track 1).bin").write_bytes(b"1")
    (tmp_path / "Game (Track 2).bin").write_bytes(b"2")
    (tmp_path / "Game.cue").write_text('FILE "Game (Track 1).bin" BINARY\n  TRACK 01 MODE2/2352\nFILE "Game (Track 2).bin" BINARY\n'
                                       'FILE "../escape.bin" BINARY\n')
    assert BX.companions(tmp_path, "Game.cue") == ["Game.cue", "Game (Track 1).bin", "Game (Track 2).bin"]
    for t in ("track01.bin", "track02.raw", "track03.bin"):
        (tmp_path / t).write_bytes(b"t")
    (tmp_path / "disc.gdi").write_text("3\n1 0 4 2352 track01.bin 0\n2 600 0 2352 track02.raw 0\n3 45000 4 2352 \"track03.bin\" 0\n")
    assert BX.companions(tmp_path, "disc.gdi") == ["disc.gdi", "track01.bin", "track02.raw", "track03.bin"]


# ------------------------------------------------------------------------------------------------- export()

def build(tmp_path, files: dict, meta: dict, name="b1"):
    d = tmp_path / "cache" / "mods" / GID / name
    d.mkdir(parents=True)
    for rel, data in files.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_bytes(data)
    (d / ".gbox-mod.json").write_text(json.dumps({"name": name, "game_id": GID, **meta}))
    (d / "preview.png").write_bytes(b"\x89PNG")                     # gBox's own picture: never exported
    return d


def cfg(tmp_path):
    return SimpleNamespace(cache=tmp_path / "cache", runtime=tmp_path / "runtime", data_dir=tmp_path / "data")


def game(src, plat="gamecube", title="Zelda (USA)"):
    return {"game_id": GID, "title": title, "platform": plat, "source_name": src}


def test_same_format_copy_keeps_the_original_name_and_skips_gboxs_files(tmp_path):
    d = build(tmp_path, {"game.iso": b"MODDED" * 100}, {"image": "game.iso", "title": "Link as Sonic"})
    dest = tmp_path / "out"
    dest.mkdir()
    seen = []
    r = BX.export(cfg(tmp_path), game=game("Zelda (USA).iso"), rom=None, folder=d, meta=json.loads((d / ".gbox-mod.json").read_text()),
                  dest=dest, fmt="same", label="Link as Sonic", progress=lambda f, m: seen.append(f))
    out = Path(r["dir"])
    assert out == dest / "Zelda - Link as Sonic"
    assert [f["path"] for f in r["files"]] == ["Zelda (USA).iso"] and Path(r["main"]).read_bytes() == b"MODDED" * 100
    assert r["kind"] == "copy" and not r["notice"] and seen[-1] == 1.0
    again = BX.export(cfg(tmp_path), game=game("Zelda (USA).iso"), rom=None, folder=d, meta={"image": "game.iso"}, dest=dest,
                      fmt="same", label="Link as Sonic")
    assert Path(again["dir"]).name == "Zelda - Link as Sonic (2)", "never over an earlier export"
    with pytest.raises(ValueError, match="absolute"):
        BX.export(cfg(tmp_path), game=game("a.iso"), rom=None, folder=d, meta={"image": "game.iso"}, dest=Path("rel"), fmt="same")


def test_same_format_gcz_n64_byte_order_and_zip_under_the_original_name(tmp_path):
    data = _disc()
    d = build(tmp_path, {"Zelda (USA).iso": data}, {"image": "Zelda (USA).iso"})
    dest = tmp_path / "out"
    dest.mkdir()
    r = BX.export(cfg(tmp_path), game=game("Zelda (USA).gcz"), rom=None, folder=d, meta={"image": "Zelda (USA).iso"}, dest=dest)
    assert r["kind"] == "gcz" and Path(r["main"]).name == "Zelda (USA).gcz"
    filemods.gcz_to_iso(r["main"], tmp_path / "back.iso")
    assert (tmp_path / "back.iso").read_bytes() == data
    z = b"\x80\x37\x12\x40" + bytes(range(256)) * 4
    n = build(tmp_path, {"Mario.z64": z}, {"image": "Mario.z64"}, name="n64")
    r = BX.export(cfg(tmp_path), game=game("Super Mario 64 (USA).v64", "n64", "Super Mario 64 (USA)"), rom=None, folder=n,
                  meta={"image": "Mario.z64"}, dest=dest, label="Luigi")
    assert Path(r["main"]).name == "Super Mario 64 (USA).v64" and Path(r["main"]).read_bytes() == BX.n64_order(z, ".v64")
    orig = tmp_path / "lib" / "Super Mario 64 (USA).zip"
    orig.parent.mkdir()
    with zipfile.ZipFile(orig, "w") as zf:
        zf.writestr("Super Mario 64 (U) [!].n64", BX.n64_order(z, ".n64"))
    r = BX.export(cfg(tmp_path), game=game(orig.name, "n64", "Super Mario 64 (USA)"), rom=orig, folder=n,
                  meta={"image": "Mario.z64"}, dest=dest, label="Wario")
    with zipfile.ZipFile(r["main"]) as zf:
        assert zf.namelist() == ["Super Mario 64 (U) [!].n64"], "the original's inner name and byte order"
        assert zf.read("Super Mario 64 (U) [!].n64") == BX.n64_order(z, ".n64")


def test_chd_with_chdman_and_without_it(tmp_path, monkeypatch):
    d = build(tmp_path, {"disc.gdi": b"1\n1 0 4 2352 track01.bin 0\n", "track01.bin": b"T" * 4096},
              {"image": "disc.gdi"})
    dest = tmp_path / "out"
    dest.mkdir()
    monkeypatch.setattr(BX, "find_tool", lambda cfg, name: None)
    r = BX.export(cfg(tmp_path), game=game("Crazy Taxi (USA).chd", "dreamcast", "Crazy Taxi (USA)"), rom=None, folder=d,
                  meta={"image": "disc.gdi"}, dest=dest, label="Sonic Taxi")
    assert r["fallback"] == ".gdi" and "chdman isn't installed on this PC" in r["notice"]
    assert sorted(f["path"] for f in r["files"]) == ["Crazy Taxi (USA).gdi", "track01.bin"], "the plain gdi + tracks"
    ran = []

    def fake_run(argv, **kw):
        ran.append(argv)
        Path(argv[argv.index("-o") + 1]).write_bytes(b"MComprHD")
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(BX, "find_tool", lambda cfg, name: "C:/tools/chdman.exe" if name == "chdman" else None)
    monkeypatch.setattr(BX.subprocess, "run", fake_run)
    r = BX.export(cfg(tmp_path), game=game("Crazy Taxi (USA).chd", "dreamcast", "Crazy Taxi (USA)"), rom=None, folder=d,
                  meta={"image": "disc.gdi"}, dest=dest, label="Sonic Taxi")
    assert ran[0][:3] == ["C:/tools/chdman.exe", "createcd", "-i"] and ran[0][3].endswith("disc.gdi") and ran[0][-1] == "-f"
    assert [f["path"] for f in r["files"]] == ["Crazy Taxi (USA).chd"] and not r["notice"]


def test_patch_against_the_original_plain_and_zip(tmp_path):
    orig = tmp_path / "lib" / "Zelda (USA).iso"
    orig.parent.mkdir()
    base = bytearray(_disc())
    orig.write_bytes(bytes(base))
    base[0x3000:0x3004] = b"MOD!"
    d = build(tmp_path, {"game.iso": bytes(base)}, {"image": "game.iso", "name": "b1"})
    dest = tmp_path / "out"
    dest.mkdir()
    r = BX.export(cfg(tmp_path), game=game(orig.name), rom=orig, folder=d, meta={"image": "game.iso", "name": "b1"},
                  dest=dest, fmt="patch", label="Patch")
    assert r["changed_bytes"] == 4 and r["apply_to"]["file"] == "Zelda (USA).iso"
    bps = Path(r["main"])
    assert bps.name == "Zelda (USA).bps" and RX.apply_bps(orig.read_bytes(), bps.read_bytes()) == bytes(base)
    assert {f["path"] for f in r["files"]} >= {"Zelda (USA).bps", "Zelda (USA).ips", "README.txt"}
    with pytest.raises(ValueError, match="original game file"):
        BX.export(cfg(tmp_path), game=game(orig.name), rom=None, folder=d, meta={"image": "game.iso"}, dest=dest, fmt="patch")
    assert not (dest / "Zelda - b1").exists(), "a failed export leaves no half-written folder"
    r = BX.export(cfg(tmp_path), game=game(orig.name), rom=orig, folder=d, meta={"image": "game.iso"}, dest=dest, fmt="zip", label="Z")
    with zipfile.ZipFile(r["main"]) as zf:
        assert zf.namelist() == ["Zelda (USA).iso"] and zf.read("Zelda (USA).iso") == bytes(base)
    r = BX.export(cfg(tmp_path), game=game("Zelda (USA).gcz"), rom=None, folder=d, meta={"image": "game.iso"}, dest=dest,
                  fmt="plain", label="P")
    assert [f["path"] for f in r["files"]] == ["Zelda (USA).iso"], "plain = the image the build boots, uncompressed"


def test_folder_game_keeps_the_disc_folder_and_leaves_previews_out(tmp_path):
    rom = tmp_path / "lib" / "BLUS30001" / "PS3_GAME" / "USRDIR" / "EBOOT.BIN"
    rom.parent.mkdir(parents=True)
    rom.write_bytes(b"ELF")
    d = build(tmp_path, {"PS3_GAME/USRDIR/EBOOT.BIN": b"ELF", "PS3_GAME/USRDIR/data.bin": b"modded", "PS3_DISC.SFB": b"s"},
              {"files": ["PS3_GAME/USRDIR/data.bin"]})
    (d / "PS3_GAME/USRDIR/data.bin.part").write_bytes(b"half")
    dest = tmp_path / "out"
    dest.mkdir()
    r = BX.export(cfg(tmp_path), game=game("EBOOT.BIN", "ps3", "Resistance"), rom=rom, folder=d, meta={"files": []}, dest=dest,
                  label="Mod")
    assert r["kind"] == "folder" and Path(r["main"]).name == "BLUS30001"
    assert sorted(f["path"] for f in r["files"]) == ["BLUS30001/PS3_DISC.SFB", "BLUS30001/PS3_GAME/USRDIR/EBOOT.BIN",
                                                     "BLUS30001/PS3_GAME/USRDIR/data.bin"]


# ------------------------------------------------------------------------------------------------- the worker op

class FakeCtx(Ctx):
    def __init__(self, config):
        super().__init__(config)
        self.server, self.headers, self.seen = "http://spark.test", {"Authorization": "Bearer t"}, []

    def progress(self, pct, msg):
        self.seen.append((pct, msg))


def test_download_stages_without_launching_and_reports_progress(tmp_path, monkeypatch):
    c = cfg(tmp_path)
    calls = []

    def fake_stage(config, server, headers, gid, name, progress=None):
        calls.append((gid, name))
        progress(20, "Checking build")
        progress(24, "Fetching mod: 50/100 MB")
        build(tmp_path, {"game.iso": b"x" * 2048}, {"image": "game.iso"}, name=name)
        progress(28, "Fetching mod: 100/100 MB")
        return name
    monkeypatch.setattr(filemods, "stage", fake_stage)
    monkeypatch.setattr(T, "launch_game", None, raising=False)       # nothing here may launch
    ctx = FakeCtx(c)
    out = T.build_local(T.BuildLocalIn(op="download", game_id=GID, name="b1"), ctx)["result"]
    assert calls == [(GID, "b1")] and out["here"] and out["folder"] == "b1" and out["size"] == 2048 and out["files"] == 1
    pcts = [p for p, _ in ctx.seen]
    assert pcts == sorted(pcts) and pcts[0] == 2 and 50 <= pcts[1] <= 55 and pcts[-1] == 100
    assert T.build_local(T.BuildLocalIn(op="locate", game_id=GID, name="b1"), ctx)["result"]["dir"].endswith("b1")
    assert T.build_local(T.BuildLocalIn(op="locate", game_id=GID, name="zz"), ctx)["result"] == {"here": False}
    with pytest.raises(ValueError):
        T.build_local(T.BuildLocalIn(op="download", game_id=GID, name="../x"), ctx)


def test_export_op_downloads_then_writes_to_the_chosen_folder(tmp_path, monkeypatch):
    c = cfg(tmp_path)
    monkeypatch.setattr(filemods, "stage", lambda config, server, headers, gid, name, progress=None: (
        build(tmp_path, {"game.iso": _disc()}, {"image": "game.iso", "title": "Sonic"}, name=name), name)[1])

    class R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"game_id": GID, "title": "Zelda (USA)", "platform": "gamecube", "source_paths": [], "format": "gcz",
                    "library": "nolib", "rel_path": "GameCube/Zelda (USA).gcz", "profile_id": "p"}
    monkeypatch.setattr(T.httpx, "get", lambda url, **kw: R())
    monkeypatch.setattr(T, "rom_path", lambda g, config: (_ for _ in ()).throw(T.ToolUnavailable("no library here")))
    dest = tmp_path / "Exports"
    dest.mkdir()
    ctx = FakeCtx(c)
    out = T.build_local(T.BuildLocalIn(op="export", game_id=GID, name="b1", dest=str(dest), format="same", label="Sonic"), ctx)["result"]
    assert out["kind"] == "gcz" and out["main"] == str(dest / "Zelda - Sonic" / "Zelda (USA).gcz")
    assert ctx.seen[-1][0] == 100 and ctx.seen[-1][1].startswith("Exported to")
    with pytest.raises(ValueError, match="absolute"):
        T.build_local(T.BuildLocalIn(op="export", game_id=GID, name="b1", dest="relative"), ctx)
    with pytest.raises(ValueError, match="not a folder"):
        T.build_local(T.BuildLocalIn(op="export", game_id=GID, name="b1", dest=str(dest / "nope")), ctx)


# ------------------------------------------------------------------------------------------------- the server routes

def test_local_list_formats_and_queueing_download_and_export(tmp_path):
    cfg_, app, store, h = fixture(tmp_path)
    w = store.get("worker", "w1")
    store.put("worker", "w1", w | {"tools": ["characters", "build_local"]})
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        loc = get(c, h, "/api/builds/local?node=i9-NUC")
        assert loc["known"] and loc["online"] and set(loc["builds"]) == {f"{GID}/g1_patch", f"{GID}/cast_g1_wrestlers", f"{GID}/g1_local_only"}
        assert loc["builds"][f"{GID}/cast_g1_wrestlers"]["staged"] is True
        assert get(c, h, "/api/builds/local?node=nobody")["builds"] == {}
        f = get(c, h, f"/api/builds/{GID}/g1_patch/formats")
        assert f["image"] == "game.z64" and [o["id"] for o in f["formats"]] == ["same", "plain", "patch", "zip"]
        r = c.post(f"/api/builds/{GID}/g1_patch/local", headers=h, json={"op": "download", "node": "i9-NUC"})
        assert r.status_code == 200, r.text
        job = store.get("job", r.json()["job_id"])
        assert job["tool"] == "build_local" and job["require_worker"] == "w1" and job["state"] == "queued"
        assert job["input"]["op"] == "download" and job["input"]["name"] == "g1_patch"
        r = c.post(f"/api/builds/{GID}/g1_patch/local", headers=h,
                   json={"op": "export", "node": "i9-NUC", "dest": "D:\\Games\\Exports", "format": "same"})
        assert r.status_code == 200, r.text
        job = store.get("job", r.json()["job_id"])
        assert job["input"] == {"op": "export", "game_id": GID, "name": "g1_patch", "dest": "D:\\Games\\Exports",
                                     "format": "same", "label": "Patch card"}, "the label is the name the operator sees"
        assert c.post(f"/api/builds/{GID}/g1_patch/local", headers=h, json={"op": "export", "node": "i9-NUC"}).status_code == 422
        assert c.post(f"/api/builds/{GID}/g1_patch/local", headers=h,
                      json={"op": "export", "node": "i9-NUC", "dest": "D:\\x", "format": "rar"}).status_code == 422
        assert c.post(f"/api/builds/{GID}/g1_patch/local", headers=h, json={"op": "download", "node": "spark"}).status_code == 422
        assert c.post(f"/api/builds/{GID}/g1_patch/local", headers=h, json={"op": "download", "node": "ghost"}).status_code == 422
        assert c.post(f"/api/builds/{GID}/nope/local", headers=h, json={"op": "download", "node": "i9-NUC"}).status_code == 404
        store.put("worker", "w1", w | {"tools": ["characters"]})                 # a worker not updated yet
        r = c.post(f"/api/builds/{GID}/g1_patch/local", headers=h, json={"op": "download", "node": "i9-NUC"})
        assert r.status_code == 409 and "build_local" in r.json()["detail"]
