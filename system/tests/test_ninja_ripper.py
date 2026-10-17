"""ninja_ripper (#443): .rip parser bounds, GLB conversion, discovery, background-testing rules - all with fakes."""
import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import background_testing as bt
from gbox import ninja_ripper as nr
from gbox.config import Config


def make_rip(verts, faces, textures=("tex_0.dds",), shaders=("vs.bin",), uv=True, normal=True, magic=nr.RIP_MAGIC,
             version=4):
    """A NinjaRipper v4 .rip: POSITION(3f) [NORMAL(3f)] [TEXCOORD(2f)] per vertex, u32 triangle indices."""
    attrs, off = [("POSITION", 0, 3)], 12
    if normal:
        attrs.append(("NORMAL", 0, 3))
    if uv:
        attrs.append(("TEXCOORD", 0, 2))
    stride = sum(n for _, _, n in attrs) * 4
    b = struct.pack("<8I", magic, version, len(faces), len(verts), stride, len(textures), len(shaders), len(attrs))
    o = 0
    for sem, idx, n in attrs:
        b += sem.encode() + b"\0" + struct.pack("<4I", idx, o, 4 * n, n) + struct.pack(f"<{n}I", *([0] * n))
        o += 4 * n
    for t in (*textures, *shaders):
        b += t.encode() + b"\0"
    for f in faces:
        b += struct.pack("<3I", *f)
    for i, (x, y, z) in enumerate(verts):
        b += struct.pack("<3f", x, y, z)
        if normal:
            b += struct.pack("<3f", 0, 0, 1)
        if uv:
            b += struct.pack("<2f", i * 0.25, 0.5)
    return b


TRI = [(0, 0, 0), (1, 0, 0), (0, 1, 2)]


def read_glb(data):
    magic, ver, total = struct.unpack_from("<4sII", data, 0)
    assert magic == b"glTF" and ver == 2 and total == len(data)
    jlen, jtype = struct.unpack_from("<I4s", data, 12)
    assert jtype == b"JSON"
    gl = json.loads(data[20:20 + jlen])
    blen, btype = struct.unpack_from("<I4s", data, 20 + jlen)
    assert btype == b"BIN\0" and 28 + jlen + blen == len(data)
    return gl, data[28 + jlen:]


def test_parse_reads_header_attributes_names_indices_and_vertices():
    rip = nr.parse_rip(make_rip(TRI, [(0, 1, 2)]))
    assert rip.vertex_count == 3 and rip.face_count == 1 and rip.stride == 32
    assert [(a.semantic, a.offset, a.types) for a in rip.attrs] == [("POSITION", 0, [0, 0, 0]), ("NORMAL", 12, [0, 0, 0]),
                                                                    ("TEXCOORD", 24, [0, 0])]
    assert rip.textures == ["tex_0.dds"] and rip.shaders == ["vs.bin"] and list(rip.indices) == [0, 1, 2]


@pytest.mark.parametrize("data,msg", [
    (make_rip(TRI, [(0, 1, 2)], magic=0x12345678), "magic"),
    (make_rip(TRI, [(0, 1, 2)], version=3), "version"),
    (make_rip(TRI, [(0, 1, 2)])[:-5], "truncated"),
    (make_rip(TRI, [(0, 1, 2)])[:20], "truncated"),
    (struct.pack("<8I", nr.RIP_MAGIC, 4, 1, nr.MAX_VERTICES + 1, 12, 0, 0, 0), "bounds"),
    (struct.pack("<8I", nr.RIP_MAGIC, 4, 0, 1, nr.MAX_STRIDE + 4, 0, 0, 0), "out of bounds"),
    (struct.pack("<8I", nr.RIP_MAGIC, 4, 0, 1, 12, 0, 0, 1) + b"POSITION\0" + struct.pack("<4I", 0, 4, 12, 3)
     + struct.pack("<3I", 0, 0, 0), "outside"),
    (struct.pack("<8I", nr.RIP_MAGIC, 4, 0, 1, 12, 0, 0, 1) + b"POSITION\0" + struct.pack("<4I", 0, 0, 12, 3)
     + struct.pack("<3I", 0, 7, 0), "element type"),
    (struct.pack("<8I", nr.RIP_MAGIC, 4, 0, 0, 12, 1, 0, 0) + b"A" * (nr.MAX_STR + 10), "unterminated"),
])
def test_parse_rejects_bad_files_with_a_reason(data, msg):
    with pytest.raises(nr.RipError, match=msg):
        nr.parse_rip(data)


def test_mesh_converts_d3d_handedness_and_drops_out_of_range_faces():
    rip = nr.parse_rip(make_rip(TRI, [(0, 1, 2), (0, 1, 9)]))
    m = nr.mesh_from_rip(rip)
    assert list(m["tris"]) == [0, 2, 1] and m["dropped_faces"] == 1
    assert list(m["pos"])[6:9] == [0.0, 1.0, -2.0]
    assert list(m["nrm"])[:3] == [0.0, 0.0, -1.0] and m["texture"] == "tex_0.dds"
    keep = nr.mesh_from_rip(rip, d3d_to_gltf=False)
    assert list(keep["tris"]) == [0, 1, 2] and list(keep["pos"])[8] == 2.0


def test_rips_to_glb_builds_valid_binary_gltf_with_embedded_png_texture(tmp_path):
    (tmp_path / "Mesh_0000.rip").write_bytes(make_rip(TRI, [(0, 1, 2)], textures=("tex_0.png",)))
    (tmp_path / "Mesh_0001.rip").write_bytes(make_rip(TRI, [(0, 1, 2)], textures=("missing.dds",), uv=False))
    (tmp_path / "Mesh_0002.rip").write_bytes(b"junk")
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 16
    (tmp_path / "tex_0.png").write_bytes(png)
    glb, summary = nr.rips_to_glb(nr.rip_files(tmp_path))
    gl, binary = read_glb(glb)
    assert summary["meshes"] == 2 and summary["triangles"] == 2 and summary["textures"] == 1
    assert summary["skipped"][0]["file"] == "Mesh_0002.rip" and "missing.dds" in summary["missing_textures"]
    assert [n["name"] for n in gl["nodes"]] == ["Mesh_0000", "Mesh_0001"]
    acc = gl["accessors"][gl["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
    assert acc["min"] == [0.0, 0.0, -2.0] and acc["max"] == [1.0, 1.0, 0.0]
    view = gl["bufferViews"][gl["images"][0]["bufferView"]]
    assert binary[view["byteOffset"]:view["byteOffset"] + view["byteLength"]] == png
    assert "TEXCOORD_0" not in gl["meshes"][1]["primitives"][0]["attributes"]


def test_rips_to_glb_reports_why_nothing_converted(tmp_path):
    (tmp_path / "a.nr").write_bytes(b"NR")
    with pytest.raises(nr.RipError, match="2.x"):
        nr.rips_to_glb(nr.rip_files(tmp_path, "*.nr"))


def test_texture_names_cannot_escape_the_rip_folder(tmp_path):
    for name, want in (("..\\..\\secret.png", "secret.png"), ("../x/y.png", "y.png"), ("..", None)):
        rip = nr.parse_rip(make_rip(TRI, [(0, 1, 2)], textures=(name,)))
        assert nr.mesh_from_rip(rip)["texture"] == want


def _install(tmp_path, dll_names=("NinjaRipperIntercept.dll",)):
    home = tmp_path / "NinjaRipper1.7.1"
    (home / "x64").mkdir(parents=True)
    (home / "NinjaRipper.exe").write_bytes(b"MZ")
    for n in dll_names:
        (home / "x64" / n).write_bytes(b"MZ")
    (home / "x64" / "d3d11.dll").write_bytes(b"MZ")
    return home


def test_find_install_from_config_and_dll_heuristic(tmp_path, monkeypatch):
    home = _install(tmp_path)
    monkeypatch.setattr(nr, "pe_machine", lambda p: "x64")
    cfg = Config(data_dir=tmp_path / "data", ninja_ripper={"path": str(home)})
    inst = nr.find_install(cfg, refresh=True)
    assert inst["home"] == str(home) and inst["launcher"].endswith("NinjaRipper.exe") and inst["source"] == "config"
    assert [Path(p).name for p in inst["dlls"]["x64"]] == ["NinjaRipperIntercept.dll"]   # the d3d11.dll proxy is skipped
    assert nr.pick_dll(inst, "x64").name == "NinjaRipperIntercept.dll"


def test_pick_dll_refuses_to_guess(tmp_path):
    inst = {"dlls": {"x64": ["a_ninja.dll", "b_ripper.dll"]}}
    with pytest.raises(nr.Unsupported, match="dll"):
        nr.pick_dll(inst, "x64")
    assert nr.pick_dll(inst | {"dll": "C:/x/chosen.dll"}, "x64").name == "chosen.dll"


def test_check_hook_explains_how_to_install(tmp_path, monkeypatch):
    monkeypatch.setattr(nr, "search_roots", lambda cfg: [])
    monkeypatch.setattr(nr.sys, "platform", "win32")
    monkeypatch.delenv("NINJA_RIPPER_HOME", raising=False)
    nr._FOUND.clear()
    why = nr.check(Config(data_dir=tmp_path))
    assert "not installed" in why and "never downloads" in why and "[ninja_ripper] path" in why
    monkeypatch.setattr(nr.sys, "platform", "linux")
    assert "Windows" in nr.check(Config(data_dir=tmp_path))


def test_list_rips_and_snapshot_find_rip_sets_newest_first(tmp_path):
    a, b = tmp_path / "out" / "2026-10-01", tmp_path / "out" / "2026-10-02"
    for d, t in ((a, 100), (b, 200)):
        d.mkdir(parents=True)
        (d / "Mesh_0000.rip").write_bytes(make_rip(TRI, [(0, 1, 2)]))
        (d / "tex_0.dds").write_bytes(b"DDS ")
        import os
        os.utime(d / "Mesh_0000.rip", (t, t))
        os.utime(d / "tex_0.dds", (t, t))
    sets = nr.list_rips([tmp_path / "out"])
    assert [Path(s["path"]).name for s in sets] == ["2026-10-02", "2026-10-01"]
    assert sets[0]["rip"] == 1 and sets[0]["textures"] == 1
    assert len(nr.snapshot([tmp_path / "out"])) == 2


def test_hotkey_parsing():
    assert nr.parse_hotkey("F10") == [0x79]
    assert nr.parse_hotkey("ctrl+F11") == [0x11, 0x7A]
    assert nr.parse_hotkey("") == [0x79]
    for bad in ("F99", "ctrl", "ctrl+banana"):
        with pytest.raises(ValueError):
            nr.parse_hotkey(bad)


# --- background-testing rules -----------------------------------------------------------------

def test_agent_owned_matches_the_session_observer_rule():
    assert bt.agent_owned({"owner": "agent"}, {})
    assert bt.agent_owned({}, {"agent_use": True})
    assert not bt.agent_owned({"owner": "you"}, {"agent_use": True})
    assert not bt.agent_owned(None, None)


def test_worker_testing_reason_honours_the_tasks_menu():
    testing = {"excluded": ["operator-pc"], "workers": [{"id": "w1", "name": "operator-pc", "background_testing": False},
                                                        {"id": "w2", "name": "test-pc", "background_testing": True}]}
    assert "excluded" in bt.worker_testing_reason(testing, "w1")
    assert bt.worker_testing_reason(testing, "w2") is None
    assert "not registered" in bt.worker_testing_reason(testing, "w9")


class FakeApi:
    def __init__(self, testing, labels=None, jobs=None):
        self.testing, self.labels, self.jobs = testing, labels or {}, jobs or {}

    def __call__(self, ctx, method, path, **kw):
        if path == "/api/testing/workers":
            return self.testing
        if path == "/api/session_labels":
            return self.labels
        if path.startswith("/api/jobs/"):
            return self.jobs.get(path.rsplit("/", 1)[-1], {})
        raise AssertionError(path)


OK_TESTING = {"excluded": [], "workers": [{"id": "w2", "name": "test-pc", "background_testing": True}]}


def ctx(agent_use=True):
    arts = {}
    return SimpleNamespace(agent_use=agent_use, worker="w2", server="http://cp", headers={}, job_id="j1",
                           config=Config(), progress=lambda *a: None, arts=arts,
                           artifact=lambda name, data, mt="", **prov: arts.__setitem__(name, data))


def test_guard_requires_agent_jobs_allowed_pcs_and_agent_owned_sessions(monkeypatch):
    monkeypatch.setattr(nr, "_api", FakeApi(OK_TESTING, labels={"w2-abc": {"owner": "you"}}, jobs={"def": {"agent_use": True}}))
    with pytest.raises(PermissionError, match="agent test jobs"):
        nr.guard(ctx(agent_use=False))
    nr.guard(ctx())                                                  # launch on an allowed PC
    with pytest.raises(PermissionError, match="not an agent-owned"):
        nr.guard(ctx(), "w2-abc")                                    # the operator's session
    nr.guard(ctx(), "w2-def")                                        # launched by an agent job
    monkeypatch.setattr(nr, "_api", FakeApi({"excluded": ["test-pc"], "workers": OK_TESTING["workers"]}))
    with pytest.raises(PermissionError, match="excluded"):
        nr.guard(ctx())


def test_rip_and_stop_only_touch_processes_the_tool_launched(tmp_path, monkeypatch):
    c = ctx()
    c.config = Config(data_dir=tmp_path)
    monkeypatch.setattr(nr, "_api", FakeApi(OK_TESTING))
    monkeypatch.setattr(nr, "find_install", lambda cfg, refresh=False: {"home": str(tmp_path), "launcher": None, "dlls": {}})
    with pytest.raises(PermissionError, match="not launched"):
        nr.ninja_ripper(nr.NinjaIn(op="rip", pid=4242), c)
    with pytest.raises(PermissionError, match="not launched"):
        nr.ninja_ripper(nr.NinjaIn(op="stop", pid=4242), c)
    nr.save_ledger(c.config, {"77": {"attached": True}})
    with pytest.raises(PermissionError, match="session_op"):
        nr.ninja_ripper(nr.NinjaIn(op="stop", pid=77), c)


def test_rip_presses_the_hotkey_and_reports_the_new_set(tmp_path, monkeypatch):
    c = ctx()
    c.config = Config(data_dir=tmp_path, ninja_ripper={"hotkey": "F11", "output_dir": str(tmp_path / "rips")})
    (tmp_path / "rips").mkdir()
    monkeypatch.setattr(nr, "_api", FakeApi(OK_TESTING))
    monkeypatch.setattr(nr, "find_install", lambda cfg, refresh=False: {"home": str(tmp_path / "nr"), "launcher": None, "dlls": {}})
    monkeypatch.setattr(nr, "alive", lambda pid: True)
    nr.save_ledger(c.config, {"55": {"attached": False}})
    pressed = []

    def fake_press(hk, pid):
        pressed.append((hk, pid))
        d = tmp_path / "rips" / "frame1"
        d.mkdir()
        (d / "Mesh_0000.rip").write_bytes(make_rip(TRI, [(0, 1, 2)]))
        return {"hotkey": hk, "focused": True}
    monkeypatch.setattr(nr, "press", fake_press)
    monkeypatch.setattr(nr.time, "sleep", lambda s: None)
    out = nr.ninja_ripper(nr.NinjaIn(op="rip", pid=55, wait_s=5), c)["result"]
    assert pressed == [("F11", 55)] and out["new_files"] == 1 and Path(out["sets"][0]["path"]).name == "frame1"
    imp = nr.ninja_ripper(nr.NinjaIn(op="import", name="crate"), c)
    assert imp["result"]["summary"]["meshes"] == 1 and imp["result"]["glb"]
    assert nr._validate(nr.NinjaOut(**imp), c.arts) == []
    assert nr._validate(nr.NinjaOut(**imp), {"ninja_rip.glb": b"nope"}) == ["ninja_rip.glb is not a binary glTF"]


def test_launch_refuses_32bit_injection_and_unknown_files(tmp_path, monkeypatch):
    c = ctx()
    c.config = Config(data_dir=tmp_path)
    monkeypatch.setattr(nr, "_api", FakeApi(OK_TESTING))
    monkeypatch.setattr(nr, "find_install", lambda cfg, refresh=False: {"home": str(tmp_path), "launcher": None, "dlls": {}})
    with pytest.raises(FileNotFoundError):
        nr.ninja_ripper(nr.NinjaIn(op="launch", exe=str(tmp_path / "nope.exe")), c)
    exe = tmp_path / "game.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(nr, "pe_machine", lambda p: "x86")
    with pytest.raises(nr.Unsupported, match="64-bit"):
        nr.ninja_ripper(nr.NinjaIn(op="launch", exe=str(exe), mode="inject"), c)
    with pytest.raises(nr.Unsupported, match="launcher_args"):
        nr.ninja_ripper(nr.NinjaIn(op="launch", exe=str(exe)), c)


def test_launcher_template_expands_args():
    assert nr._fmt(["{launcher}", "-exe", "{exe}", "{args}", "-out", "{out}"], launcher="L", exe="E", args=["a", "b"],
                   cwd="C", out="O") == ["L", "-exe", "E", "a", "b", "-out", "O"]
