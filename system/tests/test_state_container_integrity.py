"""Incomplete RetroArch containers must not become preserved captures or overwrite a moment."""
import hashlib
import struct
import zlib
from types import SimpleNamespace

import httpx
import pytest

from gbox import tools


def rastate(mem):
    def block(tag, value):
        return tag + struct.pack('<I', len(value)) + value + b'P' * ((-len(value)) % 8)
    return b'RASTATE\x01' + block(b'META', b'non-Flycast') + block(b'MEM ', mem) + b'END ' + bytes(4)


def rzip(data, codec=1):
    if codec == 1:
        compress = zlib.compress
    else:
        compress = pytest.importorskip('zstandard').ZstdCompressor().compress
    chunks = [compress(data[offset:offset + 32]) for offset in range(0, len(data), 32)]
    return b'#RZIPv' + bytes([codec]) + b'#' + struct.pack('<IQ', 32, len(data)) + b''.join(
        struct.pack('<I', len(chunk)) + chunk for chunk in chunks)


def malformed(case):
    packed = rzip(rastate(b'non-Flycast core state'))
    if case == 'empty_raw':
        return b''
    if case == 'zero_total_with_chunks':
        # Exact observed failure class: RZIPv2 with valid chunk-size but an
        # unfinished total-length header. No codec dependency is needed to
        # reject trailing chunks after zero declared output.
        return b'#RZIPv\x02#' + struct.pack('<IQ', 131072, 0) + packed[20:]
    if case == 'zero_total_without_chunks':
        return b'#RZIPv\x02#' + struct.pack('<IQ', 131072, 0)
    if case == 'truncated_header':
        return packed[:12]
    if case == 'truncated_chunk':
        return packed[:-1]
    if case == 'trailing_bytes':
        return packed + b'unaccounted'
    if case == 'declared_size_mismatch':
        data = bytearray(packed)
        struct.pack_into('<Q', data, 12, struct.unpack_from('<Q', data, 12)[0] + 1)
        return bytes(data)
    if case == 'rastate_missing_end':
        return rastate(b'non-Flycast core state')[:-8]
    if case == 'empty_mem':
        return rastate(b'')
    raise ValueError(case)


BAD_CASES = ['empty_raw', 'zero_total_with_chunks', 'zero_total_without_chunks', 'truncated_header',
             'truncated_chunk', 'trailing_bytes', 'declared_size_mismatch',
             'rastate_missing_end', 'empty_mem']


def setup_session(tmp_path, monkeypatch):
    states = tmp_path / 'states' / 'OtherCore'
    states.mkdir(parents=True)
    target = states / 'Current.state9'
    other = states / 'Current.state10'
    target.write_bytes(b'original-target-moment')
    other.write_bytes(b'another-moment')
    saved, loaded, artifacts, frames = [], [], [], []

    def save(slot):
        saved.append(slot)
        target.write_bytes(b'placeholder')
        return {'verified': True, 'path': str(target), 'bytes': target.stat().st_size, 'slot': 9}

    def frame():
        frames.append(True)
        return b'native-frame'

    adapter = SimpleNamespace(name='retroarch', save_state=save, slot=9,
                              load_state=loaded.append, get_frame=frame)
    monkeypatch.setitem(tools.SESSIONS, 'container-test', (adapter, {'_rom_path': 'Current.rom', 'game_id': 'g'}))
    monkeypatch.setattr(tools.time, 'sleep', lambda _: None)
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), server='http://test', headers={},
                          artifact=lambda *args, **kwargs: artifacts.append((args, kwargs)))
    return adapter, ctx, target, other, saved, loaded, artifacts, frames


def download(monkeypatch, data):
    monkeypatch.setattr(tools.httpx, 'get', lambda *args, **kwargs: httpx.Response(
        200, content=data, request=httpx.Request('GET', 'http://test')))
    return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize('case', BAD_CASES)
def test_malformed_import_refused_before_placeholder_save_overwrite_or_load(tmp_path, monkeypatch, case):
    _, ctx, target, other, saved, loaded, artifacts, _ = setup_session(tmp_path, monkeypatch)
    before = target.read_bytes(), other.read_bytes()
    data = malformed(case)
    digest = download(monkeypatch, data)
    with pytest.raises(RuntimeError, match='checkpoint'):
        tools.state_transfer(tools.StateXIn(session_id='container-test', op='import', artifact=digest), ctx)
    assert (target.read_bytes(), other.read_bytes()) == before
    assert saved == loaded == artifacts == []
    assert hashlib.sha256(data).hexdigest() == digest


@pytest.mark.parametrize('case', BAD_CASES)
def test_malformed_saved_export_refused_without_mutating_file_or_artifact(tmp_path, monkeypatch, case):
    _, ctx, target, other, saved, loaded, artifacts, _ = setup_session(tmp_path, monkeypatch)
    data = malformed(case)
    target.write_bytes(data)
    with pytest.raises(RuntimeError, match='checkpoint'):
        tools.state_transfer(tools.StateXIn(session_id='container-test', op='export_saved', slot=9), ctx)
    assert target.read_bytes() == data and other.read_bytes() == b'another-moment'
    assert saved == loaded == artifacts == []


def test_malformed_new_save_cannot_be_exported_as_verified_capture(tmp_path, monkeypatch):
    adapter, ctx, target, other, saved, loaded, artifacts, _ = setup_session(tmp_path, monkeypatch)
    data = malformed('zero_total_with_chunks')

    def save(slot):
        saved.append(slot)
        target.write_bytes(data)
        return {'verified': True, 'path': str(target), 'bytes': len(data), 'slot': 9}

    adapter.save_state = save
    with pytest.raises(RuntimeError, match='checkpoint container'):
        tools.state_transfer(tools.StateXIn(session_id='container-test', op='export', slot=9), ctx)
    assert target.read_bytes() == data and other.read_bytes() == b'another-moment'
    assert saved == [9] and loaded == artifacts == []


def test_session_save_does_not_attach_thumbnail_or_return_success_for_bad_container(tmp_path, monkeypatch):
    adapter, ctx, target, _, _, loaded, artifacts, frames = setup_session(tmp_path, monkeypatch)
    target.write_bytes(malformed('zero_total_with_chunks'))
    adapter.save_state = lambda slot=9: {'verified': True, 'path': str(target), 'slot': slot}
    before = target.read_bytes()
    with pytest.raises(RuntimeError, match='checkpoint container'):
        tools.session_op(tools.SessionIn(session_id='container-test', op='save_state', args={'slot': 9}), ctx)
    assert target.read_bytes() == before
    assert loaded == artifacts == frames == []


@pytest.mark.parametrize('container', ['raw', 'rastate', 'rzip1', 'rzip2', 'rzip1_raw'])
@pytest.mark.parametrize('op', ['export_saved', 'import'])
def test_valid_non_flycast_envelopes_and_raw_states_keep_exact_bytes(tmp_path, monkeypatch, container, op):
    _, ctx, target, other, saved, loaded, artifacts, _ = setup_session(tmp_path, monkeypatch)
    # Deliberately not a supported Flycast serializer/version/topology.
    mem = b'other-core-memory-layout\x00\xff'
    data = {'raw': mem, 'rastate': rastate(mem)}.get(container)
    if data is None:
        data = rzip(mem if container == 'rzip1_raw' else rastate(mem), codec=2 if container == 'rzip2' else 1)
    if op == 'export_saved':
        target.write_bytes(data)
        result = tools.state_transfer(tools.StateXIn(session_id='container-test', op=op, slot=9), ctx)['result']
        assert result['artifact'] == hashlib.sha256(data).hexdigest()
        assert artifacts[0][0][1] == data and saved == loaded == []
    else:
        digest = download(monkeypatch, data)
        result = tools.state_transfer(tools.StateXIn(session_id='container-test', op=op, artifact=digest, slot=9), ctx)['result']
        assert result['load_requested'] is True and result['load_verified'] is False
        assert saved == loaded == [9] and artifacts == []
    assert target.read_bytes() == data and other.read_bytes() == b'another-moment'


def test_other_adapters_do_not_inherit_retroarch_container_rules():
    # This validator cannot interpret Dolphin/RPCS3/Yuzu serialization.
    for adapter in ('dolphin', 'rpcs3', 'yuzu', ''):
        tools._validate_state_container(malformed('zero_total_with_chunks'), adapter)
        tools._validate_state_container(b'', adapter)


def test_empty_retroarch_import_cannot_destroy_existing_moment(tmp_path, monkeypatch):
    _, ctx, target, other, saved, loaded, artifacts, _ = setup_session(tmp_path, monkeypatch)
    before = target.read_bytes(), other.read_bytes()
    digest = download(monkeypatch, b'')
    with pytest.raises(RuntimeError, match='checkpoint is empty'):
        tools.state_transfer(tools.StateXIn(session_id='container-test', op='import', artifact=digest), ctx)
    assert (target.read_bytes(), other.read_bytes()) == before
    assert saved == loaded == artifacts == []
