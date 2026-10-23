"""Regression replay of the observed Ship Deck intro that disconnected all goals."""
import json
import math
from pathlib import Path

from gbox.mercs.titles import re5_ps3 as R
from gbox.mercs.titles.re5_nav import NavMesh


def recorded_stage():
    path = Path(__file__).parent/"fixtures/re5_navigation/ship_deck_spawn.json"
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    links = [[] for _ in data["triangles"]]
    for u,v,edge,cost in data["links"]:
        links[u].append((v,edge,cost if cost is not None else 1.))
    return data,NavMesh(data["points"],data["triangles"],links)


def test_recorded_single_intro_failure_disconnected_every_real_time_bonus():
    data,mesh = recorded_stage()
    assert len(data["goals"])==11
    assert sum(mesh.route(data["spawn"],b["pos"]) is not None for b in data["goals"])==11
    blocked = {tuple(data["intro_failed_link"])}
    assert sum(mesh.route(data["spawn"],b["pos"],blocked_links=blocked) is not None for b in data["goals"])==0


def test_recorded_intro_wait_cannot_spend_route_budget_or_learn_a_false_wall(tmp_path):
    data,mesh = recorded_stage()
    now = [0.]
    bot = R.Bot(clock=lambda:now[0],learn_dir=tmp_path)
    player = {"ptr":0x303f8a00,"pos":tuple(data["spawn"]),"rot":2.27,"hp":1000,"hp_max":1000,"action":0}
    bonuses = [{"ptr":b["id"],"kind":"time","pos":tuple(b["pos"])} for b in data["goals"]]
    snap = {"player":player,"nav":mesh,"bonuses":bonuses,"timer":120.,"timer_start":120.,"enemies":[]}
    for i in range(17):
        now[0] = i*.5
        assert bot.tick(dict(snap))=={"hold":set()}
        assert bot.stats["phase"]=="waiting_round_start"
    assert not bot.blocked_links and not bot.bonus_skip and bot.route_for is None
    assert not bot.nav_learning.link_penalties(mesh)
    now[0] = 8.1
    action = bot.tick(snap | {"timer":119.9})
    assert bot.round_input_ready and bot.stats["phase"]=="gather_time"
    assert bot.route_for is not None and bot.route
    assert action.get("hold") and "r1" not in action["hold"]
    assert not bot.blocked_links and not bot.bonus_skip


def test_temporary_failed_portal_reopens_real_checkpoint_paths_after_bounded_recheck(tmp_path):
    data,mesh = recorded_stage()
    bot = R.Bot(clock=lambda:10.,learn_dir=tmp_path)
    goal = next(b for b in data["goals"] if b["id"]==0x304772b0)
    target = {"ptr":goal["id"],"pos":tuple(goal["pos"])}
    player = {"pos":tuple(data["spawn"]),"rot":2.27,"action":0}
    bot.route = mesh.route(player["pos"],target["pos"],pull=False)
    # The ordinary follower skips the first portal already within WP_REACHED.
    # Replay the actual first pending edge recorded in the learning database.
    first = next(i for i,w in enumerate(bot.route) if getattr(w,"link",None)==tuple(data["intro_failed_link"]))
    bot.route = bot.route[first:]
    bot._route_mesh,bot._route_pos = mesh,player["pos"]
    bot._block_route(target,10.,"temporary obstruction witnessed")
    assert tuple(data["intro_failed_link"]) in bot.blocked_links
    assert mesh.route(player["pos"],target["pos"],blocked_links=bot.blocked_links) is None
    bot._expire_navigation_blocks(17.9)
    assert bot.blocked_links
    bot._expire_navigation_blocks(18.)
    assert not bot.blocked_links and bot.nav_learning.link_penalties(mesh)
    candidates = [{"ptr":b["id"],"kind":"time","pos":tuple(b["pos"])} for b in data["goals"]]
    assert bot._bonus(player,[],candidates,18.,mesh,100.) is not None
    assert bot.stats["unreachable_bonuses"]==0
