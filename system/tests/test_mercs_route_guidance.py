from gbox.mercs.route_guidance import Guidance
from test_re5_nav import floor_pair
import threading
import time
from gbox.mercs import reviewer


def guide(mesh,points):
    g = Guidance('/unused','BLUS30491')
    g.geometry,g.at = mesh.learning_sig,0.
    g.rows = [{'id':'operator-path','points':points}]
    return g


def test_operator_suggestion_guides_only_an_applicable_supported_floor():
    mesh = floor_pair()
    start,goal = (150.,0.,50.),(50.,0.,150.)
    g = guide(mesh,[start,(140.,0.,60.),goal])
    baseline = mesh.route(start,goal)
    result = g.route(mesh,start,goal,baseline,1.)
    assert result['suggestion_id'] == 'operator-path' and result['route'][-1] == goal
    assert g.route(mesh,start,goal,baseline,1.,blocked_links={(0,1)}) is None
    assert g.route(mesh,start,goal,baseline,1.,hazards=[(goal,50.)]) is None
    assert g.route(mesh,start,goal,None,1.) is None


def test_suggestion_does_not_authorize_unsupported_height_or_reverse_drop():
    mesh = floor_pair()
    start,goal = (150.,0.,50.),(50.,0.,150.)
    g = guide(mesh,[start,(150.,500.,50.),goal])
    assert g.route(mesh,start,goal,mesh.route(start,goal),1.) is None
    g = guide(mesh,[goal,start])
    assert g.route(mesh,start,goal,mesh.route(start,goal),1.) is None


def test_locked_annotation_read_is_single_flight_and_never_blocks_movement(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    mesh = floor_pair()
    start,goal = (150.,0.,50.),(50.,0.,150.)
    def delayed(*_):
        calls.append(1)
        entered.set()
        assert release.wait(2.)
        return [{'id':'delayed','points':[start,goal]}]
    monkeypatch.setattr(reviewer,'validated_suggestions',delayed)
    g = Guidance('/unused','BLUS30491')
    try:
        before = time.monotonic()
        assert g.route(mesh,start,goal,mesh.route(start,goal),1.) is None
        assert time.monotonic()-before < .2
        assert entered.wait(1.)
        for now in (2.,10.,20.):
            assert g.route(mesh,start,goal,mesh.route(start,goal),now) is None
        assert len(calls) == 1
    finally:
        release.set()
    for _ in range(100):
        if not g.refreshing:
            break
        time.sleep(.005)
    assert not g.refreshing
    assert g.route(mesh,start,goal,mesh.route(start,goal),2.)['suggestion_id'] == 'delayed'


def test_delayed_previous_geometry_result_cannot_seed_new_floor(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    old,new = floor_pair(),floor_pair(y=500.)
    start,goal = (150.,0.,50.),(50.,0.,150.)
    def delayed(*_):
        entered.set()
        assert release.wait(2.)
        return [{'id':'old','points':[start,goal]}]
    monkeypatch.setattr(reviewer,'validated_suggestions',delayed)
    g = Guidance('/unused','BLUS30491')
    g.route(old,start,goal,old.route(start,goal),1.)
    assert entered.wait(1.)
    higher_start,higher_goal = (150.,500.,50.),(50.,500.,150.)
    assert g.route(new,higher_start,higher_goal,new.route(higher_start,higher_goal),2.) is None
    release.set()
    for _ in range(100):
        if not g.refreshing:
            break
        time.sleep(.005)
    assert g.rows == [] and g.geometry == new.learning_sig
