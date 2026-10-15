import hashlib
import json
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox import tas, tas_api
from gbox.store import Store


def record(tag, payload):
    return struct.pack('<cI', tag, len(payload))+payload


def tape(path, n=8):
    data = bytearray(tas.MAGIC)
    for f in range(n):
        if f in (0, 3, 5):
            data += record(b'S', tas.encode_state(f, bytes([f])*64, 1 if f == 5 else 0 if f == 0 else 2))
        frame = struct.pack('<QHHII', f, 1, 0, 1234, 0)+bytes([0, 0 if f < 4 else 1, 0, 1, 3, 8, 0, 0])
        data += record(b'F', frame+struct.pack('<BBB Hh', 0, 1, 0, 7, f % 2))
    data += record(b'E', struct.pack('<Q', n))
    path.write_bytes(data)
    return bytes(data)


def test_full_timeline_retains_restore_and_level_attempts(tmp_path):
    path = tmp_path/'a.gbt'; tape(path)
    info = tas.index(path)
    assert info['frames'] == 8 and info['state_restores'] == 1
    assert [s['label'] for s in info['segments']] == ['1-1', '1-2']
    assert info['segments'][0]['end_frame'] == 4
    assert info['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert not info['replay_verified']


def test_segment_starts_at_nearest_checkpoint_preserves_later_restore(tmp_path):
    source, target = tmp_path/'a.gbt', tmp_path/'b.gbt'; tape(source)
    result = tas.slice_tape(source, target, 4, 7)
    assert result == dict(start_frame=1, end_frame=4, source_start=4, source_end=7, checkpoint_frame=3)
    info = tas.index(target)
    assert info['frames'] == 4 and info['state_restores'] == 1
    _, reason, state = tas.decode_state(next(tas.records(target))[2])
    assert reason == 0 and state == bytes([3])*64
    assert tas.index(source)['frames'] == 8


@pytest.mark.parametrize('damage', ['footer', 'length', 'sequence', 'tag', 'tail'])
def test_corrupt_tapes_rejected_without_playback(tmp_path, damage):
    path = tmp_path/'a.gbt'; data = bytearray(tape(path))
    if damage == 'footer': data = data[:-13]
    if damage == 'length': data[17:21] = struct.pack('<I', tas.MAX_RECORD+1)
    if damage == 'sequence':
        offset = next(off for off, tag, _ in tas.records(path) if tag == b'F')
        data[offset+5:offset+13] = struct.pack('<Q', 2)
    if damage == 'tag': data[16] = ord('X')
    if damage == 'tail': data += b'junk'
    path.write_bytes(data)
    with pytest.raises(ValueError): tas.index(path)


def test_delta_rle_is_bounded_and_exact():
    previous = b'abcde'
    encoded = struct.pack('<QBBI', 0, 1, 1, 5)+struct.pack('<HB', 2, 0)+struct.pack('<HB', 3, 1)+b'XYZ'
    assert tas.decode_state(encoded, previous)[2] == b'ab'+bytes(x ^ y for x, y in zip(b'cde', b'XYZ'))
    for bad in (encoded[:-1], encoded+bytes(3), encoded[:14]+b'\0\0\0'):
        with pytest.raises(ValueError): tas.decode_state(bad, previous)


def api(tmp_path, workers=lambda: [], submit=lambda *a, **k: {}):
    store = Store(tmp_path/'db')
    store.put('session', 'pc-human', {'session_id': 'pc-human', 'game_id': 'mario', 'title': 'Mario', 'state': 'ended'})
    app = FastAPI()
    tas_api.install(app, store, SimpleNamespace(data_dir=tmp_path), lambda: 'operator', submit, workers)
    return TestClient(app), store, app


def upload(c, path, rid='a'*32):
    meta = dict(session_id='pc-human', game_id='mario', core_options='', **{key: 'b'*64 for key in
                ('core_sha256', 'proxy_sha256', 'rom_sha256', 'prg_sha256', 'header_sha256', 'chr_sha256')})
    return c.post('/api/tas/captures/pc-human/'+rid, content=path.read_bytes(), headers={'x-gbox-tas-meta': json.dumps(meta)})


def test_archive_durable_digest_download_and_honest_legacy_status(tmp_path):
    c, store, _ = api(tmp_path); path = tmp_path/'a.gbt'; tape(path)
    result = upload(c, path)
    assert result.status_code == 200, result.text
    row = result.json()
    assert 'path' not in row and 'core_options' not in row and 'checkpoints' not in row
    assert c.get('/api/tas/runs/'+row['id']+'/file').content == path.read_bytes()
    assert len(c.get('/api/tas/runs?game_id=mario').json()['runs']) == 1
    assert c.get('/api/tas/runs?game_id=other').json()['runs'] == []
    assert not row['replay_verified']
    assert 'cannot be reconstructed' in c.get('/api/tas/runs').json()['legacy_reason']
    assert not list((tmp_path/'tas-runs').glob('upload-*'))


def test_archive_rejects_automated_copies_corrupt_files_and_run_collision(tmp_path):
    c, store, _ = api(tmp_path); path = tmp_path/'a.gbt'; tape(path)
    store.put('slabel', 'pc-human', {'owner': 'agent'})
    assert upload(c, path).status_code == 409
    store.put('slabel', 'pc-human', {'owner': 'you'})
    assert upload(c, path).status_code == 200
    tape(path, 6)
    assert upload(c, path).status_code == 409
    path.write_bytes(b'bad')
    assert upload(c, path, 'c'*32).status_code == 422
    assert not list((tmp_path/'tas-runs').glob('upload-*'))


def test_play_waits_without_touching_games_and_idle_requires_verified_run(tmp_path):
    c, store, app = api(tmp_path); path = tmp_path/'a.gbt'; tape(path)
    assert upload(c, path).status_code == 200
    assert c.post('/api/tas/runs/'+'a'*32+'/play', json={'loop': True}).status_code == 409
    assert c.post('/api/tas/runs/'+'a'*32+'/idle', json={'enabled': True}).status_code == 200
    app.state.tas_idle_tick()
    assert store.all('job') == []
    assert c.post('/api/tas/runs/'+'a'*32+'/result', json={'job_id': 'unrelated', 'status': {'state':'finished','mismatches':0}}).status_code == 409


def test_play_tool_registered_and_does_not_use_normal_game_switch():
    from gbox import tas_tool
    from gbox.registry import REGISTRY
    assert 'tas_play' in REGISTRY
    assert REGISTRY['tas_play'].on_accept is not None


def test_capture_is_not_enabled_for_agents_or_unsupported_platforms(tmp_path):
    ad = SimpleNamespace(capture_gameplay=False, config=SimpleNamespace(runtime=tmp_path))
    assert tas.prepare(ad, 'core', 'missing') is None
    ad.capture_gameplay=True; ad.platform='gamecube'
    assert tas.prepare(ad, 'core', 'missing') is None


def test_full_receipts_require_exact_end_and_never_promote_a_level_to_full_run(tmp_path):
    c, store, app = api(tmp_path); path = tmp_path/'a.gbt'; tape(path)
    assert upload(c, path).status_code == 200
    rid='a'*32
    store.put('job', 'j', {'tool':'tas_play','input':{'run_id':rid,'sprite':'sonic'}})
    def result(frame, **kw):
        return c.post('/api/tas/runs/'+rid+'/result',json={'job_id':'j','status':dict(state='finished',frame=frame,loops=0,mismatches=0,**kw)})
    assert result(4).json()['verified'] is False
    assert result(8).json()['verified'] is True
    assert c.get('/api/tas/runs/'+rid).json()['full_verified_sprites']==['sonic']
    store.put('job','j',{'tool':'tas_play','input':{'run_id':rid,'segment':'level-4','sprite':'sonic'}})
    assert result(5).json()['verified'] is True
    assert c.get('/api/tas/runs/'+rid).json()['full_verified_sprites']==[]


def test_core_archive_hash_validation_and_current_source_runtime_only(tmp_path):
    c, store, app = api(tmp_path)
    data=b'MZ'+bytes(500);sha=hashlib.sha256(data).hexdigest()
    assert c.post('/api/tas/cores/'+sha,content=data).status_code==200
    assert c.get('/api/tas/cores/'+sha).content==data
    assert c.post('/api/tas/cores/'+'a'*64,content=data).status_code==422
    assert c.get('/api/tas/cores/not-a-digest').status_code==422
    source=tas.fingerprint(Path(tas.__file__).parent/'native/tas_core.c')
    assert c.post('/api/tas/runtime/windows/'+source,content=data,headers={'x-gbox-sha256':sha}).status_code==200
    assert c.get('/api/tas/runtime/windows/'+source+'/manifest').json()['sha256']==sha
    assert c.get('/api/tas/runtime/windows/'+source+'/file').content==data
    assert c.post('/api/tas/runtime/windows/'+'b'*64,content=data,headers={'x-gbox-sha256':sha}).status_code==409


def test_sprite_pose_fit_keeps_feet_and_lz2_rejects_bad_data():
    from PIL import Image
    from gbox.tas_sprites import fit,lz2
    image=Image.new('RGBA',(10,20));image.putpixel((2,5),(255,0,0,255));image.putpixel((6,17),(0,0,255,255))
    output=fit(image,16,32)
    assert output.getchannel('A').getbbox()[3]==32
    assert lz2(b'\x02abc\x23Z\xff')==b'abcZZZZ'
    assert lz2(b'\x02abc\x83\x00\x00\xff')==b'abcabca'
    for data in (b'', b'\x81\xff\xff', b'\xe4\x02\xff'):
        with pytest.raises(ValueError):lz2(data)


def test_idle_dispatch_uses_only_verified_full_run_and_respects_resources_and_existing_games(tmp_path):
    import time
    worker={'id':'idlepc','name':'Idle PC','os':'windows','online':True,'tools':['tas_play'],'idle_seconds':600,
            'active_jobs':0,'resources':{'sampled_at':time.time(),'cpu_percent':20,'memory_percent':30,'memory_available_bytes':8*2**30}}
    submitted=[]
    def submit(req,**kw):
        submitted.append(req.model_dump());return {'id':'job','state':'queued'}
    c,store,app=api(tmp_path,workers=lambda:[worker],submit=submit)
    store.catalog_get=lambda gid:{'game_id':gid,'title':'Mario','platform':'nes'}
    path=tmp_path/'a.gbt';tape(path);assert upload(c,path).status_code==200
    rid='a'*32
    assert c.post('/api/tas/runs/'+rid+'/idle',json={'enabled':True,'sprite':'sonic'}).status_code==200
    app.state.tas_idle_tick();assert submitted==[]
    row=store.get('tas_run',rid);store.put('tas_run',rid,row|{'replay_receipts':[{'job_id':'old','verified':True,'sprite':'sonic','segment':''}]})
    worker['resources']['cpu_percent']=80
    app.state.tas_idle_tick();assert submitted==[]
    worker['resources']['cpu_percent']=20
    store.put('session','idlepc-human',{'session_id':'idlepc-human','state':'running','game_id':'another'})
    app.state.tas_idle_tick();assert submitted==[]
    store.put('session','idlepc-human',{'session_id':'idlepc-human','state':'ended'})
    app.state.tas_idle_tick()
    assert len(submitted)==1 and submitted[0]['agent_use'] and submitted[0]['low_priority']
    assert submitted[0]['require_worker']=='idlepc' and submitted[0]['input']['loop'] is True


def test_current_capture_status_is_explicit_and_does_not_expose_worker_paths(tmp_path):
    c,store,_=api(tmp_path)
    row=store.get('session','pc-human');store.put('session','pc-human',row|{'state':'running'})
    assert c.get('/api/tas/runs?session_id=pc-human').json()['capture']['state']=='unavailable'
    store.put('session','pc-human',row|{'state':'running','detail':{'tas_capture':{'id':'run','state':'recording','frame':900,'path':'private'}}})
    assert c.get('/api/tas/runs?session_id=pc-human').json()['capture']==dict(id='run',state='recording',frame=900)
