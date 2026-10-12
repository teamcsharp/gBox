"""#1393 "paste": blender_copy must land copybuffer.blend where the operator's Blender reads it, not only in the worker's
%TEMP%. The candidate directories (Blender's preference, its computed temp base, the running Blender's own TEMP and
user profile, the worker's TEMP / LOCALAPPDATA, C:\\tmp) are all written, and the result says which ones were."""
import os
import sys
import types
from pathlib import Path

import pytest

from gbox import blender_copy as bc


def mkdirs(tmp_path, *names):
    out = []
    for n in names:
        p = tmp_path / n
        p.mkdir(parents=True, exist_ok=True)
        out.append(p)
    return out


def test_candidate_dirs_prefers_blenders_own_temp_and_drops_missing_and_duplicates(tmp_path):
    pref, base, bltemp, lad, worker_temp, lad_worker, sysdrive = mkdirs(
        tmp_path, "pref", "base", "bl-temp", "jay-localappdata/Temp", "worker-temp", "svc-localappdata/Temp", "drive")
    (sysdrive / "tmp").mkdir()
    running = [{"exe": "C:/B/blender.exe", "pid": 7, "user": "JAYBUILTFINALE\\jay", "temp": str(bltemp),
                "localappdata": str(lad.parent), "userprofile": ""}]
    probe = {"pref": str(pref), "base": str(base), "version": "4.2.3"}
    env = {"TEMP": str(worker_temp), "TMP": str(worker_temp).upper(),          # TMP = TEMP in another case: one entry
           "LOCALAPPDATA": str(lad_worker.parent), "SystemDrive": str(sysdrive)}
    dirs = bc.candidate_dirs(running, probe, env)
    got = [os.path.normcase(str(d)) for d in dirs]
    want = [os.path.normcase(str(p)) for p in (pref, base, bltemp, lad, worker_temp)]
    assert got[:5] == want                                      # Blender's own places first, then the worker's TEMP
    assert os.path.normcase(str(lad_worker)) in got and os.path.normcase(str(sysdrive / "tmp")) in got
    assert len(got) == len(set(got))                            # no duplicates
    assert all(Path(d).is_dir() for d in got)                   # a missing dir is never offered (Blender would not use it)
    # C:\Users\jay\...\Temp was derived from the process user but does not exist here: dropped, not written
    assert os.path.normcase(bc._user_temp("JAYBUILTFINALE\\jay")) not in got


def test_candidate_dirs_without_blender_running_still_has_the_worker_temp(tmp_path, monkeypatch):
    (worker_temp,) = mkdirs(tmp_path, "wt")
    monkeypatch.setattr(bc, "running_blenders", lambda: [])
    dirs = bc.candidate_dirs(None, {}, {"TEMP": str(worker_temp)})
    assert dirs[0] == worker_temp


def test_user_temp_from_domain_user():
    assert bc._user_temp("JAYBUILTFINALE\\Ehm Ecks").endswith(os.path.join("Users", "Ehm Ecks", "AppData", "Local", "Temp"))
    assert bc._user_temp("") == ""


def test_running_blenders_reads_exe_user_and_environment(monkeypatch):
    class Proc:
        def __init__(self, info, user, env):
            self.info, self._user, self._env = info, user, env
        def username(self):
            return self._user
        def environ(self):
            if self._env is None:
                raise PermissionError("another user")
            return self._env
    fake = types.SimpleNamespace(process_iter=lambda attrs: [
        Proc({"name": "blender.exe", "exe": "C:/B/4.2/blender.exe", "pid": 5}, "PC\\jay", {"TEMP": "C:/jaytemp", "LOCALAPPDATA": "C:/jay/lad"}),
        Proc({"name": "blender.exe", "exe": "C:/B/4.1/blender.exe", "pid": 6}, "PC\\other", None),
        Proc({"name": "notepad.exe", "exe": "C:/n.exe", "pid": 8}, "PC\\jay", {}),
        Proc({"name": "blender.exe", "exe": None, "pid": 9}, "PC\\jay", {})])
    monkeypatch.setitem(sys.modules, "psutil", fake)
    got = bc.running_blenders()
    assert [g["exe"] for g in got] == ["C:/B/4.2/blender.exe", "C:/B/4.1/blender.exe"]
    assert got[0]["temp"] == "C:/jaytemp" and got[0]["localappdata"] == "C:/jay/lad" and got[0]["user"] == "PC\\jay"
    assert got[1]["temp"] == "" and got[1]["user"] == "PC\\other"           # unreadable environment: still a candidate exe


def test_probe_tempdir_parses_blenders_answer(monkeypatch):
    calls = []
    def run(args, **kw):
        calls.append(args)
        return types.SimpleNamespace(stdout='Blender 4.2.3\nGBOX_TEMP {"base": "C:/jay/Temp", "pref": "", "version": "4.2.3"}\n', stderr="")
    monkeypatch.setattr(bc.subprocess, "run", run)
    assert bc.probe_tempdir("C:/B/blender.exe") == {"base": "C:/jay/Temp", "pref": "", "version": "4.2.3"}
    assert "--factory-startup" not in calls[0] and "-b" in calls[0]        # the operator's preferences must count
    monkeypatch.setattr(bc.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no exe")))
    assert bc.probe_tempdir("C:/B/blender.exe") == {}


@pytest.fixture
def fake_blender(monkeypatch, tmp_path):
    """A pretend headless Blender: the import script 'writes' the staged copybuffer and reports GBOX_RESULT."""
    runs = []
    def run(args, **kw):
        runs.append(args)
        if "--python-expr" in args:
            return types.SimpleNamespace(stdout='GBOX_TEMP {"base": "' + str(tmp_path / "base").replace("\\", "/") + '", "pref": "", "version": "4.2.3"}', stderr="")
        out = Path(args[args.index("--") + 2])
        out.write_bytes(b"BLENDER-v423" + b"\0" * 32)
        return types.SimpleNamespace(stdout='GBOX_RESULT {"objects": 3, "meshes": 2, "triangles": 1200, "materials": 2, "images": 2, "packed": 2, "version": "4.2.3"}', stderr="")
    monkeypatch.setattr(bc.subprocess, "run", run)
    monkeypatch.setattr(bc, "find_blender", lambda: "C:/B/4.2/blender.exe")
    monkeypatch.setattr(bc, "running_blenders", lambda: [{"exe": "C:/B/4.2/blender.exe", "pid": 1, "user": "PC\\jay", "temp": "", "localappdata": "", "userprofile": ""}])
    monkeypatch.setattr(bc.platform, "node", lambda: "JAYBUILTFINALE")
    return runs


def test_to_blender_writes_every_candidate_and_reports_them(fake_blender, monkeypatch, tmp_path):
    a, b = mkdirs(tmp_path, "base", "worker-temp")
    missing = tmp_path / "gone"                                              # listed but unwritable: reported, not fatal
    monkeypatch.setattr(bc, "candidate_dirs", lambda running, probe: [a, b, missing])
    r = bc.to_blender(tmp_path / "asset.glb", ["Node.001"])
    assert r["copybuffers"] == [str(a / "copybuffer.blend"), str(b / "copybuffer.blend")]
    assert r["copybuffer"] == r["copybuffers"][0]
    assert (a / "copybuffer.blend").read_bytes().startswith(b"BLENDER-v423") and (b / "copybuffer.blend").is_file()
    assert list(r["skipped"]) == [str(missing)] and "FileNotFoundError" in r["skipped"][str(missing)]
    assert r["blender"] == "C:/B/4.2/blender.exe" and r["blender_version"] == "4.2.3" and r["host"] == "JAYBUILTFINALE"
    assert r["running"] == ["C:/B/4.2/blender.exe"] and r["blender_tempdir"].endswith("base")
    assert r["objects"] == 3 and r["triangles"] == 1200 and r["packed"] == 2 and "version" not in r
    assert "Ctrl+V" in r["next"] and "JAYBUILTFINALE" in r["next"]
    imp = next(x for x in fake_blender if "--python" in x)
    assert "--factory-startup" in imp and imp[imp.index("--") + 3] == '["Node.001"]'
    assert imp[imp.index("--") + 2].endswith("copybuffer.blend") and not Path(imp[imp.index("--") + 2]).exists()   # staged in a temp dir, gone after


def test_to_blender_fails_readably_when_nothing_could_be_written(fake_blender, monkeypatch, tmp_path):
    monkeypatch.setattr(bc, "candidate_dirs", lambda running, probe: [tmp_path / "nope"])
    with pytest.raises(RuntimeError, match="could not be written anywhere.*nope"):
        bc.to_blender(tmp_path / "asset.glb")
    monkeypatch.setattr(bc, "candidate_dirs", lambda running, probe: [])
    with pytest.raises(RuntimeError, match="no temp directory exists"):
        bc.to_blender(tmp_path / "asset.glb")


def test_to_blender_reports_an_import_failure(fake_blender, monkeypatch, tmp_path):
    monkeypatch.setattr(bc.subprocess, "run", lambda args, **kw: types.SimpleNamespace(stdout="", stderr="Error: glTF import failed"))
    with pytest.raises(RuntimeError, match="couldn't import.*glTF import failed"):
        bc.to_blender(tmp_path / "asset.glb")


def test_tool_result_carries_the_source_for_the_preview(fake_blender, monkeypatch, tmp_path):
    (a,) = mkdirs(tmp_path, "t")
    monkeypatch.setattr(bc, "candidate_dirs", lambda running, probe: [a])
    fetched = []
    monkeypatch.setattr(bc, "_fetch", lambda ctx, url, suffix: fetched.append(url) or (tmp_path / "asset.glb"))
    r = bc.blender_copy(bc.CopyIn(artifact="ab12"), None)["result"]            # @tool returns the plain function
    assert fetched == ["/api/artifacts/ab12"] and r["source"] == "/api/artifacts/ab12" and r["copybuffers"] == [str(a / "copybuffer.blend")]
    assert bc.blender_copy(bc.CopyIn(character="mario"), None)["result"]["source"] == "/api/characters/mario/model"
    assert bc.blender_copy(bc.CopyIn(path=str(tmp_path / "asset.glb")), None)["result"]["source"] == str(tmp_path / "asset.glb")
