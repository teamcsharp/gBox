from types import SimpleNamespace
import pytest
from gbox import tools as T, autoplay, pso_campaign as P, pad_takeover
from gbox.mercs import warm_boot


@pytest.fixture
def setup(monkeypatch):
    sid='focus-test-pso'
    ad=SimpleNamespace(_pso_coop_new_card={'isolated':True})
    game={'game_id':'436e0bb84d5337d1','platform':'gamecube'}
    monkeypatch.setitem(T.SESSIONS,sid,(ad,game))
    monkeypatch.setattr(T,'AUTOPLAY',{})
    monkeypatch.setattr(T,'_session_game_id',lambda *_:game['game_id'])
    monkeypatch.setattr(autoplay,'Driver',lambda *_a,**_k:SimpleNamespace())
    monkeypatch.setattr(warm_boot,'autoplay_control',lambda *_:False)
    order=[]
    monkeypatch.setattr(P,'preflight',lambda *_:order.append('preflight') or {})
    monkeypatch.setattr(T,'_front',lambda *_:order.append('focus'))
    monkeypatch.setattr(T,'_demo_front',lambda *_:order.append('idle_focus'))
    monkeypatch.setattr(T,'_start_playbook',lambda *_:order.append('start') or {})
    ctx=SimpleNamespace(server='http://example.invalid',headers={'authorization':'Bearer test'},agent_use=True)
    return sid,ad,order,ctx


@pytest.mark.parametrize('owned,demo,screensaver,human,expected',[
    (True,True,False,False,['preflight','focus','start']),
    (True,False,False,False,['preflight','focus','start']),
    (False,True,False,False,['preflight','idle_focus','start']),
    (False,False,False,False,['preflight','start']),
    (False,True,True,False,['preflight','focus','start']),
    (True,True,False,True,['preflight','start']),
    (False,True,True,True,['preflight','start'])])
def test_pso_start_focus_respects_dedicated_pc_and_operator_lease(setup,monkeypatch,owned,demo,screensaver,human,expected):
    sid,ad,order,ctx=setup
    monkeypatch.setattr(pad_takeover,'active',lambda exact_sid:human if exact_sid==sid else pytest.fail('Wrong session lease'))
    T._autoplay(T.AutoplayIn(session_id=sid,op='start',mode='playbook',campaign=P.COOP_CAMPAIGN,
        demo=demo,owns_keyboard=owned,screensaver=screensaver),ctx)
    assert order==expected


def test_failed_preflight_never_raises_window_or_starts_bot(setup,monkeypatch):
    sid,ad,order,ctx=setup
    def fail(*_):raise ValueError('Unsupported exact build')
    monkeypatch.setattr(P,'preflight',fail)
    with pytest.raises(ValueError,match='exact build'):
        T._autoplay(T.AutoplayIn(session_id=sid,op='start',campaign=P.COOP_CAMPAIGN,owns_keyboard=True),ctx)
    assert order==[]


def test_unisolated_coop_never_raises_window(setup):
    sid,ad,order,ctx=setup;ad._pso_coop_new_card={}
    with pytest.raises(ValueError,match='pso_coop=true'):
        T._autoplay(T.AutoplayIn(session_id=sid,op='start',campaign=P.COOP_CAMPAIGN,owns_keyboard=True),ctx)
    assert order==[]
