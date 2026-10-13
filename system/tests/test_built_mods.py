"""Built mods gallery (/api/mods/built): the persistent index of the configured cache (markers only in the request,
sizes walked in the background), join with mod cards, card registration, path safety."""
import io
import json
import os
import threading
import time

from fastapi.testclient import TestClient
from PIL import Image

from gbox import built_mods
from gbox.config import Config
from gbox.server import create_app


def png(color="red") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(out, "PNG")
    return out.getvalue()


def build(cache, gid, name, meta, files=None):
    d = cache / "mods" / gid / name
    d.mkdir(parents=True)
    for rel, data in (files or {}).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_bytes(data)
    (d / ".gbox-mod.json").write_text(json.dumps({"name": name, "game_id": gid, **meta}))
    return d


def fixture(tmp_path):
    cache = tmp_path / "hdd-cache"                      # not data_dir/cache: the configured cache dir is what is scanned
    cfg = Config(data_dir=tmp_path / "data", cache_dir=cache)
    lib = cache / "characters" / "hucast"
    lib.mkdir(parents=True)
    (lib / "preview.png").write_bytes(png("blue"))
    build(cache, "pso", "cast_pso_ult", {
        "built": 2000.0, "image": "pso.gdi", "writer": "gbox.pso_enemy.build_cast", "verified_in_game": False,
        "previews": ["previews/atlas.webp", "notes.txt", "../outside.png", "/abs/elsewhere.png"],
        "cast": [{"slot": "enemy:booma", "character": "hucast", "status": "built"},
                 {"slot": "enemy:gobooma", "character": "ramar", "status": "failed", "reason": "too many triangles"}],
        "cast_source": "Phantasy Star Online"},
        {"pso.gdi": b"x" * 10, "frames_preview.png": png(), "previews/atlas.webp": b"RIFF0000WEBP", "notes.txt": b"n"})
    build(cache, "cf3", "cf_hucast_taffy", {
        "built": 3000.0, "title": "HUcast as Taffy", "characters": ["hucast"], "replaces": ["Taffy"],
        "files": ["@image: fighter sprites (gbox.clayfighter_swap)"], "requests": [7]},
        {"frames_preview.png": png("green")})
    build(cache, "mgsvr", "mgsvr_hucast", {"built": 1000.0, "character": "hucast", "slot": "player"})
    stage = build(cache, "mgsvr", "mgsvr_hucast~abc", {"built": 4000.0})                       # staged copy: not listed
    (stage / ".gbox-staged-of").write_text("mgsvr_hucast")
    (cache / "mods" / "mgsvr" / "half").mkdir()                                                # no marker: not a build
    app = create_app(cfg)
    store = app.state.store
    store.put("mod", "card1", {"id": "card1", "title": "HUcast in MGS VR", "game_id": "mgsvr", "verified": True,
                               "calls": [{"tool": "@launch", "input": {"mod": "mgsvr_hucast"}}], "state_slot": 3,
                               "requests": [5], "ts": 10})
    store.put("request", "r5", {"id": "r5", "number": 5, "title": "Put HUcast in MGS VR", "status": "done"})
    store.put("session", "w-1", {"session_id": "w-1", "game_id": "mgsvr", "mod": "mgsvr_hucast", "state": "ended",
                                 "started": 50, "exit": "quit"})
    store.put("job", "j1", {"id": "j1", "tool": "launch_game", "state": "failed", "finished": 60, "error": "core crashed",
                            "input": {"game": {"game_id": "cf3"}, "mod": "cf_hucast_taffy"}})
    return cfg, app, store, {"Authorization": f"Bearer {cfg.token()}"}


def ready(app, timeout=10.0):
    """The index made its first marker pass and walked every folder's size (the server itself never waits)."""
    assert app.state.built_mods.wait(timeout), "the built mods index did not settle"


def test_scan_reads_the_configured_cache_and_skips_staging_and_half_builds(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    recs = built_mods.scan(built_mods.mods_root(cfg))
    assert sorted((r["game_id"], r["name"]) for r in recs) == [("cf3", "cf_hucast_taffy"), ("mgsvr", "mgsvr_hucast"),
                                                               ("pso", "cast_pso_ult")]
    pso = next(r for r in recs if r["name"] == "cast_pso_ult")
    # the marker's listed pictures + the fixed preview names, nothing else (no folder listing; notes.txt, paths out
    # of the folder dropped)
    assert pso["images"] == ["frames_preview.png", "previews/atlas.webp"]
    assert pso["size"] is None                                   # a marker read never walks the folder
    assert built_mods.folder_size(tmp_path / "hdd-cache" / "mods" / "pso" / "cast_pso_ult")[2] == 5


def test_gallery_joins_cards_launches_tickets_and_previews(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    with TestClient(app) as c:
        ready(app)
        r = c.get("/api/mods/built", headers=h).json()
    assert r["cache_dir"].endswith("mods") and "hdd-cache" in r["cache_dir"]
    assert [m["name"] for m in r["items"]] == ["cf_hucast_taffy", "cast_pso_ult", "mgsvr_hucast"]   # newest build first
    cf, pso, vr = r["items"]
    assert cf["writer"] == "clayfighter_swap" and cf["changes"] == [{"donor": "hucast", "slot": "Taffy"}]
    assert cf["last_launch"]["state"] == "failed" and "core crashed" in cf["last_launch"]["error"]
    assert cf["tickets"] == [{"number": 7}] and cf["verified"] is False
    assert cf["donor_previews"] == [{"slug": "hucast", "url": "/api/characters/hucast/preview"}]
    assert pso["writer"] == "pso_enemy" and pso["cast"] is True
    assert [x["status"] for x in pso["report"]] == ["built", "failed"]
    assert pso["changes"][1] == {"donor": "ramar", "slot": "enemy:gobooma", "status": "failed", "reason": "too many triangles"}
    assert pso["images"][0] == {"name": "frames_preview.png", "url": "/api/mods/built/pso/cast_pso_ult/image/frames_preview.png"}
    assert vr["card_id"] == "card1" and vr["verified"] is True and vr["state_slot"] == 3
    assert vr["tickets"] == [{"number": 5, "id": "r5", "title": "Put HUcast in MGS VR", "status": "done"}]
    assert vr["last_launch"]["state"] == "ended" and vr["last_launch"]["session_id"] == "w-1"
    assert {g["game_id"] for g in r["games"]} == {"cf3", "mgsvr", "pso"}
    assert {w["writer"] for w in r["writers"]} == {"clayfighter_swap", "pso_enemy", "mgsvr"}


def test_filters_search_and_pages(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    with TestClient(app) as c:
        ready(app)
        assert [m["name"] for m in c.get("/api/mods/built?game_id=pso", headers=h).json()["items"]] == ["cast_pso_ult"]
        assert c.get("/api/mods/built?writer=mgsvr", headers=h).json()["total"] == 1
        assert [m["name"] for m in c.get("/api/mods/built?q=taffy", headers=h).json()["items"]] == ["cf_hucast_taffy"]
        assert c.get("/api/mods/built?q=%237", headers=h).json()["total"] == 1                       # ticket number
        page = c.get("/api/mods/built?offset=1&limit=1", headers=h).json()
        assert page["total"] == 3 and [m["name"] for m in page["items"]] == ["cast_pso_ult"]
        assert c.get("/api/mods/built").status_code == 401


def test_every_build_gets_a_launchable_card_once(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    with TestClient(app) as c:
        ready(app)
        first = c.get("/api/mods/built?fresh=true", headers=h).json()
        cards = store.all("mod")
        made = [m for m in cards if m.get("auto_registered")]
        assert sorted(built_mods.card_mod(m) for m in made) == ["cast_pso_ult", "cf_hucast_taffy"]   # card1 already covers VR
        cf = next(m for m in made if built_mods.card_mod(m) == "cf_hucast_taffy")
        assert cf["calls"] == [{"tool": "@launch", "input": {"mod": "cf_hucast_taffy"}}] and cf["game_id"] == "cf3"
        assert cf["title"] == "HUcast as Taffy" and cf["requests"] == [7] and "hucast -> Taffy" in cf["desc"]
        # idempotent: rescans add nothing, and the gallery now links each build to its card
        c.get("/api/mods/built?fresh=true", headers=h)
        assert built_mods.register_missing(store, built_mods.scan(built_mods.mods_root(cfg))) == []
        assert len(store.all("mod")) == len(cards)
        again = c.get("/api/mods/built?fresh=true", headers=h).json()
        assert all(m["card_id"] for m in again["items"])
        listed = {m["id"] for m in c.get("/api/mods?game_id=cf3", headers=h).json()}
        assert cf["id"] in listed
    assert first["items"]


def test_a_writers_own_card_replaces_the_stand_in(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    with TestClient(app) as c:
        ready(app)
        c.get("/api/mods/built?fresh=true", headers=h)
        stand_in = next(m for m in store.all("mod") if built_mods.card_mod(m) == "cast_pso_ult")
        c.post(f"/api/mods/{stand_in['id']}/thumb?append=true", headers=h, content=png("red"))
        saved = c.post("/api/mods", headers=h, json={"title": "PSO enemies as wrestlers", "game_id": "pso", "requests": [9],
                                                     "calls": [{"tool": "@launch", "input": {"mod": "cast_pso_ult"}}]}).json()
        cards = [m for m in store.all("mod") if built_mods.card_mod(m) == "cast_pso_ult"]
        assert [m["id"] for m in cards] == [saved["id"]] and not saved.get("auto_registered")
        assert saved["shots"] and saved["thumb"] == saved["shots"][0] and saved["requests"] == [9]
        pso = c.get("/api/mods/built?game_id=pso&fresh=true", headers=h).json()["items"][0]
        assert pso["card_id"] == saved["id"] and len(pso["shots"]) == 1
        # same title as the stand-in: the card keeps its id and is no longer marked as a stand-in
        cf = next(m for m in store.all("mod") if built_mods.card_mod(m) == "cf_hucast_taffy")
        again = c.post("/api/mods", headers=h, json={"title": cf["title"], "game_id": "cf3", "verified": True,
                                                      "calls": [{"tool": "@launch", "input": {"mod": "cf_hucast_taffy"}}]}).json()
        assert again["id"] == cf["id"] and "auto_registered" not in again and again["verified"] is True


def test_same_title_for_another_mod_keeps_both_cards(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    import hashlib
    mid = hashlib.sha1(b"cf3:hucast as taffy").hexdigest()[:12]
    store.put("mod", mid, {"id": mid, "title": "HUcast as Taffy", "game_id": "cf3",
                           "calls": [{"tool": "cheats", "input": {"code": "x"}}], "ts": 1})
    built_mods.register_missing(store, built_mods.scan(built_mods.mods_root(cfg)))
    assert store.get("mod", mid)["calls"][0]["tool"] == "cheats"
    new = [m for m in store.all("mod") if built_mods.card_mod(m) == "cf_hucast_taffy"]
    assert len(new) == 1 and new[0]["title"] == "HUcast as Taffy [cf_hucast_taffy]"


def test_image_route_streams_previews_and_refuses_everything_else(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    secret = tmp_path / "hdd-cache" / "mods" / "pso" / "secret.png"
    secret.write_bytes(png())
    with TestClient(app) as c:
        ok = c.get("/api/mods/built/pso/cast_pso_ult/image/frames_preview.png", headers=h)
        assert ok.status_code == 200 and ok.headers["content-type"] == "image/png" and ok.content.startswith(b"\x89PNG")
        assert c.get("/api/mods/built/pso/cast_pso_ult/image/previews/atlas.webp", headers=h).headers["content-type"] == "image/webp"
        token = cfg.token()
        assert c.get(f"/api/mods/built/pso/cast_pso_ult/image/frames_preview.png?token={token}").status_code == 200
        for bad in ["pso/cast_pso_ult/image/notes.txt", "pso/cast_pso_ult/image/pso.gdi", "pso/cast_pso_ult/image/..%2Fsecret.png",
                    "pso/cast_pso_ult/image/previews/..%2F..%2Fsecret.png", "pso/cast_pso_ult/image/other%2Fx.png",
                    "pso/nope/image/frames_preview.png", "mgsvr/mgsvr_hucast~abc/image/x.png", "..%2Fpso/cast_pso_ult/image/frames_preview.png",
                    "pso/cast_pso_ult/image/missing.png"]:
            assert c.get(f"/api/mods/built/{bad}", headers=h).status_code == 404, bad
        assert c.get("/api/mods/built/pso/cast_pso_ult/image/frames_preview.png").status_code == 401
    for gid, mod, name in [("pso", "cast_pso_ult", "../secret.png"), ("pso", "..", "secret.png"), ("..", "pso", "secret.png"),
                           ("pso", "cast_pso_ult", "/etc/passwd.png"), ("pso", "cast_pso_ult", "C:/x.png")]:
        try:
            built_mods.image_path(cfg, gid, mod, name)
        except ValueError:
            continue
        raise AssertionError((gid, mod, name))


def test_symlinked_picture_is_refused(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    folder = tmp_path / "hdd-cache" / "mods" / "pso" / "cast_pso_ult"
    outside = tmp_path / "outside.png"
    outside.write_bytes(png())
    try:
        (folder / "link.png").symlink_to(outside)
    except OSError:
        return                                                    # no symlink privilege (Windows without developer mode)
    built_mods._FOLDER_CACHE.clear()
    assert "link.png" not in built_mods.read_folder(folder)["images"]
    try:
        built_mods.image_path(cfg, "pso", "cast_pso_ult", "link.png")
    except ValueError:
        return
    raise AssertionError("a symlink out of the mod folder was served")


def test_screenshot_after_launch_appends_in_game_shots(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    with TestClient(app) as c:
        ready(app)
        a = c.post("/api/mods/card1/thumb?append=true", headers=h, content=png("red")).json()
        b = c.post("/api/mods/card1/thumb?append=true", headers=h, content=png("blue")).json()
        assert len(b["shots"]) == 2 and b["thumb"] == a["thumb"] == a["shots"][0]
        vr = c.get("/api/mods/built?game_id=mgsvr&fresh=true", headers=h).json()["items"][0]
        assert [s["sha256"] for s in vr["shots"]] == b["shots"]                    # newest in-game shot first
        assert all(s["url"].startswith("/api/artifacts/") for s in vr["shots"])


def test_writer_shapes_normalize():
    assert built_mods.changes_of({"roster": [{"fighter": "kasumi", "character": "hucast"}]}) == [{"donor": "hucast", "slot": "kasumi"}]
    assert built_mods.changes_of({"character": "hucast", "enemies": ["booma", "rappy"]}) == [
        {"donor": "hucast", "slot": "enemy:booma, enemy:rappy"}]
    assert built_mods.changes_of({"enemies": {"booma": "hucast"}}) == [{"donor": "hucast", "slot": "enemy:booma"}]
    assert built_mods.changes_of({"characters": ["a", "b"], "replaces": ["X", "Y"]}) == [
        {"donor": "a", "slot": "X"}, {"donor": "b", "slot": "Y"}]
    assert built_mods.changes_of({"files": ["a"]}) == []
    assert built_mods.writer_of({"writer": "gbox.jgr (cast chain)"}, "x") == "jgr"
    assert built_mods.writer_of({"files": ["DATA.BIN (gbox.defjam_writer)"]}, "x") == "defjam_writer"
    assert built_mods.writer_of({}, "pe2_hucast") == "pe2"
    assert built_mods.tickets_of({"ticket": "#12", "requests": [3, "x"]}, {"requests": [3]}) == [3, 12]
    assert built_mods.verified_of({"gameplay_verified": True}, None) and not built_mods.verified_of({}, {"verified": False})


def test_folder_scan_is_cached_until_the_marker_changes(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    folder = tmp_path / "hdd-cache" / "mods" / "cf3" / "cf_hucast_taffy"
    first = built_mods.read_folder(folder)
    assert built_mods.read_folder(folder) is first
    time.sleep(0.01)
    (folder / ".gbox-mod.json").write_text(json.dumps({"name": "cf_hucast_taffy", "game_id": "cf3", "title": "Renamed!",
                                                       "built": 5000.0}))
    assert built_mods.read_folder(folder)["meta"]["title"] == "Renamed!"


# ------------------------------------------------------------------ the persistent index (fast answers on a busy disk)

class SlowDisk:
    """A fake slow cache disk: every stat / listing under the cache costs time. Calls from outside the index's own
    threads (the request) cost `delay` and are recorded; the index's background threads pay `bg_delay`."""

    def __init__(self, monkeypatch, root, delay=2.0, bg_delay=0.0):
        self.root, self.delay, self.bg_delay, self.foreign, self.bg = os.fspath(root), delay, bg_delay, [], 0
        for name in ("stat", "lstat", "scandir", "listdir"):
            monkeypatch.setattr(os, name, self.wrap(getattr(os, name), name))

    def wrap(self, real, name):
        def slow(p=".", *a, **k):
            s = os.fspath(p) if isinstance(p, (str, os.PathLike)) else ""
            if isinstance(s, str) and s.startswith(self.root):
                if threading.current_thread().name == "asset-index":
                    pass                                   # the asset sidebar's own background index, not a request
                elif threading.current_thread().name.startswith("built-mods"):
                    self.bg += 1
                    time.sleep(self.bg_delay)
                else:
                    self.foreign.append((name, s))
                    time.sleep(self.delay)
            return real(p, *a, **k)
        return slow


def test_endpoint_answers_from_the_index_without_touching_the_disk(tmp_path, monkeypatch):
    cfg, app, store, h = fixture(tmp_path)
    for i in range(40):                                                   # plenty of builds, a few big folders
        build(tmp_path / "hdd-cache", f"g{i % 5}", f"bulk_{i}", {"built": 100.0 + i},
              {f"disc/t{j}.bin": b"x" * 64 for j in range(20)})
    with TestClient(app) as c:
        ready(app, 30)
        disk = SlowDisk(monkeypatch, tmp_path / "hdd-cache", delay=2.0)  # any touch by the request blows the budget
        t0 = time.perf_counter()
        r = c.get("/api/mods/built?limit=200", headers=h)
        took = time.perf_counter() - t0
        assert r.status_code == 200 and disk.foreign == [], disk.foreign[:5]
        body = r.json()
        assert body["all"] == 43 and body["indexing"] is False and body["sizing"] == 0
        assert all(isinstance(m["size"], int) for m in body["items"])
        assert took < 1.0, took
        print(f"GET /api/mods/built?limit=200, 43 builds, slow disk: {took * 1000:.1f} ms")
        t0 = time.perf_counter()
        ref = c.post("/api/mods/built/refresh", headers=h)               # never waits for the pass it asks for
        assert ref.status_code == 200 and ref.json()["indexing"] is True and time.perf_counter() - t0 < 1.0
        assert disk.foreign == []


def test_a_cold_index_answers_at_once_and_fills_in_the_background(tmp_path, monkeypatch):
    cfg, app, store, h = fixture(tmp_path)
    disk = SlowDisk(monkeypatch, tmp_path / "hdd-cache", delay=2.0, bg_delay=0.05)
    with TestClient(app) as c:
        t0 = time.perf_counter()
        cold = c.get("/api/mods/built", headers=h).json()
        assert time.perf_counter() - t0 < 1.0 and cold["indexing"] is True and disk.foreign == []
        ready(app, 60)
        warm = c.get("/api/mods/built", headers=h).json()
    assert warm["indexing"] is False
    assert [m["name"] for m in warm["items"]] == ["cf_hucast_taffy", "cast_pso_ult", "mgsvr_hucast"]
    assert all(m["size"] > 0 for m in warm["items"]) and disk.bg > 0 and disk.foreign == []


def test_the_index_persists_and_a_restart_walks_nothing(tmp_path, monkeypatch):
    cfg, app, store, h = fixture(tmp_path)
    with TestClient(app) as c:
        ready(app)
        sizes = {m["name"]: (m["size"], m["files"]) for m in c.get("/api/mods/built", headers=h).json()["items"]}
    assert sizes["cast_pso_ult"][1] == 5 and all(s > 0 for s, _ in sizes.values())
    saved = json.loads((cfg.data_dir / built_mods.INDEX_FILE).read_text())
    assert saved["root"] == str(built_mods.mods_root(cfg))
    assert set(saved["mods"]) == {"cf3/cf_hucast_taffy", "mgsvr/mgsvr_hucast", "pso/cast_pso_ult"}
    walked, reads = [], []
    monkeypatch.setattr(built_mods, "folder_size", lambda f, stop=None: walked.append(f) or (0, 0, 0))
    real_read = built_mods.read_folder
    monkeypatch.setattr(built_mods, "read_folder", lambda f, st=None: reads.append(f) or real_read(f, st))
    app2 = create_app(cfg)
    idx = app2.state.built_mods
    assert {r["name"] for r in idx.records()} == set(sizes) and idx.status()["indexing"] is True   # before any pass
    with TestClient(app2) as c:
        ready(app2)
        again = {m["name"]: (m["size"], m["files"]) for m in c.get("/api/mods/built", headers=h).json()["items"]}
    assert again == sizes and walked == [] and reads == []              # unchanged markers: nothing re-read or walked


def test_refresh_reads_only_new_and_changed_markers(tmp_path, monkeypatch):
    import shutil
    cfg, app, store, h = fixture(tmp_path)
    cache = tmp_path / "hdd-cache"
    with TestClient(app) as c:
        ready(app)
        reads, walked, gate = [], [], threading.Event()
        real_read, real_size = built_mods.read_folder, built_mods.folder_size

        def size(f, stop=None):
            walked.append(f.name)
            gate.wait(10)
            return real_size(f, stop)
        monkeypatch.setattr(built_mods, "read_folder", lambda f, st=None: reads.append(f.name) or real_read(f, st))
        monkeypatch.setattr(built_mods, "folder_size", size)
        build(cache, "pso", "new_build", {"built": 9000.0, "title": "Fresh"}, {"disc/big.iso": b"z" * 1000})
        marker = cache / "mods" / "cf3" / "cf_hucast_taffy" / ".gbox-mod.json"
        marker.write_text(json.dumps({**json.loads(marker.read_text()), "title": "Retitled"}))
        r = c.post("/api/mods/built/refresh", headers=h).json()
        assert r["ok"] and r["indexing"] is True
        for _ in range(500):                                               # the marker pass lands; sizes are pending
            body = c.get("/api/mods/built", headers=h).json()
            if not body["indexing"]:
                break
            time.sleep(0.01)
        items = {m["name"]: m for m in body["items"]}
        assert items["new_build"]["size"] is None and items["cf_hucast_taffy"]["size"] is None and body["sizing"] == 2
        assert items["cf_hucast_taffy"]["mod_title"] == "Retitled" and items["cast_pso_ult"]["size"] > 0
        gate.set()
        ready(app)
        body = c.get("/api/mods/built", headers=h).json()
        items = {m["name"]: m for m in body["items"]}
        assert sorted(reads) == ["cf_hucast_taffy", "new_build"] and sorted(walked) == ["cf_hucast_taffy", "new_build"]
        assert items["new_build"]["size"] >= 1000 and body["sizing"] == 0 and body["indexing"] is False
        assert body["items"][0]["name"] == "new_build"
        # a deleted build leaves the index; the timer runs this same incremental pass
        shutil.rmtree(cache / "mods" / "pso" / "new_build")
        c.post("/api/mods/built/refresh", headers=h)
        ready(app)
        assert "new_build" not in {m["name"] for m in c.get("/api/mods/built", headers=h).json()["items"]}
        assert sorted(reads) == ["cf_hucast_taffy", "new_build"]


def test_game_titles_come_from_the_catalog_and_writers_from_the_marker(tmp_path):
    cfg, app, store, h = fixture(tmp_path)
    store.upsert_catalog([{"game_id": "pso", "title": "Phantasy Star Online Ver. 2 (USA)", "platform": "dreamcast"},
                          {"game_id": "cf3", "title": "ClayFighter 63 1/3 (USA)", "platform": "n64"}])
    build(tmp_path / "hdd-cache", "zz", "zz_mystery", {"built": 10.0, "game_title": "Marker Game",
                                                        "writer": "gbox.jgr (cast chain)"})
    with TestClient(app) as c:
        ready(app)
        r = c.get("/api/mods/built", headers=h).json()
    items = {m["name"]: m for m in r["items"]}
    pso = items["cast_pso_ult"]
    assert pso["game_title"] == pso["title"] == "Phantasy Star Online Ver. 2 (USA)" and pso["platform"] == "dreamcast"
    assert items["cf_hucast_taffy"]["game_title"] == "ClayFighter 63 1/3 (USA)"
    assert items["zz_mystery"]["game_title"] == "Marker Game" and items["zz_mystery"]["writer"] == "jgr"
    assert items["mgsvr_hucast"]["game_title"] == "mgsvr"                 # nothing names the game: its id
    assert {g["game_id"]: g["title"] for g in r["games"]}["pso"] == "Phantasy Star Online Ver. 2 (USA)"
    card = next(m for m in store.all("mod") if built_mods.card_mod(m) == "cf_hucast_taffy")
    assert card["game_title"] == "ClayFighter 63 1/3 (USA)"
