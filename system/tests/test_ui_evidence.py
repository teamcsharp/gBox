"""scripts/ui_evidence.py: the fixture server's routing (no browser is launched here)."""
import importlib.util
import json
import struct
import threading
import urllib.request
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ui_evidence.py"
spec = importlib.util.spec_from_file_location("ui_evidence", SCRIPT)
ue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ue)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ui_evidence"


@pytest.fixture
def server(tmp_path):
    clients = tmp_path / "clients"
    (clients / "web" / "viz").mkdir(parents=True)
    (clients / "desktop").mkdir()
    (clients / "web" / "index.html").write_text("<title>gBox</title>", encoding="utf-8")
    (clients / "web" / "viz" / "builds.js").write_text("// builds", encoding="utf-8")
    (clients / "desktop" / "live-poll.js").write_text("// poll", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside the tree", encoding="utf-8")
    fx = ue.Fixtures({
        "routes": {
            "/api/builds": {"items": [{"key": "g/x"}]},
            "/api/builds/*/details": {"name": "any"},
            "/api/catalog?q=a": {"total": 1},
            "/api/char/x/model.glb": {"$glb": {"height": 1.5}},
            "/api/err": {"$status": 409, "$body": {"detail": "busy"}},
            "/api/when": {"t": "$now-60"},
            "POST /api/jobs": {"$by": "tool", "cases": {"pick_preview": {"id": "p", "state": "succeeded"}},
                               "$default": {"id": "d", "state": "queued"}},
        },
        "lists": ["/api/things"],
    })
    srv = ue.make_server(clients, fx)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", fx
    srv.shutdown()


def call(url, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"),
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.headers.get("content-type"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type"), e.read()


def test_get_answers_from_the_fixture(server):
    base, _ = server
    st, ct, body = call(base + "/api/builds?token=abc")              # the shells' token never matters
    assert st == 200 and ct == "application/json" and json.loads(body) == {"items": [{"key": "g/x"}]}
    assert json.loads(call(base + "/api/builds/g1/cast/details")[2]) == {"name": "any"}      # glob
    assert json.loads(call(base + "/api/catalog?q=a&token=t")[2]) == {"total": 1}            # exact query
    st, _, body = call(base + "/api/err")
    assert st == 409 and json.loads(body) == {"detail": "busy"}
    t = json.loads(call(base + "/api/when")[2])["t"]
    assert isinstance(t, float) and abs(t - (ue.time.time() - 60)) < 30


def test_unknown_paths_answer_empty_json_never_forwarded(server):
    base, fx = server
    st, ct, body = call(base + "/api/nothing/here?x=1")
    assert st == 200 and ct == "application/json" and json.loads(body) == {}
    assert json.loads(call(base + "/api/things")[2]) == []                  # a listed collection
    assert json.loads(call(base + "/api/things/1")[2]) == {}                # its members stay objects
    assert json.loads(call(base + "/api/sessions?include_ended=false")[2]) == []
    assert "/api/nothing/here?x=1" in fx.misses
    st, ct, body = call(base + "/api/characters/kane/preview")             # pictures get a placeholder
    assert st == 200 and ct == "image/svg+xml" and body.startswith(b"<svg")


def test_non_get_is_a_no_op_unless_a_fixture_answers(server):
    base, fx = server
    assert json.loads(call(base + "/api/builds", {"display_name": "x"}, "PATCH")[2]) == {"ok": True}
    assert json.loads(call(base + "/api/anything/else", {"a": 1})[2]) == {"ok": True}
    assert json.loads(call(base + "/api/builds")[2]) == {"items": [{"key": "g/x"}]}         # nothing changed
    assert json.loads(call(base + "/api/jobs", {"tool": "pick_preview"})[2])["id"] == "p"   # chosen by a body field
    assert json.loads(call(base + "/api/jobs", {"tool": "other"})[2])["id"] == "d"
    assert json.loads(call(base + "/api/builds/scheduled/q1/cancel", {}, "DELETE")[2]) == {"ok": True}


def test_static_routes_follow_the_control_plane(server):
    base, _ = server
    assert call(base + "/")[2] == b"<title>gBox</title>"
    st, ct, body = call(base + "/viz/builds.js")
    assert st == 200 and ct.startswith("text/javascript") and body == b"// builds"
    assert call(base + "/live-poll.js")[2] == b"// poll"
    assert call(base + "/clients/desktop/live-poll.js")[2] == b"// poll"
    assert call(base + "/clients/../secret.txt")[0] == 404
    assert call(base + "/viz/..%2F..%2Fsecret.txt")[0] == 404


def test_synthetic_glb_is_a_skinned_gltf_binary(server):
    base, _ = server
    st, ct, body = call(base + "/api/char/x/model.glb")
    assert st == 200 and ct == "model/gltf-binary"
    magic, version, length = struct.unpack("<4sII", body[:12])
    assert magic == b"glTF" and version == 2 and length == len(body)
    n, kind = struct.unpack("<I4s", body[12:20])
    gltf = json.loads(body[20:20 + n])
    assert kind == b"JSON" and len(gltf["skins"][0]["joints"]) == len(ue.RIG_ROLES) == 18
    assert {n["name"] for n in gltf["nodes"]} >= set(ue.RIG_ROLES.values())


def test_pr_fixture_files_load_and_are_synthetic():
    files = sorted(p for p in FIXTURES.glob("*.json") if not p.name.startswith("_"))
    assert files, "no PR fixtures"
    for f in files:
        data = ue.load_fixture_file(f)
        assert data["shots"] and all({"name", "url"} <= set(s) for s in data["shots"]), f.name
        text = f.read_text(encoding="utf-8")
        assert "10.89." not in text and "token=" not in text.replace("#token=fixture", ""), f.name
