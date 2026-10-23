"""The idle demonstration poll must not fetch and decode completed job history beside a live game."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from gbox import gameplay_demo
from gbox.store import Store


@pytest.mark.parametrize('state',['queued','running','done'])
def test_idle_demo_poll_uses_only_live_jobs_and_preserves_admission(tmp_path,monkeypatch,state):
    store=Store(tmp_path)
    store.put('job','large-old',{'tool':'gameplay_demo','state':'done','output':{'historical':'x'*200000}})
    store.put('job','current',{'tool':'gameplay_demo','state':state})
    original=store.all
    def all_rows(kind,**kwargs):
        if kind=='job':pytest.fail('the complete job archive was decoded during an idle poll')
        return original(kind,**kwargs)
    monkeypatch.setattr(store,'all',all_rows)
    calls=[]
    archive=SimpleNamespace(runs=lambda **kwargs:calls.append('archive') or [])
    app=FastAPI()
    gameplay_demo.install(app,store,SimpleNamespace(gameplay_memory_enabled=True),lambda:None,
                          lambda *args,**kwargs:pytest.fail('no demonstration launch is authorized here'),lambda:[],archive)
    app.state.gameplay_demo_idle_tick()
    assert calls==(['archive'] if state=='done' else [])
