"""Read-only, content-addressed references to code actually installed on the prime worker."""
import hashlib
import json
from pathlib import Path


def root():
    return Path(__file__).resolve().parents[1]


def read(relative, source=None):
    base = Path(source or root()).resolve()
    parts = Path(relative).parts
    if not parts or parts[0] != 'gbox' or '..' in parts or Path(relative).suffix != '.py':
        raise ValueError('Only gbox Python source files may be shared')
    path = base / relative
    if any(p.is_symlink() for p in (path, *path.parents) if p != base and base in p.parents):
        raise ValueError('Shared source cannot be a symlink')
    if not path.resolve().is_relative_to(base / 'gbox'):
        raise ValueError('Source path escapes gbox')
    data = path.read_bytes()
    if len(data) > 4 * 1024**2:
        raise ValueError('Source exceeds 4 MiB limit')
    return data


def inventory(source=None):
    base = Path(source or root()).resolve()
    out = []
    for path in sorted((base / 'gbox').rglob('*.py')):
        rel = path.relative_to(base).as_posix()
        try:
            data = read(rel, base)
            out.append({'path': rel, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)})
        except (ValueError, OSError):
            continue
    return {'source_root': str(base), 'files': out,
            'note': 'Installed source is reference evidence, not necessarily reviewed Git main. Never edit this runtime in place.'}


def references(workspace, destination, source=None):
    """Preserve missing/different runtime sources outside the tracked checkout, with provenance."""
    base = Path(source or root())
    dest = Path(destination)
    manifest = inventory(base)
    differences = []
    for entry in manifest['files']:
        tracked = Path(workspace) / 'system' / entry['path']
        live = read(entry['path'], base)
        if tracked.is_file() and tracked.read_bytes().replace(b'\r\n', b'\n') == live.replace(b'\r\n', b'\n'):
            continue
        digest = hashlib.sha256(live).hexdigest()
        target = dest / 'blobs' / (digest + '.py')
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(live)
        differences.append(entry | {'sha256': digest, 'reference': str(target),
                                    'state': 'different' if tracked.exists() else 'missing_in_checkout'})
    dest.mkdir(parents=True, exist_ok=True)
    index = dest / 'manifest.json'
    index.write_text(json.dumps(manifest | {'differences': differences}, indent=2), encoding='utf-8')
    return {'manifest': str(index), 'source_root': str(base), 'differences': len(differences),
            'instructions': 'Consult this manifest before claiming a module is missing. Read reference copies; '
                            'port required source into the isolated checkout, test, and publish through normal delivery. '
                            'Kiosks can retrieve installed sources through authenticated /api/analysis/sources and /file?path=.'}
