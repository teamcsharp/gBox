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
UPDATE_RECEIPT = '.gbox-savemgo-launcher-update.json'
UPDATE_SCHEMA = 'gbox-savemgo-applied-launcher-update-v1'
DATA_UPDATE_RECEIPT = '.gbox-savemgo-data-update.json'
DATA_UPDATE_SCHEMA = 'gbox-savemgo-verified-data-update-v1'
UPDATE_ZIP = 'dev_hdd0/tmp/NPMG00010.zip'
UPDATE_PREFIX = 'dev_hdd0/game/NPMG00010/'
UPDATE_FILES = {'USRDIR/EBOOT.BIN': 32 * 2**20, 'PARAM.SFO': 64 * 1024,
                'ICON0.PNG': 2 * 2**20, 'PIC1.PNG': 16 * 2**20, 'PS3LOGO.DAT': 64 * 1024}
UPDATE_PATHS = {UPDATE_PREFIX + name for name in UPDATE_FILES}
LAUNCHER_TEMP_FILES = {'dev_hdd0/tmp/mgo_launcher.txt'}
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
            or lower in {'rpcs3.buf', 'update_history.log'} or lower.startswith('rpcs3.log')
            or lower in LAUNCHER_TEMP_FILES)


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


def _read_receipt(path):
    path = _guard(path)
    if not path.is_file() or path.stat().st_size > 4 * 2**20 or path.stat().st_nlink != 1:
        raise BundleError('SaveMGO receipt is missing, linked or unbounded; existing profile left unchanged')
    try:
        result = json.loads(path.read_text(encoding='utf8'))
    except (ValueError, UnicodeError):
        raise BundleError('SaveMGO receipt is malformed; existing profile left unchanged') from None
    if not isinstance(result, dict):
        raise BundleError('SaveMGO receipt is malformed; existing profile left unchanged')
    return result


def _base_receipt(receipt, profile):
    expected = {row['path']: row for row in profile['immutable_manifest']}
    files = receipt.get('immutable_files')
    if (receipt.get('schema') != SCHEMA or receipt.get('source_fingerprint') != profile['source_fingerprint']
            or not re.fullmatch('[0-9a-f]{64}', str(receipt.get('archive_sha256', '')))
            or not isinstance(files, dict) or not expected.keys() <= files.keys()
            or files.keys() - expected.keys() - LAUNCHER_TEMP_FILES):
        raise BundleError('SaveMGO base receipt identity or inventory differs')
    for name, row in expected.items():
        prior = files[name]
        if (not isinstance(prior, dict) or prior.get('size') != row['size'] or prior.get('crc32') != row['crc32']
                or not re.fullmatch('[0-9a-f]{64}', str(prior.get('sha256', '')))
                or name in profile['critical_sha256'] and prior['sha256'] != profile['critical_sha256'][name]):
            raise BundleError('SaveMGO base receipt content differs')


def _revision(value):
    if not isinstance(value, str) or not re.fullmatch(r'00\.[0-9]{2}', value) or not '00.30' < value <= '00.99':
        raise BundleError('SaveMGO launcher update revision is outside the supported monotonic range')
    return value


def _launcher_sfo(data):
    from .catalog import param_sfo
    try:
        values = param_sfo(data) if data.startswith(b'\0PSF') else {}
    except (ValueError, IndexError, KeyError, struct.error):
        values = {}
    if values.get('TITLE_ID') != 'NPMG00010' or values.get('CATEGORY') != 'HG':
        raise BundleError('SaveMGO launcher update title/category differs')
    return _revision(values.get('APP_VER'))


def _update_archive(path):
    """Validate an update already downloaded/applied by the bundled game; never extract it."""
    path = _guard(path)
    before = path.stat()
    if not path.is_file() or not 0 < before.st_size <= 16 * 2**20 or before.st_nlink != 1:
        raise BundleError('SaveMGO launcher update ZIP is linked or exceeds its budget')
    files, expanded = {}, 0
    try:
        with zipfile.ZipFile(path) as archive:
            entries, seen = archive.infolist(), set()
            if len(entries) not in (5, 6):
                raise BundleError('SaveMGO launcher update must contain only its five allowed files')
            for entry in entries:
                name = _safe_name(entry.orig_filename)
                if name.casefold() in seen:
                    raise BundleError('SaveMGO launcher update has colliding paths')
                seen.add(name.casefold())
                mode = stat.S_IFMT(entry.external_attr >> 16)
                if (mode not in (0, stat.S_IFREG, stat.S_IFDIR) or entry.external_attr & 0x400
                        or entry.flag_bits & 1 or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise BundleError('Unsupported launcher update member attributes')
                if entry.is_dir() and name == 'USRDIR':
                    continue
                if entry.is_dir() or name not in UPDATE_FILES or not 0 < entry.file_size <= UPDATE_FILES[name]:
                    raise BundleError('SaveMGO launcher update contains a forbidden path or member size')
                expanded += entry.file_size
                if expanded > 32 * 2**20:
                    raise BundleError('SaveMGO launcher update expanded-size budget exceeded')
                data = archive.read(entry)  # ZIP CRC is checked; the member is bounded above.
                if len(data) != entry.file_size:
                    raise BundleError('SaveMGO launcher update member size differs')
                if name == 'USRDIR/EBOOT.BIN' and not data.startswith(b'SCE\0'):
                    raise BundleError('SaveMGO launcher update executable is not a PS3 SELF')
                if name.endswith('.PNG') and not data.startswith(b'\x89PNG\r\n\x1a\n'):
                    raise BundleError('SaveMGO launcher update image type differs')
                if name == 'PARAM.SFO':
                    revision = _launcher_sfo(data)
                files[UPDATE_PREFIX + name] = {'size': len(data), 'crc32': f'{entry.CRC:08x}',
                                               'sha256': hashlib.sha256(data).hexdigest()}
        if files.keys() != UPDATE_PATHS:
            raise BundleError('SaveMGO launcher update is incomplete')
        archive_sha = _hash_file(path)['sha256']
    except (zipfile.BadZipFile, RuntimeError, zlib.error, EOFError):
        raise BundleError('SaveMGO launcher update ZIP failed integrity validation') from None
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise BundleError('SaveMGO launcher update changed during validation')
    return {'app_ver': revision, 'update_sha256': archive_sha, 'files': files}


def _update_receipt(receipt, base, profile):
    files = receipt.get('files')
    if (receipt.get('schema') != UPDATE_SCHEMA or receipt.get('source_fingerprint') != profile['source_fingerprint']
            or receipt.get('base_archive_sha256') != base['archive_sha256']
            or receipt.get('provenance') != 'local ZIP already applied by bundled launcher; not vendor-signature authenticated'
            or not re.fullmatch('[0-9a-f]{64}', str(receipt.get('update_sha256', '')))
            or not isinstance(files, dict) or files.keys() != UPDATE_PATHS):
        raise BundleError('SaveMGO launcher update receipt identity or inventory differs')
    _revision(receipt.get('app_ver'))
    for name, row in files.items():
        maximum = UPDATE_FILES[name[len(UPDATE_PREFIX):]]
        if (not isinstance(row, dict) or type(row.get('size')) is not int or not 0 < row['size'] <= maximum
                or not re.fullmatch('[0-9a-f]{8}', str(row.get('crc32', '')))
                or not re.fullmatch('[0-9a-f]{64}', str(row.get('sha256', '')))):
            raise BundleError('SaveMGO launcher update receipt content differs')


def _overlay_profile(profile, base, update, *, full=False):
    files = update['files']
    if not UPDATE_PATHS <= {r['path'] for r in profile['immutable_manifest']}:
        raise BundleError('SaveMGO base does not contain the complete launcher update scope')
    critical = dict(profile['critical_sha256'])
    if full:
        critical.update({name: row['sha256'] for name, row in base['immutable_files'].items()})
    critical.update({name: row['sha256'] for name, row in files.items()})
    rows = [dict(row, **{k: files[row['path']][k] for k in ('size', 'crc32')}) if row['path'] in files else row
            for row in profile['immutable_manifest']]
    return profile | {'immutable_manifest': rows, 'critical_sha256': critical}


def _check_added_immutable(home, profile):
    expected = {row['path'] for row in profile['files']}
    allowed = {RECEIPT, UPDATE_RECEIPT, DATA_UPDATE_RECEIPT, '.gbox-savemgo-running.lock', UPDATE_ZIP}
    count = 0
    for directory, directories, names in os.walk(home, followlinks=False):
        here = Path(directory)
        directories[:] = [name for name in directories if not _mutable((here / name).relative_to(home).as_posix() + '/')]
        for name in directories:
            _guard(here / name)
        for name in names:
            relative = (here / name).relative_to(home).as_posix()
            count += 1
            if count > 20000:
                raise BundleError('SaveMGO installed inventory exceeds its bounded verification budget')
            if not _mutable(relative) and relative not in expected | allowed:
                raise BundleError('Unexpected immutable file outside the SaveMGO launcher update scope')


def _record_update(path, value):
    _guard(path)
    fd, temporary = tempfile.mkstemp(prefix='.gbox-savemgo-update-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _data_overlay(home, profile, base):
    """Use a separately verified CDN receipt for already-applied game data.

    Creating this receipt requires an explicit comparison with the fixed HTTPS
    CDN. The launcher log alone is not evidence; no changed file is auto-trusted.
    The original archive receipt remains unchanged, and updated bytes are always
    rehashed. Scope excludes the host emulator, firmware, launcher and profiles.
    """
    path = _guard(home / DATA_UPDATE_RECEIPT)
    if not path.exists():
        return profile, base
    update = _read_receipt(path)
    files = update.get('files')
    if (update.get('schema') != DATA_UPDATE_SCHEMA
            or update.get('source_fingerprint') != profile['source_fingerprint']
            or update.get('base_archive_sha256') != base['archive_sha256']
            or update.get('provenance') != 'installed bytes compared with https://cdn.mgo2.net/'
            or not isinstance(files, dict) or not 0 < len(files) <= 512):
        raise BundleError('SaveMGO data update receipt identity or inventory differs')
    prefix = 'dev_hdd0/game/NPMG00020/'
    expected = {r['path'] for r in profile['immutable_manifest']}
    total = 0
    for name, row in files.items():
        _safe_name(name)
        if (name not in expected or not (name.startswith(DATA_ROOT + '/') or name == prefix + 'plugin.sprx')
                or not isinstance(row, dict) or type(row.get('size')) is not int
                or not 0 < row['size'] <= MAX_MEMBER
                or row.get('url') != 'https://cdn.mgo2.net/' + name[len(prefix):]
                or not re.fullmatch('[0-9a-f]{8}', str(row.get('crc32', '')))
                or not re.fullmatch('[0-9a-f]{64}', str(row.get('sha256', '')))):
            raise BundleError('SaveMGO data update receipt scope or content differs')
        total += row['size']
    if total > 2 * 2**30:
        raise BundleError('SaveMGO data update exceeds its budget')
    rows = [dict(row, **{k: files[row['path']][k] for k in ('size', 'crc32')}) if row['path'] in files else row
            for row in profile['immutable_manifest']]
    critical = profile['critical_sha256'] | {name: row['sha256'] for name, row in files.items()}
    return (profile | {'immutable_manifest': rows, 'critical_sha256': critical},
            base | {'immutable_files': base['immutable_files'] | files})


def _verify_managed(home, profile, base, progress, *, source_archive=None):
    _base_receipt(base, profile)
    profile, base = _data_overlay(home, profile, base)
    path = _guard(home / UPDATE_RECEIPT)
    previous = _read_receipt(path) if path.exists() else None
    if previous is not None:
        _update_receipt(previous, base, profile)
    archive = _guard(home / UPDATE_ZIP)
    candidate = _update_archive(archive) if archive.exists() else None
    adopt = candidate is not None and (previous is None or candidate['update_sha256'] != previous['update_sha256'])
    if adopt:
        if previous is not None and candidate['app_ver'] <= previous['app_ver']:
            raise BundleError('SaveMGO launcher update is not newer than the adopted revision')
        update = candidate | {'schema': UPDATE_SCHEMA, 'source_fingerprint': profile['source_fingerprint'],
            'base_archive_sha256': base['archive_sha256'],
            'provenance': 'local ZIP already applied by bundled launcher; not vendor-signature authenticated'}
        with runtime_lease(home):  # do not race a running bundled launcher or replace its game files
            _check_added_immutable(home, profile)
            overlay = _overlay_profile(profile, base, update, full=True)
            result = verify_install(home, overlay, progress=progress)
            # The exact installed payload must match every ZIP member, including images/logo.
            if any(result['immutable_files'][name]['sha256'] != row['sha256'] for name, row in update['files'].items()):
                raise BundleError('SaveMGO launcher update is only partially applied')
            _record_update(path, update)
        previous = update
    else:
        if previous and candidate and any(candidate[k] != previous[k] for k in ('app_ver', 'files')):
            raise BundleError('SaveMGO launcher update ZIP and receipt differ')
        if previous:
            _check_added_immutable(home, profile)
        overlay = _overlay_profile(profile, base, previous) if previous else profile
        cached = dict(base, immutable_files=dict(base['immutable_files']))
        if previous:
            for name, row in previous['files'].items():
                cached['immutable_files'][name] = row
        if source_archive is not None:
            with runtime_lease(home):
                result = verify_install(home, overlay, progress=progress, _cache=cached, archive=source_archive)
        else:
            result = verify_install(home, overlay, progress=progress, _cache=cached)
    if previous and _launcher_sfo((home / SFO).read_bytes()) != previous['app_ver']:
        raise BundleError('SaveMGO installed launcher revision and update receipt differ')
    return result | {'launcher_revision': previous['app_ver'] if previous else profile['app_ver'],
                     'launcher_update_sha256': previous['update_sha256'] if previous else None}


def _heal_file(path, archive, name, row, profile):
    """Restore one drifted member from the verified source archive, atomically.

    The archive was fingerprinted and its critical identity validated before the
    verify pass, so its members are the trusted content. The restored file must
    match the manifest row and, for critical files, the pinned identity; the
    replacement lands with os.replace so the home never holds a partial file.
    """
    if name.startswith(DATA_ROOT + '/') or name == 'dev_hdd0/game/NPMG00020/plugin.sprx':
        raise BundleError(f'SaveMGO game data differs and needs update verification; left unchanged: {name}')
    fd, tmp = tempfile.mkstemp(prefix='.heal-', dir=str(path.parent))
    digest, crc, size = hashlib.sha256(), 0, 0
    try:
        with zipfile.ZipFile(archive) as zipped:
            info = zipped.getinfo(PREFIX + name)
            if info.file_size != row['size']:
                raise BundleError(f'SaveMGO source archive member differs from its manifest: {name}')
            with os.fdopen(fd, 'wb') as dst, zipped.open(info) as src:
                for block in iter(lambda: src.read(BLOCK), b''):
                    size += len(block)
                    if size > row['size']:
                        raise BundleError(f'SaveMGO source archive member exceeded its declared size: {name}')
                    dst.write(block); digest.update(block); crc = zlib.crc32(block, crc)
        if size != row['size'] or f'{crc & 0xffffffff:08x}' != row['crc32']:
            raise BundleError(f'SaveMGO source archive member CRC differs from its manifest: {name}')
        result = {'size': size, 'crc32': row['crc32'], 'sha256': digest.hexdigest()}
        if name in profile['critical_sha256'] and result['sha256'] != profile['critical_sha256'][name]:
            raise BundleError(f'SaveMGO source archive critical file differs from its pinned identity: {name}')
        try:
            os.replace(tmp, path)
        except OSError as exc:
            raise BundleError(f'SaveMGO drifted file is locked and could not be restored: {name}') from exc
        info = path.stat()
        if not path.is_file() or info.st_size != size:
            raise BundleError(f'Restored SaveMGO file did not settle: {name}')
        return result | {'mtime_ns': info.st_mtime_ns}
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def verify_install(root, profile, *, progress=None, _cache=None, _percent=5, archive=None):
    """Verify local immutable files; leave personal configuration/saves/caches untouched.

    A private previous staging receipt can reuse unchanged file stats. Critical
    files are always rehashed; initial adoption hashes/CRC-checks every immutable file.

    When `archive` is given (the just-fingerprinted source package), a file whose
    content drifted from the manifest is restored from the archive and re-checked
    instead of failing the launch. Files that are changing while they are read are
    never restored: a live writer is reported, not fought. Restored paths are
    returned as `healed_files` so the launch surface reports them.
    """
    root = _guard(root)
    if not root.is_dir() or profile.get('schema') != SCHEMA:
        raise BundleError('Invalid SaveMGO installation or discovery profile')
    if profile.get('critical_sha256', {}).get('rpcs3.exe') != EXECUTABLE_SHA256:
        raise BundleError('Discovery profile has the wrong pinned SaveMGO executable')
    expected = profile['immutable_manifest']
    cached = (_cache or {}).get('immutable_files', {}) if (_cache or {}).get('source_fingerprint') == profile['source_fingerprint'] else {}
    verified, healed = {}, []
    for index, row in enumerate(expected):
        name = row['path']
        _safe_name(name)
        path = _guard(root / name)
        try:
            info = path.stat()
        except FileNotFoundError:
            if archive is not None:
                verified[name] = _heal_file(path, archive, name, row, profile)
                healed.append(name)
                if index % 32 == 0:
                    _notify(progress, _percent, f'Verifying local SaveMGO immutable files: {index + 1:,} / {len(expected):,} checked')
                continue
            raise BundleError(f'SaveMGO immutable installation file is missing: {name}')
        if not path.is_file() or info.st_nlink != 1:
            if archive is not None:
                verified[name] = _heal_file(path, archive, name, row, profile)
                healed.append(name)
                if index % 32 == 0:
                    _notify(progress, _percent, f'Verifying local SaveMGO immutable files: {index + 1:,} / {len(expected):,} checked')
                continue
            raise BundleError(f'SaveMGO immutable installation file is missing, linked or differs: {name}')
        previous = cached.get(name, {})
        if info.st_size != row['size']:
            if archive is not None:
                verified[name] = _heal_file(path, archive, name, row, profile)
                healed.append(name)
                if index % 32 == 0:
                    _notify(progress, _percent, f'Verifying local SaveMGO immutable files: {index + 1:,} / {len(expected):,} checked')
                continue
            raise BundleError(f'SaveMGO immutable installation file differs: {name} '
                              f'(expected size {row["size"]}, found {info.st_size})')
        if (name not in profile['critical_sha256'] and Path(name).suffix.casefold() not in ('.exe', '.dll')
                and previous.get('size') == info.st_size
                and previous.get('mtime_ns') == info.st_mtime_ns and previous.get('crc32') == row['crc32']
                and re.fullmatch('[0-9a-f]{64}', str(previous.get('sha256', '')))):
            result = {k: previous[k] for k in ('size', 'crc32', 'sha256')}
        else:
            result = _hash_file(path, progress, _percent, 'Verifying local SaveMGO immutable files')
        after = path.stat()
        if (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise BundleError(f'SaveMGO immutable file changed during verification: {name}')
        problem = None
        if result['size'] != row['size']:
            problem = f'size differs (expected {row["size"]}, found {result["size"]})'
        elif result['crc32'] != row['crc32']:
            problem = f'CRC differs (expected {row["crc32"]}, found {result["crc32"]})'
        elif previous.get('sha256') and result['sha256'] != previous['sha256']:
            problem = 'content differs from the verified receipt'
        elif name in profile['critical_sha256'] and result['sha256'] != profile['critical_sha256'][name]:
            problem = 'critical identity differs'
        if problem:
            if archive is None:
                raise BundleError(f'SaveMGO immutable content integrity differs: {name} ({problem})')
            verified[name] = _heal_file(path, archive, name, row, profile)
            healed.append(name)
        else:
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
            'immutable_files': verified, 'reused': True, 'profile_values_read': False,
            'healed_files': healed}


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
            receipt = _read_receipt(receipt_path)
            if (receipt.get('schema') != SCHEMA or receipt.get('source_fingerprint') != fingerprint
                    or not re.fullmatch('[0-9a-f]{64}', str(receipt.get('archive_sha256', '')))):
                raise BundleError('SaveMGO receipt identity differs; existing profile left unchanged')
            result = _verify_managed(home, profile, receipt, progress, source_archive=archive)
            if result.get('healed_files'):
                for name in result['healed_files']:
                    receipt['immutable_files'][name] = result['immutable_files'][name]
                _record_update(receipt_path, receipt)
                _notify(progress, 8, 'Restored drifted SaveMGO file(s): ' + ', '.join(result['healed_files']))
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
                return result | {'archive_sha256': source['sha256'], 'adopted_existing': True,
                                 'launcher_revision': profile['app_ver'], 'launcher_update_sha256': None}
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
                             'archive_sha256': source['sha256'], 'reused': False,
                             'launcher_revision': profile['app_ver'], 'launcher_update_sha256': None}
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
