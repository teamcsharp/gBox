from pathlib import Path
import threading
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from gbox import blender_copy as B, desktop_bridge as D
from gbox.store import canon, sha256


@pytest.fixture
def paired(tmp_path, monkeypatch):
    inp = B.CopyIn(character='doa2_bay')
    job = {'id': 'local-job', 'tool': 'blender_copy', 'actor': 'operator', 'input': inp.model_dump(),
           'origin': {'desktop_federation_key': 'key', 'desktop_federation_authority': 'authority'}}
    mapping = {'id': 'central-job', 'local_job_id': job['id'], 'tool': job['tool'], 'authority': 'authority',
               'remote': 'http://spark:8765', 'execution_input_sha256': sha256(canon(job['input']))}
    rows = {('job', job['id']): job, ('desktop_bridge_job', 'key'): mapping}
    bridge = SimpleNamespace(store=SimpleNamespace(lock=threading.RLock(), get=lambda kind, key: rows.get((kind,key))),
                             authority='authority', remote=mapping['remote'], token='paired-source-token')
    ctx = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path), job_id=job['id'],
                          server='http://127.0.0.1:18765', headers={'authorization': 'Bearer local-only-token'})
    monkeypatch.setitem(D._LOCAL_AUTHORITIES, str(tmp_path.resolve()), bridge)
    return ctx, inp, job, mapping, bridge


def test_federated_bayman_copy_downloads_from_its_source_and_writes_locally(paired, monkeypatch, tmp_path):
    ctx, inp, job, mapping, bridge = paired
    requests, copied = [], []
    def get(url, **kwargs):
        requests.append((url, kwargs['headers']))
        assert url == 'http://spark:8765/api/characters/doa2_bay/blender'
        return httpx.Response(200, content=b'glTF-source-model', headers={'content-type':'model/gltf-binary'},
                              request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx, 'get', get)
    monkeypatch.setattr(B.tempfile, 'mkdtemp', lambda **kw: str(tmp_path))
    def to_blender(path, nodes):
        copied.append(Path(path).read_bytes())
        return {'host': 'this-pc', 'copybuffer': 'local-copybuffer.blend'}
    monkeypatch.setattr(B, 'to_blender', to_blender)
    result = B.blender_copy(inp, ctx)['result']
    assert copied == [b'glTF-source-model'] and result['host'] == 'this-pc'
    assert requests[0][1] == {'authorization':'Bearer paired-source-token',
                               'x-gbox-parent-job':'central-job', 'x-gbox-actor':'operator'}
    assert ctx.server == 'http://127.0.0.1:18765'
    assert ctx.headers == {'authorization':'Bearer local-only-token'}


@pytest.mark.parametrize('field,value', [('local_job_id','another-job'), ('remote','http://foreign.example'),
    ('authority','another-installation'), ('tool','launch_game'), ('execution_input_sha256','wrong')])
def test_source_requires_exact_persisted_job_mapping(paired, field, value):
    ctx, _, _, mapping, _ = paired
    mapping[field] = value
    with pytest.raises(ValueError, match='paired job'):
        D.asset_source_context(ctx)


def test_origin_header_alone_does_not_select_remote_credentials(paired):
    ctx, _, job, _, _ = paired
    job['origin'] = {'remote':'http://foreign.example'}
    assert D.asset_source_context(ctx) is None


def test_changed_input_refuses_remote_source(paired):
    ctx, _, job, _, _ = paired
    job['input'] = {'character':'different-model'}
    with pytest.raises(ValueError, match='paired job'):
        D.asset_source_context(ctx)


def test_unpaired_local_copy_retains_local_source(tmp_path):
    ctx = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path), job_id='local-job')
    assert D.asset_source_context(ctx) is None


def test_missing_character_model_returns_not_found_instead_of_server_error(tmp_path, monkeypatch):
    from gbox import characters, server
    from gbox.config import Config
    cfg = Config(data_dir=tmp_path/'data', cache_dir=tmp_path/'cache')
    monkeypatch.setattr(characters, 'library_root', lambda config: tmp_path/'characters')
    app = server.create_app(cfg)
    with TestClient(app, headers={'authorization':'Bearer '+cfg.token()}) as client:
        assert client.get('/api/characters/doa2_bay/model').status_code == 404
