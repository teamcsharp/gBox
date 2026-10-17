import json
import os
from pathlib import Path
import sys
import threading

import psutil
import pytest
from scripts.browser_lifecycle import Registry, browser_args, clean_profile, settings


def test_sandbox_and_local_endpoint_are_the_default(monkeypatch,tmp_path):
    monkeypatch.delenv('GBOX_BROWSER_NO_SANDBOX',raising=False)
    args=browser_args(sys.executable,tmp_path)
    assert '--no-sandbox' not in args
    assert '--remote-debugging-address=127.0.0.1' in args
    assert '--remote-debugging-port=0' in args
    monkeypatch.setenv('GBOX_BROWSER_NO_SANDBOX','1')
    monkeypatch.delenv('GBOX_BROWSER_NO_SANDBOX_REASON',raising=False)
    with pytest.raises(ValueError):browser_args(sys.executable,tmp_path)
    monkeypatch.setenv('GBOX_BROWSER_NO_SANDBOX_REASON','Explicit isolated Linux container')
    if os.name=='nt':
        with pytest.raises(ValueError):browser_args(sys.executable,tmp_path)
    else:assert '--no-sandbox' in browser_args(sys.executable,tmp_path)


def test_queue_is_bounded_and_memory_budget_applies(tmp_path):
    reg=Registry(tmp_path/'state');me=psutil.Process()
    reg.update({'id':'busy','state':'running','broker_pid':me.pid,'broker_created':me.create_time(),'rss':100*2**20})
    limits={'max_queue':1,'max_sessions':2,'budget_mb':10,'queue_s':.1}
    with pytest.raises(TimeoutError):reg.acquire(limits,threading.Event())
    assert sum(r['state']=='cancelled' for r in reg.rows())==1
    reg.update({'id':'queued','state':'queued','queued_at':0,'broker_pid':me.pid,'broker_created':me.create_time()})
    with pytest.raises(RuntimeError,match='queue is full'):reg.acquire(limits,threading.Event())
    reg.db.close()


def test_profile_cleanup_requires_owned_path_marker_and_dead_processes(tmp_path):
    reg=Registry(tmp_path/'state');outside=tmp_path/'valuable';outside.mkdir();(outside/'keep').write_text('keep')
    with pytest.raises(ValueError):clean_profile(reg,{'id':'valuable','profile':str(outside)})
    assert (outside/'keep').read_text()=='keep'
    profile=reg.root/'profiles'/'owned';profile.mkdir();(profile/'gbox-owner.json').write_text(json.dumps({'id':'owned'}))
    me=psutil.Process();row={'id':'owned','profile':str(profile),'members':[{'pid':me.pid,'created':me.create_time()}]}
    with pytest.raises(RuntimeError):clean_profile(reg,row)
    row['members']=[];clean_profile(reg,row);assert not profile.exists();reg.db.close()


def test_recover_dead_supervisor_profile_before_a_new_lease(tmp_path):
    reg=Registry(tmp_path/'state');profile=reg.root/'profiles'/'dead';profile.mkdir()
    (profile/'gbox-owner.json').write_text(json.dumps({'id':'dead'}))
    reg.update({'id':'dead','state':'running','broker_pid':999999999,'broker_created':1,'profile':str(profile),'members':[]})
    row=reg.acquire({'max_queue':2,'max_sessions':1,'budget_mb':512,'queue_s':1},threading.Event())
    assert row['state']=='starting' and not profile.exists()
    assert next(r for r in reg.rows() if r['id']=='dead')['recovered']
    reg.update(row,state='closed');reg.db.close()
