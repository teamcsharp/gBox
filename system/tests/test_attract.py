"""HyperSpin / Attract-Mode library: config+romlist parsing, shared MAME folder, search, media, launch routing."""
from conftest import run_job
from gbox import catalog, systems
from gbox.config import Library

HDR = "#Name;Title;Emulator;CloneOf;Year;Manufacturer;Category;Players;Rotation;Control;Status;DisplayCount;DisplayType;AltRomname;AltTitle;Extra;Buttons\n"


def emu(root, name, system, rompath, romext, art=None):
    lines = [f"executable           RocketLauncher\\RocketLauncher.exe", f"rompath              {rompath}",
             f"romext               {romext}", f"system               {system}"]
    if art:
        lines.append(f"artwork    snap      {art}")
    (root / "emulators" / f"{name}.cfg").write_text("\n".join(lines) + "\n")


def make_tree(root):
    for d in ("emulators", "romlists", "collections/Sega Dreamcast/roms", "collections/Sega Dreamcast/snap",
              "collections/Mame/roms", "collections/Nintendo Entertainment System/roms", "collections/PC Games/roms"):
        (root / d).mkdir(parents=True, exist_ok=True)
    emu(root, "Sega Dreamcast", "Sega Dreamcast", r"collections\Sega Dreamcast\roms", ".chd;.cdi", r"collections\Sega Dreamcast\snap")
    emu(root, "Mame", "MAME", r"collections\Mame\roms", ".zip;.7z")
    emu(root, "Capcom Classics", "Capcom Classics", r"collections\Mame\roms", ".zip;.7z")   # virtual collection
    emu(root, "Nintendo Entertainment System", "Nintendo Entertainment System",
        r"collections\Nintendo Entertainment System\roms", ".zip;.7z")
    emu(root, "PC Games", "PC Games", r"collections\PC Games\roms", ".bat")
    dc = root / "collections/Sega Dreamcast"
    (dc / "roms/Phantasy Star Online Ver. 2 (USA).chd").write_bytes(b"x")
    (dc / "roms/Soulcalibur (USA).chd").write_bytes(b"x")
    (dc / "snap/Phantasy Star Online Ver. 2 (USA).png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    for n in ("sf2", "sf2ce", "neogeo", "1942"):
        (root / f"collections/Mame/roms/{n}.zip").write_bytes(b"x")
    (root / "collections/Mame/roms/area51").mkdir()                       # CHD-only arcade set (a folder)
    (root / "collections/Mame/roms/area51/area51.chd").write_bytes(b"x")
    (root / "collections/Nintendo Entertainment System/roms/Zelda (USA).zip").write_bytes(b"x")
    (root / "collections/Nintendo Entertainment System/roms/Unlisted Game (USA).zip").write_bytes(b"x")
    (root / "collections/PC Games/roms/Half-Life.bat").write_text("start hl.exe")
    (root / "romlists/Sega Dreamcast.txt").write_text(HDR +
        "Phantasy Star Online Ver. 2 (USA);Phantasy Star Online Ver. 2 (USA);Sega Dreamcast;;2001;Sega;RPG;4P;;;;;;;;;\n"
        "Soulcalibur (USA);Soulcalibur (USA);Sega Dreamcast;;1999;Namco;Fighter;2P;;;;;;;;;\n"
        "Missing Game (USA);Missing Game (USA);Sega Dreamcast;;2000;X;Y;;;;;;;;;;\n")
    (root / "romlists/Mame.txt").write_text(HDR + "sf2;Street Fighter II;MAME;;1991;Capcom;Fighter;2P;;;;;;;;;\n"
                                           "sf2ce;Street Fighter II CE;MAME;sf2;1992;Capcom;Fighter;2P;;;;;;;;;\n"
                                           "1942;1942;MAME;;1984;Capcom;Shooter;2P;;;;;;;;;\n"
                                           "area51;Area 51;MAME;;1995;Atari;Shooter;2P;;;;;;;;;\n")
    (root / "romlists/Capcom Classics.txt").write_text(HDR + "sf2;Street Fighter II;Capcom Classics;;1991;Capcom;Fighter;2P;;;;;;;;;\n")
    (root / "romlists/Nintendo Entertainment System.txt").write_text(HDR + "Zelda (USA);The Legend of Zelda;NES;;1986;Nintendo;Adventure;1P;;;;;;;;;\n")


def test_classify():
    assert systems.classify("Sega Dreamcast")[:2] == ("dreamcast", "flycast")
    assert systems.classify("Nintendo GameCube")[:2] == ("gamecube", "dolphin")
    assert systems.classify("Capcom Classics", "Capcom Classics", "collections/Mame/roms")[:2] == ("arcade", "mame")
    assert systems.classify("Atari Classics", "", "collections/MAME/roms")[0] == "arcade"
    assert systems.classify("Sony PlayStation 2")[:2] == ("ps2", "pcsx2")
    assert systems.classify("Teknoparrot")[1] is None and systems.classify("Microsoft XBOX 360")[1] is None
    assert systems.classify("Nintendo Wii U")[1] is None and systems.classify("Nintendo Wii")[1] == "dolphin"


def test_scan_attract(tmp_path):
    make_tree(tmp_path)
    entries, problems, stats = catalog.scan_attract(tmp_path, "hs")
    by = {e.title: e for e in entries}
    pso = by["Phantasy Star Online Ver. 2 (USA)"]
    assert pso.platform == "dreamcast" and pso.core == "flycast" and pso.year == "2001" and pso.manufacturer == "Sega"
    assert pso.rel_path == "collections/Sega Dreamcast/roms/Phantasy Star Online Ver. 2 (USA).chd"
    assert pso.media["snap"][0] == "collections/Sega Dreamcast/snap/Phantasy Star Online Ver. 2 (USA)"
    assert "collections/Mame/snap/sf2" in by["Street Fighter II"].media["snap"]           # art beside the real folder
    assert pso.launch == {"kind": "attract", "library": "hs", "rel_path": pso.rel_path,
                          "emulator": "Sega Dreamcast", "name": "Phantasy Star Online Ver. 2 (USA)"}
    sf2 = by["Street Fighter II"]
    assert sorted(sf2.collections) == ["Capcom Classics", "Mame"] and sf2.platform == "arcade"   # deduped across collections
    assert by["Street Fighter II CE"].clone_of == "sf2"
    assert "neogeo" not in {e.rel_path.rsplit("/", 1)[-1][:-4] for e in entries}        # unlisted arcade zip = bios
    assert "Unlisted Game" in by and by["The Legend of Zelda"].core == "mesen"            # unlisted console rom kept
    assert by["Area 51"].rel_path == "collections/Mame/roms/area51" and by["Area 51"].format == "dir"
    assert by["Half-Life"].core is None                                                   # Windows-node only
    assert stats["listed_missing"] == 1 and stats["unlisted_arcade_skipped"] == 1
    assert len({e.game_id for e in entries}) == len(entries)


def test_listing_cache(tmp_path):
    make_tree(tmp_path)
    cache = {}
    catalog.scan_attract(tmp_path, "hs", cache)
    keys = {k for k in cache if k.startswith("ls2|")}
    assert keys and all(cache[k]["items"] for k in keys)


def test_search_media_launch_routing(plane, cfg, tmp_path):
    make_tree(tmp_path / "hs")
    cfg.libraries.append(Library(id="hs", kind="attract", paths={"windows": str(tmp_path / "hs"), "linux": str(tmp_path / "hs")}))
    job = run_job(plane, "scan_library", {"include_steam": False})
    assert job["state"] == "succeeded", job
    assert job["output"]["count"] == 9 and job["output"]["per_library"]["hs"]["entries"] == 9
    r = plane.get("/api/catalog", params={"q": "phantasy ver"}).json()
    assert r["total"] == 1
    gid = r["items"][0]["game_id"]
    assert plane.get("/api/catalog", params={"q": "capcom fighter"}).json()["total"] == 2
    assert plane.get("/api/catalog", params={"platform": "arcade"}).json()["total"] == 4
    assert plane.get("/api/catalog/facets").json()["platforms"]["dreamcast"] == 2
    m = plane.get(f"/api/media/{gid}/snap")
    assert m.status_code == 200 and m.content.startswith(b"\x89PNG")
    assert plane.get(f"/api/media/{gid}/boxart").status_code == 404
    assert plane.get(f"/api/media/{gid}/best").content.startswith(b"\x89PNG")          # falls back to snap
    pc = plane.get("/api/catalog", params={"q": "half-life"}).json()["items"][0]
    def lands_on(job):           # #2386: an operator Play from this PC is pinned to its own worker when the OS rule allows
        if job["require_worker"]:
            return next(w["os"] for w in plane.get("/api/workers").json() if w["id"] == job["require_worker"])
        return job["require_os"]
    assert lands_on(plane.post(f"/api/games/{pc['game_id']}/launch").json()) == "windows"
    assert lands_on(plane.post(f"/api/games/{gid}/launch").json()) == "linux"


def test_session_frames_and_input(plane):
    sid = "w1-j1"
    assert plane.post(f"/api/sessions/{sid}/frame", content=b"\xff\xd8jpeg\xff\xd9").status_code == 200
    assert plane.get(f"/api/sessions/{sid}/frame.jpg").content == b"\xff\xd8jpeg\xff\xd9"
    plane.post(f"/api/sessions/{sid}/input", json={"events": [{"key": "a", "down": True}, {"key": "a", "down": False}]})
    assert len(plane.get(f"/api/sessions/{sid}/input").json()) == 2
    assert plane.get(f"/api/sessions/{sid}/input").json() == []


def test_bulk_ingest_is_fast_and_reingest_keeps_status(tmp_path):
    import time
    from gbox.store import Store
    st = Store(tmp_path)
    rows = [{"game_id": f"g{i}", "title": f"Game {i}", "platform": "arcade", "system": "MAME", "library": "hs",
             "collections": ["Mame"], "playable": "untested"} for i in range(20000)]
    t = time.time()
    st.upsert_catalog(rows)
    st.catalog_update("g5", playable="launches (retroarch)")
    st.upsert_catalog([dict(r) for r in rows])            # rescan: must not be quadratic, must keep learned status
    assert time.time() - t < 30
    assert st.search("game 19999")[0] == 1 and st.search(platform="arcade")[0] == 20000
    assert st.catalog_get("g5")["playable"] == "launches (retroarch)"
    assert Store(tmp_path).search("game 5")[0] >= 1        # reopen: fts consistent, no rebuild needed


def test_every_mapped_core_has_an_arm64_build():
    import re
    import httpx
    import pytest
    from gbox.provision import CORE_FALLBACKS
    try:
        idx = httpx.get("https://buildbot.libretro.com/nightly/linux/aarch64/latest/", timeout=30).text
    except httpx.HTTPError:
        pytest.skip("buildbot unreachable")
    avail = set(re.findall(r"([a-z0-9_]+)_libretro\.so\.zip", idx))
    missing = [c for _, _, c, _ in systems.RULES if c and c not in avail and not set(CORE_FALLBACKS.get(c, [])) & avail]
    assert not missing, f"cores with no linux/aarch64 build: {missing}"
