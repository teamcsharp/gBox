"""Periodic quick-shot attempts require contact and native action feedback; QTEs win."""
import math
import json
from pathlib import Path

import pytest

from gbox.mercs import bot_logic as BL
from gbox.mercs.titles import re6_switch as R
from test_re6_switch import _fresh_caches, brain, round_guest, run


def ready_bot():
    bot = R.Bot(stats={}, clock=lambda:24.)
    p = {'ptr':123, 'generation':4, 'equipped':0, 'weapon_id':3, 'ammo':18,
         'state':0, 'action':'cPlAction_pl_act_wait', 'hp':900, 'hp_max':900, 'pos':(0.,0.,0.)}
    enemy = {'ptr':456, 'hp':700, 'pos':(0.,0.,300.)}
    bot._round_started = 0.
    bot._prompt_shown = []
    bot._ppos = p['pos']
    bot._snap = {'player':p, 'enemies':[enemy],
                 'laser':{'up':True, 'from':(0.,R.CHEST_H,0.), 'at':(0.,R.CHEST_H,300.)}}
    return bot, p, enemy


def act(bot, p, enemy, now):
    return bot._periodic_quick_attack(p, [enemy], lambda _:300., now)


def test_four_default_requests_require_separate_release_and_native_observation():
    bot, p, enemy = ready_bot()
    assert act(bot,p,enemy,23.9) is None
    for i in range(4):
        now = 24. + i*.5
        assert act(bot,p,enemy,now) == {'hold':()}
        assert bot.stats['act'] == 'periodic_quick_release'
        assert act(bot,p,enemy,now+.05) == {'hold':('zl','zr')}
        assert bot.stats['periodic_qa_requests'] == i+1
        p['action'] = 'cPlAction_pl_act_weapon_comn_quick_shot'
        bot._periodic_qa_observe(p,now+.1)
        assert act(bot,p,enemy,now+.1) == {'hold':()}
        p['action'] = 'cPlAction_pl_act_wait'
        act(bot,p,enemy,now+.2)
    assert bot.periodic_qa_remaining == 0
    assert bot.stats['periodic_qa_native_actions'] == 4
    assert act(bot,p,enemy,47.9) is None
    assert bot.stats['periodic_qa_bursts'] == 1


@pytest.mark.parametrize('problem', ['no_laser','wall','empty','unknown_ammo','item','grab','prompt','down'])
def test_due_timer_does_not_override_combat_safety(problem):
    bot,p,enemy=ready_bot()
    if problem=='no_laser': bot._snap['laser']=None
    elif problem=='wall': bot._snap['laser']['at']=(0.,R.CHEST_H,100.)
    elif problem=='empty': p['ammo']=0
    elif problem=='unknown_ammo': p['ammo']=None
    elif problem=='item': p['equipped']=12
    elif problem=='grab': p['state']=8
    elif problem=='prompt': bot._prompt_shown=[{'key':'zr'}]
    elif problem=='down': bot.down=True
    assert act(bot,p,enemy,24.) is None
    assert bot.periodic_qa_remaining==0 and 'periodic_qa_requests' not in bot.stats


@pytest.mark.parametrize('problem', ['stale','moved','weapon','player'])
def test_release_carryover_is_short_and_bound_to_same_player_weapon_target(problem):
    bot,p,enemy=ready_bot()
    act(bot,p,enemy,24.)
    now=24.05
    if problem=='stale': now=24.3
    elif problem=='moved': enemy['pos']=(100.,0.,300.)
    elif problem=='weapon': p['equipped']=1
    else:p['generation']=5
    assert act(bot,p,enemy,now) is None
    assert 'periodic_qa_requests' not in bot.stats


def test_unobserved_native_attack_aborts_burst_instead_of_blindly_counting_success():
    bot,p,enemy=ready_bot()
    act(bot,p,enemy,24.)
    act(bot,p,enemy,24.05)
    assert act(bot,p,enemy,25.4) is None
    assert bot.stats['periodic_qa_unconfirmed']==1 and bot.periodic_qa_remaining==0
    assert bot.stats.get('periodic_qa_native_actions',0)==0


def test_current_gun_action_is_released_then_finishes_before_quick_shot():
    bot,p,enemy=ready_bot()
    p.update(action='cPlAction_pl_act_weapon_fire',state=2)
    assert act(bot,p,enemy,24.)=={'hold':()}
    assert act(bot,p,enemy,24.05)=={'hold':()}
    p.update(action='cPlAction_pl_act_wait',state=0)
    assert act(bot,p,enemy,24.1)=={'hold':('zl','zr')}


@pytest.mark.parametrize('pending', ['qshot_release','quick','quick_settle','hit_qs'])
def test_current_counter_prompt_preempts_pending_combat_sequence(pending):
    bot,clock,snap=brain(round_guest(enemies=((0.,0.,300.,700),)))
    bot.held=lambda *_:False
    snap['prompts']=[{'ab':1000,'type':1,'key':'zr'}]
    if pending=='quick_settle':bot.quick_at=clock[0]
    else:setattr(bot,pending,2 if pending in ('quick','hit_qs') else True)
    assert run(bot,snap,clock,1)[0]=={'tap':'zr'}
    assert bot.stats['act']=='prompt_zr'


@pytest.mark.parametrize('interrupt', ['counter','hold'])
def test_prompt_interrupt_cannot_acknowledge_or_resume_an_old_burst(interrupt):
    bot,clock,snap=brain(round_guest(enemies=((0.,0.,300.,700),)))
    p=snap['player']
    life=(p.get('ptr'),p.get('generation'),p.get('equipped'),p.get('weapon_id'))
    bot.periodic_qa_wait={'at':clock[0],'seen':False,'life':life}
    bot.periodic_qa_remaining=3
    bot.periodic_qa_last=clock[0]
    if interrupt=='counter':snap['prompts']=[{'ab':1000,'type':1,'key':'zr'}]
    else:p['state']=8
    p['action']='cPlAction_pl_act_attack_ex'
    run(bot,snap,clock,1)
    assert bot.stats['periodic_qa_interrupted']==1
    assert bot.periodic_qa_wait is None and bot.periodic_qa_remaining==0
    assert bot.stats.get('periodic_qa_native_actions',0)==0
    snap['prompts']=[];p['state']=0
    run(bot,snap,clock,1)
    assert bot.stats.get('periodic_qa_native_actions',0)==0
    assert bot.stats.get('periodic_qa_requests',0)==0


def test_stick_prompt_is_continuous_and_not_stripped_by_the_boost_governor():
    bot,clock,snap=brain(round_guest(enemies=()))
    bot.held=lambda *_:False
    snap['prompts']=[{'ab':1000,'type':1,'key':'stick'}]
    snap['player']['action']='cPlAction_pl_act_attack_ex'
    outs=run(bot,snap,clock,3)
    assert all(set(out.get('hold',())) & R.STICK_KEYS for out in outs)
    assert bot.stats.get('boost_releases',0)==0


def test_settings_are_bounded_persistent_and_disable_clears_pending_burst(tmp_path,monkeypatch):
    for name in ('PERIODIC_QA','PERIODIC_QA_COUNT','PERIODIC_QA_INTERVAL_S'):
        monkeypatch.setattr(R,name,getattr(R,name))
    path=tmp_path/'logic.json'
    out=BL.handle('re6',{'PERIODIC_QA_COUNT':99,'PERIODIC_QA_INTERVAL_S':1},path=path)
    assert R.PERIODIC_QA_COUNT==8 and R.PERIODIC_QA_INTERVAL_S==8
    assert {r['name']:r['value'] for r in out['knobs']}['PERIODIC_QA'] is True
    bot,p,e=ready_bot();bot.periodic_qa_remaining=4
    BL.handle('re6',{'PERIODIC_QA':False},path=path)
    assert act(bot,p,e,30.) is None and bot.periodic_qa_remaining==0
    R.PERIODIC_QA=True
    assert BL.apply_saved('re6',path)['PERIODIC_QA'] is False


def test_profile_keeps_tuning_mods_and_enables_target_gated_grenade_policy():
    profile=json.loads((Path(__file__).resolve().parents[1]/'profiles/gamedata/01002A000CD48000-ram.json').read_text())
    ops=dict(profile['mercs']['playing_ops'])
    for name in ('infinite_ammo','infinite_grenades','auto_qte','auto_qte_ram'):
        assert ops[name]=={'on':True}
    assert ops['fire_rate']=={'multiplier':5,'magnum':5,'throw':5}
    assert ops['bot_options']=={'nades':True,'flash':True,'bomb_drop':False,'aim_lock':True}


def test_explicit_free_native_state_is_not_overridden_by_stationary_grab_guess():
    bot,clock,snap=brain(round_guest(enemies=((0.,0.,900.,700),)))
    bot.held=lambda *_:True
    snap['player']['state']=0
    out=run(bot,snap,clock,1)[0]
    assert bot.stats['act']!='break_free' and bot.stats['holds']==0
    snap['player']['state']=8
    run(bot,snap,clock,1)
    assert bot.stats['act']=='break_free' and bot.stats['holds']==1


def test_two_ineffective_close_kicks_yield_to_bounded_gun_acquisition():
    bot,clock,snap=brain(round_guest(enemies=((0.,0.,100.,700),)))
    outs=run(bot,snap,clock,22)
    assert bot.stats['cc_kicks']==2
    assert any('zl' in out.get('hold',()) for out in outs)
    assert bot.stats['shots']==0  # acquiring a camera line does not prove a shot
    snap['laser']={'from':(0.,R.CHEST_H,0.),'at':(0.,R.CHEST_H,100.),'up':True}
    outs=run(bot,snap,clock,8)
    assert any('zr' in out.get('hold',()) for out in outs)


def test_melee_windup_keeps_defense_ahead_of_post_kick_aim_window():
    bot,clock,snap=brain(round_guest(enemies=((0.,0.,100.,700),)))
    snap['enemies'][0]['action']='cEm5000ActCatch'
    outs=run(bot,snap,clock,22)
    assert bot.stats['cc_kicks']>=3
    assert not any('zl' in out.get('hold',()) for out in outs)


def test_new_round_discards_prior_target_gun_window_and_pending_burst():
    bot,p,enemy=ready_bot()
    bot.died,bot.continued=True,'yes'
    bot._cc_last_kick=(456,700,2)
    bot._cc_gun_target,bot._cc_gun_until=456,50.
    bot.periodic_qa_remaining=3
    bot.periodic_qa_arm={'target':456}
    bot._round_start({'timer':R.ROUND_TIME_S},40.)
    assert bot._cc_last_kick is None and bot._cc_gun_target is None
    assert bot._cc_gun_until<40.
    assert bot.periodic_qa_remaining==0 and bot.periodic_qa_arm is None
    assert bot.periodic_qa_due==40.+R.PERIODIC_QA_INTERVAL_S


def test_managed_replay_answers_no_in_direct_dead_tick_even_when_legacy_retry_is_on(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(R,'REPLAY_ON_DEATH',True)
    bot,clock,snap=brain(round_guest(hp=0))
    bot.round_control=SimpleNamespace(managed=True)
    snap['continue_cursor']=R.CONTINUE_YES
    run(bot,snap,clock,1)
    clock[0]+=R.DEAD_WAIT_S+.1
    assert run(bot,snap,clock,1)[0]=={'tap':'dright'}
    snap['continue_cursor']=R.CONTINUE_NO
    assert run(bot,snap,clock,1)[0]=={'tap':'a'}
    assert bot.continued=='no'


def test_semi_auto_waits_native_cooldown_with_aim_held_then_fires_at_contact():
    bot,clock,snap=brain(round_guest(enemies=((0.,0.,900.,700),),
        laser=((0.,R.CHEST_H,900.),(0.,R.CHEST_H,0.),.86)))
    snap['player'].update(weapon_id=3,fire_cooldown_s=.2)
    outs=run(bot,snap,clock,12)
    assert all('zr' not in out.get('hold',()) for out in outs)
    assert any('zl' in out.get('hold',()) for out in outs)
    assert bot.stats['fire_contact_verified'] and not bot.stats['fire_trigger_requested']
    snap['player']['fire_cooldown_s']=0.
    assert any('zr' in out.get('hold',()) for out in run(bot,snap,clock,3))


def test_unattributed_trigger_requests_do_not_train_weapon_accuracy(monkeypatch):
    from gbox.mercs.brain import knowledge
    monkeypatch.setattr(knowledge,'record_shot',lambda *_args,**_kw:pytest.fail('No bullet/damage-source proof'))
    bot=R.Bot(stats={})
    bot._k_shot({'entry':{'measurement':'trigger_request'},'hit':True},1.)
    assert bot.stats['unattributed_shot_learning_skips']==1


def test_native_stick_prompt_is_not_rerouted_by_floor_mesh():
    from gbox.mercs.titles import re6_switch_wall as W
    class Mesh:
        def locate(self, *_):pytest.fail('A native stick QTE is not navigation')
    bot,p,enemy=ready_bot()
    bot.stats['act']='prompt_stick'
    snap={'player':p,'navmesh':Mesh(),'mercenaries_phase':R.PHASE_PLAYING}
    request={'hold':('lup','lright')}
    assert W.mesh_guard(bot,snap,request)==request


def test_no_hp_change_is_not_misreported_as_off_target_or_used_for_aim_training():
    bot=R.Bot(stats={})
    bot.doing='fire';bot.fire_down=True
    bot._aimctx={'target':456,'source':'laser','dist':300.,'yaw_err':0.}
    bot._pulls_tick(1.)
    bot.doing='aim'
    bot._pulls_tick(1.1)
    bot._pulls_tick(1.1+R.HIT_S+.01)
    entry=bot.look.shots[-1]
    assert entry['outcome']=='miss:no_damage' and entry['measurement']=='trigger_request'
    assert 'unverified' in entry['damage_evidence']
    assert bot.stats['unattributed_shot_learning_skips']==1
