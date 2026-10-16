"""The owned SaveMGO portable bundle, isolated from generic RPCS3 provisioning.

Discovery fingerprints bounded ZIP metadata and critical content. First staging
also records the complete archive SHA-256. No account/configuration values are
parsed, reported, uploaded, or shared between PCs.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import tempfile
import time
import unicodedata
import zipfile
import zlib

PREFIX = 'SaveMGO/SaveMGO/MGO2/'
EXECUTABLE_SHA256 = '39077e3a9b0fee50045fed4be8dbc423ef222fd0addfab109e6593358beebab3'
EBOOT = 'dev_hdd0/game/NPMG00010/USRDIR/EBOOT.BIN'
DATA_ROOT = 'dev_hdd0/game/NPMG00020/USRDIR'
SFO = 'dev_hdd0/game/NPMG00010/PARAM.SFO'
DATA_SFO = 'dev_hdd0/game/NPMG00020/PARAM.SFO'
FIRMWARE = 'dev_flash/vsh/module/vsh.self'
SCHEMA = 'gbox-savemgo-bundle-v1'
RECEIPT = '.gbox-savemgo-receipt.json'
class BundleError(ValueError):
    """Invalid or busy owned package; user cancellation exceptions stay separate."""


def claim_reason(worker, job):
    """Old workers ignore the bundle launch kind and would select generic RPCS3.

    The builtin asset tool is advertised only by a process that loaded this bundle
    integration. A source update on disk alone does not refresh an older worker.
    """
    game = (job.get('input') or {}).get('game') or {}
    if job.get('tool') != 'launch_game' or (game.get('launch') or {}).get('kind') != 'savemgo_bundle':
        return None
    if worker.get('os') != 'windows':
        return 'SaveMGO needs a Windows PC with bundled-emulator support; queued launch retained.'
    if 'savemgo_assets' not in (worker.get('tools') or []):
        return ('Restart the idle gBox app on this PC to load SaveMGO bundled-emulator support; '
                'the queued launch is retained until its worker has refreshed.')
    return None


MAX_ENTRIES, MAX_EXPANDED, MAX_ARCHIVE, MAX_MEMBER = 6000, 12 * 2**30, 10 * 2**30, 2 * 2**30
BLOCK = 1024 * 1024
MUTABLE_DIRS = {'cache', 'captures', 'config', 'guiconfigs', 'glcache', 'log',
                'dev_bdvd', 'dev_flash2', 'dev_flash3', 'dev_hdd1', 'dev_usb000',
                'games', 'savestates', 'shaderlog', 'ppu_progs', 'spu_progs'}


def _notify(progress, percent, text):
    if progress:
        progress(percent, text)  # Cancellation exceptions must propagate.


def _mutable(name):
    lower = name.casefold()
    return (lower.split('/')[0] in MUTABLE_DIRS or lower.startswith('dev_hdd0/home/')
            or lower.startswith('dev_hdd0/vsh/') or lower.startswith('dev_hdd0/locks/')
            or lower in {'rpcs3.buf', 'update_history.log'} or lower.startswith('rpcs3.log'))


def _absolute(path):
    return Path(os.path.abspath(os.fspath(path)))  # Do not resolve away a link before checking it.


def _drive_type(anchor):
    if os.name == 'nt':
        import ctypes
        return ctypes.windll.kernel32.GetDriveTypeW(str(anchor))
    return None


def _remote_runtime(path):
    return str(path).startswith(('\\\\', '//')) or _drive_type(path.anchor) == 4


def _guard(path):
    path = _absolute(path)
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise BundleError('SaveMGO paths cannot traverse symlinks or reparse points')
    return path


def _safe_name(name):
    if not name or len(name) > 240 or '\\' in name or name.startswith('/'):
        raise BundleError('Unsafe SaveMGO ZIP path')
    parts = name.rstrip('/').split('/')
    for part in parts:
        if (not part or part in ('.', '..') or part[-1:] in ('.', ' ')
                or re.search(r'[<>:"|?*]', part) or unicodedata.normalize('NFC', part) != part
                or any(unicodedata.category(c) in ('Cc', 'Cf') for c in part)
                or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part, re.I)):
            raise BundleError('Unsafe or ambiguous Windows ZIP path')
    if len(parts) > 24:
        raise BundleError('SaveMGO ZIP path is too deep')
    return '/'.join(parts)


def _inventory(archive):
    entries, seen, files = archive.infolist(), {}, {}
    if not 1 <= len(entries) <= MAX_ENTRIES:
        raise BundleError('SaveMGO ZIP entry budget exceeded')
    expanded = 0
    for entry in entries:
        full = _safe_name(entry.orig_filename)
        key = full.casefold()
        if key in seen:
            raise BundleError('SaveMGO ZIP contains duplicate or case-colliding paths')
        seen[key] = entry.is_dir()
        mode = stat.S_IFMT(entry.external_attr >> 16)
        if (mode not in (0, stat.S_IFREG, stat.S_IFDIR) or entry.external_attr & 0x400
                or entry.flag_bits & 1 or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
            raise BundleError('Unsupported linked, encrypted or compressed SaveMGO member')
        if entry.is_dir() and full in ('SaveMGO', 'SaveMGO/SaveMGO', PREFIX.rstrip('/')):
            continue
        if not entry.filename.startswith(PREFIX):
            raise BundleError('SaveMGO ZIP has content outside its fixed portable root')
        relative = full[len(PREFIX):] if full.startswith(PREFIX) else ''
        if not relative:
            continue
        if not entry.is_dir():
            if not 0 <= entry.file_size <= MAX_MEMBER:
                raise BundleError('SaveMGO ZIP member budget exceeded')
            expanded += entry.file_size
            if expanded > MAX_EXPANDED:
                raise BundleError('SaveMGO expanded-size budget exceeded')
            files[relative] = {'path': relative, 'size': entry.file_size, 'crc32': f'{entry.CRC:08x}',
                               'compressed_size': entry.compress_size, 'method': entry.compress_type}
    for full in seen:
        if any(seen.get(str(p)) is False for p in PurePosixPath(full).parents if str(p) != '.'):
            raise BundleError('SaveMGO file/directory path collision')
    return files, expanded


def _read_critical(archive, name, maximum):
    info = archive.getinfo(PREFIX + name)
    if not 0 < info.file_size <= maximum:
        raise BundleError('Invalid SaveMGO critical-file size')
    try:
        with archive.open(info) as stream:
            data = stream.read(maximum + 1)
    except (zipfile.BadZipFile, RuntimeError, zlib.error, EOFError):
        raise BundleError('SaveMGO critical ZIP member failed integrity validation') from None
    if len(data) != info.file_size:
        raise BundleError('Invalid SaveMGO critical-file content')
    return data


def identify(path):
    """Read-only discovery; None for unrelated ZIPs, ValueError for invalid candidate bundles."""
    path = Path(path)
    if path.suffix.casefold() != '.zip' or not path.is_file():
        return None
    before = path.stat()
    try:
        opened = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return None
    with opened as archive:
        if PREFIX + 'rpcs3.exe' not in archive.namelist():
            return None
        if before.st_size > MAX_ARCHIVE:
            raise BundleError('SaveMGO archive-size budget exceeded')
        files, expanded = _inventory(archive)
        required = {'rpcs3.exe', EBOOT, SFO, DATA_SFO, FIRMWARE, 'config/config.yml',
                    'config/rpcn.yml', 'config/input_configs/global/Default.yml'}
        if not required <= files.keys() or any(not any(n.startswith('dev_hdd0/game/NPMG00020/USRDIR/' + group + '/')
                                                      for n in files) for group in ('dbm', 'o', 'sdpack', 'speech')):
            raise BundleError('Incomplete SaveMGO emulator, firmware, configuration or game-data bundle')
        critical = {}
        for name, bound in [('rpcs3.exe', 128 * 2**20), (EBOOT, 32 * 2**20),
                            (SFO, 64 * 1024), (DATA_SFO, 64 * 1024), (FIRMWARE, 32 * 2**20)]:
            data = _read_critical(archive, name, bound)
            critical[name] = hashlib.sha256(data).hexdigest()
            if name == 'rpcs3.exe' and (not data.startswith(b'MZ') or critical[name] != EXECUTABLE_SHA256):
                raise BundleError('SaveMGO requires its exact bundled RPCS3 executable')
            if name == EBOOT and not data.startswith(b'SCE\0'):
                raise BundleError('SaveMGO boot executable is not an owned PS3 SELF')
            if name in (SFO, DATA_SFO):
                from .catalog import param_sfo
                if not data.startswith(b'\0PSF'):
                    raise BundleError('SaveMGO title metadata is malformed')
                try:
                    values = param_sfo(data)
                except (ValueError, IndexError, KeyError, struct.error):
                    raise BundleError('SaveMGO title metadata is malformed') from None
                if values.get('TITLE_ID') != ('NPMG00010' if name == SFO else 'NPMG00020'):
                    raise BundleError('SaveMGO title identity differs')
                if name == SFO and values.get('APP_VER') != '00.30':
                    raise BundleError('Unsupported SaveMGO game revision')
        ordered = [files[k] for k in sorted(files)]
        fingerprint = hashlib.sha256(json.dumps({'schema': SCHEMA, 'files': ordered, 'critical': critical},
                                                sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise BundleError('SaveMGO archive changed during discovery')
    return {'schema': SCHEMA, 'kind': 'savemgo_bundle', 'title': 'Metal Gear Online', 'platform': 'ps3',
            'serial': 'NPMG00010', 'app_ver': '00.30', 'source_fingerprint': fingerprint,
            'archive_size': before.st_size, 'files': ordered, 'critical_sha256': critical,
            'file_count': len(files), 'expanded_bytes': expanded,
            'immutable_manifest': [r for r in ordered if not _mutable(r['path'])],
            'launch': {'kind': 'savemgo_bundle', 'source_fingerprint': fingerprint,
                       'executable': 'rpcs3.exe', 'eboot': EBOOT}}


def _byte_progress(text, done, total, started):
    elapsed = max(.001, time.monotonic() - started)
    return f'{text}: {done / 2**20:,.1f} / {total / 2**20:,.1f} MiB ({done / 2**20 / elapsed:,.1f} MiB/s)'


def _hash_file(path, progress=None, percent=0, text='Checking SaveMGO content', *, span=0):
    digest, crc, size = hashlib.sha256(), 0, 0
    total, started, last_notice = path.stat().st_size, time.monotonic(), 0.0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(BLOCK), b''):
            digest.update(block)
            crc = zlib.crc32(block, crc)
            size += len(block)
            now = time.monotonic()
            if size == total or now - last_notice >= .5:
                _notify(progress, percent + span * min(1, size / max(1, total)),
                        _byte_progress(text, size, total, started))
                last_notice = now
    return {'size': size, 'sha256': digest.hexdigest(), 'crc32': f'{crc & 0xffffffff:08x}'}


def verify_install(root, profile, *, progress=None, _cache=None, _percent=5):
    """Verify local immutable files; leave personal configuration/saves/caches untouched.

    A private previous staging receipt can reuse unchanged file stats. Critical
    files are always rehashed; initial adoption hashes/CRC-checks every immutable file.
    """
    root = _guard(root)
    if not root.is_dir() or profile.get('schema') != SCHEMA:
        raise BundleError('Invalid SaveMGO installation or discovery profile')
    if profile.get('critical_sha256', {}).get('rpcs3.exe') != EXECUTABLE_SHA256:
        raise BundleError('Discovery profile has the wrong pinned SaveMGO executable')
    expected = profile['immutable_manifest']
    cached = (_cache or {}).get('immutable_files', {}) if (_cache or {}).get('source_fingerprint') == profile['source_fingerprint'] else {}
    verified = {}
    for index, row in enumerate(expected):
        name = row['path']
        _safe_name(name)
        path = _guard(root / name)
        info = path.stat()
        if not path.is_file() or info.st_size != row['size'] or info.st_nlink != 1:
            raise BundleError('SaveMGO immutable installation file is missing, linked or differs')
        previous = cached.get(name, {})
        if (name not in profile['critical_sha256'] and Path(name).suffix.casefold() not in ('.exe', '.dll')
                and previous.get('size') == info.st_size
                and previous.get('mtime_ns') == info.st_mtime_ns and previous.get('crc32') == row['crc32']
                and re.fullmatch('[0-9a-f]{64}', str(previous.get('sha256', '')))):
            result = {k: previous[k] for k in ('size', 'crc32', 'sha256')}
        else:
            result = _hash_file(path, progress, _percent, 'Verifying local SaveMGO immutable files')
        after = path.stat()
        if ((info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
                or result['size'] != row['size'] or result['crc32'] != row['crc32']
                or previous.get('sha256') and result['sha256'] != previous['sha256']
                or name in profile['critical_sha256'] and result['sha256'] != profile['critical_sha256'][name]):
            raise BundleError('SaveMGO immutable content integrity differs')
        verified[name] = result | {'mtime_ns': info.st_mtime_ns}
        if index % 32 == 0:
            _notify(progress, _percent, f'Verifying local SaveMGO immutable files: {index + 1:,} / {len(expected):,} checked')
    # Unknown DLLs beside the executable could change what the pinned runner loads.
    expected_names = {r['path'].casefold() for r in profile['files']}
    for path in root.iterdir():
        if path.suffix.casefold() in ('.exe', '.dll') and path.name.casefold() not in expected_names:
            raise BundleError('Unexpected executable or DLL in SaveMGO portable home')
    return {'home': root, 'executable': root / 'rpcs3.exe', 'eboot': root / EBOOT,
            'data_root': root / DATA_ROOT,
            'source_fingerprint': profile['source_fingerprint'], 'verified': True,
            'immutable_files': verified, 'reused': True, 'profile_values_read': False}


@contextmanager
def _lock(path, progress, timeout=180):
    _guard(path)
    with path.open('a+b') as handle:
        handle.seek(0)
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b'0'); handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt
                    handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise BundleError('Another SaveMGO preparation is still active')
                _notify(progress, 1, 'Waiting for this PC’s SaveMGO preparation'); time.sleep(.2)
        try:
            yield
        finally:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def prepare(archive, config, progress=None, *, existing_root=None, expected_fingerprint=None):
    """Prepare a per-PC portable home atomically; never update an existing profile."""
    archive = _guard(archive)
    profile = identify(archive)
    if profile is None:
        raise BundleError('This is not the supported SaveMGO portable package')
    if expected_fingerprint is not None and profile['source_fingerprint'] != expected_fingerprint:
        raise BundleError('SaveMGO package changed since catalog discovery; rescan before preparing')
    base = _guard(_absolute(config.runtime) / 'savemgo')
    if _remote_runtime(base):
        raise BundleError('SaveMGO executable/profile must live on a local disk')
    base.mkdir(parents=True, exist_ok=True)
    fingerprint = profile['source_fingerprint']
    home = _guard(base / fingerprint)
    with _lock(base / (fingerprint + '.lock'), progress):
        if home.exists():
            receipt_path = _guard(home / RECEIPT)
            if not receipt_path.is_file() or receipt_path.stat().st_size > 4 * 2**20:
                raise BundleError('Existing SaveMGO home has no bounded verified receipt; left unchanged')
            receipt = json.loads(receipt_path.read_text(encoding='utf8'))
            if (receipt.get('schema') != SCHEMA or receipt.get('source_fingerprint') != fingerprint
                    or not re.fullmatch('[0-9a-f]{64}', str(receipt.get('archive_sha256', '')))):
                raise BundleError('SaveMGO receipt identity differs; existing profile left unchanged')
            result = verify_install(home, profile, progress=progress, _cache=receipt)
            return result | {'archive_sha256': receipt['archive_sha256']}
        # The existing office package is adopted read-only, never copied to another PC.
        existing = Path(existing_root) if existing_root is not None else None
        if existing is not None and existing.is_dir():
            receipt_path = base / (fingerprint + '-existing.json')
            cached = json.loads(receipt_path.read_text()) if receipt_path.is_file() and receipt_path.stat().st_size <= 4 * 2**20 else None
            if cached and cached.get('installed_root') != str(_absolute(existing)):
                cached = None
            try:
                result = verify_install(existing, profile, progress=progress, _cache=cached)
            except (OSError, BundleError):
                result = None
            if result:
                source = _hash_file(archive, progress, 5, 'Fingerprinting owned SaveMGO archive', span=85)
                receipt = {'schema': SCHEMA, 'source_fingerprint': fingerprint,
                           'archive_sha256': source['sha256'], 'installed_root': str(_absolute(existing)),
                           'immutable_files': result['immutable_files']}
                receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding='utf8')
                return result | {'archive_sha256': source['sha256'], 'adopted_existing': True}
        if shutil.disk_usage(base).free < profile['expanded_bytes'] + 512 * 2**20:
            raise BundleError('Not enough local disk space for SaveMGO plus safety margin')
        before = archive.stat()
        source = _hash_file(archive, progress, 1, 'Fingerprinting owned SaveMGO archive', span=14)
        stage = Path(tempfile.mkdtemp(prefix='.stage-' + fingerprint[:12] + '-', dir=base))
        try:
            copied, immutable = 0, {}
            started, last_notice = time.monotonic(), 0.0
            with zipfile.ZipFile(archive) as zipped:
                _inventory(zipped)
                for row in profile['files']:
                    target = _guard(stage / row['path'])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    digest, crc, size = hashlib.sha256(), 0, 0
                    with zipped.open(PREFIX + row['path']) as src, target.open('xb') as dst:
                        for block in iter(lambda: src.read(BLOCK), b''):
                            size += len(block)
                            if size > row['size']:
                                raise BundleError('SaveMGO member exceeded its declared size')
                            dst.write(block); digest.update(block); crc = zlib.crc32(block, crc)
                            copied += len(block)
                            now = time.monotonic()
                            if copied == profile['expanded_bytes'] or now - last_notice >= .5:
                                _notify(progress, 15 + 75 * copied / max(1, profile['expanded_bytes']),
                                    _byte_progress('Preparing this PC’s SaveMGO portable home', copied, profile['expanded_bytes'], started))
                                last_notice = now
                    if size != row['size'] or f'{crc & 0xffffffff:08x}' != row['crc32']:
                        raise BundleError('SaveMGO archive member CRC/size differs')
                    if not _mutable(row['path']):
                        immutable[row['path']] = {'size': size, 'crc32': row['crc32'],
                            'sha256': digest.hexdigest(), 'mtime_ns': target.stat().st_mtime_ns}
            after = archive.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise BundleError('SaveMGO archive changed during preparation')
            receipt = {'schema': SCHEMA, 'source_fingerprint': fingerprint,
                       'archive_sha256': source['sha256'], 'immutable_files': immutable}
            (stage / RECEIPT).write_text(json.dumps(receipt, sort_keys=True), encoding='utf8')
            result = verify_install(stage, profile, progress=progress, _cache=receipt, _percent=90)
            _notify(progress, 95, 'SaveMGO portable home verified; ready for its bundled emulator')
            stage.rename(home)
            return result | {'home': home, 'executable': home / 'rpcs3.exe', 'eboot': home / EBOOT,
                             'data_root': home / DATA_ROOT,
                             'archive_sha256': source['sha256'], 'reused': False}
        except BaseException:
            # Only our unpublished, uniquely named stage is removed; never any existing profile.
            if stage.parent == base and stage.name.startswith('.stage-' + fingerprint[:12] + '-'):
                _guard(stage); shutil.rmtree(stage)
            raise


@contextmanager
def runtime_lease(home):
    """Hold for the entire owned emulator lifetime; a second launch fails closed."""
    home = _guard(home)
    if _remote_runtime(home) or not home.is_dir():
        raise BundleError('SaveMGO portable home is unavailable')
    with _lock(home / '.gbox-savemgo-running.lock', None, timeout=0):
        yield
