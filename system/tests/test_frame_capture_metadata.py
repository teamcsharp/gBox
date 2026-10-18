"""Coverage evidence must belong to the exact PNG and emulator that produced it."""
import ctypes
from ctypes import wintypes
import hashlib
import io
import os
import time
from types import SimpleNamespace

from PIL import Image, ImageGrab
import pytest

from gbox import adapters, tools


def png(color='red'):
    stream = io.BytesIO()
    Image.new('RGB', (16, 12), color).save(stream, format='PNG')
    return stream.getvalue()


def session(monkeypatch, data, metadata, host='windows', pid=123):
    ad = SimpleNamespace(proc=SimpleNamespace(pid=pid), get_frame=lambda: data)
    monkeypatch.setitem(tools.SESSIONS, 'capture-metadata', (ad, {'game_id': 'owned-game'}))
    monkeypatch.setattr(tools, 'HOST_OS', host)
    monkeypatch.setattr(tools, 'mean_luma', lambda _: 42.0)
    monkeypatch.setattr(adapters, '_last_grab', metadata)
    artifacts = []
    ctx = SimpleNamespace(artifact=lambda *args, **kwargs: artifacts.append((args, kwargs)))
    return ctx, artifacts


@pytest.mark.parametrize('covered, source', [(0, 'chromium-gpu-surface'), (2, 'desktop-compositor')])
def test_exact_capture_metadata_survives_output_schema_and_artifact_provenance(monkeypatch, covered, source):
    data = png()
    metadata = {'pid':123, 'sha256':hashlib.sha256(data).hexdigest(), 'covered':covered, 'source':source,
                'covered_titles':['Unrelated application title'], 'frame_age_s':0.2}
    ctx, artifacts = session(monkeypatch, data, metadata)
    result = tools.FrameOut.model_validate(tools.get_frame(tools.FrameIn(session_id='capture-metadata'),ctx)).model_dump()
    assert result['covered'] == covered and result['capture_source'] == source
    assert result['sha256'] == metadata['sha256'] and (result['width'],result['height']) == (16,12)
    assert artifacts[0][0][1] == data
    assert artifacts[0][1] == {'session':'capture-metadata','game':'owned-game','covered':covered,'capture_source':source,
        'capture_occlusion':'unknown','gameplay_verified':False}
    assert 'covered_titles' not in result and 'pid' not in result and 'frame_age_s' not in result
    assert tools._png_validate(tools.FrameOut.model_validate(result), {'frame.png':data}) == []


@pytest.mark.parametrize('mismatch', ['pid', 'png', 'empty', 'missing_proc'])
def test_stale_or_other_process_capture_metadata_is_not_forwarded(monkeypatch, mismatch):
    data = png()
    metadata = {'pid':123,'sha256':hashlib.sha256(data).hexdigest(),'covered':9,'source':'desktop-compositor'}
    if mismatch == 'pid':metadata['pid'] = 999
    if mismatch == 'png':metadata['sha256'] = hashlib.sha256(png('blue')).hexdigest()
    if mismatch == 'empty':metadata = {}
    ctx, artifacts = session(monkeypatch,data,metadata,pid=None if mismatch == 'missing_proc' else 123)
    result = tools.FrameOut.model_validate(tools.get_frame(tools.FrameIn(session_id='capture-metadata'),ctx)).model_dump()
    assert result['covered'] == 0 and result['capture_source'] is None
    assert artifacts[0][1] == {'session':'capture-metadata','game':'owned-game','covered':0,
        'capture_occlusion':'unknown','gameplay_verified':False}


@pytest.mark.parametrize('invalid', [-1,10,True,'9',None])
def test_invalid_coverage_counts_are_not_attached(monkeypatch, invalid):
    data = png()
    ctx, artifacts = session(monkeypatch,data,{'pid':123,'sha256':hashlib.sha256(data).hexdigest(),
        'covered':invalid,'source':'desktop-compositor'})
    result = tools.FrameOut.model_validate(tools.get_frame(tools.FrameIn(session_id='capture-metadata'),ctx))
    assert result.covered == 0 and result.capture_source is None
    assert 'capture_source' not in artifacts[0][1]


def test_linux_session_does_not_consume_windows_capture_metadata(monkeypatch):
    ctx, artifacts = session(monkeypatch,png(),{},host='linux')
    monkeypatch.setattr(adapters,'win_grab_state',lambda:pytest.fail('Linux capture must not read Windows global metadata'))
    result = tools.FrameOut.model_validate(tools.get_frame(tools.FrameIn(session_id='capture-metadata'),ctx))
    assert result.covered == 0 and result.capture_source is None
    assert artifacts[0][1]['covered'] == 0


def test_desktop_capture_does_not_reuse_session_metadata(monkeypatch):
    ctx, artifacts = session(monkeypatch,png(),{'pid':123,'covered':9})
    monkeypatch.setattr(adapters,'grab_png',lambda display,region:png('blue'))
    monkeypatch.setattr(adapters,'win_grab_state',lambda:pytest.fail('Desktop capture must not read session metadata'))
    result = tools.FrameOut.model_validate(tools.get_frame(tools.FrameIn(),ctx))
    assert result.covered == 0 and result.capture_source is None
    assert artifacts[0][1] == {'covered':0,'capture_occlusion':'unknown','gameplay_verified':False}


def window(monkeypatch, tmp_path, foreign=2, fail=False):
    monkeypatch.setenv('GBOX_GAME_FRAME_DIR',str(tmp_path))
    monkeypatch.setattr(adapters,'_last_grab',{'pid':999,'covered':9,'sha256':'old-digest'})
    seen = []
    def owner_window(point):
        seen.append((point.x,point.y))
        return 2 if len(seen) <= foreign else 1
    owner_window.argtypes = owner_window.restype = None
    def rect(hwnd,address):
        value = ctypes.cast(address,ctypes.POINTER(wintypes.RECT)).contents
        value.left,value.top,value.right,value.bottom = 0,0,400,300
        return 1
    def pid(hwnd,address):
        ctypes.cast(address,ctypes.POINTER(wintypes.DWORD)).contents.value = 999 if hwnd == 2 else 123
        return 1
    user = SimpleNamespace(GetWindowRect=rect,WindowFromPoint=owner_window,GetWindowThreadProcessId=pid)
    monkeypatch.setattr(ctypes,'windll',SimpleNamespace(user32=user),raising=False)
    monkeypatch.setattr(adapters,'_pid_window',lambda pid:1)
    def grab(*args,**kwargs):
        if fail:raise OSError('capture failed')
        return Image.new('RGB',(16,12),'red')
    monkeypatch.setattr(ImageGrab,'grab',grab)
    monkeypatch.setattr(adapters,'_win_title',lambda _:pytest.fail('Other application titles are not needed for coverage'))
    return seen


def test_window_capture_records_exact_returned_png_identity(monkeypatch,tmp_path):
    seen = window(monkeypatch,tmp_path)
    data = adapters.win_grab(123)
    state = adapters.win_grab_state()
    assert len(seen) == 9
    assert state == {'pid':123,'covered':2,'source':'desktop-compositor','frame_age_s':0,
                     'sha256':hashlib.sha256(data).hexdigest()}


def test_gpu_surface_records_its_own_digest_and_pid(monkeypatch,tmp_path):
    monkeypatch.setenv('GBOX_GAME_FRAME_DIR',str(tmp_path))
    monkeypatch.setattr(adapters,'_last_grab',{'pid':999,'covered':9,'sha256':'old'})
    monkeypatch.setattr(adapters,'_pid_window',lambda _:pytest.fail('A fresh GPU surface must not inspect desktop windows'))
    data = png('green');(tmp_path/'123.png').write_bytes(data)
    returned = adapters.win_grab(123)
    state = adapters.win_grab_state()
    assert returned == data and state['sha256'] == hashlib.sha256(returned).hexdigest()
    assert state['pid'] == 123 and state['covered'] == 0 and state['source'] == 'chromium-gpu-surface'
    assert 0 <= state['frame_age_s'] < 5 and 'covered_titles' not in state


@pytest.mark.parametrize('failure', ['no_window','read_pixels','covered_window','invalid_cached_png','stale_cached_png'])
def test_failed_capture_clears_previous_success_metadata(monkeypatch,tmp_path,failure):
    window(monkeypatch,tmp_path,foreign=9 if failure == 'covered_window' else 0,fail=failure == 'read_pixels')
    if failure in ('no_window','invalid_cached_png','stale_cached_png'):
        monkeypatch.setattr(adapters,'_pid_window',lambda _:0)
    if failure == 'invalid_cached_png':(tmp_path/'123.png').write_bytes(b'not-a-png')
    if failure == 'stale_cached_png':
        target = tmp_path/'123.png';target.write_bytes(png());stamp=time.time()-60;os.utime(target,(stamp,stamp))
    with pytest.raises((RuntimeError,OSError)):
        adapters.win_grab(123)
    assert adapters.win_grab_state() == {}


def test_real_adapter_metadata_reaches_covered_frame_consumers(monkeypatch,tmp_path):
    window(monkeypatch,tmp_path,foreign=2)
    data = adapters.win_grab(123)
    ctx, artifacts = session(monkeypatch,data,adapters.win_grab_state())
    output = tools.FrameOut.model_validate(tools.get_frame(tools.FrameIn(session_id='capture-metadata'),ctx)).model_dump()
    assert output['covered'] == artifacts[0][1]['covered'] == 2
    assert output['capture_source'] == 'desktop-compositor'


@pytest.mark.parametrize("mismatch", ["pid", "png", "unknown-status"])
def test_adapter_metadata_cannot_smuggle_another_frame_or_claim_gameplay(monkeypatch,mismatch):
    data=png();ctx,arts=session(monkeypatch,data,{})
    ad=tools.SESSIONS['capture-metadata'][0]
    meta={'pid':123,'sha256':hashlib.sha256(data).hexdigest(),'covered':0,
          'source':'cxbx-print-window','occlusion':'sampled-clear','gameplay_verified':True}
    if mismatch=='pid':meta['pid']=999
    if mismatch=='png':meta['sha256']='bad'
    if mismatch=='unknown-status':meta['occlusion']='uncovered'
    ad.frame_capture_state=lambda:meta
    result=tools.FrameOut.model_validate(tools.get_frame(tools.FrameIn(session_id='capture-metadata'),ctx))
    assert result.capture_occlusion=='unknown' and result.gameplay_verified is False
    if mismatch!='unknown-status':assert result.capture_source is None
