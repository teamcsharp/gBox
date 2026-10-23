from types import SimpleNamespace

from gbox.mercs.titles.re5_mines import Controller
from gbox.mercs.titles.re5_nav import Learning
from test_re5_nav import floor_pair


def test_mine_sites_survive_rounds_and_remain_geometry_specific(tmp_path):
    mesh, pos = floor_pair(), (150.,0.,50.)
    path = tmp_path/'navigation.json'
    learning = Learning(path)
    assert not learning.note_mine(mesh,(-200.,0.,50.),'placements')
    for _ in range(2):
        learning.note_mine(mesh,pos,'placements')
        learning.note_mine(mesh,pos,'damage_windows')
    learning.note_mine(mesh,pos,'candidate_deaths',3)
    learning.save()
    loaded = Learning(path)
    site = loaded.mine_site(mesh,pos)
    assert site['defer'] and site['candidate_deaths'] == 3 and site['confirmed_kills'] == 0
    assert not loaded.mine_site(floor_pair(y=500.),(150.,500.,50.))['defer']
    assert mesh.route(pos,(50.,0.,150.)), 'a bad mine site must not obstruct navigation'


def test_explosion_window_requires_observed_zero_hp_and_never_counts_disappearance(tmp_path):
    mesh, pos = floor_pair(), (150.,0.,50.)
    learning = Learning(tmp_path/'navigation.json')
    c = Controller(SimpleNamespace(),{},lambda *args:None)
    c.bind_learning(learning,mesh)
    c.blast_windows = [{'actor':9,'pos':pos,'at':1.,'hp':1000,'damage':False,'enemies':{2,3}}]
    c.observe_blasts({'player':{'hp':800},'enemies':[{'ptr':2,'hp':0}]},1.5)
    c.observe_blasts({'player':{'hp':700},'enemies':[{'ptr':2,'hp':0}]},1.6)
    site = learning.mine_site(mesh,pos)
    assert site['damage_windows'] == 1 and site['candidate_deaths'] == 1
    assert site['confirmed_kills'] == 0
    assert 'unconfirmed' in c.events[0]['attribution']
    c.observe_blasts({'player':{'hp':700},'enemies':[{'ptr':3,'hp':0}]},4.)
    assert learning.mine_site(mesh,pos)['candidate_deaths'] == 1
    assert not c.blast_windows


def test_scope_reset_discards_unfinished_explosion_attribution():
    c = Controller(SimpleNamespace(),{},lambda *args:None)
    c.blast_windows = [{'actor':9}]
    c.reset_round(0.,player=10)
    assert not c.blast_windows


def test_mine_evidence_updates_without_synchronous_full_navigation_file_writes(tmp_path, monkeypatch):
    mesh,pos = floor_pair(),(150.,0.,50.)
    learning = Learning(tmp_path/'navigation.json')
    c = Controller(SimpleNamespace(),{},lambda *args:None)
    c.bind_learning(learning,mesh)
    def forbidden():
        raise AssertionError('mine observations must use the existing periodic/round-end learning flush')
    monkeypatch.setattr(learning,'save',forbidden)
    for counter in ('placements','detonations','retreats','damage_windows','candidate_deaths'):
        c.learn(pos,counter)
    assert learning.mine_site(mesh,pos)['candidate_deaths'] == 1
