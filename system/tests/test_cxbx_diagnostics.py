"""The diagnostic collector cannot become a general file/process inspector."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import cxbx_diagnostics as diag


@pytest.fixture
def evidence(tmp_path):
    runtime = tmp_path / "runtime"
    home = runtime / "xbox" / "cxbx"
    home.mkdir(parents=True)
    xbe = runtime / "extract" / "rom-exact" / "Jet Set Radio Future (USA)" / "default.xbe"
    xbe.parent.mkdir(parents=True)
    xbe.write_bytes(b"XBEH" + b"game" * 200)
    for name in ("cxbxr-ldr.exe", "cxbxr-emu.dll", "cxbx.exe", "SDL2.dll"):
        (home / name).write_bytes(b"MZ" + name.encode() * 100)
    (home / "settings.ini").write_text(
        "[gui]\nDataStorageToggle=0x1\nRecentXbeFiles=private-other-game\n"
        "[core]\nLoggedModules=0x1\nLoggedModules=0x2\nFlagsLLE=0\n"
        "[video]\nDirect3DDevice=0\nFullScreen=false\n"
        "[input-profile-0]\nDeviceName=private-controller\n"
        "[network]\nadapter_name=private-network\n")
    (home / ".gbox-installed.json").write_text(json.dumps({"tag": "CI-585c49a", "sha256": "a" * 64,
                                                           "source": "https://example.invalid/release", "secret": "private"}))
    (home / "gbox-kernel.log").write_text("Xbe::Xbe: Title identified as Jet Set Radio Future\nHost D3DCaps\n")
    (home / "gbox-launch.log").write_bytes(b"")
    save = home / "EmuDisk" / "Partition1" / "save.dat"
    save.parent.mkdir(parents=True)
    save.write_bytes(b"private-save-never-read")
    launch = {"game_id": "game", "job_id": "job", "worker_id": "worker", "session_id": "worker-job",
              "started": 100, "finished": 104, "detail": {"rom": str(xbe), "launch_pid": 43128}}
    return SimpleNamespace(runtime=runtime), home, xbe, launch


def collect(evidence):
    cfg, _, xbe, launch = evidence
    return diag.collect(cfg, xbe=xbe, launch=launch)


def test_exact_snapshot_preserves_files_and_never_reads_saves_or_processes(evidence, monkeypatch):
    cfg, home, xbe, launch = evidence
    initial = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in cfg.runtime.rglob("*") if p.is_file()}
    real_open, opened = os.open, []

    def guarded(path, flags, *args, **kwargs):
        assert flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC) == 0
        assert "EmuDisk" not in str(path)
        opened.append(Path(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(diag.os, "open", guarded)
    import psutil
    monkeypatch.setattr(psutil, "Process", lambda *_: pytest.fail("PID-only inspection is forbidden"))
    result = collect(evidence)
    assert result["read_only"] is True
    assert result["files"]["default.xbe"]["sha256"] == hashlib.sha256(xbe.read_bytes()).hexdigest()
    assert result["settings"]["selected_values"]["core"]["loggedmodules"] == ["0x1", "0x2"]
    serialized = json.dumps(result)
    assert "private-other-game" not in serialized and "private-controller" not in serialized
    assert "private-network" not in serialized and "private-save-never-read" not in serialized
    assert "secret" not in result["installation_receipt"]["recorded"]
    assert result["process"]["state"] == "not_inspected"
    assert result["process"]["recorded_launch_pid"] == 43128
    assert len(opened) == 9
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == state for p, state in initial.items())


@pytest.mark.parametrize("field,value", [("session_id", "other-job"), ("job_id", ""),
    ("game_id", 1), ("started", float("nan")), ("finished", float("inf")),
    ("started", True), ("finished", 99), ("detail", {})])
def test_invalid_launch_binding_fails_before_file_read(evidence, monkeypatch, field, value):
    cfg, _, xbe, launch = evidence
    monkeypatch.setattr(diag, "_read", lambda *a, **k: pytest.fail("bad identity read a file"))
    with pytest.raises(ValueError):
        diag.collect(cfg, xbe=xbe, launch=launch | {field: value})


@pytest.mark.parametrize("location", ["outside/default.xbe", "runtime/xbox/cxbx/default.xbe",
                                       "runtime/extract/rom-exact/save.dat"])
def test_caller_cannot_select_unrelated_source(evidence, location):
    cfg, _, _, launch = evidence
    target = cfg.runtime.parent / location
    with pytest.raises(ValueError):
        diag.collect(cfg, xbe=target, launch=launch | {"detail": {"rom": str(target)}})


def test_missing_files_and_oversized_binary_are_explicit(evidence, monkeypatch):
    _, home, _, _ = evidence
    (home / "SDL2.dll").unlink()
    monkeypatch.setattr(diag, "BINARY_LIMIT", 10)
    result = collect(evidence)
    assert result["files"]["SDL2.dll"]["state"] == "missing"
    assert result["files"]["default.xbe"]["state"] == "unavailable"
    assert "size limit" in result["files"]["default.xbe"]["reason"]
    assert "sha256" not in result["files"]["default.xbe"]


def test_log_is_bounded_sample_not_false_full_hash(evidence):
    _, home, _, _ = evidence
    value = b"A" * diag.LOG_SAMPLE + b"private-middle" * 10000 + b"Z" * diag.LOG_SAMPLE
    (home / "gbox-kernel.log").write_bytes(value)
    item = collect(evidence)["logs"]["gbox-kernel.log"]
    assert item["sampled"] and "sha256" not in item and "text" not in item
    assert len(item["head"]) == len(item["tail"]) == diag.LOG_SAMPLE
    assert item["head_sha256"] == hashlib.sha256(value[:diag.LOG_SAMPLE]).hexdigest()
    assert "private-middle" not in json.dumps(item)
    assert "not independently established" in item["attribution"]


def test_stale_log_and_current_settings_not_asserted_as_launch_snapshot(evidence):
    _, home, _, _ = evidence
    os.utime(home / "gbox-kernel.log", (50, 50))
    result = collect(evidence)
    assert result["logs"]["gbox-kernel.log"]["mtime_before_launch"]
    assert any("launch-time" in value for value in result["limitations"])


def test_symlink_file_never_read(evidence, tmp_path):
    _, home, _, _ = evidence
    source = tmp_path / "secret"
    source.write_text("should-not-be-read")
    (home / "settings.ini").unlink()
    (home / "settings.ini").symlink_to(source)
    result = collect(evidence)["settings"]
    assert result["state"] == "unavailable" and "symlinks" in result["reason"]
    assert "should-not-be-read" not in json.dumps(result)


def test_reparse_parent_rejected_before_open(evidence, monkeypatch):
    _, home, _, _ = evidence
    original = Path.lstat

    def fake(path, *a, **k):
        info = original(path, *a, **k)
        if path == home:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.setattr(Path, "lstat", fake)
    result = collect(evidence)
    assert result["files"]["cxbxr-ldr.exe"]["state"] == "unavailable"
    assert result["files"]["default.xbe"]["state"] == "read"


def test_growth_during_read_is_bounded_and_has_no_digest(evidence, monkeypatch):
    _, home, _, _ = evidence
    target = home / "cxbxr-ldr.exe"
    original = diag._final_path

    def mutate(reader):
        if os.fstat(reader.fileno()).st_ino == target.stat().st_ino:
            with target.open("ab") as writer:
                writer.write(b"growth" * 1000)
        return original(reader)

    monkeypatch.setattr(diag, "_final_path", mutate)
    item = collect(evidence)["files"]["cxbxr-ldr.exe"]
    assert item["state"] == "unavailable" and "changed" in item["reason"]
    assert "sha256" not in item


def test_handle_target_mismatch_rejected_before_read(evidence, monkeypatch):
    monkeypatch.setattr(diag, "_final_path", lambda reader: Path("/unrelated/secret"))
    assert collect(evidence)["files"]["default.xbe"]["state"] == "unavailable"


def test_malformed_receipt_is_diagnostic_not_crash(evidence):
    _, home, _, _ = evidence
    (home / ".gbox-installed.json").write_text("{malformed}")
    item = collect(evidence)["installation_receipt"]
    assert "parse_error" in item and "text" not in item


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
def test_nonfinite_receipt_is_explicit_parse_error(evidence, constant):
    _, home, _, _ = evidence
    (home / ".gbox-installed.json").write_text('{"at":' + constant + '}')
    result = collect(evidence)
    assert "parse_error" in result["installation_receipt"]
    assert "recorded" not in result["installation_receipt"]
    json.dumps(result, allow_nan=False)
