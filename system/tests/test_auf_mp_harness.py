from gbox import auf_mp_harness as h


def frame_with_dot(player, dx, dy, colour=(0, 100, 100)):
    cx, cy = h.RADAR_CENTRES[player]
    tx, ty = round(cx + dx), round(cy + dy)

    def pixel(x, y):
        if abs(x - tx) <= 1 and abs(y - ty) <= 1:
            return colour
        if (x, y) == (round(cx), round(cy)):
            return (0x99, 0, 0)  # own red dot must be ignored
        return (10, 20, 60)
    return pixel


def test_dot_colour_thresholds():
    assert h.is_other_player_dot((0, 0x64, 0x64))
    assert not h.is_other_player_dot((0x99, 0, 0))
    assert not h.is_other_player_dot((10, 20, 60))


def test_bearing_ahead_right_behind():
    b, d, n = h.radar_bearing(frame_with_dot(1, 0.5, -15.5), 1)
    assert abs(b) < 3 and 14 < d < 17 and n == 9
    b, _, _ = h.radar_bearing(frame_with_dot(1, 15.5, 0.5), 1)
    assert 85 < b < 95
    b, _, _ = h.radar_bearing(frame_with_dot(2, 0.5, 15, colour=(200, 20, 20)), 2)  # P2 sees P1 red
    assert abs(abs(b) - 180) < 5


def test_no_dot_and_outside_radius():
    assert h.radar_bearing(frame_with_dot(1, 0, 0, colour=(10, 20, 60)), 1) is None
    assert h.radar_bearing(frame_with_dot(1, 40, 0), 1) is None


def test_pause_sequences():
    assert list(h.pause_select(1, "Restart Mission")) == ["Return", "g", "g", "g", "x", "f", "x"]
    assert list(h.pause_select(2, "Continue Mission")) == ["6", "1"]
    assert list(h.pause_select(1, "Quit Mission", confirm=False)) == ["Return"] + ["g"] * 4 + ["x"]


def test_turn_key():
    assert h.turn_key(5) is None
    assert h.turn_key(40) == "Right"
    assert h.turn_key(-40, player=2) == "b"


def test_cycle_keys_maps_and_characters():
    assert h.cycle_keys(h.MP_MAPS, "Arsenal", "Cooling Station", "h", "f") == ["f", "f"]
    assert h.cycle_keys(h.MP_MAPS, "Dungeon", "Cooling Station", "h", "f") == ["f", "f", "f"]
    assert h.cycle_keys(h.MP_MAPS, "Castle", "Cooling Station", "h", "f") == ["h"]
    assert h.cycle_keys(h.MP_MAPS, "Abbey", "Abbey", "h", "f") == []
    assert h.MAP_LEVEL["Cooling Station"] == "maps/dm1.ngc"
    order = h.MP_CHARACTERS_WITH_BOND
    assert h.cycle_keys(order, "IDENTICON GUARD", "BOND", "o", "u") == ["o"]
    assert h.cycle_keys(order, "SUPER THUG", "BOND", "o", "u") == ["u"]
    assert set(h.MP_CHARACTERS) | {"BOND"} == set(order)


def test_other_player_dot_colour_depends_on_viewer():
    from gbox.auf_mp_harness import is_other_player_dot, radar_bearing, RADAR_CENTRES
    assert is_other_player_dot((0, 100, 100), 1) and not is_other_player_dot((0, 100, 100), 2)
    assert is_other_player_dot((200, 20, 20), 2) and not is_other_player_dot((200, 20, 20), 1)
    cx, cy = RADAR_CENTRES[2]
    # red dot 10 px to the right of P2's radar centre -> bearing +90
    def px(x, y):
        return (200, 20, 20) if abs(x - (cx + 10)) <= 1 and abs(y - cy) <= 1 else (0, 0, 0)
    b, d, n = radar_bearing(px, 2)
    assert abs(b - 90) < 5 and 8 < d < 12 and n >= 2
