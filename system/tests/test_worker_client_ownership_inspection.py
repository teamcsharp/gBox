"""Desktop reload recognizes positively stale ownership without modifying it."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from gbox import config, worker_client_control as C, worker_results as W


@pytest.fixture
def owned(tmp_path,monkeypatch):
    source=tmp_path/'gbox.toml';source.write_text('')
    runtime=tmp_path/'runtime';runtime.mkdir()
    manifest=runtime/'gbox-running.json'
    monkeypatch.setattr(config,'load',lambda _:SimpleNamespace(runtime=runtime))
    return source,runtime,manifest


def test_all_proven_stale_records_are_idle_and_bytes_untouched(owned,monkeypatch):
    source,runtime,manifest=owned
    rows={'gone':{'pid':41},'reused':{'pid':42,'ts':1000},
          'linux_reused':{'pid':43,'linux_identity':{'boot_id':'old','start_ticks':10}}}
    manifest.write_text(json.dumps(rows,indent=2));before=manifest.read_bytes()
    calls=[]
    def absent(pid,**kwargs):
        calls.append((pid,kwargs));return False
    monkeypatch.setattr(W,'_pid_alive',absent)
    result=C.inspect_disk(source)
    assert result['reason'] is None and result['stale_ownership_records']==3
    assert manifest.read_bytes()==before
    assert calls==[(41,{'recorded_at':None,'recorded_identity':None}),
                   (42,{'recorded_at':1000,'recorded_identity':None}),
                   (43,{'recorded_at':None,'recorded_identity':rows['linux_reused']['linux_identity']})]
    assert list(runtime.iterdir())==[manifest]


@pytest.mark.parametrize('answer',[True,None,0,'unknown'])
def test_live_or_unknown_result_is_never_treated_as_absence(owned,monkeypatch,answer):
    source,_,manifest=owned
    manifest.write_text('{"live":{"pid":42,"ts":1000}}')
    monkeypatch.setattr(W,'_pid_alive',lambda *a,**kw:answer)
    assert C.inspect_disk(source)['reason']


@pytest.mark.parametrize('record',[{'pid':42},{'pid':42,'ts':None},{'pid':42,'ts':'bad'}])
def test_legacy_unknown_owner_remains_protected(owned,monkeypatch,record):
    source,_,manifest=owned;manifest.write_text(json.dumps({'legacy':record}))
    monkeypatch.setattr(W,'_pid_alive',lambda *a,**kw:True)
    assert C.inspect_disk(source)['reason']


@pytest.mark.parametrize('records',[None,[],True,{'bad':None},{'bad':[]},{'':{'pid':42}}])
def test_malformed_manifest_is_not_idle(owned,monkeypatch,records):
    source,_,manifest=owned;manifest.write_text(json.dumps(records))
    monkeypatch.setattr(W,'_pid_alive',lambda *a,**kw:pytest.fail('malformed record must not be queried'))
    assert C.inspect_disk(source)['reason']


@pytest.mark.parametrize('record',[{}, {'pid':0},{'pid':True},{'pid':'42'},{'pid':-1}])
def test_invalid_pid_retains_protection_via_inspection_error(owned,record):
    source,_,manifest=owned;manifest.write_text(json.dumps({'invalid':record}))
    with pytest.raises(RuntimeError,match='Invalid owned emulator PID'):
        C.inspect_disk(source)


def test_permission_query_failure_does_not_release_ownership(owned,monkeypatch):
    source,_,manifest=owned;manifest.write_text('{"owner":{"pid":42}}')
    def denied(*a,**kw):raise PermissionError('fixture')
    monkeypatch.setattr(W,'_pid_alive',denied)
    with pytest.raises(PermissionError):C.inspect_disk(source)


@pytest.mark.parametrize('kind',['new_owner','removed','same_parsed_different_bytes'])
def test_digest_rejects_manifest_changes_during_process_query(owned,monkeypatch,kind):
    source,_,manifest=owned;manifest.write_text('{"old":{"pid":42,"ts":1000}}')
    def changing(*a,**kw):
        if kind=='removed':manifest.unlink()
        elif kind=='new_owner':manifest.write_text('{"new":{"pid":44,"ts":2000}}')
        else:manifest.write_text('{ "old": { "pid":42, "ts":1000 } }')
        return False
    monkeypatch.setattr(W,'_pid_alive',changing)
    assert 'changed during inspection' in C.inspect_disk(source)['reason']


@pytest.mark.parametrize('initial',[None,'{}'])
def test_manifest_created_during_result_scan_is_not_idle(owned,monkeypatch,initial):
    source,runtime,manifest=owned
    if initial is not None:manifest.write_text(initial)
    (runtime/'worker-results').mkdir()
    scan=C.os.scandir
    def changed(path):
        manifest.write_text('{"new":{"pid":44,"ts":2000}}')
        return scan(path)
    monkeypatch.setattr(C.os,'scandir',changed)
    assert 'changed during inspection' in C.inspect_disk(source)['reason']


@pytest.mark.parametrize('where',['result.json','rejected/result.json'])
def test_stale_game_records_do_not_bypass_pending_result_guard(owned,monkeypatch,where):
    source,runtime,manifest=owned;manifest.write_text('{"old":{"pid":42}}')
    result=runtime/'worker-results'/'namespace'/where
    result.parent.mkdir(parents=True);result.write_text('{}')
    monkeypatch.setattr(W,'_pid_alive',lambda *a,**kw:False)
    assert 'results still need reconciliation' in C.inspect_disk(source)['reason']


def test_native_windows_reuse_proof_is_used_by_disk_check(owned,monkeypatch):
    import ctypes
    from ctypes import wintypes
    source,_,manifest=owned;manifest.write_text('{"old":{"pid":42,"ts":1000}}')
    def opened(*a):return 1
    def exit_code(handle,code):code._obj.value=259;return True
    def times(handle,created,*a):
        tick=int((2000+11_644_473_600)*10_000_000)
        created._obj.dwLowDateTime=tick&0xffffffff;created._obj.dwHighDateTime=tick>>32
        return True
    def close(handle):return True
    api=SimpleNamespace(OpenProcess=opened,GetExitCodeProcess=exit_code,GetProcessTimes=times,CloseHandle=close)
    monkeypatch.setattr(W,'os',SimpleNamespace(name='nt'))
    monkeypatch.setattr(ctypes,'WinDLL',lambda *a,**kw:api,raising=False)
    before=hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert C.inspect_disk(source)['reason'] is None
    assert hashlib.sha256(manifest.read_bytes()).hexdigest()==before
