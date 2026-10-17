"""Release verification must fail before installing any untrusted bytes."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile

import pytest


spec = importlib.util.spec_from_file_location("install_photocraft", Path(__file__).parents[1] / "scripts" / "install_photocraft.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def fixture(tmp_path, *, extra_entry=False, wrong_file_hash=False):
    files = {"editor.js": b"verified editor", "LICENSE-MIT": b"retained license"}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        for name, content in files.items():
            bundle.writestr("photocraft-test/" + name, content)
        if extra_entry:
            bundle.writestr("photocraft-test/../../escaped", b"must never extract")
    archive = tmp_path / "release.zip"
    archive.write_bytes(output.getvalue())
    manifest = {
        "version": "test",
        "runtime_dir": "photocraft/runtime/test",
        "archive": {"url": "https://unused.invalid/release.zip", "size": archive.stat().st_size,
                    "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "prefix": "photocraft-test/"},
        "files": {name: {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()} for name, content in files.items()},
    }
    if wrong_file_hash:
        manifest["files"]["editor.js"]["sha256"] = "0" * 64
    pin = tmp_path / "manifest.json"
    pin.write_text(json.dumps(manifest))
    return archive, pin, tmp_path / "data", files


def test_installs_verified_bytes_and_retains_existing_user_projects(tmp_path):
    archive, pin, data, files = fixture(tmp_path)
    root = data / "photocraft/runtime/test"
    root.mkdir(parents=True)
    project = root / "saved-project.pcraft"
    project.write_bytes(b"user work")
    result = installer.install(data, archive, manifest_path=pin)
    assert result["state"] == "ready"
    assert {name: (root / name).read_bytes() for name in files} == files
    assert project.read_bytes() == b"user work"
    archive.unlink()
    assert installer.install(data, archive, manifest_path=pin)["downloaded"] is False


@pytest.mark.parametrize("attack", ["archive_hash", "file_hash", "extra_path"])
def test_corrupt_or_unexpected_release_never_writes_runtime(tmp_path, attack):
    archive, pin, data, _ = fixture(tmp_path, extra_entry=attack == "extra_path", wrong_file_hash=attack == "file_hash")
    if attack == "archive_hash":
        content = archive.read_bytes()
        archive.write_bytes(content[:-1] + bytes([content[-1] ^ 1]))
    with pytest.raises(ValueError):
        installer.install(data, archive, manifest_path=pin)
    assert not data.exists()
    assert not (tmp_path / "escaped").exists()
