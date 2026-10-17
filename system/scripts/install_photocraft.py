#!/usr/bin/env python3
"""Install the pinned, verified upstream PhotoCraft web build into GBox data.

No Rust build, global installation or service restart is performed. The release
archive and every extracted file are verified against the reviewed manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen
import zipfile


SYSTEM = Path(__file__).resolve().parents[1]
MANIFEST = SYSTEM / "gbox" / "photocraft_runtime.json"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verified(root: Path, manifest: dict) -> bool:
    for name, record in manifest["files"].items():
        item = root / name
        if item.is_symlink() or not item.is_file():
            return False
        if item.stat().st_size != record["size"] or digest(item.read_bytes()) != record["sha256"]:
            return False
    return True


def install(data_dir: Path, archive_path: Path | None = None, *, manifest_path: Path = MANIFEST) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = data_dir.resolve() / manifest["runtime_dir"]
    root.resolve().relative_to(data_dir.resolve())
    if root.is_symlink():
        raise ValueError("Runtime directory must not be a symbolic link")
    if verified(root, manifest):
        return {"version": manifest["version"], "state": "ready", "path": str(root), "downloaded": False}
    archive = manifest["archive"]
    if archive_path is None:
        request = Request(archive["url"], headers={"User-Agent": "GBox-PhotoCraft-Installer/1"})
        with urlopen(request, timeout=120) as response:
            data = response.read(archive["size"] + 1)
    else:
        if archive_path.stat().st_size != archive["size"]:
            raise ValueError("PhotoCraft archive size does not match the pinned release")
        data = archive_path.read_bytes()
    if len(data) != archive["size"] or digest(data) != archive["sha256"]:
        raise ValueError("PhotoCraft archive failed the pinned SHA256/size verification")
    # Extract only the exact flat allowlist. Do not use extractall, executable
    # installers, or paths controlled by the downloaded archive.
    import io

    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        names = [entry.filename for entry in bundle.infolist() if not entry.is_dir()]
        expected = {archive["prefix"] + name for name in manifest["files"]}
        if len(names) != len(expected) or set(names) != expected:
            raise ValueError("PhotoCraft archive file list differs from the pinned release")
        contents = {}
        for name, record in manifest["files"].items():
            if Path(name).name != name or "/" in name or "\\" in name:
                raise ValueError("Invalid runtime manifest filename")
            entry = bundle.getinfo(archive["prefix"] + name)
            if entry.file_size != record["size"]:
                raise ValueError(f"Unexpected size for {name}")
            content = bundle.read(entry)
            if digest(content) != record["sha256"]:
                raise ValueError(f"SHA256 verification failed for {name}")
            contents[name] = content
    root.mkdir(parents=True, exist_ok=True)
    # Files are replaced atomically only after the complete archive is verified.
    # Existing unrelated files and saved editing projects remain untouched.
    for name, content in contents.items():
        target = root / name
        if target.is_symlink():
            raise ValueError("Runtime files must not be symbolic links")
        with tempfile.NamedTemporaryFile(dir=root, prefix=".install-", delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(content)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    if not verified(root, manifest):
        raise RuntimeError("Installed PhotoCraft runtime did not verify")
    return {"version": manifest["version"], "state": "ready", "path": str(root), "downloaded": archive_path is None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=SYSTEM / "gbox-data")
    parser.add_argument("--archive", type=Path, help="Use an already downloaded release zip (still verified)")
    args = parser.parse_args()
    print(json.dumps(install(args.data_dir, args.archive), indent=2))


if __name__ == "__main__":
    main()
