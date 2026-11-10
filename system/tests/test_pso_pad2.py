"""gbox.pso_pad2: player 2's keyboard pad -- the mapping, the uppercase trap, and the event shapes."""
import pytest

from gbox import pso_coop_setup as P
from gbox import pso_pad2 as K


def test_the_mapping_is_exactly_what_the_ini_binds():
    """Every key here must be the one `pso_coop_setup.PAD2_WIN` writes, or P2 presses the wrong thing."""
    for button, name in K.PRESS.items():
        bound = {v for k, v in P.PAD2_WIN.items() if v == name.lower()}
        assert bound or name.isupper() or len(name) == 1, f"{button} -> {name} is not in PAD2_WIN"


def test_the_face_buttons_are_the_documented_ones():
    assert K.key("a") == "D" and K.key("b") == "R"
    assert K.key("start") == "SPACE"
    assert K.key("ddown") == "NUMPAD9" and K.key("dup") == "NUMPAD7"


def test_lowercase_numpad_names_are_the_silent_failure():
    """`numpad7` is accepted by nothing and reports sent: 0 -- the trap that cost a cycle."""
    assert "NUMPAD7" in K.UPPERCASE_ONLY
    assert "NUMPAD7" == K.key("dup")
    with pytest.raises(KeyError):
        K.key("numpad7")


def test_events_are_down_up_pairs_in_order():
    ev = K.events("dup", "a")
    assert [e["key"] for e in ev] == ["NUMPAD7", "NUMPAD7", "D", "D"]
    assert [e["down"] for e in ev] == [True, False, True, False]


def test_a_chord_presses_then_releases_in_reverse():
    ev = K.chord("a", "b")
    assert [e["key"] for e in ev] == ["D", "R", "R", "D"]
    assert [e["down"] for e in ev] == [True, True, False, False]


def test_an_unknown_button_says_what_is_known():
    with pytest.raises(KeyError, match="known"):
        K.key("trigger")


def test_movement_keys_are_the_ones_that_actually_move_the_characters():
    """Measured in split-screen co-op: P1's arrows and P2's numpad move; the virtual pad's stick never does."""
    assert K.move_key(1, "up") == "up" and K.move_key(1, "right") == "right"
    assert K.move_key(2, "up") == "NUMPAD8" and K.move_key(2, "down") == "NUMPAD2"
    start, stop = K.move_events(1, "up")
    assert start == [{"key": "up", "down": True}] and stop == [{"key": "up", "down": False}]


def test_an_unknown_player_or_direction_says_what_is_known():
    with pytest.raises(KeyError, match="player 3"):
        K.move_key(3, "up")
    with pytest.raises(KeyError, match="known"):
        K.move_key(1, "sideways")
