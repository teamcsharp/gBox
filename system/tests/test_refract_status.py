"""Read-only readiness uses bounded local evidence, never setup or game launch."""
import json
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from gbox import refract as R
from gbox import refract_status as S
from test_refract import quest_config, declared, PKG


def write(path, data=b"present"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(data).encode() if isinstance(data, dict) else data)


@pytest.fixture
def install(tmp_path, monkeypatch):
    from gbox import storage_policy
    monkeypatch.setattr(R, "HOST_OS", "windows")
    monkeypatch.setattr(R.platform, "node", lambda: "QUESTPC")
    monkeypatch.setattr(R.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(storage_policy, "system_drive", lambda *args: "Z:")
    # These filesystem fixtures also run on Linux CI; native drive inspection is tested separately.
    monkeypatch.setattr(S, "_network_path", lambda path: str(path).startswith(("\\\\", "//")))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    for name in ("setup", "download", "run_setup", "stage_package", "install_app"):
        monkeypatch.setattr(R, name, lambda *args, **kwargs: pytest.fail("status attempted setup"))
    monkeypatch.setattr(R.subprocess, "run", lambda *args, **kwargs: pytest.fail("status ran a process"))
    monkeypatch.setattr(R.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("status launched a process"))
    monkeypatch.setattr(R.socket, "socket", lambda *args, **kwargs: pytest.fail("status opened a socket"))
    cfg = quest_config(tmp_path, owned={PKG: declared()})
    lay = R.Layout(R.root(cfg))
    return cfg, lay


def complete(lay):
    for rel in R.RELEASE_FILES:
        write(lay.release / rel)
    write(lay.release / R.RELEASE_RECEIPT, {k: R.REFRACT[k] for k in ("version", "tag", "commit", "sha256")})
    for path in (lay.aapt2, lay.system_img, lay.sysroot / "refract_symlinks.txt", lay.sysroot / "system/bin/linker64"):
        write(path)
    for name in ("com.android.runtime", "com.android.art"):
        (lay.sysroot / "apex" / name).mkdir(parents=True)
    for i in range(50):
        write(lay.sysroot / "system/lib64" / f"lib{i}.so")
    dest = lay.packages / PKG / "203"
    apk = dest / f"{PKG}.apk"
    write(apk, b"apk")
    members = [[f"{PKG}.apk", 3, 123]]
    for kind in ("main", "patch"):
        name = f"{kind}.203.{PKG}.obb"
        write(dest / "obb" / name, b"obb-data")
        members.append([f"{PKG}/{name}", 8, 456])
    package = {"package": PKG, "version_code": 203, "apk": str(apk), "apk_size": 3, "apk_crc": 123}
    write(dest / R.PACKAGE_RECEIPT, {"package": package, "identity": {"members": members},
                                   "verified": {row[0]: "crc32" for row in members}})
    app = lay.apps / PKG
    write(app / "app.properties", f"package={PKG}\nversionCode=203\nactivity=test.Activity\napk={apk}\n".encode())
    write(app / "classes.jar")
    for name in ("libbink2androidarm64.so", "libbinkpluginandroidarm64.so", "libc++_shared.so", "libovraudio64.so",
                 "libovrplatformloader.so", "libOVRPlugin.so", "libplaycore.so", "libUE4.so", "libvrapi.so",
                 "libopenxr_runtime.so", "librefract_driver.so", "librefract_ovrplatform.so"):
        write(app / "lib/arm64" / name)
    write(app / R.INSTALL_RECEIPT, {"want": {"apk": [str(apk), 3, 123],
                                           "installer": R.installer_version(), "refract": R.REFRACT["version"]}})


def test_missing_install_reports_facts_without_creating_folders(install):
    cfg, lay = install
    assert not lay.root.exists()
    result = S.status(cfg)
    assert result["state"] == "missing" and not result["setup_ready"]
    assert result["ownership"] == {"owned": True, "via": "declaration"}
    assert not result["rendering_verified"] and not result["gameplay_verified"]
    assert not result["memory_read_supported"] and not result["autoplay_supported"]
    assert not lay.root.exists()


def test_complete_receipts_and_files_are_setup_evidence_not_gameplay_proof(install):
    cfg, lay = install
    complete(lay)
    before = {str(path.relative_to(lay.root)): path.read_bytes() for path in lay.root.rglob("*") if path.is_file()}
    result = S.status(cfg)
    assert result["state"] == "ready" and result["setup_ready"]
    assert result["checks"]["package_files"] and result["checks"]["app_current"]
    assert result["verification"] == "receipts_and_file_metadata"
    assert not result["content_hashes_verified"] and not result["gameplay_verified"]
    assert before == {str(path.relative_to(lay.root)): path.read_bytes() for path in lay.root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("broken", ["native", "obb", "apk_size", "classes", "installer", "receipt", "sysroot",
                                  "game_library", "app_identity"])
def test_partial_install_cannot_report_ready(install, broken):
    cfg, lay = install
    complete(lay)
    dest, app = lay.packages / PKG / "203", lay.apps / PKG
    if broken == "native":
        (lay.release / R.RELEASE_FILES[0]).unlink()
    elif broken == "obb":
        (dest / "obb" / f"patch.203.{PKG}.obb").unlink()
    elif broken == "apk_size":
        write(dest / f"{PKG}.apk", b"shorter-than-receipt")
    elif broken == "classes":
        (app / "classes.jar").unlink()
    elif broken == "installer":
        receipt = json.loads((app / R.INSTALL_RECEIPT).read_text())
        receipt["want"]["installer"] = "old"
        write(app / R.INSTALL_RECEIPT, receipt)
    elif broken == "receipt":
        write(dest / R.PACKAGE_RECEIPT, b"{broken")
    elif broken == "game_library":
        (app / "lib/arm64/libUE4.so").unlink()
    elif broken == "app_identity":
        write(app / "app.properties", b"package=com.other.game\nversionCode=203\nactivity=test.Activity\n")
    else:
        (lay.sysroot / "system/lib64/lib0.so").unlink()
    result = S.status(cfg)
    assert result["state"] == "partial" and not result["setup_ready"]
    assert result["missing"]


def test_bounded_receipt_and_clock_never_fall_back_to_setup(install):
    cfg, lay = install
    complete(lay)
    write(lay.apps / PKG / R.INSTALL_RECEIPT, b"x" * (S.MAX_JSON_BYTES + 1))
    result = S.status(cfg)
    assert not result["setup_ready"] and "app_receipt:oversize" in result["issues"]
    times = iter([0., 10.])
    result = S.status(cfg, clock=lambda: next(times, 10.))
    assert result["state"] == "incomplete" and not result["setup_ready"]
    assert result["budget_exhausted"]


def test_receipt_paths_are_not_followed_and_contents_are_not_returned(install):
    cfg, lay = install
    complete(lay)
    path = lay.packages / PKG / "203" / R.PACKAGE_RECEIPT
    receipt = json.loads(path.read_text())
    receipt["package"]["apk"] = "C:/private/credential-secret"
    receipt["identity"]["members"].append(["../../credential-secret", 1, 1])
    write(path, receipt)
    result = S.status(cfg)
    assert not result["setup_ready"]
    assert "credential-secret" not in json.dumps(result)


@pytest.mark.parametrize("extra", [{"path": "D:/other"}, {"pid": 7}, {"op": "setup"},
                                  {"package": "../bad"}, {"version_code": 204}])
def test_typed_tool_has_no_arbitrary_path_pid_operation_or_unknown_build(extra):
    with pytest.raises(ValidationError):
        S.StatusIn(**extra)


def test_tool_returns_worker_identity_without_session_or_network(install):
    cfg, _ = install
    result = S.refract_status(S.StatusIn(), SimpleNamespace(config=cfg, worker="worker-id"))
    assert result["worker_id"] == "worker-id" and result["result"]["version_code"] == 203


def test_cli_status_reuses_the_same_read_only_evidence(install, monkeypatch, capsys):
    from gbox import config
    cfg, _ = install
    monkeypatch.setattr(config, "load", lambda: cfg)
    assert R.main(["status"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schema"] == "gbox.refract.readiness/1" and result["state"] == "missing"


def test_network_root_is_rejected_before_filesystem_checks(install, monkeypatch):
    cfg, _ = install
    cfg.quest.root["windows"] = "//server/share/refract"
    monkeypatch.setattr(S._Probe, "entry", lambda *a, **k: pytest.fail("network filesystem accessed"))
    result = S.status(cfg)
    assert result["state"] == "unsupported" and not result["setup_ready"]


def test_meta_ownership_is_bounded_and_only_returns_ownership_facts(install):
    cfg, lay = install
    cfg.quest.owned = {}
    write(R.meta_library_path(), {"access_token": "secret-token", "games": [
        {"package": PKG, "owned": True, "source": "meta", "private_note": "not returned"}]})
    result = S.status(cfg)
    assert result["ownership"] == {"owned": True, "via": "meta"}
    assert result["state"] == "missing" and "secret-token" not in json.dumps(result)
    write(R.meta_library_path(), {"games": [{"package": PKG, "owned": True, "source": "import"}]})
    assert S.status(cfg)["ownership"] == {"owned": False}


def test_operation_budget_marks_result_incomplete(install, monkeypatch):
    cfg, lay = install
    complete(lay)
    monkeypatch.setattr(S, "MAX_OPERATIONS", 1)
    result = S.status(cfg, clock=lambda: 0.)
    assert result["operations"] == 1 and result["budget_exhausted"]
    assert result["state"] == "incomplete" and not result["setup_ready"]


@pytest.mark.parametrize("member", [["different.apk", 4, 999], [f"patch.204.{PKG}.obb", 8, 456]])
def test_conflicting_package_receipt_reports_partial_instead_of_raising(install, member):
    cfg, lay = install
    complete(lay)
    path = lay.packages / PKG / "203" / R.PACKAGE_RECEIPT
    receipt = json.loads(path.read_text())
    receipt["identity"]["members"].append(member)
    write(path, receipt)
    result = S.status(cfg)
    assert result["state"] == "partial" and not result["checks"]["package_receipt"]
    assert "package_receipt:invalid" in result["issues"]


def test_redirected_installation_ancestor_is_rejected_without_reading_descendants(install, monkeypatch):
    cfg, lay = install
    complete(lay)
    original_lstat, original_open = Path.lstat, Path.open
    inspected = []

    def lstat(path, *args, **kwargs):
        inspected.append(path)
        if path == lay.root:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400, st_size=0)
        assert not path.is_relative_to(lay.root), "followed a redirected ancestor"
        return original_lstat(path, *args, **kwargs)

    def open_file(path, *args, **kwargs):
        assert not path.is_relative_to(lay.root), "read a redirected descendant"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(Path, "open", open_file)
    result = S.status(cfg)
    assert not result["setup_ready"] and "filesystem:redirected" in result["issues"]
    assert inspected.count(lay.root) == 1  # bounded cached ancestor checks


def test_agent_worker_dispatch_does_not_install_audio_dependencies_or_change_volume(install, monkeypatch):
    from gbox import worker as W
    cfg, _ = install
    monkeypatch.setattr(W, "HOST_OS", "windows")
    monkeypatch.setattr(W.deps, "install_for", lambda *a: pytest.fail("read-only job attempted dependency/audio setup"))
    delivered = []
    monkeypatch.setattr(W, "_deliver_finished", lambda *a: delivered.append(a[3]))
    execute = W.execute

    def attributed(name, inp, ctx):
        assert ctx.agent_use is True
        return execute(name, inp, ctx)

    monkeypatch.setattr(W, "execute", attributed)
    job = {"id": "a" * 16, "tool": "refract_status", "input": {}, "agent_use": True}
    W._run_job(job, cfg, "worker-id", "http://unused", {}, None, set(), set(), set(), None)
    assert delivered[0]["ok"] and delivered[0]["output"]["result"]["state"] == "missing"
    assert W._quiet_agent_job(job) is False  # also keeps it out of the background volume loop
    assert W._quiet_agent_job(job | {"tool": "launch_game"}) is True


def test_mapped_network_drive_is_identified_without_opening_it(monkeypatch):
    monkeypatch.setattr(R, "HOST_OS", "windows")
    calls = []
    api = SimpleNamespace(GetDriveTypeW=lambda anchor: calls.append(anchor) or 4)
    monkeypatch.setattr(R, "ctypes", SimpleNamespace(windll=SimpleNamespace(kernel32=api), c_wchar_p=lambda x: x))
    from pathlib import PureWindowsPath
    assert S._network_path(PureWindowsPath("M:/refract"))
    assert calls == ["M:\\"]
