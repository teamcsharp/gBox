"""Live PSO face edits are session/address pinned, preserve pause state and show native encoded previews."""
import hashlib
import io
import struct
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox import pso_faces as F, pso_gc as G, pso_gc_swap as W
from gbox.models import Permission
from gbox.photo_skin import Placement
from gbox.store import Store


def chunk(fmt=4, size=32, raw=None):
    if raw is None:
        raw = W.gx_encode(np.asarray(Image.new('RGBA', (size, size), (64, 128, 192, 255))), fmt)
    header = bytearray(16)
    header[:4] = b'GVRT'
    struct.pack_into('<I', header, 4, len(raw) + 8)
    header[11] = fmt
    struct.pack_into('>HH', header, 12, size, size)
    return bytes(header) + raw


def placement(photo='a' * 64):
    return Placement(photo=photo, maps=[0], quad=[[.4, .4], [.6, .4], [.6, .6], [.4, .6]], feather=0)


@pytest.mark.parametrize('fmt', [1, 4, 5, 14])
def test_native_preview_preserves_unedited_pixels_and_decodes_exact_candidate(fmt):
    # The wide endpoints and unused source colors are valid CMPR, but whole-map recompression loses that encoding.
    raw = struct.pack('>HHI', 0xffff, 0, 0xaaaaaaaa) * 64 if fmt == 14 else None
    original = chunk(fmt, raw=raw)
    before = G.gvr_decode(original)
    candidate, preview = F.preview_image(original, Image.new('RGBA', (30, 30), 'red'), placement(), [])
    after = G.gvr_decode(candidate)
    assert candidate[:16] == original[:16] and len(candidate) == len(original)
    assert np.array_equal(np.asarray(Image.open(io.BytesIO(preview))), after)
    # Far outside the small projected face and all compression blocks touching that face.
    assert np.array_equal(after[:8, :8], before[:8, :8]), 'Untouched texture pixels changed outside the face patch'


def test_mask_can_erase_photo_without_destroying_original_texture():
    original = chunk()
    native, _ = F.preview_image(original, Image.new('RGBA', (20, 20), 'red'), placement(),
                                [F.Stroke(x=.5, y=.5, radius=.3, erase=True)])
    assert native == original


@pytest.fixture
def live(tmp_path, monkeypatch):
    import gbox.pso_gc_live as GC
    monkeypatch.setattr(GC.GC, 'check', lambda self: 0x80010000)
    native = chunk()
    raw = native[16:]
    class Adapter:
        def __init__(self):
            self.mem = raw
            self.state = 'PLAYING'
            self.calls = []
            self._pso_face_maps = {'known': {'addresses': [0x80020000], 'original': raw, 'current': raw,
                                  'chunk': native, 'offset': 16, 'chunk_sha': F.digest(native)}}
        def read_memory(self, address, n):
            self.calls.append(('read', address, n))
            return self.mem[:n]
        def write_memory(self, address, data):
            self.calls.append(('write', address, data))
            self.mem = data
        def query_runtime(self): return {'state': self.state}
        def pause(self): self.calls.append(('pause',)); self.state = 'PAUSED'
        def resume(self): self.calls.append(('resume',)); self.state = 'PLAYING'
    ad = Adapter()
    replacement = W.gvr_like(native, Image.new('RGBA', (32, 32), 'red'))
    candidate = F.digest(replacement)
    provenance = {'session_id': 's', 'key': 'known', 'original_gvr': F.digest(native)}
    def get(url, **kwargs):
        return SimpleNamespace(content=replacement, json=lambda: provenance, raise_for_status=lambda: None)
    monkeypatch.setattr(F.httpx, 'get', get)
    ctx = SimpleNamespace(server='http://test', headers={}, config=SimpleNamespace(data_dir=tmp_path,
                          granted_permissions=[Permission.READ, Permission.MEMORY_WRITE]))
    inp = F.FaceIn(op='apply', session_id='s', key='known', address=0x80020000, candidate=candidate)
    return ad, ctx, inp, provenance, native


@pytest.mark.parametrize('playing', [True, False])
def test_apply_and_restore_preserve_original_pause_state(live, playing):
    ad, ctx, inp, _, native = live
    ad.state = 'PLAYING' if playing else 'PAUSED'
    result = F.apply('s', ad, inp, ctx)
    assert result['memory_verified'] and ad.mem != native[16:]
    assert ad.state == ('PLAYING' if playing else 'PAUSED')
    assert sum(c[0] == 'pause' for c in ad.calls) == int(playing)
    inp.op = 'restore'
    F.apply('s', ad, inp, ctx)
    assert ad.mem == native[16:] and ad.state == ('PLAYING' if playing else 'PAUSED')


@pytest.mark.parametrize('change', ['address', 'bytes', 'session', 'key', 'source'])
def test_wrong_address_recycled_texture_or_foreign_candidate_never_writes(live, change):
    ad, ctx, inp, provenance, _ = live
    if change == 'address': inp.address += 4
    if change == 'bytes': ad.mem = b'other allocation' * 100
    if change == 'session': provenance['session_id'] = 'foreign'
    if change == 'key': provenance['key'] = 'foreign'
    if change == 'source': provenance['original_gvr'] = '0' * 64
    with pytest.raises(ValueError): F.apply('s', ad, inp, ctx)
    assert not any(c[0] == 'write' for c in ad.calls)


def test_write_failure_still_restores_playing_state(live):
    ad, ctx, inp, _, _ = live
    def fail(*a): raise RuntimeError('failed write')
    ad.write_memory = fail
    with pytest.raises(RuntimeError, match='failed write'): F.apply('s', ad, inp, ctx)
    assert ad.state == 'PLAYING' and ad.calls[-1] == ('resume',)


def test_unknown_runtime_state_cannot_write_without_confirmed_pause(live):
    ad, ctx, inp, _, _ = live
    ad.state = 'UNKNOWN'
    with pytest.raises(Exception, match='[Pp]aus|state|running'): F.apply('s', ad, inp, ctx)
    assert not any(c[0] == 'write' for c in ad.calls)


def test_resident_match_scan_rejects_common_patterns_and_ambiguous_hits():
    data = bytes(range(128))
    assert F.matches(b'noise' + data + b'tail', data) == [0x80000005]
    assert F.matches(data * 9, data) == []
    assert F.matches(bytes(4096), bytes(128)) == []


@pytest.fixture
def api(tmp_path):
    store = Store(tmp_path)
    app = FastAPI()
    F.routes(app, store, lambda: 'operator')
    image = io.BytesIO()
    Image.new('RGB', (20, 20), 'red').save(image, format='PNG')
    photo = store.put_artifact(image.getvalue(), 'face.png', 'image/png', {'photo_skin_source': True}).sha256
    store.put('photo_source', photo, {'photo': photo, 'label': 'Saved face'})
    original = chunk()
    sha = store.put_artifact(original, 'face.gvr', 'application/octet-stream',
                             {'pso_face_session': 's', 'pso_face_key': 'known'}).sha256
    client = TestClient(app)
    assert client.post('/api/pso/faces/inspections', json={'session_id': 's', 'key': 'e' * 32, 'chunk': sha}).status_code == 200
    return client, store, photo, sha


def test_face_preview_routes_validate_sources_and_preserve_lineage(api):
    client, store, photo, source = api
    assert client.get('/api/pso/faces/photos').json()[0]['label'] == 'Saved face'
    body = {'session_id': 's', 'key': 'e' * 32, 'chunk': source, 'settings': placement(photo).model_dump()}
    r = client.post('/api/pso/faces/preview', json=body)
    assert r.status_code == 200, r.text
    result = r.json()
    assert result['native_quantized'] and store.read_artifact(result['candidate'])
    assert store.get('artifact', result['candidate'])['provenance']['original_gvr'] == source
    assert client.post('/api/pso/faces/preview', json=body | {'session_id': 'other'}).status_code == 422
    assert client.post('/api/pso/faces/preview', json=body | {'key': 'other'}).status_code == 422
    assert client.post('/api/pso/faces/preview', json=body | {'strokes': [{'x': -1, 'y': 0}]}).status_code == 422


def test_identical_texture_and_candidate_bytes_stay_pinned_independently_for_two_sessions(api):
    client, store, photo, source = api
    second = {'session_id': 's2', 'key': 'f' * 32, 'chunk': source}
    assert client.post('/api/pso/faces/inspections', json=second).status_code == 200
    body = {'session_id': 's', 'key': 'e' * 32, 'chunk': source, 'settings': placement(photo).model_dump()}
    first = client.post('/api/pso/faces/preview', json=body)
    other = client.post('/api/pso/faces/preview', json=body | second)
    assert first.status_code == other.status_code == 200
    a, b = first.json()['candidate'], other.json()['candidate']
    assert a == b  # the bytes share storage, but each inspection owns an independent review record
    for sid, key in [('s', 'e' * 32), ('s2', 'f' * 32)]:
        response = client.get('/api/pso/faces/candidates/' + a, params={'session_id': sid, 'key': key})
        assert response.status_code == 200 and response.json()['original_gvr'] == source
    assert client.get('/api/pso/faces/candidates/' + a, params={'session_id': 's', 'key': 'f' * 32}).status_code == 404
    assert client.post('/api/pso/faces/inspections', json=second | {'session_id': 'different'}).status_code == 409


def test_authorization_rejects_stale_source_worker_missing_permission_and_expired_input(tmp_path):
    store = Store(tmp_path)
    sources = {f'gbox/{name}': F.digest(Path(F.__file__).with_name(name).read_bytes().replace(b'\r\n', b'\n'))
               for name in ('pso_faces.py', 'pso_gc.py', 'pso_gc_swap.py', 'tools.py', 'adapters.py')}
    store.put('session', 'w-s', {'state': 'running', 'worker_id': 'w'})
    store.put('worker', 'w', {'build_sources': sources})
    cfg = SimpleNamespace(granted_permissions=['read', 'memory_write'])
    body = {'command_id': str(uuid.uuid4()), 'expires': time.time() + 10, 'input': {'op': 'restore'}}
    assert F.authorize(store, cfg, 'w-s', body).op == 'restore'
    with pytest.raises(ValueError, match='expired'): F.authorize(store, cfg, 'w-s', body | {'expires': 1})
    cfg.granted_permissions = ['read']
    with pytest.raises(PermissionError): F.authorize(store, cfg, 'w-s', body)
    cfg.granted_permissions = ['memory_write']
    store.put('worker', 'w', {'build_sources': sources | {'gbox/pso_faces.py': 'old'}})
    with pytest.raises(ValueError, match='idle update'): F.authorize(store, cfg, 'w-s', body)
