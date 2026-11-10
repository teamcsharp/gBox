"""gbox.pso_coop.Controller._nearest_warp: pick the FORWARD teleporter, not the pad
P1 just stepped off. A zone's teleporter pair is bidirectional, so pure
nearest-distance snaps back to the entry pad instead of advancing the zone."""
import math

from gbox import pso_coop as C


def pad(x, z, room=None, cls='Teleport'):
    e = {'x': x, 'z': z, 'class': cls}
    if room is not None:
        e['room'] = room
    return e


def bare():
    return object.__new__(C.Controller)


def test_single_pad_is_never_dropped_even_if_it_is_the_entry_pad():
    # A one-pad room must not strand the bot: even a backtrack-lookalike pad wins.
    state = {'entities': [pad(0.0, 0.0, room=10)]}
    c = bare()
    assert c._nearest_warp(state, 10, 1.0, 0.0, entry=(0.0, 0.0))['x'] == 0.0


def test_entry_none_preserves_nearest_distance_behavior():
    state = {'entities': [pad(0.0, 0.0, room=10), pad(100.0, 0.0, room=10)]}
    c = bare()
    assert c._nearest_warp(state, 10, 5.0, 0.0)['x'] == 0.0


def test_backtrack_pad_within_radius_is_skipped_when_a_forward_pad_exists():
    # P1 entered at x=0 (the pad right behind him), stepped forward to x ~ 3+, and
    # the forward pad sits far away. The entry pad must be dropped.
    state = {'entities': [pad(0.0, 0.0, room=10), pad(120.0, 0.0, room=10)]}
    c = bare()
    chosen = c._nearest_warp(state, 10, 3.0, 0.0, entry=(0.0, 0.0))
    assert chosen['x'] == 120.0


def test_forward_filter_falls_back_when_every_pad_is_near_entry():
    # If (incorrectly) both pads read within BACKTRACK_RADIUS of entry, keep the
    # nearest rather than returning None and stalling.
    state = {'entities': [pad(0.0, 0.0, room=10), pad(10.0, 0.0, room=10)]}
    c = bare()
    chosen = c._nearest_warp(state, 10, 3.0, 0.0, entry=(0.0, 0.0))
    assert chosen is not None and chosen['x'] == 0.0


def test_same_room_beats_off_room_before_entry_filtering():
    # Same-room preference still holds; the off-room forward pad must not win just
    # because the same-room pad is the entry pad when it is the ONLY same-room pad.
    state = {'entities': [pad(0.0, 0.0, room=10), pad(200.0, 0.0, room=99)]}
    c = bare()
    assert c._nearest_warp(state, 10, 3.0, 3.0, entry=(0.0, 0.0))['room'] == 10


def test_no_warps_returns_none():
    assert bare()._nearest_warp({'entities': []}, 10, 0.0, 0.0, entry=(0.0, 0.0)) is None


def test_non_finite_or_misclassed_entities_are_ignored():
    state = {'entities': [pad(float('nan'), 0.0, room=10),
                          {'x': 0.0, 'z': 0.0, 'class': 'Monster'},
                          pad(50.0, 0.0, room=10)]}
    c = bare()
    assert c._nearest_warp(state, 10, 3.0, 0.0, entry=(0.0, 0.0))['x'] == 50.0
