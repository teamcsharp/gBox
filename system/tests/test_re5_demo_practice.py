"""Real RE5 Bot + measured mesh + selected demonstration, without input replay."""
from copy import deepcopy

import pytest

from gbox.mercs.titles import re5_ps3 as R
from gbox.mercs.titles.re5_nav import NavMesh
from tests.test_re5_mercs import world

RID='d'*32


def mesh():
    return NavMesh([(-5000.,0.,-5000.),(5000.,0.,-5000.),(5000.,0.,5000.),(-5000.,0.,5000.)],
                   [(0,1,2),(0,2,3)],[[(1,2,1.)],[(0,0,1.)]])


def setup(tmp_path):
    floor=mesh()
    now=[100.]
    bot=R.Bot(clock=lambda:now[0],learn_dir=tmp_path,
              stats={'selected_route_id':RID,'mercenaries_mode':'reunion'})
    row={'id':RID,'title':'BLUS30491','mode':'reunion','geometry':floor.learning_sig,
         'kind':'recorded_demonstration','adopted':True,'bot_eligible':True,
         'source':{'control':'human','round_source_id':'atlas:BLUS30491:real-human-record'},
         'points':[(0.,0.,0.),(0.,0.,800.),(600.,0.,800.)],'traversals':[]}
    guidance=bot.operator_guidance
    guidance.geometry,guidance.at,guidance.rows=floor.learning_sig,now[0],[row]
    return bot,floor,now


def test_selected_human_demonstration_drives_real_bot_using_supported_floor_and_inputs(tmp_path):
    bot,floor,now=setup(tmp_path)
    memory=world(player_pos=(0.,0.,0.))
    before=deepcopy(memory.b)
    snapshot=dict(R.snapshot(memory),nav=floor)
    action=bot.tick(snapshot)
    assert bot.stats['phase']=='practice_human_route'
    assert bot.stats['demonstration_status']=='practice'
    assert bot.stats['demonstration_progress']=='1/3'
    assert bot.plan_target['id']=='demonstration:'+RID+':1'
    assert bot.route and floor.floor_segment(snapshot['player']['pos'],bot.route[0])
    assert 'lup' in action['hold'] and action['hold'] <= {'lup','cross','rleft','rright'}
    assert memory.b==before and snapshot['player']['pos']==(0.,0.,0.)
    assert 'tap' not in action  # no blind traversal, checkpoint claim or controller replay
    now[0]+=.1
    next_snapshot=dict(R.snapshot(world(player_pos=(0.,0.,800.))),nav=floor)
    bot.tick(next_snapshot)
    assert bot.stats['demonstration_progress']=='2/3'
    assert bot.plan_target['pos']==(600.,0.,800.)  # advances only after a measured arrival


def test_actual_nearby_enemy_interrupts_demo_with_same_combat_action_as_unassisted_planner(tmp_path):
    bot,floor,now=setup(tmp_path/'demo')
    bot.tick(dict(R.snapshot(world()),nav=floor))
    before_index=bot.operator_guidance.practice_state['index']
    now[0]+=.1
    memory=world(enemies=[((0.,0.,60.),800,800)])
    snapshot=dict(R.snapshot(memory),nav=floor)
    action=bot.tick(snapshot)
    baseline=R.Bot(clock=lambda:now[0],learn_dir=tmp_path/'baseline',stats={'mercenaries_mode':'reunion'})
    expected=baseline.tick(dict(R.snapshot(world(enemies=[((0.,0.,60.),800,800)])),nav=floor))
    assert action==expected and 'ldown' in action['hold']
    assert bot.operator_guidance.practice_state['index']==before_index
    assert bot._following_route is False


def test_practice_collects_a_live_nearby_hourglass_before_resuming_recorded_path(tmp_path):
    bot,floor,now=setup(tmp_path)
    snapshot=dict(R.snapshot(world()),nav=floor)
    bot.tick(snapshot)
    before_index=bot.operator_guidance.practice_state['index']
    bonus={'kind':'time','ptr':0x30008800,'pos':(0.,0.,100.)}
    now[0]+=.1
    action=bot.tick(dict(snapshot,bonuses=[bonus]))
    assert action=={'tap':'square'}
    assert bot.stats['phase']=='practice_take_time'
    assert bot.plan_target['id']==bonus['ptr']
    assert bot.operator_guidance.practice_state['index']==before_index
    now[0]+=.5
    bot.tick(dict(snapshot,bonuses=[]))
    assert bot.stats['phase']=='practice_human_route'
    assert bot.operator_guidance.practice_state['index']==before_index


def test_approved_demo_segment_cannot_move_through_floor_that_fails_live_revalidation(tmp_path,monkeypatch):
    bot,floor,_=setup(tmp_path)
    snapshot=R.snapshot(world())
    monkeypatch.setattr(floor,'floor_segment',lambda *_:False)
    action=bot._follow(snapshot['player'],{'ptr':'demonstration:'+RID+':1','pos':(0.,0.,800.)},
                       floor,False,100.,learn=False,approved_route=[(0.,0.,800.)])
    assert action=={'hold':set()}
    assert 'no longer has supported floor' in bot.stats['route']
