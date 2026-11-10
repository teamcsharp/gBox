import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gbox'))
import pytest
from room_atlas import Atlas, layout_hash


def make(tmp_path):
    a = Atlas('re4', root=tmp_path)
    r1 = a.observe_room('L1', 'A', [{'kind': 'checkpoint', 'name': 'cp1', 'pos': [1, 2, 3]}])
    r2 = a.observe_room('L1', 'B', [{'kind': 'switch', 'name': 'sw1', 'pos': [4, 5, 6]}])
    r3 = a.observe_room('L1', 'C', [{'kind': 'button', 'name': 'b1'}])
    return a, r1, r2, r3


def test_merge_visits_gain_confidence(tmp_path):
    a, r1, *_ = make(tmp_path)
    c1 = a.confidence(r1)
    a.observe_room('L1', 'A', [{'kind': 'checkpoint', 'name': 'cp1', 'pos': [1, 2, 3]}])
    assert a.data['rooms'][r1]['visits'] == 2
    assert a.data['rooms'][r1]['landmarks']['checkpoint:cp1']['seen'] == 2
    assert a.confidence(r1) > c1


def test_layout_hash_order_independent_and_variants_split(tmp_path):
    x = [{'kind': 'switch', 'name': 's', 'pos': [1, 1]}, {'kind': 'exit', 'name': 'e'}]
    assert layout_hash(x) == layout_hash(x[::-1])
    a = Atlas('g', root=tmp_path)
    assert a.observe_room('L', 'R', x) != a.observe_room('L', 'R', x[:1])


def test_route_and_landmark_lookup(tmp_path):
    a, r1, r2, r3 = make(tmp_path)
    a.observe_link(r1, r2, via='door1')
    a.observe_link(r2, r3, via='door2')
    plan = a.route_to_landmark(r1, 'button', 'b1')
    assert plan['status'] == 'ok' and [s['via'] for s in plan['steps']] == ['door1', 'door2']
    assert a.route_to_landmark(r1, 'switch')['steps'][0]['via'] == 'door1'


def test_failing_link_avoided_and_unknown_not_guessed(tmp_path):
    a, r1, r2, r3 = make(tmp_path)
    a.observe_link(r1, r3, via='bad', ok=False)
    assert a.route(r1, r3)['status'] == 'unknown'
    a.observe_link(r1, r2, via='d'); a.observe_link(r2, r3, via='d2')
    assert a.route(r1, r3)['status'] == 'ok'
    assert a.route_to_landmark(r1, 'checkpoint', 'nope')['status'] == 'unknown'


def test_coverage_frontier_and_persistence(tmp_path):
    a, r1, r2, _ = make(tmp_path)
    a.observe_link(r1, 'L1/Z#default', via='door')
    a.save()
    b = Atlas('re4', root=tmp_path)
    cov = b.coverage()
    assert cov['rooms'] == 3 and cov['unvisited_frontier'] == ['L1/Z#default']
    assert cov['landmarks']['switch'] == 1


def test_bad_landmark_rejected(tmp_path):
    with pytest.raises(ValueError):
        Atlas('g', root=tmp_path).observe_room('L', 'R', [{'kind': 'bogus', 'name': 'x'}])
