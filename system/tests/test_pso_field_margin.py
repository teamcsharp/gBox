from pso_owned_evidence import original_test_path
import copy
import json
import math
from pathlib import Path
import struct
import time

import pytest
from gbox import pso_coop_geometry as G
from test_pso_geometry import plane, player, state, fixture_memory, allow

ROOT = original_test_path('field-margin-recovery/test_field_margin.py').resolve().parent


@pytest.fixture(scope='module')
def forest():
    source = ROOT.parent / 'observer-v1/field-geometry-receipt-1793622503722814000.json'
    rows = json.loads(source.read_text())['result']['triangles']
    evidence = json.loads((ROOT.parent / 'observer-v1/layer-evidence-1793631324322752100.json').read_text())['result']
    return G.Atlas(rows), evidence['native']['players']


def assert_path(atlas, margin, row, p):
    assert row and row['player_ptr'] == p['ptr']
    assert row['start'] == {k: p[k] for k in ('x', 'y', 'z')}
    assert row['path'][0] == [p['x'], p['z']]
    assert row['path'][1] == [row['waypoint']['x'], row['waypoint']['z']]
    assert 0 < math.dist(*row['path'][:2]) <= 6
    assert 0 < row['path_length'] <= 12
    assert math.isclose(row['path_length'], sum(math.dist(a, b) for a, b in zip(row['path'], row['path'][1:])))
    assert len(row['path']) == len(row['path_heights']) <= 16
    view = margin._view(p)
    assert all(margin.clear(a, b, view['base']) for a, b in zip(row['path'], row['path'][1:]))
    target = dict(p, x=row['path'][-1][0], z=row['path'][-1][1], y=row['path_heights'][-1])
    assert atlas.project(target)['geometry_layer'] == row['geometry_layer']
    assert row['clearance_verified'] is False and row['dynamic_passability_verified'] is False


@pytest.mark.parametrize('slot', ['1', '2'])
def test_actual_forest_players_reenter_own_normal_margin(forest, slot):
    atlas, players = forest
    p = players[slot]
    assert atlas.project(p) is None
    margin = G.MarginViews(atlas)
    row = margin.recover(p, 'actual-layout')
    assert_path(atlas, margin, row, p)
    assert row['geometry_layer'] == '3574e623f76944e6786c8c2acc28f6385ffd13f632d95529bd42c4fd5c01d5b9'
    assert row['path'][-1] == ([227.5, 492.5] if slot == '1' else [242.5, 522.5])


def test_actual_repeated_and_moving_margin_queries_reuse_bounded_own_surface(forest):
    atlas, players = forest
    margin = G.MarginViews(atlas)
    first = margin.recover(players['2'], 'same')
    revision = margin.revision
    for _ in range(20):
        assert margin.recover(players['2'], 'same') == first
    p = dict(players['2'], x=247.5, z=522.5, y=26.18403439164456)
    assert_path(atlas, margin, margin.recover(p, 'same'), p)
    assert margin.revision == revision


@pytest.mark.parametrize('p', [player(x=-2.5), player(x=2.5, y=20), player(x=float('nan')), player(x=True)])
def test_unknown_falling_and_invalid_start_never_snaps(p):
    assert G.MarginViews(G.Atlas(plane())).recover(p, 'test') is None


def test_already_safe_has_no_recovery_and_overlapping_layers_are_not_guessed():
    assert G.MarginViews(G.Atlas(plane())).recover(player(), 'test') is None
    margin = G.MarginViews(G.Atlas(plane() + plane(y=30)))
    assert margin.recover(player(x=2.5), 'test') is None
    assert margin.recover(player(x=2.5, y=30), 'test') is None


def test_no_route_across_missing_cell_cliff_or_corner():
    atlas = G.Atlas(plane())
    margin = G.MarginViews(atlas)
    base = {(0, 0): 0., (1, 0): 0., (2, 0): 0.}
    assert margin.clear((2.5, 2.5), (12.5, 2.5), base)
    del base[(1, 0)]
    assert not margin.clear((2.5, 2.5), (12.5, 2.5), base)
    base[(1, 0)] = 30.
    assert not margin.clear((2.5, 2.5), (12.5, 2.5), base)
    assert not margin.clear((4.99, 4.99), (5.01, 5.01), {(0, 0): 0., (1, 1): 0.})


def test_thin_island_and_distant_interior_have_no_recovery():
    assert G.MarginViews(G.Atlas(plane(x1=5))).recover(player(x=2.5), 'test') is None
    atlas = G.Atlas(plane(x1=200, z1=200), size=20)
    assert G.MarginViews(atlas).recover(player(x=10, z=50), 'test') is None


def test_center_start_has_nonzero_immediate_waypoint():
    atlas = G.Atlas(plane())
    p = player(x=2.5)
    margin = G.MarginViews(atlas)
    assert_path(atlas, margin, margin.recover(p, 'test'), p)


def test_provider_refreshes_for_new_margin_work_and_keeps_normal_view_absent(monkeypatch):
    triangles = plane(); allow(monkeypatch, triangles)
    ad, _, _, _ = fixture_memory(triangles)
    provider = G.Provider(ad); s = state()
    assert provider.snapshot(s)['geometry_refreshed']
    assert not provider.snapshot(s)['geometry_refreshed']
    s['players'][2]['x'] = 2.5
    result = provider.snapshot(s)
    assert result['geometry_refreshed'] and 2 not in result['geometry_players']
    assert 1 in result['geometry_players'] and set(result['geometry_recovery_players']) == {2}
    reads = ad.reads
    again = provider.snapshot(s)
    assert not again['geometry_refreshed'] and ad.reads > reads
    assert again['geometry_recovery_players'] == result['geometry_recovery_players']
    s['players'][2]['x'] = 7.5
    result = provider.snapshot(s)
    assert 2 in result['geometry_players'] and 2 not in result['geometry_recovery_players']


def test_changed_actor_or_allocation_discards_recovery_authority(monkeypatch):
    triangles = plane(); allow(monkeypatch, triangles)
    ad, regions, base, _ = fixture_memory(triangles)
    provider = G.Provider(ad); s = state(); s['players'][2]['x'] = 2.5
    assert provider.snapshot(s)['geometry_recovery_players']
    old = provider.margin
    regions[0x8050EA10] = struct.pack('>2I', 0x80DA1000, 0x80DA3000)
    assert not provider.snapshot(s)['geometry_verified'] and provider.margin is None
    s['players'][2]['ptr'] = '80DA3000'
    result = provider.snapshot(s)
    assert result['geometry_refreshed'] and provider.margin is not old
    assert result['geometry_recovery_players'][2]['player_ptr'] == '80DA3000'
    blob = bytearray(regions[base]); blob[-1] ^= 1; regions[base] = bytes(blob)
    old = provider.margin
    result = provider.snapshot(s)
    assert result['geometry_refreshed'] and provider.margin is not old


def test_native_binding_change_during_margin_work_fails_closed(monkeypatch):
    triangles = plane(); allow(monkeypatch, triangles)
    ad, regions, _, _ = fixture_memory(triangles)
    provider = G.Provider(ad); s = state(); s['players'][2]['x'] = 2.5
    original = G.MarginViews.recover
    def changed(self, player, identity):
        result = original(self, player, identity)
        regions[0x805D49B8] = struct.pack('>I', 1)
        return result
    monkeypatch.setattr(G.MarginViews, 'recover', changed)
    result = provider.snapshot(s)
    assert not result['geometry_verified'] and 'geometry_recovery_players' not in result


def test_failed_thin_surface_does_not_repeat_expensive_refresh_loop(monkeypatch):
    triangles = plane(x1=5); allow(monkeypatch, triangles)
    ad, _, _, _ = fixture_memory(triangles)
    provider = G.Provider(ad); s = state()
    for p in s['players'].values():
        p['x'] = 2.5
    assert provider.snapshot(s)['geometry_refreshed']
    revision = provider.margin.revision
    for _ in range(5):
        result = provider.snapshot(s)
        assert result['geometry_verified'] and not result['geometry_refreshed']
        assert not result['geometry_players'] and not result['geometry_recovery_players']
    assert provider.margin.revision == revision
