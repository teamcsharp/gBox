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
    files.update({M.UPDATE_PREFIX + 'ICON0.PNG': b'\x89PNG\r\n\x1a\nbase-icon',
                  M.UPDATE_PREFIX + 'PIC1.PNG': b'\x89PNG\r\n\x1a\nbase-picture',
                  M.UPDATE_PREFIX + 'PS3LOGO.DAT': b'base-logo'})
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


def applied_update(home, *, revision='00.35', title='NPMG00010', category='HG', extra=None,
                   install=True, omit=None, eboot=b'SCE\0updated-owned-launcher', compression=zipfile.ZIP_DEFLATED):
    files = {'USRDIR/EBOOT.BIN': eboot,
             'PARAM.SFO': sfo({'TITLE_ID': title, 'APP_VER': revision, 'CATEGORY': category}),
             'ICON0.PNG': b'\x89PNG\r\n\x1a\nupdated-icon',
             'PIC1.PNG': b'\x89PNG\r\n\x1a\nupdated-picture', 'PS3LOGO.DAT': b'updated-logo'}
    if install:
        for name, data in files.items():
            if name != omit:
                (home / M.UPDATE_PREFIX / name).write_bytes(data)
    archive = home / M.UPDATE_ZIP; archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, 'w', compression=compression) as z:
        z.writestr('USRDIR/', b'')
        for name, data in (files | (extra or {})).items():z.writestr(name, data)
    return archive, files


def test_applied_update_adopts_only_metadata_and_preserves_original_identity_and_profiles(bundle, monkeypatch):
    first = M.prepare(bundle.archive, bundle.cfg)
    home = first['home']; baseline_receipt = (home / M.RECEIPT).read_bytes()
    private = home / 'config/rpcn.yml'; private.write_bytes(b'personal-account-not-read')
    update_zip, files = applied_update(home)
    old = {name: ((home / M.UPDATE_PREFIX / name).read_bytes(), (home / M.UPDATE_PREFIX / name).stat().st_mtime_ns)
           for name in files}
    original = M._hash_file; hashed = []
    def tracked(path, *a, **kw):
        hashed.append(Path(path)); return original(path, *a, **kw)
    monkeypatch.setattr(M, '_hash_file', tracked)
    result = M.prepare(bundle.archive, bundle.cfg)
    assert result['launcher_revision'] == '00.35'
    assert result['launcher_update_sha256'] == hashlib.sha256(update_zip.read_bytes()).hexdigest()
    assert result['source_fingerprint'] == first['source_fingerprint']
    assert result['archive_sha256'] == first['archive_sha256']
    assert (home / M.RECEIPT).read_bytes() == baseline_receipt
    assert private.read_bytes() == b'personal-account-not-read' and private not in hashed
    assert set(home / row['path'] for row in M.identify(bundle.archive)['immutable_manifest']) <= set(hashed)
    assert old == {name: ((home / M.UPDATE_PREFIX / name).read_bytes(), (home / M.UPDATE_PREFIX / name).stat().st_mtime_ns)
                   for name in files}
    receipt = json.loads((home / M.UPDATE_RECEIPT).read_text())
    assert set(receipt['files']) == M.UPDATE_PATHS and 'not vendor-signature authenticated' in receipt['provenance']


def test_recorded_update_reuses_when_launcher_removes_temporary_zip(bundle):
    home = M.prepare(bundle.archive, bundle.cfg)['home']; archive, _ = applied_update(home)
    M.prepare(bundle.archive, bundle.cfg); before = (home / M.UPDATE_RECEIPT).read_bytes(); archive.unlink()
    result = M.prepare(bundle.archive, bundle.cfg)
    assert result['launcher_revision'] == '00.35' and result['launcher_update_sha256']
    assert (home / M.UPDATE_RECEIPT).read_bytes() == before


def test_base_runtime_repair_preserves_verified_launcher_update(bundle):
    first = M.prepare(bundle.archive, bundle.cfg); home = first['home']
    applied_update(home); M.prepare(bundle.archive, bundle.cfg)
    launcher = (home / M.EBOOT).read_bytes()
    update_receipt = (home / M.UPDATE_RECEIPT).read_bytes()
    (home / 'known.dll').write_bytes(b'drift')
    result = M.prepare(bundle.archive, bundle.cfg)
    assert result['healed_files'] == ['known.dll'] and result['launcher_revision'] == '00.35'
    assert (home / M.EBOOT).read_bytes() == launcher
    assert (home / M.UPDATE_RECEIPT).read_bytes() == update_receipt
    assert M.prepare(bundle.archive, bundle.cfg)['healed_files'] == []


@pytest.mark.parametrize('change', ['runtime', 'firmware', 'companion', 'unknown_file'])
def test_update_refuses_any_changed_base_immutable_even_restored_mtime(bundle, change):
    home = M.prepare(bundle.archive, bundle.cfg)['home']; applied_update(home)
    path = {'runtime': home / 'known.dll', 'firmware': home / M.FIRMWARE,
            'companion': home / M.DATA_ROOT / 'o/data.bin', 'unknown_file': home / M.DATA_ROOT / 'o/new.bin'}[change]
    if path.exists():
        st = path.stat(); content = path.read_bytes(); path.write_bytes(bytes([content[0] ^ 1]) + content[1:])
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    else:path.write_bytes(b'unknown companion')
    with pytest.raises(M.BundleError):M.prepare(bundle.archive, bundle.cfg)
    assert not (home / M.UPDATE_RECEIPT).exists()


@pytest.mark.parametrize('kwargs', [dict(title='BLUS00000'), dict(category='GD'), dict(revision='00.30'),
                                    dict(revision='01.00'), dict(eboot=b'MZhost-executable'),
                                    dict(extra={'rpcs3.exe': b'MZelevation-attempt'}),
                                    dict(extra={'../outside': b'escape'}), dict(extra={'PARAM.sfo': b'collision'})])
def test_update_rejects_wrong_identity_revision_host_code_and_unsafe_zip(bundle, kwargs):
    home = M.prepare(bundle.archive, bundle.cfg)['home']; applied_update(home, **kwargs)
    with pytest.raises(M.BundleError):M.prepare(bundle.archive, bundle.cfg)
    assert not (home / M.UPDATE_RECEIPT).exists()


def test_partial_update_is_not_repaired_or_adopted(bundle):
    home = M.prepare(bundle.archive, bundle.cfg)['home']; original = (home / M.EBOOT).read_bytes()
    applied_update(home, omit='USRDIR/EBOOT.BIN')
    before = (home / M.SFO).read_bytes()
    with pytest.raises(M.BundleError):M.prepare(bundle.archive, bundle.cfg)
    assert (home / M.EBOOT).read_bytes() == original and (home / M.SFO).read_bytes() == before
    assert not (home / M.UPDATE_RECEIPT).exists()


def test_update_requires_complete_base_receipt_and_does_not_reinstall(bundle):
    home = M.prepare(bundle.archive, bundle.cfg)['home']; applied_update(home)
    (home / M.RECEIPT).unlink(); before = (home / M.EBOOT).read_bytes()
    with pytest.raises(M.BundleError, match='receipt'):M.prepare(bundle.archive, bundle.cfg)
    assert (home / M.EBOOT).read_bytes() == before and not (home / M.UPDATE_RECEIPT).exists()


def test_update_refuses_corrupt_or_incomplete_base_receipt(bundle):
    home = M.prepare(bundle.archive, bundle.cfg)['home']; applied_update(home)
    receipt = json.loads((home / M.RECEIPT).read_text()); del receipt['immutable_files']['known.dll']
    (home / M.RECEIPT).write_text(json.dumps(receipt))
    with pytest.raises(M.BundleError, match='base receipt'):M.prepare(bundle.archive, bundle.cfg)
    assert not (home / M.UPDATE_RECEIPT).exists()


def test_recorded_update_rejects_tampered_payload_even_with_restored_stats(bundle):
    home = M.prepare(bundle.archive, bundle.cfg)['home']; archive, _ = applied_update(home)
    M.prepare(bundle.archive, bundle.cfg); archive.unlink()
    path = home / M.UPDATE_PREFIX / 'ICON0.PNG'; st = path.stat(); before = path.read_bytes()
    path.write_bytes(before[:-1] + b'!'); os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    with pytest.raises(M.BundleError):M.prepare(bundle.archive, bundle.cfg)


@pytest.mark.parametrize('change', ['json', 'fingerprint', 'revision', 'hash', 'files'])
def test_corrupt_update_receipt_never_becomes_a_new_adoption(bundle, change):
    home = M.prepare(bundle.archive, bundle.cfg)['home']; archive, _ = applied_update(home)
    M.prepare(bundle.archive, bundle.cfg); path = home / M.UPDATE_RECEIPT
    receipt = json.loads(path.read_text())
    if change == 'fingerprint':receipt['source_fingerprint'] = '0' * 64
    if change == 'revision':receipt['app_ver'] = '00.36'; archive.unlink()
    if change == 'hash':receipt['files'][M.EBOOT]['sha256'] = '0' * 64
    if change == 'files':receipt['files'].pop(M.SFO)
    path.write_text('not json' if change == 'json' else json.dumps(receipt))
    before = path.read_bytes()
    with pytest.raises(M.BundleError):M.prepare(bundle.archive, bundle.cfg)
    assert path.read_bytes() == before


def test_future_update_requires_strictly_newer_revision_and_keeps_base_receipt(bundle):
    home = M.prepare(bundle.archive, bundle.cfg)['home']; baseline = (home / M.RECEIPT).read_bytes()
    applied_update(home); M.prepare(bundle.archive, bundle.cfg)
    applied_update(home, revision='00.36', eboot=b'SCE\0newer-launcher')
    assert M.prepare(bundle.archive, bundle.cfg)['launcher_revision'] == '00.36'
    prior = (home / M.UPDATE_RECEIPT).read_bytes()
    applied_update(home, revision='00.35')
    with pytest.raises(M.BundleError, match='not newer'):M.prepare(bundle.archive, bundle.cfg)
    assert (home / M.UPDATE_RECEIPT).read_bytes() == prior and (home / M.RECEIPT).read_bytes() == baseline


def test_same_revision_different_zip_cannot_replace_accepted_receipt(bundle):
    home = M.prepare(bundle.archive, bundle.cfg)['home']; applied_update(home); M.prepare(bundle.archive, bundle.cfg)
    prior = (home / M.UPDATE_RECEIPT).read_bytes()
    applied_update(home, eboot=b'SCE\0different-same-revision')
    with pytest.raises(M.BundleError, match='not newer'):M.prepare(bundle.archive, bundle.cfg)
    assert (home / M.UPDATE_RECEIPT).read_bytes() == prior


def test_active_runtime_lease_blocks_adoption_without_touching_files(bundle):
    home = M.prepare(bundle.archive, bundle.cfg)['home']; applied_update(home); before = (home / M.EBOOT).read_bytes()
    with M.runtime_lease(home):
        with pytest.raises(M.BundleError, match='active'):M.prepare(bundle.archive, bundle.cfg)
    assert (home / M.EBOOT).read_bytes() == before and not (home / M.UPDATE_RECEIPT).exists()


def test_corrupt_update_crc_does_not_adopt(bundle):
    # Stored bytes avoid flipping a DEFLATE flag that can leave decoded content unchanged.
    home = M.prepare(bundle.archive, bundle.cfg)['home']; archive, _ = applied_update(home, compression=zipfile.ZIP_STORED)
    with zipfile.ZipFile(archive) as z:entry = z.getinfo('USRDIR/EBOOT.BIN')
    raw = bytearray(archive.read_bytes()); n, e = struct.unpack_from('<HH', raw, entry.header_offset + 26)
    raw[entry.header_offset + 30 + n + e] ^= 1; archive.write_bytes(raw)
    with pytest.raises(M.BundleError):M.prepare(bundle.archive, bundle.cfg)
    assert not (home / M.UPDATE_RECEIPT).exists()


def test_legacy_receipt_allows_launcher_temporary_status_changes(bundle, monkeypatch):
    name = 'dev_hdd0/tmp/mgo_launcher.txt'
    bundle.files[name] = b'old-launcher-status'; bundle.write()
    original = M._mutable
    with monkeypatch.context() as patch:
        patch.setattr(M, '_mutable', lambda path: False if path == name else original(path))
        first = M.prepare(bundle.archive, bundle.cfg)
    home = first['home']; baseline = (home / M.RECEIPT).read_bytes()
    (home / name).write_bytes(b'launcher updated status')
    applied_update(home)
    result = M.prepare(bundle.archive, bundle.cfg)
    assert result['source_fingerprint'] == first['source_fingerprint']
    assert result['launcher_revision'] == '00.35'
    assert (home / name).read_bytes() == b'launcher updated status'
    assert (home / M.RECEIPT).read_bytes() == baseline


def data_receipt(home, first, name):
    row = M._hash_file(home / name)
    row['url'] = 'https://cdn.mgo2.net/' + name.removeprefix('dev_hdd0/game/NPMG00020/')
    value = {'schema': M.DATA_UPDATE_SCHEMA, 'source_fingerprint': first['source_fingerprint'],
             'base_archive_sha256': first['archive_sha256'],
             'provenance': 'installed bytes compared with https://cdn.mgo2.net/', 'files': {name: row}}
    (home / M.DATA_UPDATE_RECEIPT).write_text(json.dumps(value))
    return value


def test_verified_data_update_keeps_original_receipt_and_detects_later_drift(bundle):
    first = M.prepare(bundle.archive, bundle.cfg); home = first['home']
    baseline = (home / M.RECEIPT).read_bytes()
    name = M.DATA_ROOT + '/o/data.bin'
    (home / name).write_bytes(b'new CDN game data')
    with pytest.raises(M.BundleError):M.prepare(bundle.archive, bundle.cfg)
    data_receipt(home, first, name)
    applied_update(home)
    assert M.prepare(bundle.archive, bundle.cfg)['launcher_revision'] == '00.35'
    assert M.prepare(bundle.archive, bundle.cfg)['verified']
    assert (home / M.RECEIPT).read_bytes() == baseline
    (home / name).write_bytes(b'bad CDN game data')
    with pytest.raises(M.BundleError):M.prepare(bundle.archive, bundle.cfg)


@pytest.mark.parametrize('bad', ['host', 'firmware', 'source', 'url'])
def test_data_receipt_cannot_authorize_unrelated_changes(bundle, bad):
    first = M.prepare(bundle.archive, bundle.cfg); home = first['home']
    name = {'host': 'rpcs3.exe', 'firmware': M.FIRMWARE}.get(bad, M.DATA_ROOT + '/o/data.bin')
    value = data_receipt(home, first, name)
    if bad == 'source':value['source_fingerprint'] = 'wrong'
    if bad == 'url':value['files'][name]['url'] = 'https://example.com/file'
    (home / M.DATA_UPDATE_RECEIPT).write_text(json.dumps(value))
    with pytest.raises(M.BundleError):M.prepare(bundle.archive, bundle.cfg)
