"""Synthetic native resources only; no account files, ROMs or emulator processes."""
import hashlib
import hmac
import json
from pathlib import Path
import struct
from types import SimpleNamespace
import wave

import pytest

from gbox import savemgo_assets as M


def put(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return path


def dar(members):
    data = bytearray(struct.pack('>I', len(members)))
    for name, value in members:
        data += name.encode() + b'\0'
        data += b'\0' * (-len(data) % 4)
        data += struct.pack('>I', len(value))
        data += b'\0' * (-len(data) % 16)
        data += value + b'\0'
    return bytes(data)


def qar(members):
    data = bytearray()
    for _, value in members:
        data += value
        data += b'\0' * (-len(data) % 128)
    offset = len(data)
    data += struct.pack('>HH', len(members), 0)
    data += b''.join(struct.pack('>II', 0, len(value)) for _, value in members)
    data += b''.join(name.encode() + b'\0' for name, _ in members)
    data += struct.pack('>I', offset)
    return bytes(data)


def encrypted(data, stage='stage/test'):
    key = M._stage_key(stage)
    words = struct.unpack('<8Q', key)
    plain = data + b'\0' * 8
    result = bytearray(plain)
    previous = words[0]
    for index in range(len(plain) // 8):
        value = struct.unpack_from('<Q', plain, index * 8)[0] ^ previous ^ words[index % 7 + 1]
        struct.pack_into('<Q', result, index * 8, value)
        previous = value
    return bytes(result) + hmac.new(key, result, hashlib.md5).digest()


def music(container='bgm', *, samples=32, channels=2):
    offset = 0x820 if container == 'dbm' else 0x20 if container == 'bgm' else 0
    value = bytearray(offset + 0x800)
    value[:4] = b'DLBM' if container == 'dbm' else b'\0\0\0\x10' if container == 'bgm' else b'MTA2'
    value[offset:offset + 4] = b'MTA2'
    value[offset + 0x40:offset + 0x44] = b'HEAD'
    struct.pack_into('>H', value, offset + 0x56, channels)
    struct.pack_into('>II', value, offset + 0x58, 0, samples)
    struct.pack_into('>f', value, offset + 0x7c, 48000)
    return bytes(value)


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / 'home/dev_hdd0/game/NPMG00020/USRDIR'
    root.mkdir(parents=True)
    native = {'o/stage/test/cache.dar': encrypted(dar([('actor.mdn', b'MDN synthetic geometry'), ('run.mtar', b'synthetic animation')])),
              'o/dl/p/stage/test/cache.qar': encrypted(qar([('face.txn', b'synthetic texture'), ('eyes.txn', b'second texture')])),
              'o/slotdat/actors.slot': b'native slot', 'o/stage/test/world.geom': b'native map',
              'o/stage/test/voice.spc': b'native speech', 'o/stage/test/pack.ssp': b'native effects',
              'o/bgm/theme.bgm': music(), 'dbm/title.dbm': music('dbm'), 'o/common_n.dat': b'native common',
              'o/dl/p/bgm/expansion.bgm': music(), 'o/dl/p/slotdat/expansion.slot': b'native expansion',
              'o/sdpack_e/weapon.ssp': b'native effects', 'o/dl/p/speech_e/voice.spc': b'native voice',
              'o/dl/p/vox_ex1.dat': b'native expansion voice'}
    excluded = {'o/online/account.sav': b'private save', 'o/online/password.dat': b'private account',
                'o/stage/test/start.self': b'program', 'config/rpcn.yml': b'private config',
                'speech/config.yml': b'private config', 'unrelated.dat': b'unrelated',
                'o/dl/p/account.dat': b'private account', 'o/clanemblem/custom.emb': b'private player emblem'}
    for name, value in (native | excluded).items():
        put(root, name, value)
    return SimpleNamespace(root=root, native=native, excluded=excluded, out=tmp_path / 'exports')


def test_inventory_is_native_only_and_filters_private_files(tree):
    result = M.inventory(tree.root, include_members=True, source_fingerprint='a' * 64)
    assert {a['path'] for a in result['assets']} == set(tree.native)
    assert result['summary']['files'] == len(tree.native)
    assert result['summary']['bytes'] == sum(map(len, tree.native.values()))
    assert result['summary']['indexed_archives'] == 2 and result['summary']['archive_members'] == 4
    assert not result['issues']
    assert result['fingerprint_verification'] == 'caller_supplied'
    assert result['source_fingerprint'] == 'a' * 64
    assert result['readiness']['decoded_models'] is False
    assert all(a['state'] == 'native_only' and not a['readiness']['cross_game_ready'] for a in result['assets'])
    assert {a['audio']['container'] for a in result['assets'] if 'audio' in a} == {'KCEJ', 'DLBM/KCEJ'}
    assert M.data_root(tree.root.parents[3]) == tree.root


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'a:stream', 'dir\\file', 'a//b', 'NUL.txn',
                                  'dir/COM2.bin', 'trailing.', 'trailing ', 'dir/../file', 'wild*.txn',
                                  'quest?.txn', 'pipe|.txn', 'quote".txn', '<tag>.txn'])
def test_unsafe_member_paths_rejected(name):
    with pytest.raises(ValueError):
        M._index(dar([(name, b'native')]), '.dar')


def test_nul_cannot_enter_a_requested_relative_path():
    with pytest.raises(ValueError):
        M._relative('a\x00b')


@pytest.mark.parametrize('extension,builder', [('.dar', dar), ('.qar', qar)])
def test_authenticated_index_and_member_bounds(tree, extension, builder):
    relative = 'o/stage/test/new' + extension
    blob = encrypted(builder([('a.mdn', b'one'), ('b.txn', b'two')]))
    source = put(tree.root, relative, blob)
    result = M.archive_index(tree.root, relative)
    assert result['checksum_verified'] is True and result['logical_stage'] == 'stage/test'
    assert result['sha256'] == hashlib.sha256(blob).hexdigest()
    assert [(r['name'], r['size']) for r in result['members']] == [('a.mdn', 3), ('b.txn', 3)]
    source.write_bytes(blob[:-1] + bytes([blob[-1] ^ 1]))
    with pytest.raises(ValueError, match='checksum'):
        M.archive_index(tree.root, relative)
    other = 'o/stage/another/new' + extension
    put(tree.root, other, blob)
    with pytest.raises(ValueError, match='checksum'):
        M.archive_index(tree.root, other)
    with pytest.raises(ValueError, match='Duplicate'):
        M._index(builder([('a.mdn', b'one'), ('A.MDN', b'two')]), extension)


@pytest.mark.parametrize('payload,extension', [
    (b'\0\0\0\0', '.dar'), (b'\0\0\x20\x01', '.dar'),
    (dar([('x.mdn', b'one')])[:-5], '.dar'),
    (b'\0' * 16, '.qar'), (qar([('x.txn', b'one')])[:-8] + b'\xff' * 4, '.qar')])
def test_truncated_or_oversized_archive_index_rejected(payload, extension):
    with pytest.raises(ValueError):
        M._index(payload, extension)


def test_selected_native_and_authenticated_members_preserve_provenance(tree):
    events = []
    result = M.export(tree.root, tree.out, paths=['o/slotdat/actors.slot'], members=[
        {'archive': 'o/stage/test/cache.dar', 'name': 'actor.mdn'},
        {'archive': 'o/dl/p/stage/test/cache.qar', 'name': 'face.txn'}], progress=events.append)
    assert result['state'] == 'exported' and not result['reused']
    assert len(result['files']) == 3 and max(e['files'] for e in events) == 3
    assert any(e['phase'] == 'verify' for e in events)
    manifest = json.loads(Path(result['manifest']).read_text())
    assert manifest['native_only'] and manifest['fingerprint_verification'] == 'not_provided'
    for row in result['files']:
        value = (Path(result['directory']) / row['output']).read_bytes()
        assert hashlib.sha256(value).hexdigest() == row['sha256'] and len(value) == row['size']
        assert not row['readiness']['decoded'] and not row['readiness']['cross_game_ready']
        if 'member' in row:
            assert row['archive_checksum_verified'] is True and row['logical_stage'] == 'stage/test'
            assert row['archive_sha256'] == hashlib.sha256(tree.native[row['source_path']]).hexdigest()
    assert all((tree.root / name).read_bytes() == value for name, value in (tree.native | tree.excluded).items())
    again = M.export(tree.root, tree.out, paths=['o/slotdat/actors.slot'], members=[
        {'archive': 'o/stage/test/cache.dar', 'name': 'actor.mdn'},
        {'archive': 'o/dl/p/stage/test/cache.qar', 'name': 'face.txn'}])
    assert again['reused'] and again['bundle_id'] == result['bundle_id']
    (Path(result['directory']) / result['files'][0]['output']).write_bytes(b'tampered')
    with pytest.raises(ValueError, match='changed'):
        M.export(tree.root, tree.out, paths=['o/slotdat/actors.slot'], members=[
            {'archive': 'o/stage/test/cache.dar', 'name': 'actor.mdn'},
            {'archive': 'o/dl/p/stage/test/cache.qar', 'name': 'face.txn'}])


@pytest.mark.parametrize('kwargs', [{}, {'paths': ['o/online/account.sav']}, {'paths': ['config/rpcn.yml']},
                                  {'paths': ['*', 'o/common_n.dat']}, {'source_fingerprint': 'not-verified'},
                                  {'members': [{'archive': 'o/stage/test/cache.dar', 'name': 'absent.mdn'}]},
                                  {'paths': ['*'], 'members': [{'archive': 'o/stage/test/cache.dar', 'name': 'actor.mdn'}]}])
def test_bad_export_selection_rejected(tree, kwargs):
    with pytest.raises(ValueError):
        M.export(tree.root, tree.out, **kwargs)
    assert not tree.out.exists()


def test_selected_budget_checked_before_read(tree, monkeypatch):
    monkeypatch.setattr(M, 'MAX_EXPORT_BYTES', 2)
    monkeypatch.setattr(M, '_read', lambda *args: pytest.fail('Budget must be checked before payload allocation'))
    with pytest.raises(ValueError, match='byte limit'):
        M.export(tree.root, tree.out, paths=['o/common_n.dat'])


@pytest.mark.parametrize('operation', ['selected', 'all', 'audio'])
def test_output_cannot_mutate_source_tree(tree, operation):
    with pytest.raises(ValueError, match='immutable'):
        if operation == 'selected':
            M.export(tree.root, tree.root / 'output', paths=['o/common_n.dat'])
        elif operation == 'all':
            M.export_all(tree.root, tree.root / 'output')
        else:
            M.decode_music(tree.root, 'o/bgm/theme.bgm', tree.root / 'output', decoder=tree.root / 'missing')
    assert not (tree.root / 'output').exists()


def test_full_export_streams_all_resources_and_reuses_immutable_bundle(tree, monkeypatch):
    events, reads = [], []
    original = M._read
    def bounded(path, limit):
        reads.append(path.name)
        assert path.name == 'manifest.json', 'Full export must not allocate asset payloads through _read'
        return original(path, limit)
    monkeypatch.setattr(M, '_read', bounded)
    monkeypatch.setattr(M, 'STREAM_CHUNK_BYTES', 31)
    result = M.export(tree.root, tree.out, paths=['*'], progress=events.append)
    assert result['native_only'] and not result['archives_unpacked'] and not result['reused']
    assert {row['source_path'] for row in result['files']} == set(tree.native)
    assert result['bytes'] == sum(map(len, tree.native.values()))
    assert events[-1] == {'phase': 'complete', 'files': len(tree.native), 'total_files': len(tree.native),
                          'bytes': result['bytes'], 'total_bytes': result['bytes']}
    assert {'hash', 'copy', 'verify', 'complete'} == {event['phase'] for event in events}
    assert len(events) > len(tree.native) * 2
    for row in result['files']:
        assert (Path(result['directory']) / row['output']).read_bytes() == tree.native[row['source_path']]
    assert M.export_all(tree.root, tree.out)['reused'] is True
    extra = Path(result['directory']) / 'not-in-manifest'
    extra.write_bytes(b'changed')
    with pytest.raises(ValueError, match='changed'):
        M.export_all(tree.root, tree.out)
    assert all((tree.root / name).read_bytes() == value for name, value in (tree.native | tree.excluded).items())


def test_full_export_accepts_native_file_larger_than_member_limit(tree, monkeypatch):
    monkeypatch.setattr(M, 'MAX_MEMBER_BYTES', 1)
    result = M.export_all(tree.root, tree.out)
    assert len(result['files']) == len(tree.native)


def test_full_export_budget_and_disk_reserve(tree, monkeypatch):
    with pytest.raises(ValueError, match='budget'):
        M.export_all(tree.root, tree.out, max_bytes=1)
    assert not tree.out.exists()
    with pytest.raises(ValueError, match='12 GiB'):
        M.export_all(tree.root, tree.out, max_bytes=M.MAX_FULL_EXPORT_BYTES + 1)
    monkeypatch.setattr(M.shutil, 'disk_usage', lambda _: SimpleNamespace(free=1))
    with pytest.raises(ValueError, match='free disk'):
        M.export_all(tree.root, tree.out)
    assert list(tree.out.iterdir()) == []


def test_full_export_cancel_during_copy_cleans_owned_stage(tree):
    cancelled = False
    def progress(event):
        nonlocal cancelled
        if event['phase'] == 'copy':
            cancelled = True
    with pytest.raises(InterruptedError, match='cancelled'):
        M.export_all(tree.root, tree.out, cancel=lambda: cancelled, progress=progress)
    assert list(tree.out.iterdir()) == []
    assert all((tree.root / name).read_bytes() == value for name, value in tree.native.items())


def test_full_export_source_change_between_passes_rejected(tree):
    def progress(event):
        if event['phase'] == 'hash' and event['path'] == 'o/common_n.dat':
            (tree.root / 'o/slotdat/actors.slot').write_bytes(b'changed during plan')
    with pytest.raises(ValueError, match='changed'):
        M.export_all(tree.root, tree.out, progress=progress)
    assert not tree.out.exists() or list(tree.out.iterdir()) == []


@pytest.mark.parametrize('reuse', [False, True])
def test_verification_heartbeat_can_cancel_without_publishing_or_deleting_bundle(tree, reuse):
    existing = M.export_all(tree.root, tree.out) if reuse else None
    def progress(event):
        if event['phase'] == 'verify':
            raise InterruptedError('operator cancel via progress heartbeat')
    with pytest.raises(InterruptedError, match='heartbeat'):
        M.export_all(tree.root, tree.out, progress=progress)
    assert not list(tree.out.glob('.savemgo-*'))
    assert len(list(tree.out.iterdir())) == (1 if reuse else 0)
    if existing:
        assert Path(existing['directory']).is_dir()


@pytest.mark.parametrize('operation', ['inventory', 'export_all'])
def test_unreadable_subtree_fails_closed_instead_of_publishing_incomplete_inventory(tree, monkeypatch, operation):
    def broken_walk(path, *, followlinks, onerror):
        assert followlinks is False
        onerror(PermissionError('synthetic resource subtree denied'))
        yield str(path), [], []
    monkeypatch.setattr(M.os, 'walk', broken_walk)
    with pytest.raises(PermissionError, match='subtree denied'):
        if operation == 'inventory':
            M.inventory(tree.root)
        else:
            M.export_all(tree.root, tree.out)
    assert not tree.out.exists()


def test_cleanup_refuses_unowned_directory(tmp_path):
    with pytest.raises(ValueError, match='unowned'):
        M._remove_stage(tmp_path, tmp_path.parent)
    assert tmp_path.exists()


def test_reparse_or_symlink_is_not_followed(tree, tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    put(outside, 'private.dat', b'private')
    link = tree.root / 'o/stage/linked'
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Creating a symlink requires Windows developer mode')
    with pytest.raises(ValueError, match='Symlinks'):
        M.export_all(tree.root, tree.out)
    assert not tree.out.exists()


@pytest.mark.parametrize('container', ['bgm', 'dbm', 'mta2'])
def test_audio_metadata_is_validated_without_claiming_decode(container):
    metadata = M._audio_header(music(container))
    assert metadata['channels'] == 2 and metadata['sample_rate'] == 48000 and metadata['samples'] == 32
    assert metadata['decoded'] is False and metadata['codec'] == 'MTA2'
    assert M._audio_header(music(container, channels=0)) is None
    assert M._audio_header(music(container, samples=0)) is None


def test_decoder_unavailable_is_honest_and_does_not_create_output(tree, monkeypatch):
    monkeypatch.setattr(M, 'find_vgmstream', lambda *args: None)
    result = M.decode_music(tree.root, 'o/bgm/theme.bgm', tree.out)
    assert result['state'] == 'decoder_unavailable' and result['decoded'] is False
    assert result['native_export'] is True and not tree.out.exists()


def test_existing_decoder_is_invoked_for_exact_source_and_validated(tree, monkeypatch, tmp_path):
    decoder = put(tmp_path, 'existing-decoder.exe', b'owned synthetic stub')
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        with wave.open(args[3], 'wb') as out:
            out.setnchannels(2); out.setsampwidth(2); out.setframerate(48000)
            out.writeframes(b'\0' * (32 * 2 * 2))
    monkeypatch.setattr(M.subprocess, 'run', run)
    result = M.decode_music(tree.root, 'o/bgm/theme.bgm', tree.out, decoder=decoder)
    assert result['state'] == 'decoded' and result['decoded'] is True
    assert calls[0][0][0:3] == [str(decoder), '-i', '-o']
    assert calls[0][0][-1] == str(tree.root / 'o/bgm/theme.bgm')
    assert calls[0][1]['timeout'] == 90 and calls[0][1]['check'] is True
    assert Path(result['path']).is_file() and result['sha256'] == hashlib.sha256(Path(result['path']).read_bytes()).hexdigest()
    assert result['source_sha256'] == hashlib.sha256(tree.native['o/bgm/theme.bgm']).hexdigest()
    assert not list(tree.out.glob('.savemgo-*'))


def test_wrong_decoded_wav_is_rejected_and_stage_cleaned(tree, monkeypatch, tmp_path):
    decoder = put(tmp_path, 'existing-decoder.exe', b'owned synthetic stub')
    def run(args, **kwargs):
        with wave.open(args[3], 'wb') as out:
            out.setnchannels(2); out.setsampwidth(2); out.setframerate(48000)
            out.writeframes(b'\0' * 4)
    monkeypatch.setattr(M.subprocess, 'run', run)
    with pytest.raises(ValueError, match='metadata'):
        M.decode_music(tree.root, 'o/bgm/theme.bgm', tree.out, decoder=decoder)
    assert list(tree.out.iterdir()) == []
