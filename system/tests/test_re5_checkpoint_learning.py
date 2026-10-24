import math
import struct

import pytest

from gbox.mercs import engine
from gbox.mercs.titles import re5_combat as C, re5_ps3 as R
from gbox.mercs.titles.re5_nav import NavMesh


def open_mesh():
    return NavMesh([(-1000.,0.,-1000.), (1000.,0.,-1000.), (1000.,0.,1000.), (-1000.,0.,1000.)],
                   [(0,1,2),(0,2,3)], [[(1,2,1.)],[(0,0,1.)]])


def test_bot_holds_checkpoint_when_tour_order_changes_and_resumes_after_observed_combat(tmp_path):
    now = [10.]
    bot = R.Bot(clock=lambda: now[0], learn_dir=tmp_path)
    p = {"pos": (100.,0.,0.), "rot": 0., "hp": 1000}
    nav = open_mesh()
    bonuses = [{"ptr": 1, "pos": (200.,0.,0.), "kind": "time", "seconds": 60},
               {"ptr": 2, "pos": (-300.,0.,0.), "kind": "time", "seconds": 60}]
    assert bot._bonus(p,[],bonuses,now[0],nav,100)["ptr"] == 1
    now[0] = 11.
    bot._tour_goal = 2
    bot._tour_at = 11.
    assert bot._bonus(p,[],bonuses,now[0],nav,100)["ptr"] == 1
    # Combat/QTE-owned inputs pause the goal's walking lease.
    now[0] = 35.
    bot._interrupt_route_walk()
    assert bot._bonus(p,[],bonuses,now[0],nav,100)["ptr"] == 1
    now[0] = 36.
    assert bot._bonus(p,[],bonuses[1:],now[0],nav,100)["ptr"] == 2


def test_time_checkpoint_outranks_closer_combo_bonus_and_stage_recall_applies_bounded_policy(tmp_path):
    bot = R.Bot(learn_dir=tmp_path)
    p = {"pos": (100.,0.,0.), "rot": 0.}
    bonuses = [{"ptr": 1, "pos": (120.,0.,0.), "kind": "combo"},
               {"ptr": 2, "pos": (-300.,0.,0.), "kind": "time"}]
    assert bot._bonus(p,[],bonuses,10,open_mesh(),100)["ptr"] == 2
    bot.recall([{"observed": {"stuck": 3, "reflection": {"policy": {"bonus_commitment": True,
                 "allow_unverified_routes": True}}}}])
    assert bot.bonus_commitment.patience_s == 16.
    assert "verified floor only" in bot.stats["round_policy_applied"]
    bot.recall([])
    assert bot.bonus_commitment.patience_s == 12.


class Escape:
    def __init__(self): self.escape = {"actor": 123, "pos": (100.,0.,0.), "at": 0.}
    def clear_escape(self, now, position):
        if math.dist(position,self.escape["pos"]) >= 600.:
            self.escape = None
            return True
        return False


def test_mine_retreat_holds_checkpoint_and_walks_only_measured_floor(tmp_path):
    bot = R.Bot(clock=lambda: 10., learn_dir=tmp_path)
    bot.mines = Escape()
    bot.bonus_commitment.choose(77,[77],0.)
    p = {"pos": (100.,0.,100.), "rot": 0.}
    act = bot._mine_retreat(p,{"nav": open_mesh()},10.)
    assert bot.stats["phase"] == "leave_proximity_bomb"
    assert bot.route_for == "mine_escape:123" and not bot._route_learn
    assert "l1" not in act.get("hold",()) and "r1" not in act.get("hold",())
    assert bot.bonus_commitment.goal == 77
    assert all(open_mesh().floor_segment(a,b) for a,b in zip([p["pos"]]+bot.route,bot.route))
    assert bot._mine_retreat(p,{},11.) is None  # blocked escape cannot permanently suppress ordinary gunplay
    assert "blocked:" in bot.stats["mine_retreat_status"]
    assert bot.mines.escape is not None  # optional placement still requires actual departure
    assert bot._mine_retreat(p | {"pos": (100.,0.,700.)},{},12.) is None
    assert bot.mines.escape is None


def test_mine_retreat_cannot_bypass_recovery_or_selected_qte(tmp_path):
    bot = R.Bot(clock=lambda: 10., learn_dir=tmp_path)
    bot.mines = Escape()
    p = {"pos": (100.,0.,100.), "rot": 0., "hp": 1000}
    snap = {"player": p, "timer": 100., "prompt": "mash", "recovery_active": True, "nav": open_mesh()}
    assert bot._tick(snap) == {"hold": set()}
    assert bot.stats.get("phase") != "leave_proximity_bomb"


def test_confirmed_distant_laser_target_can_fire_while_an_unconfirmed_one_cannot(tmp_path, monkeypatch):
    # Sparse guest memory is sufficient: an in-hand direct rifle with a long first-hit ray.
    class Mem:
        def __init__(self): self.raw = {}
        def rd(self,a,n): return bytes(self.raw.get(a+i,0) for i in range(n))
        def put(self,a,fmt,*values):
            for i,b in enumerate(struct.pack(fmt,*values)): self.raw[a+i] = b
    m = Mem()
    player = 0x30400000
    m.put(C.S_PLAYER,">I",0x30300000)
    m.put(0x30300000+0x28,">I",player)
    m.put(player,">I",0x016172B8)
    m.put(player+C.P_ACTION,">B",C.AIMING)
    slot = player+C.P_INV
    m.put(slot+C.INV_ID,">I",0x112)
    m.put(slot+C.INV_ROUNDS,">i",50)
    m.put(slot+C.INV_HAND,">I",1)
    m.put(slot+C.INV_USED,">B",1)
    snap = {"player": {"ptr": player, "pos": (0.,0.,0.), "rot": 0., "hp": 1000, "action": C.AIMING},
            "enemies": [{"ptr": 0x30500000,"slot": 0,"pos": (0.,0.,6000.),"hp": 800,"hp_max": 800}],
            "laser": {"from": (0.,149.,46.),"at": (0.,110.,6000.)},"timer": 100.,"combo": 0}
    monkeypatch.setattr(C,"STEADY_HEAD",False)
    bot = C.Combat(m,{},learn_dir=tmp_path)
    act = bot.tick(snap,snap["player"],snap["enemies"][0],10.)
    assert {"l1","r1"} <= act["hold"]
    snap["laser"]["at"] = (0.,110.,1000.)
    assert bot.tick(snap,snap["player"],snap["enemies"][0],10.1) == {"hold": set()}


def test_verified_recovery_uses_one_frame_circle_edges_and_rechecks_before_next_pulse(tmp_path, monkeypatch):
    class Driver:
        frame = None
        def brain(self,*args,**kw): return Brain()
        def prompt_source(self,m,stats): return lambda: "mash"
        def prompt_keys(self,button): return [("circle",)]
        def snapshot(self,m): return {"player":{"hp":1},"recovery_active":True}
        def screen(self,m,snap): return "playing"
        def recovery_active(self,m): return m[0] < 2
        def progress(self,snap): return {}
    class Brain:
        def prompt_ok(self,*a): return True
        def observe_round(self,*a): pass
        def save(self): pass
    count, sleeps, sent, stats = [0],[],[],{}
    def stopped():
        count[0] += 1
        return count[0] > 3
    engine.play_round({},count,sent.extend,stopped,stats,driver=Driver(),
                      sleep=sleeps.append,clock=lambda: count[0]*.1)
    assert sent == [{"key":"circle","down":True},{"key":"circle","down":False}]
    assert sleeps == pytest.approx([1/60,1/60])
    assert stats["resuscitate_fast_pulses"] == 1
