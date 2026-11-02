from pso_owned_evidence import original_test_path
"""Exact current held actors regain normal routes through the unchanged controller."""
import copy
import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
from gbox import pso_coop as C
from gbox import pso_coop_geometry as G
from gbox.pso_coop_nav import Maps, room_key
from test_pso_native_floor_filter import memory, POSITIONS
from test_pso_geometry import state

BASE = original_test_path('activation12-native-floor/test_controller_contract.py').parent.parent


@pytest.fixture(scope='module')
def current():
    triangles = json.loads((BASE / 'observer-v1/field-geometry-receipt-1793622503722814000.json').read_text())['result']['triangles']
    ad, regions, _, _ = memory(triangles)
    st = state()
    for slot, xyz in enumerate(POSITIONS[:2], 1):
        st['players'][slot].update(ptr=f'{(0x80DA62A0, 0x80DA8830)[slot-1]:08X}',
            x=xyz[0], y=xyz[1], z=xyz[2], hp=(33, 38)[slot-1], hp_max=(33, 38)[slot-1],
            heading_deg=(168.013916015625, 176.693115234375)[slot-1], room=8)
    regions[0x8050EA10] = struct.pack('>2I', 0x80DA62A0, 0x80DA8830)
    provider = G.Provider(ad)
    first = provider.snapshot(st)
    assert first['geometry_verified'] and first['geometry_refreshed']
    second = provider.snapshot(st)
    assert second['geometry_verified'] and not second['geometry_refreshed']
    assert set(second['geometry_players']) == {1, 2} and not second['geometry_recovery_players']
    return dict(st, **second)


def test_current_both_use_own_normal_floor_and_invalidate_prior_wall_key(current, tmp_path):
    maps = Maps(tmp_path)
    for slot, player in current['players'].items():
        nav = maps.get(current, player)
        assert nav.floor and nav.route((player['x'], player['z']), (512.5, -192.5))
        buddy = current['players'][3-slot]
        assert nav.route((player['x'], player['z']), (buddy['x'], buddy['z']))
        previous = copy.deepcopy(current)
        previous['geometry_players'][slot]['geometry_layer'] = 'a2608a43913f2dc59ee91006840962d3fb00f85bb501028651dccc38d4df9607'
        assert room_key(previous, player)[0] != room_key(current, player)[0]


def test_real_current_controller_reobserves_then_emits_normal_bounded_commands(current, tmp_path, monkeypatch):
    """No dynamic gate is supplied: use the existing conservative frontier policy."""
    st = copy.deepcopy(current)
    commands, observations = [], []
    def snapshot():
        observations.append(True)
        return st
    inputs = SimpleNamespace(hold=lambda rows: commands.extend(rows), speed=lambda: 2,
        stopped=lambda: False, wall_learning_safe=lambda: False, stats={})
    control = C.Controller(SimpleNamespace(ad=None, snapshot=snapshot), inputs, Maps(tmp_path))
    monkeypatch.setattr(C.solo, 'wait', lambda *_: None)
    assert control.tick(st) is False
    assert commands and all(keys == ['l'] for _, keys, _ in commands)
    assert len(observations) == 1  # expensive first route choice causes fresh read next tick
    commands.clear()
    # A second player's route may first be cached on the second tick. Neither
    # route search may authorize an input until the next ordinary observation.
    for _ in range(3):
        if control.tick(st):
            break
        assert all(keys == ['l'] for _, keys, _ in commands)
        commands.clear()
    movement = [row for row in commands if row[1] != ['l']]
    assert {slot for slot, _, _ in movement} == {1, 2}
    assert all(duration == .08 for _, _, duration in movement)
    assert not control.margin_attempts
    events = json.loads(inputs.stats['steering_evidence_json'])['events']
    final = events[-1]
    assert final['state'] == 'observed' and final['after_verified'] and final['same_area']
    for slot, keys, duration in movement:
        row = final['players'][str(slot)]
        assert row['source'] == 'native_route' and row['same_actor']
        assert row['keys'] == keys and row['requested_game_seconds'] == duration
        nav = control.maps.get(st, st['players'][slot])
        assert nav.allowed(nav.cell((row['before']['x'], row['before']['z'])), nav.cell(row['waypoint']))


def test_new_view_never_borrows_buddys_floor_when_own_view_missing(current, tmp_path):
    st = copy.deepcopy(current)
    del st['geometry_players'][1]
    maps = Maps(tmp_path)
    assert maps.get(st, st['players'][1]).floor is None
    assert maps.get(st, st['players'][2]).floor
