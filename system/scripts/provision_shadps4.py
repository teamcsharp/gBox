"""Install the pinned official portable Windows core without launching it.

Usage: python scripts/provision_shadps4.py --destination PATH [--archive ZIP]
The optional ZIP must match the same published SHA-256 as a downloaded copy.
This does not install games, firmware, a launcher, or change running sessions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import urllib.request
import zipfile


VERSION = '0.20.0'
RELEASE_URL = 'https://github.com/shadps4-emu/shadPS4/releases/tag/v.0.20.0'
ARCHIVE_URL = 'https://github.com/shadps4-emu/shadPS4/releases/download/v.0.20.0/shadps4-win64-sdl-2026-0.20.0.zip'
ARCHIVE_SHA256 = 'd5cdc55c57e85e5fe44ff867b420246dc832077356d943ccc43c5d950c878b37'
ARCHIVE_SIZE = 31574011
MANIFEST = 'gbox-shadps4-install.json'


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if len(members) > 2000 or sum(item.file_size for item in members) > 512 * 1024 * 1024:
        raise ValueError('Unexpected portable archive size')
    seen = set()
    for item in members:
        name = item.filename.replace('\\', '/')
        path = PurePosixPath(name)
        if (path.is_absolute() or '..' in path.parts or ':' in name or
                stat.S_ISLNK(item.external_attr >> 16) or
                any(part.endswith((' ', '.')) for part in path.parts)):
            raise ValueError('Unsafe archive member: ' + item.filename)
        key = str(path).casefold()
        if key in seen or key == MANIFEST.casefold():
            raise ValueError('Duplicate or reserved archive member: ' + item.filename)
        seen.add(key)
    return members


def provision(destination: Path, archive: Path | None = None) -> dict:
    destination = destination.expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f'Destination already exists; keep it or choose a new folder: {destination}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if archive is None:
        # Keep the verified archive next to the installation for reproducibility.
        archive = destination.parent / f'shadps4-win64-{VERSION}.zip'
        if not archive.exists():
            request = urllib.request.Request(ARCHIVE_URL, headers={'User-Agent': 'gBox-shadPS4-provisioner'})
            partial = archive.with_suffix('.zip.part')
            with urllib.request.urlopen(request, timeout=60) as response, partial.open('xb') as output:
                remaining = ARCHIVE_SIZE + 1
                while block := response.read(min(1024 * 1024, remaining)):
                    output.write(block)
                    remaining -= len(block)
                    if remaining <= 0:
                        raise ValueError('Download exceeds the published release asset size')
            partial.rename(archive)
    archive = archive.resolve()
    if archive.stat().st_size != ARCHIVE_SIZE or digest(archive) != ARCHIVE_SHA256:
        raise ValueError('Archive does not match the pinned official shadPS4 release size/SHA-256')
    with zipfile.ZipFile(archive) as bundle:
        members = _members(bundle)
        # Extract to a fresh sibling and only publish the completed installation.
        # A failed stage is retained for inspection; existing runtimes are untouched.
        stage = Path(tempfile.mkdtemp(prefix=destination.name + '-stage-', dir=destination.parent))
        files = {}
        for item in members:
            path = stage.joinpath(*PurePosixPath(item.filename.replace('\\', '/')).parts)
            if item.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(item) as src, path.open('xb') as output:
                shutil.copyfileobj(src, output)
            files[path.relative_to(stage).as_posix()] = digest(path)
    executable = [name for name in files if PurePosixPath(name).name.casefold() == 'shadps4.exe']
    if len(executable) != 1:
        raise ValueError('Expected exactly one shadPS4.exe in the official portable archive')
    manifest = {'version': VERSION, 'release_url': RELEASE_URL, 'archive_url': ARCHIVE_URL,
                'archive_sha256': ARCHIVE_SHA256, 'archive_size': ARCHIVE_SIZE,
                'executable': executable[0], 'files': files, 'launched': False}
    (stage / MANIFEST).write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    stage.rename(destination)
    return {'destination': str(destination), 'executable': str(destination / executable[0]),
            'manifest': str(destination / MANIFEST), 'version': VERSION, 'launched': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'gbox-data/runtime/shadps4')
    parser.add_argument('--archive', type=Path, help='Previously downloaded official ZIP (same hash required)')
    args = parser.parse_args()
    print(json.dumps(provision(args.destination, args.archive), indent=2))


if __name__ == '__main__':
    main()
