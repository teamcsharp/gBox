from types import SimpleNamespace
import time
import pytest
from gbox import hot_reload as H, tools as T, pso_campaign as P


@pytest.mark.parametrize('name',['pso_coop','pso_coop_geometry','pso_coop_nav','pso_coop_frontier','pso_coop_town'])
def test_only_per_run_coop_modules_are_reloadable(name):
    assert H.allowed('gbox.'+name)
    assert H.classify(['gbox/'+name+'.py'])['action']=='reload'


@pytest.mark.parametrize('name',['pso_campaign','pso_coop_mapping','pso_coop_native','pso_gc_live',
    'pso_coop_access','pso_coop_unlock','pso_coop_menu','pso_menu_observer','pso_run_review','tools','hot_reload'])
def test_native_authority_transport_and_shared_state_still_require_restart(name):
    assert not H.allowed('gbox.'+name)
    assert H.classify(['gbox/'+name+'.py'])['action']=='restart'


def run(**changes):
    value=dict(playbook_module='gbox.pso_campaign',mode='playbook',
        inp=T.AutoplayIn(session_id='pso-reload-test',op='start',campaign=P.COOP_CAMPAIGN,continuous=True),
        ctx=SimpleNamespace(job_id='original-job'),thread=SimpleNamespace(is_alive=lambda:True),
        driver=SimpleNamespace(stopped=False))
    value.update(changes)
    return value


def test_actual_campaign_wrapper_is_admitted_as_coop_core_only(monkeypatch):
    sid='pso-reload-test';value=run();ad=SimpleNamespace(coop_players=2)
    monkeypatch.setitem(T.AUTOPLAY,sid,value)
    monkeypatch.setitem(T.SESSIONS,sid,(ad,{'game_id':'owned-pso'}))
    monkeypatch.setattr(P,'matches',lambda adapter,game:adapter is ad and game['game_id']=='owned-pso')
    host=T._ReloadHost()
    assert host.playbook_of(value)=='gbox.pso_coop'
    assert host.playbook(sid)=='gbox.pso_coop'
    assert (sid,value) in host.bots()
    ad.coop_players=1
    assert host.playbook(sid) is None
    ad.coop_players=2
    monkeypatch.setattr(P,'matches',lambda *_:False)
    assert host.playbook(sid) is None


@pytest.mark.parametrize('change',[{'mode':'vision'}, {'playbook_module':'gbox.pso_fake'},
    {'inp':SimpleNamespace(campaign=P.CAMPAIGN)}, {'inp':None}])
def test_no_campaign_guess_or_single_player_admission(change):
    assert T._ReloadHost.playbook_of(run(**change)) is None


def test_restart_preserves_exact_session_input_job_and_native_owners(monkeypatch):
    sid='pso-reload-test';old=run();ad=SimpleNamespace(coop_players=2,proc=object(),
        sealed_pad_proof=object(),native_queue_lock=object(),access_journal=object())
    monkeypatch.setitem(T.SESSIONS,sid,(ad,{'game_id':'owned-pso'}))
    monkeypatch.setitem(T.AUTOPLAY,sid,old)
    calls=[]
    def start(inp,ctx):
        calls.append((inp,ctx,T.SESSIONS[sid][0]))
        monkeypatch.setitem(T.AUTOPLAY,sid,dict(old))
        return {'result':{'started':'pso campaign','mode':'playbook'}}
    monkeypatch.setattr(T,'autoplay',start)
    before=dict(vars(ad))
    result=T._ReloadHost().start(sid,old,time.time())
    assert result['restarted'] and result['job_id']=='original-job'
    assert calls==[(old['inp'],old['ctx'],ad)]
    assert vars(ad)==before


def test_operator_stop_wins_over_coop_restart(monkeypatch):
    sid='pso-reload-test';old=run();since=time.time()
    monkeypatch.setitem(T.SESSIONS,sid,(object(),{}))
    monkeypatch.setitem(T._AUTOPLAY_STOPS,sid,since+1)
    monkeypatch.setattr(T,'_telemetry_stopped',lambda _:None)
    monkeypatch.setattr(T,'autoplay',lambda *_:pytest.fail('Explicit Stop must not restart PSO'))
    result=T._ReloadHost().start(sid,old,since)
    assert not result['restarted'] and 'stopped' in result['reason']
