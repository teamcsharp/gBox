from gbox.mercs.obstacle_map import clear_segment, detour
from gbox.mercs.titles.re5_nav import Learning, NavMesh
from gbox.mercs.titles import re5_ps3 as R
import math


def room():
    return NavMesh([(-1000.,0.,-1000.),(1000.,0.,-1000.),(1000.,0.,1000.),(-1000.,0.,1000.)],
                   [(0,1,2),(0,2,3)],[[(1,2,1.)],[(0,0,1.)]])


def test_remembered_approach_detours_inside_a_floor_face_instead_of_repeating_the_wall():
    mesh=room();blocks=[{'pos':(100.,0.,0.),'radius':80.}]
    assert not clear_segment((0.,0.,0.),(400.,0.,0.),blocks)
    path=detour((0.,0.,0.),(400.,0.,0.),blocks,project=lambda p:p,
                supported=mesh.floor_segment)
    assert path and abs(path[0][2])>=80.
    previous=(0.,0.,0.)
    for point in path:
        assert mesh.floor_segment(previous,point) and clear_segment(previous,point,blocks)
        previous=point


def test_local_recovery_cannot_invent_floor_crossings_or_walk_into_a_mine():
    blocks=[{'pos':(100.,0.,0.),'radius':80.}]
    assert detour((0.,0.,0.),(400.,0.,0.),blocks,project=lambda p:p,
                  supported=lambda a,b:a==b) is None
    assert detour((0.,0.,0.),(400.,0.,0.),blocks,project=lambda p:p,
                  supported=lambda a,b:True,hazard_clear=lambda a,b:False) is None
    assert detour((0.,0.,0.),(400.,200.,0.),blocks,project=lambda p:p,
                  supported=lambda a,b:True) is None


def test_observed_blockage_survives_restart_but_expires_and_never_becomes_a_confirmed_wall(tmp_path):
    mesh=room();path=tmp_path/'learned.json';learned=Learning(path)
    event=learned.obstruction(mesh,(0.,0.,0.),(400.,0.,0.),'stationary commanded approach',approach=(400.,0.,0.))
    learned.save();loaded=Learning(path)
    rows=loaded.approach_obstacles(mesh,now=event['at']+1)
    assert len(rows)==1 and rows[0]['pos']==[100.,0.,0.] and rows[0]['wall_object_verified'] is False
    assert loaded.approach_obstacles(mesh,now=event['at']+17)==[]
    other=NavMesh([(x+2000,y,z) for x,y,z in mesh.points],mesh.tris,mesh.links)
    assert loaded.approach_obstacles(other,now=event['at']+1)==[]


def test_goal_changes_cannot_reset_the_stationary_movement_watchdog(tmp_path):
    bot=R.Bot(learn_dir=tmp_path);mesh=room()
    player={'ptr':123,'pos':(0.,0.,0.),'rot':math.pi/2,'hp':1000,'hp_max':1000,'action':0}
    snap={'player':player,'nav':mesh}
    for i in range(17):
        bot.plan_target={'id':i,'kind':'time','pos':(400.,0.,0.)}
        act=bot._avoid_observed_blockage(snap,{'hold':{'lup'}},i*.1)
    assert bot.stats['observed_blocked_approaches']==1
    assert bot.nav_learning.approach_obstacles(mesh)
    assert bot.stats.get('local_obstacle_detours',0)>=1
    assert 'lup' not in act['hold'],'the blocked forward direction must be released before turning onto the detour'


def test_turning_and_hit_recovery_do_not_train_false_walls(tmp_path):
    mesh=room();bot=R.Bot(learn_dir=tmp_path)
    p={'ptr':123,'pos':(0.,0.,0.),'rot':0.,'hp':1000,'hp_max':1000,'action':0}
    for i in range(30):bot._avoid_observed_blockage({'player':p,'nav':mesh},{'hold':{'rleft'}},i*.1)
    p['action']=6
    for i in range(30,60):bot._avoid_observed_blockage({'player':p,'nav':mesh},{'hold':{'lup'}},i*.1)
    assert not bot.nav_learning.approach_obstacles(mesh)


def test_detour_respects_previously_blocked_directed_floor_links():
    mesh=room();a=(100.,0.,-100.);b=(-100.,0.,100.)
    assert mesh.floor_segment(a,b)
    assert not mesh.floor_segment(a,b,blocked_links={(0,1)})
    assert mesh.floor_segment(b,a,blocked_links={(0,1)})


def test_bot_moves_around_a_solid_wall_missing_from_the_floor_mesh(tmp_path):
    mesh=room();bot=R.Bot(learn_dir=tmp_path)
    player={'ptr':123,'pos':(0.,0.,0.),'rot':math.pi/2,'hp':1000,'hp_max':1000,'action':0}
    goal=(400.,0.,0.);bot.plan_target={'id':1,'kind':'time','pos':goal}
    # Independent collision model: the floor map has no knowledge of this box.
    def collides(a,b):
        lo,hi=0.,1.
        for k,minimum,maximum in [(0,50.,90.),(2,-100.,100.)]:
            delta=b[k]-a[k]
            if abs(delta)<1e-9:
                if not minimum<=a[k]<=maximum:return False
            else:
                ends=sorted(((minimum-a[k])/delta,(maximum-a[k])/delta))
                lo,hi=max(lo,ends[0]),min(hi,ends[1])
                if lo>hi:return False
        return True
    for tick in range(400):
        pos=player['pos'];err=R.wrap(R.heading(goal[0]-pos[0],goal[2]-pos[2])-player['rot'])
        keys=bot._turn(err,False)
        if abs(err)<=R.TURN_TOL:keys|={'lup'}
        action=bot._avoid_observed_blockage({'player':player,'nav':mesh},{'hold':keys},tick*.1)
        chosen=action.get('hold',())
        if 'rleft' in chosen:player['rot']=R.wrap(player['rot']+.25)
        if 'rright' in chosen:player['rot']=R.wrap(player['rot']-.25)
        if 'lup' in chosen:
            step=(pos[0]+14.5*math.sin(player['rot']),0.,pos[2]+14.5*math.cos(player['rot']))
            if not collides(pos,step):player['pos']=step
        if math.dist(player['pos'],goal)<60.:break
    assert math.dist(player['pos'],goal)<60.,(player,bot.stats)
    assert bot.stats['observed_blocked_approaches']>=1 and bot.stats['local_obstacle_detours']>=1
