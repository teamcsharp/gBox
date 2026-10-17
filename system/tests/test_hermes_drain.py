import datetime as dt
import importlib.util
import json
from pathlib import Path

import pytest

from gbox import hermes_drain as D, hermes_activation as A

OWNER = 'gbox-deploy:abc123:nonce'


def stamp(value):
    return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat()


@pytest.fixture
def evidence(tmp_path):
    home, proc = tmp_path/'hermes', tmp_path/'proc'
    (home/'cron').mkdir(parents=True)
    (proc/'sys/kernel/random').mkdir(parents=True)
    (proc/'sys/kernel/random/boot_id').write_text('test-boot')
    for pid, start in ((1, 12), (42, 100)):
        (proc/str(pid)).mkdir()
        (proc/str(pid)/'stat').write_text(f'{pid} (name with spaces) S '+'0 '*18+str(start))
    files = {
        '.drain_request.json': {'action':'drain','principal':OWNER,'epoch':'test-boot:12','requested_at':stamp(990)},
        'gateway.pid': {'pid':42,'start_time':100,'kind':'hermes-gateway','hermes_home':str(home)},
        'gateway_state.json': {'pid':42,'start_time':100,'kind':'hermes-gateway','gateway_state':'draining',
                               'restart_requested':False,'exit_reason':None,'served_profiles':[],
                               'updated_at':stamp(999),'active_agents':0},
    }
    for name,data in files.items(): (home/name).write_text(json.dumps(data))
    (home/'cron/ticker_heartbeat').write_text('999 42')
    return home, proc, files


def test_exact_live_ack_is_read_only_and_not_an_idle_count(evidence):
    home,proc,_=evidence
    before={p:p.read_bytes()for p in home.rglob('*')if p.is_file()}
    result=D.acknowledgment(home,OWNER,now=1000,proc=proc)
    assert result['acknowledged'] and result['gateway_pid']==42
    assert 'active work' in result['boundary']
    assert before=={p:p.read_bytes()for p in home.rglob('*')if p.is_file()}


@pytest.mark.parametrize('file,change',[
    ('.drain_request.json',{'principal':'operator'}),('.drain_request.json',{'epoch':'old-boot:12'}),
    ('.drain_request.json',{'requested_at':stamp(-2600)}),('.drain_request.json',{'requested_at':stamp(1001)}),
    ('gateway_state.json',{'gateway_state':'running'}),('gateway_state.json',{'updated_at':stamp(980)}),
    ('gateway_state.json',{'pid':43}),('gateway_state.json',{'start_time':101}),
    ('gateway_state.json',{'restart_requested':True}),('gateway_state.json',{'served_profiles':['unknown-profile']}),
    ('gateway.pid',{'hermes_home':'/different/home'}),('gateway.pid',{'pid':True}),
])
def test_stale_wrong_or_unacknowledged_marker_cannot_hold_schedules(evidence,file,change):
    home,proc,files=evidence
    (home/file).write_text(json.dumps(files[file]|change))
    assert not D.acknowledgment(home,OWNER,now=1000,proc=proc)['acknowledged']


@pytest.mark.parametrize('heartbeat',['999 43','800 42','nan 42','1001 42','broken'])
def test_ticker_must_be_fresh_and_owned_by_draining_gateway(evidence,heartbeat):
    home,proc,_=evidence;(home/'cron/ticker_heartbeat').write_text(heartbeat)
    assert not D.acknowledgment(home,OWNER,now=1000,proc=proc)['acknowledged']


def test_expired_reused_pid_and_missing_evidence_fail_closed(evidence):
    home,proc,_=evidence
    (proc/'42/stat').write_text('42 (reused) S '+'0 '*18+'200')
    assert not D.acknowledgment(home,OWNER,now=1000,proc=proc)['acknowledged']
    (home/'.drain_request.json').unlink()
    assert not D.acknowledgment(home,OWNER,now=1000,proc=proc)['acknowledged']


def test_ack_keeps_due_inventory_visible_but_never_ignores_active_work(monkeypatch,tmp_path):
    due=[{'id':'every-minute','no_agent':True}]
    monkeypatch.setattr(A,'read_cron_snapshot',lambda *a,**k:{'hermes':[],'imminent_or_overdue':due})
    monkeypatch.setattr(A,'read_active_jobs',lambda *a:[])
    monkeypatch.setattr(D,'acknowledgment',lambda *a,**k:{'acknowledged':True})
    def api(path): return [{'id':'spark','os':'linux'}] if path=='/api/workers' else []
    result=A.activation_snapshot(tmp_path,api,home=tmp_path,drain_owner=OWNER)
    assert result['reason']=='' and result['cron']['imminent_or_overdue']==due
    assert result['cron']['held_by_external_drain']==due
    assert A.activation_snapshot(tmp_path,api,home=tmp_path)['reason']
    monkeypatch.setattr(A,'read_active_jobs',lambda *a:[{'state':'running'}])
    assert 'worker jobs' in A.activation_snapshot(tmp_path,api,home=tmp_path,drain_owner=OWNER)['reason']
    monkeypatch.setattr(A,'read_active_jobs',lambda *a:[])
    monkeypatch.setattr(A,'read_cron_snapshot',lambda *a,**k:{'hermes':[{'id':'run','state':'running'}],'imminent_or_overdue':due})
    assert 'Hermes execution' in A.activation_snapshot(tmp_path,api,home=tmp_path,drain_owner=OWNER)['reason']


def test_requested_owner_must_remain_acknowledged_even_without_imminent_jobs(monkeypatch,tmp_path):
    monkeypatch.setattr(A,'read_cron_snapshot',lambda *a,**k:{'hermes':[],'imminent_or_overdue':[]})
    monkeypatch.setattr(A,'read_active_jobs',lambda *a:[])
    monkeypatch.setattr(D,'acknowledgment',lambda *a,**k:{'acknowledged':False})
    assert 'acknowledgment' in A.activation_snapshot(tmp_path,lambda p:[],home=tmp_path,drain_owner=OWNER)['reason']


@pytest.fixture
def control():
    path=Path(__file__).resolve().parents[1]/'scripts/hermes_drain_control.py'
    spec=importlib.util.spec_from_file_location('drain_control_script',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class API:
    DRAIN_REQUEST_MAX_AGE_SECONDS=3600
    def __init__(self): self.marker=None;self.clears=0;self.suppress_notification=None
    def read_drain_request(self,**kw):return self.marker
    def write_drain_request(self,principal,**kw):
        self.suppress_notification=kw.get('suppress_notification')
        self.marker={'action':'drain','principal':principal,'requested_at':stamp(990),'epoch':'boot'}
        return self.marker
    def clear_drain_request(self,**kw):self.marker=None;self.clears+=1;return True


def test_supported_begin_and_release_only_exact_saved_marker(control,tmp_path):
    api=API();receipt=tmp_path/'receipt.json'
    control.begin(api,tmp_path,OWNER,receipt)
    assert api.suppress_notification is True
    assert control.release(api,tmp_path,OWNER,receipt)['released'] and api.clears==1
    assert control.release(api,tmp_path,OWNER,receipt)['already_absent'] and api.clears==1


def test_existing_or_changed_operator_marker_is_preserved(control,tmp_path):
    api=API();receipt=tmp_path/'receipt.json';api.marker={'principal':'operator'}
    with pytest.raises(ValueError,match='existing'):control.begin(api,tmp_path,OWNER,receipt)
    assert not receipt.exists()
    api.marker=None;control.begin(api,tmp_path,OWNER,receipt)
    api.marker=api.marker|{'requested_at':stamp(1000)}
    with pytest.raises(ValueError,match='changed'):control.release(api,tmp_path,OWNER,receipt)
    assert api.clears==0
