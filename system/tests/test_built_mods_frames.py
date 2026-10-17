"""Built mods gallery (#1553): a build launched and captured, but never saved as a card with shots, shows the real
frames captured from its sessions (get_frame, save-state pictures, observations, task evidence). Covered captures, other
sessions' frames and non-images are not joined."""
import io
import json

from fastapi.testclient import TestClient
from PIL import Image

from gbox import built_mods
from gbox.config import Config
from gbox.server import create_app


def png(color="red") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(out, "PNG")
    return out.getvalue()


def build(cache, gid, name, meta):
    d = cache / "mods" / gid / name
    d.mkdir(parents=True)
    (d / ".gbox-mod.json").write_text(json.dumps({"name": name, "game_id": gid, **meta}))
    return d


def setup(tmp_path):
    cache = tmp_path / "hdd-cache"
    cfg = Config(data_dir=tmp_path / "data", cache_dir=cache)
    build(cache, "sm64", "sm64_sonic", {"built": 2000.0, "title": "Sonic in SM64"})
    build(cache, "sm64", "sm64_cloud", {"built": 1000.0})
    app = create_app(cfg)
    store = app.state.store
    store.put("session", "s-sonic", {"session_id": "s-sonic", "game_id": "sm64", "mod": "sm64_sonic", "state": "ended",
                                     "started": 10})
    store.put("session", "s-plain", {"session_id": "s-plain", "game_id": "sm64", "state": "ended", "started": 5})
    refs = {
        "grab": store.put_artifact(png("red"), "frame.png", "image/png",
                                   {"tool": "get_frame", "session": "s-sonic", "covered": 0}),
        "covered": store.put_artifact(png("gray"), "frame.png", "image/png",
                                      {"tool": "get_frame", "session": "s-sonic", "covered": 9}),
        "state": store.put_artifact(png("blue"), "state.png", "image/png",
                                    {"tool": "session_op", "session": "s-sonic", "slot": 2}),
        "obs": store.put_artifact(png("green"), "observation-s-sonic.png", "image/png",
                                  {"session_id": "s-sonic", "game_id": "sm64", "captured": 12.0}),
        "json": store.put_artifact(b"{}", "snapshot.json", "application/json", {"session": "s-sonic"}),
        "plain": store.put_artifact(png("white"), "frame.png", "image/png", {"tool": "get_frame", "session": "s-plain"}),
    }
    return cfg, app, store, refs, {"Authorization": f"Bearer {cfg.token()}"}


def test_session_frames_join_real_captures_newest_first_and_skip_covered(tmp_path):
    cfg, app, store, refs, h = setup(tmp_path)
    sessions = [store.get("session", "s-sonic"), store.get("session", "s-plain")]
    frames = built_mods.session_frames(store, sessions)
    assert list(frames) == [("sm64", "sm64_sonic")]                    # the plain session ran no build
    got = frames[("sm64", "sm64_sonic")]
    assert [f["sha256"] for f in got] == [refs["obs"].sha256, refs["state"].sha256, refs["grab"].sha256]
    assert [f["source"] for f in got] == ["live observation", "save state 2", "get_frame"]
    assert all(f["url"] == f"/api/artifacts/{f['sha256']}" and f["session_id"] == "s-sonic" for f in got)
    assert built_mods.session_frames(store, sessions, limit=1)[("sm64", "sm64_sonic")][0]["sha256"] == refs["obs"].sha256


def test_gallery_lists_session_frames_and_drops_ones_already_card_shots(tmp_path):
    cfg, app, store, refs, h = setup(tmp_path)
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        items = {m["name"]: m for m in c.get("/api/mods/built", headers=h).json()["items"]}
        assert [f["sha256"] for f in items["sm64_sonic"]["frames"]] == [refs["obs"].sha256, refs["state"].sha256,
                                                                         refs["grab"].sha256]
        assert items["sm64_cloud"]["frames"] == []
        assert c.get(items["sm64_sonic"]["frames"][0]["url"], headers=h).status_code == 200
    # a frame already among the card's shots is shown once (as a card shot)
    card = built_mods.card_index(store.all("mod")).get(("sm64", "sm64_sonic"))
    assert card, "the gallery registers a launchable card for the build"
    store.put("mod", card["id"], card | {"shots": [refs["grab"].sha256]})
    data = built_mods.gallery(store, cfg, built_mods.scan(built_mods.mods_root(cfg)), register=False)
    sonic = next(m for m in data["items"] if m["name"] == "sm64_sonic")
    assert [s["sha256"] for s in sonic["shots"]] == [refs["grab"].sha256]
    assert [f["sha256"] for f in sonic["frames"]] == [refs["obs"].sha256, refs["state"].sha256]
