"""Portable bundle integrity/profile isolation; no emulator or network execution."""
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
from types import SimpleNamespace
import zipfile

import pytest

from gbox import savemgo as M


def sfo(values):
    keys, data, entries = b'', b'', []
    for key, value in values.items():
        raw = value.encode() + b'\0'
        entries.append(struct.pack('<HHIII', len(keys), 0x0204, len(raw), len(raw), len(data)))
        keys += key.encode() + b'\0'; data += raw
    start = 20 + 16 * len(entries)
    return b'\0PSF\1\1\0\0' + struct.pack('<III', start, start + len(keys), len(entries)) + b''.join(entries) + keys + data


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    runner = b'MZowned-fixed-rpcs3'
    monkeypatch.setattr(M, 'EXECUTABLE_SHA256', hashlib.sha256(runner).hexdigest())
    files = {'rpcs3.exe': runner, M.EBOOT: b'SCE\0owned-game',
        M.SFO: sfo({'TITLE_ID': 'NPMG00010', 'APP_VER': '00.30', 'TITLE': 'Metal Gear Online 2'}),
        M.DATA_SFO: sfo({'TITLE_ID': 'NPMG00020'}), M.FIRMWARE: b'owned-firmware',
        'config/config.yml': b'bundled-network-config', 'config/rpcn.yml': b'opaque-private-profile',
        'config/input_configs/global/Default.yml': b'bundled-controller', 'known.dll': b'known-runtime',
        'cache/initial.bin': b'initial-cache', 'dev_hdd0/home/00000001/savedata/initial.dat': b'initial-save'}
    for group in ('dbm', 'o', 'sdpack', 'speech'):
        files['dev_hdd0/game/NPMG00020/USRDIR/' + group + '/data.bin'] = group.encode() * 200
    archive = tmp_path / 'SaveMGO.zip'
    def write(extra=None):
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as z:
            for name, data in (files | (extra or {})).items():
                z.writestr(M.PREFIX + name, data)
        return archive
    return SimpleNamespace(archive=write(), files=files, write=write, cfg=SimpleNamespace(runtime=tmp_path / 'runtime'))


def test_discovery_exact_identity_without_reading_account_values(bundle, monkeypatch):
    original = M._read_critical
    names = []
    def read(z, name, maximum):
        names.append(name); return original(z, name, maximum)
    monkeypatch.setattr(M, '_read_critical', read)
    p = M.identify(bundle.archive)
    assert p['title'] == 'Metal Gear Online' and p['serial'] == 'NPMG00010'
    assert p['launch']['kind'] == 'savemgo_bundle' and p['file_count'] == len(bundle.files)
    assert len(p['source_fingerprint']) == 64 and not any(n.startswith('config/') for n in names)
    assert not any(r['path'].startswith(('config/', 'cache/', 'dev_hdd0/home/')) for r in p['immutable_manifest'])


def test_unrelated_large_or_corrupt_zip_does_not_become_savemgo(tmp_path, monkeypatch):
    p = tmp_path / 'other.zip'
    with zipfile.ZipFile(p, 'w') as z:z.writestr('game.bin', b'other')
    monkeypatch.setattr(M, 'MAX_ARCHIVE', 1)
    assert M.identify(p) is None
    p.write_bytes(b'not-a-zip')
    assert M.identify(p) is None


@pytest.mark.parametrize('path', ['../escape', 'config/../escape', '/absolute', 'NUL.txt', 'a:stream',
                                  'bad\\name', 'trailing.', 'trailing ', 'dir//file', 'a\x00b'])
def test_windows_path_aliases_and_traversal_rejected(bundle, path):
    # ZipFile itself truncates NUL; directly validate that case.
    if '\x00' in path or '\\' in path:
        with pytest.raises(ValueError):M._safe_name(path)
    else:
        bundle.write({path: b'bad'})
        with pytest.raises(ValueError):M.identify(bundle.archive)


def test_raw_zip_backslash_is_rejected_before_windows_normalizes_it(bundle):
    bundle.write({'bad/name': b'bad'})
    data = bundle.archive.read_bytes().replace(b'bad/name', b'bad\\name')
    bundle.archive.write_bytes(data)
    with pytest.raises(ValueError, match='Unsafe'):M.identify(bundle.archive)


def test_case_collisions_and_links_rejected(bundle):
    bundle.write({'KNOWN.DLL': b'collision'})
    with pytest.raises(ValueError, match='collid'):M.identify(bundle.archive)
    bundle.write()
    with zipfile.ZipFile(bundle.archive, 'a') as z:
        link = zipfile.ZipInfo(M.PREFIX + 'link'); link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16; z.writestr(link, '../outside')
    with pytest.raises(ValueError, match='linked'):M.identify(bundle.archive)


@pytest.mark.parametrize('change', ['runner', 'game_revision', 'missing_data', 'missing_firmware'])
def test_wrong_or_incomplete_package_never_identified(bundle, change):
    if change == 'runner':bundle.files['rpcs3.exe'] = b'MZwrong'
    if change == 'game_revision':bundle.files[M.SFO] = sfo({'TITLE_ID': 'NPMG00010', 'APP_VER': '00.31'})
    if change == 'missing_data':del bundle.files['dev_hdd0/game/NPMG00020/USRDIR/speech/data.bin']
    if change == 'missing_firmware':del bundle.files[M.FIRMWARE]
    bundle.write()
    with pytest.raises(ValueError):M.identify(bundle.archive)


def test_quotas_only_apply_to_recognized_package(bundle, monkeypatch):
    monkeypatch.setattr(M, 'MAX_ARCHIVE', 1)
    with pytest.raises(ValueError, match='archive-size'):M.identify(bundle.archive)


def test_prepare_atomic_receipt_and_warm_reuse_preserve_profiles(bundle, monkeypatch):
    before = bundle.archive.read_bytes()
    p = M.identify(bundle.archive)
    first = M.prepare(bundle.archive, bundle.cfg, expected_fingerprint=p['source_fingerprint'])
    home = first['home']; private = home / 'config/rpcn.yml'; save = home / 'dev_hdd0/home/00000001/savedata/new.dat'
    private.write_bytes(b'changed-private-profile'); save.write_bytes(b'personal-save')
    called = []; original = M._hash_file
    def hashed(path, *args, **kwargs):
        called.append(Path(path)); return original(path, *args, **kwargs)
    monkeypatch.setattr(M, '_hash_file', hashed)
    again = M.prepare(bundle.archive, bundle.cfg)
    assert again['reused'] and again['home'] == home
    assert set(called) == ({home / name for name in p['critical_sha256']} | {home / 'known.dll'})
    assert private.read_bytes() == b'changed-private-profile' and save.read_bytes() == b'personal-save'
    assert bundle.archive.read_bytes() == before
    receipt = json.loads((home / M.RECEIPT).read_text())
    assert receipt['archive_sha256'] == hashlib.sha256(before).hexdigest()


def test_drifted_immutable_file_restored_without_profile_overwrite(bundle):
    first = M.prepare(bundle.archive, bundle.cfg)
    private = first['home'] / 'config/rpcn.yml'; private.write_bytes(b'personal')
    (first['home'] / 'known.dll').write_bytes(b'bad--runtime!!')
    again = M.prepare(bundle.archive, bundle.cfg)
    assert again['reused'] and again['healed_files'] == ['known.dll']
    assert (first['home'] / 'known.dll').read_bytes() == b'known-runtime'
    assert private.read_bytes() == b'personal'
    receipt = json.loads((first['home'] / M.RECEIPT).read_text())
    assert receipt['immutable_files']['known.dll']['sha256'] == hashlib.sha256(b'known-runtime').hexdigest()


def test_runtime_dll_tamper_with_restored_size_mtime_is_still_detected(bundle):
    first = M.prepare(bundle.archive, bundle.cfg)
    path = first['home'] / 'known.dll'; before = path.stat()
    path.write_bytes(b'bad--runtime!'); os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(ValueError, match=r'known\.dll'):
        M.verify_install(first['home'], M.identify(bundle.archive))
    again = M.prepare(bundle.archive, bundle.cfg)
    assert again['healed_files'] == ['known.dll'] and path.read_bytes() == b'known-runtime'


def test_verifier_names_the_divergent_file_without_an_archive(bundle):
    first = M.prepare(bundle.archive, bundle.cfg)
    (first['home'] / 'known.dll').write_bytes(b'bad--runtime!')
    with pytest.raises(ValueError, match=r'SaveMGO immutable content integrity differs: known\.dll \(CRC differs'):
        M.verify_install(first['home'], M.identify(bundle.archive))


def test_drifted_critical_file_is_restored_from_the_verified_archive(bundle):
    first = M.prepare(bundle.archive, bundle.cfg)
    profile = M.identify(bundle.archive)
    (first['home'] / M.SFO).write_bytes(b'x' * 100)
    again = M.prepare(bundle.archive, bundle.cfg)
    assert again['healed_files'] == [M.SFO]
    assert (first['home'] / M.SFO).read_bytes() == bundle.files[M.SFO]
    receipt = json.loads((first['home'] / M.RECEIPT).read_text())
    assert receipt['immutable_files'][M.SFO]['sha256'] == profile['critical_sha256'][M.SFO]


def test_missing_immutable_file_is_restored_from_the_verified_archive(bundle):
    first = M.prepare(bundle.archive, bundle.cfg)
    (first['home'] / 'known.dll').unlink()
    again = M.prepare(bundle.archive, bundle.cfg)
    assert again['healed_files'] == ['known.dll']
    assert (first['home'] / 'known.dll').read_bytes() == b'known-runtime'


def test_file_being_written_is_never_restored_or_accepted(bundle):
    first = M.prepare(bundle.archive, bundle.cfg)
    original = M._hash_file
    def hash_and_write(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if Path(path).name == 'known.dll':
            with open(path, 'ab') as stream:
                stream.write(b'concurrent')
        return result
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(M, '_hash_file', hash_and_write)
    try:
        with pytest.raises(ValueError, match=r'changed during verification: known\.dll'):
            M.prepare(bundle.archive, bundle.cfg)
    finally:
        monkeypatch.undo()
    assert (first['home'] / 'known.dll').read_bytes() != b'known-runtime'


def test_prepare_reports_restored_files_and_updates_the_receipt(bundle):
    first = M.prepare(bundle.archive, bundle.cfg)
    (first['home'] / 'known.dll').write_bytes(b'bad--runtime!!')
    notices = []
    again = M.prepare(bundle.archive, bundle.cfg, progress=lambda p, text: notices.append(text))
    assert any('Restored drifted SaveMGO file(s): known.dll' in text for text in notices)
    receipt = json.loads((first['home'] / M.RECEIPT).read_text())
    assert receipt['immutable_files']['known.dll']['sha256'] == hashlib.sha256(b'known-runtime').hexdigest()
    assert (first['home'] / 'known.dll').read_bytes() == b'known-runtime'


def test_expected_catalog_fingerprint_rejects_changed_archive_before_writes(bundle):
    before = M.identify(bundle.archive)['source_fingerprint']
    bundle.write({'extra.txt': b'changed-source'})
    with pytest.raises(ValueError, match='rescan'):M.prepare(bundle.archive, bundle.cfg, expected_fingerprint=before)
    assert not bundle.cfg.runtime.exists()


def test_new_source_identity_has_separate_profile_home(bundle):
    first = M.prepare(bundle.archive, bundle.cfg)
    personal = first['home'] / 'config/rpcn.yml'; personal.write_bytes(b'old-personal')
    bundle.write({'extra.txt': b'new-source'})
    second = M.prepare(bundle.archive, bundle.cfg)
    assert first['home'] != second['home'] and personal.read_bytes() == b'old-personal'


def test_read_only_existing_verification_and_explicit_adoption(bundle, tmp_path):
    profile = M.identify(bundle.archive); existing = tmp_path / 'existing'; existing.mkdir()
    for name, data in bundle.files.items():
        p = existing / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
    (existing / 'config/rpcn.yml').write_bytes(b'personal-existing')
    before = {p.relative_to(existing).as_posix(): (p.stat().st_mtime_ns, p.read_bytes()) for p in existing.rglob('*') if p.is_file()}
    verified = M.verify_install(existing, profile)
    assert verified['verified'] and not (existing / M.RECEIPT).exists()
    adopted = M.prepare(bundle.archive, bundle.cfg, existing_root=existing)
    assert adopted['adopted_existing'] and adopted['home'] == existing
    after = {p.relative_to(existing).as_posix(): (p.stat().st_mtime_ns, p.read_bytes()) for p in existing.rglob('*') if p.is_file()}
    assert before == after


def test_unknown_dll_or_source_link_is_rejected(bundle):
    first = M.prepare(bundle.archive, bundle.cfg)
    (first['home'] / 'injected.dll').write_bytes(b'unknown')
    with pytest.raises(ValueError, match='Unexpected'):M.prepare(bundle.archive, bundle.cfg)


def test_disk_margin_checked_before_extracting(bundle, monkeypatch):
    monkeypatch.setattr(M.shutil, 'disk_usage', lambda _: SimpleNamespace(free=0))
    with pytest.raises(ValueError, match='disk space'):M.prepare(bundle.archive, bundle.cfg)
    assert not any(bundle.cfg.runtime.rglob('rpcs3.exe'))


def test_mapped_network_runtime_rejected_before_writes(bundle, monkeypatch):
    monkeypatch.setattr(M, '_drive_type', lambda anchor: 4)
    with pytest.raises(ValueError, match='local disk'):M.prepare(bundle.archive, bundle.cfg)
    assert not bundle.cfg.runtime.exists()


def test_crc_corruption_never_publishes_runtime(bundle):
    with zipfile.ZipFile(bundle.archive) as z:
        item = z.getinfo(M.PREFIX + 'known.dll'); offset = item.header_offset
    data = bytearray(bundle.archive.read_bytes()); name_len, extra_len = struct.unpack_from('<HH', data, offset + 26)
    data[offset + 30 + name_len + extra_len] ^= 1; bundle.archive.write_bytes(data)
    with pytest.raises(zipfile.BadZipFile):M.prepare(bundle.archive, bundle.cfg)
    assert not any(bundle.cfg.runtime.rglob('rpcs3.exe'))


def test_corrupt_critical_member_and_malformed_sfo_are_catalog_safe(bundle):
    with zipfile.ZipFile(bundle.archive) as z:
        item = z.getinfo(M.PREFIX + M.EBOOT); offset = item.header_offset
    data = bytearray(bundle.archive.read_bytes()); name_len, extra_len = struct.unpack_from('<HH', data, offset + 26)
    data[offset + 30 + name_len + extra_len] ^= 1; bundle.archive.write_bytes(data)
    with pytest.raises(M.BundleError, match='integrity'):M.identify(bundle.archive)
    bundle.files[M.SFO] = b'bad-sfo'; bundle.write()
    with pytest.raises(M.BundleError, match='metadata'):M.identify(bundle.archive)


def test_cancellation_propagates_and_only_unpublished_stage_is_removed(bundle):
    def cancel(percent, text):
        if percent >= 95:raise RuntimeError('cancelled')
    # Tiny fixture triggers end-of-extraction progress; no runtime should be published after cancellation.
    with pytest.raises(RuntimeError, match='cancelled'):M.prepare(bundle.archive, bundle.cfg, progress=cancel)
    assert not any(bundle.cfg.runtime.rglob('rpcs3.exe'))


def test_first_prepare_reports_bytes_throughput_and_monotonic_phases(bundle):
    notices = []
    M.prepare(bundle.archive, bundle.cfg, progress=lambda p, text: notices.append((p, text)))
    assert all(a[0] <= b[0] for a, b in zip(notices, notices[1:]))
    assert any('Fingerprinting' in text and 'MiB/s' in text and '/' in text for _, text in notices)
    assert any('Preparing' in text and 'MiB/s' in text for _, text in notices)
    assert not any('opaque-private-profile' in text for _, text in notices)


def test_runtime_lease_blocks_second_launch_and_releases(bundle):
    home = M.prepare(bundle.archive, bundle.cfg)['home']
    with M.runtime_lease(home):
        with pytest.raises(ValueError, match='active'):
            with M.runtime_lease(home):pass
    with M.runtime_lease(home):pass


def test_verifier_never_accepts_unpinned_profile(bundle):
    prepared = M.prepare(bundle.archive, bundle.cfg); profile = M.identify(bundle.archive)
    profile['critical_sha256']['rpcs3.exe'] = '0' * 64
    with pytest.raises(ValueError, match='pinned'):M.verify_install(prepared['home'], profile)
