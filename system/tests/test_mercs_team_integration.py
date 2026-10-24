"""Integration fences: human P1 survives co-op, F3 and observation transitions."""
from copy import deepcopy
import sys
from types import SimpleNamespace

import pytest

from gbox import mercs_bot as MB, padstate, tools
from gbox.mercs import driver as driver_module
from gbox.mercs import session_runtime as SR, teamplay as T
from gbox.mercs.training import participant

SID='owned-session'
GAME={'game_id': T.RE5, 'platform': 'ps3'}


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    T._EVIDENCE.clear()
    monkeypatch.setattr(SR, 're5_assistance', lambda _: {'classification': 'mod_assisted', 'verified': False,
        'effects': ['existing_training_aids'], 'reason': 'Original gameplay settings are not verified.'})
    yield
    T._EVIDENCE.clear()


def fixture_runtime(tmp_path, monkeypatch, role='solo_p1', *, p2=True):
    sent=[]
    class Adapter:
        name='rpcs3'
        config=SimpleNamespace(data_dir=tmp_path)
        proc=SimpleNamespace(poll=lambda:None)
        supported={'send_input'}
        def send_input(self, rows):
            sent.append((1, deepcopy(rows)))
        def send_input_player(self, rows, *, player):
            assert player==2
            sent.append((player,deepcopy(rows)))
    adapter=Adapter()
    rows=[participant({'ptr':0x30300000,'pos':[0,0,0],'hp':100},1,'unknown',source='native_p1'),
          participant({'ptr':0x30310000,'pos':[1,0,0],'hp':100},2,'unknown',source='native_p2')]
    class Native:
        def readiness(self, memory):
            return {'p2_verified':p2,'controller2_verified':p2,'human_observer_verified':True,
                    'active_players':deepcopy(rows)}
        def participants(self, memory, snap):
            return deepcopy(rows)
    native=Native()
    store=T.TeamStore(tmp_path)
    store.configure(SID, {'role':role}, game_id=T.RE5)
    runtime=SR.SessionRuntime(adapter,SID,T.RE5,'BLUS30491',adapter.send_input,{},clock=lambda:1.)
    adapter._mercs_bot_runtime=runtime
    monkeypatch.setattr(tools,'SESSIONS',{SID:(adapter,GAME)})
    memory=SimpleNamespace(adapter=adapter)
    snap={'player':{'ptr':0x30300000,'pos':[0,0,0],'hp':100}}
    runtime.poll(memory,native,snap)
    return SimpleNamespace(ad=adapter,store=store,runtime=runtime,memory=memory,native=native,snap=snap,sent=sent)


def test_role_transition_releases_only_owned_p1_keys_before_human_trace(tmp_path,monkeypatch):
    f=fixture_runtime(tmp_path,monkeypatch)
    f.runtime.send([{'key':'left','down':True}])
    f.store.configure(SID,{'role':'observe_human'},game_id=T.RE5)
    status=f.runtime.poll(f.memory,f.native,f.snap)
    assert status['control_player'] is None
    assert f.sent==[(1,[{'key':'left','down':True,'player':1}]),(1,[{'key':'left','down':False,'player':1}])]
    assert f.snap['players'][0]['control']=='human'
    f.runtime.send([{'key':'circle','down':True},{'key':'human_held_key','down':False}])
    assert len(f.sent)==2
    assert f.runtime.held=={1:set(),2:set()}


def test_player2_f3_stop_releases_only_the_bots_p2_keys_and_keeps_game(tmp_path,monkeypatch):
    f=fixture_runtime(tmp_path,monkeypatch,role='teammate_p2')
    f.runtime.send([{'key':'lup','down':True},{'key':'r','down':True}])
    d=SimpleNamespace(stopped=False)
    monkeypatch.setattr(tools,'AUTOPLAY',{SID:{'driver':d,'mission':'teammate'}})
    result=tools.autoplay(tools.AutoplayIn(session_id=SID,op='stop'),SimpleNamespace())['result']
    assert result['stopped'] is True and d.stopped
    assert f.ad.proc.poll() is None
    assert all(port==2 for port,_ in f.sent)
    assert f.sent[-1][1]==[{'key':'lup','down':False,'player':2},{'key':'r','down':False,'player':2}]
    assert f.runtime.held=={1:set(),2:set()}


def test_pending_p2_and_foreign_port_events_never_fall_back_to_human_p1(tmp_path,monkeypatch):
    f=fixture_runtime(tmp_path,monkeypatch,role='teammate_p2',p2=False)
    f.runtime.send([{'key':'r','down':True},{'key':'left','down':True,'player':1}, {'key':'square','down':False}])
    tools._release_all(SID)
    assert not f.sent


def test_native_p1_presence_alone_does_not_certify_human_control_between_frames(tmp_path,monkeypatch):
    f=fixture_runtime(tmp_path,monkeypatch)
    f.runtime.last_probe=-float('inf')
    status=f.runtime.poll(f.memory,f.native)
    assert status['runtime']['human_observer_verified'] is False
    f.store.configure(SID,{'role':'observe_human'},game_id=T.RE5)
    status=f.runtime.poll(f.memory,f.native,f.snap)
    assert status['runtime']['human_observer_verified'] is True
    assert f.runtime.held[1]==set()


def test_old_bot_save_after_human_role_transition_does_not_revert_animation_ram(tmp_path,monkeypatch):
    from gbox import re5_mods_tool as mods
    from gbox.mercs.titles import re5_ps3 as R
    bot=R.Bot(learn_dir=tmp_path)
    bot.m=SimpleNamespace(adapter=object(),mercs_no_modifications=True)
    monkeypatch.setattr(mods,'maintain_fire_animation',lambda *a,**kw:pytest.fail('Read-only transition must retain current fire animation settings'))
    monkeypatch.setattr(mods,'maintain_item_animation',lambda *a,**kw:pytest.fail('Read-only transition must retain current item animation settings'))
    monkeypatch.setattr(R,'save_crossings',lambda:None)
    bot.save()


@pytest.mark.parametrize('role',['teammate_p2','observe_human'])
def test_human_p1_takeover_notifications_do_not_stop_teammate_or_observation(tmp_path,monkeypatch,role):
    f=fixture_runtime(tmp_path,monkeypatch,role=role)
    d=SimpleNamespace(stopped=False,screensaver=None)
    done=[False]
    run={'thread':SimpleNamespace(ident=1,is_alive=lambda:not done[0])}
    class ImmediateThread:
        def __init__(self,*,target,daemon): self.target=target
        def start(self): self.target()
    monkeypatch.setattr(tools.threading,'Thread',ImmediateThread)
    monkeypatch.setattr(padstate,'touched_after',lambda *_:True)
    monkeypatch.setattr(tools.time,'sleep',lambda _:done.__setitem__(0,True))
    tools._takeover(run,d,SID,0)
    assert not d.stopped and not run.get('took_over') and not f.sent


def outer_play(tmp_path,monkeypatch,role,where):
    f=fixture_runtime(tmp_path,monkeypatch,role=role,p2=False)
    name='gbox.tests_team_menus'
    monkeypatch.setitem(sys.modules,name,SimpleNamespace(screen=lambda m:{'where':where}))
    prof={'map_id':'BLUS30491','menus':name,'package':[['mod',True]],'early_ops':['mod'],
          'round_ops':[['mod',True]],'playing_ops':[['mod',True]]}
    monkeypatch.setattr(MB,'profile_for',lambda *_:prof)
    monkeypatch.setattr(driver_module,'load',lambda _:f.native)
    monkeypatch.setattr(MB,'lessons_writer',lambda *_:None)
    monkeypatch.setattr(MB,'tactical_publisher',lambda *_:None)
    monkeypatch.setattr(MB,'apply_ops',lambda *_:pytest.fail('Human/co-op configuration may not apply training writes'))
    class Boot:
        def __init__(self,*a,**kw): pass
        def tick(self,*a,**kw): pytest.fail('Human/co-op menu may not receive automatic navigation')
    monkeypatch.setattr(MB,'Boot',Boot)
    calls=[]
    def engine(*args,**kw):
        calls.append(kw)
        assert kw['observe_only'] is True
        assert kw['session_runtime'].config['role']=='observe_human'
        assert f.memory.mercs_no_modifications is True
        return 'stopped'
    monkeypatch.setattr(MB,'title_engine',lambda _:SimpleNamespace(play_round=engine))
    slept=[]
    stats=MB.play(f.ad,f.ad.send_input,lambda:bool(slept),{},GAME,m=f.memory,
                  sleep=lambda s:slept.append(s),session_id=SID)
    return f,calls,stats


def test_outer_play_observes_human_round_without_brain_mods_or_menu_inputs(tmp_path,monkeypatch):
    f,calls,stats=outer_play(tmp_path,monkeypatch,'observe_human','playing')
    assert len(calls)==1 and not f.sent


@pytest.mark.parametrize('role',['teammate_p2','observe_human'])
def test_outer_play_waits_for_human_menus_and_never_recovers_or_presses_p1(tmp_path,monkeypatch,role):
    f,calls,stats=outer_play(tmp_path,monkeypatch,role,'main_menu')
    assert not calls and not f.sent


def test_outer_play_unverified_teammate_never_starts_solo_brain_in_human_round(tmp_path,monkeypatch):
    f,calls,stats=outer_play(tmp_path,monkeypatch,'teammate_p2','playing')
    assert not calls and not f.sent and stats['team_phase']=='waiting_p2'
