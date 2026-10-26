"""Stream cleanup must not make an unattended playbook yield to a phantom player."""
import pytest

from gbox import tools


@pytest.mark.parametrize("source", ["player", "ui", None])
def test_reconnect_releases_do_not_take_control_from_autoplay(source):
    # Browser releasePad()/GPU-surface blur send key-up batches when the stream
    # changes or input forwarding pauses. Default source is historically player.
    events = [{"key": key, "down": False, "player": 1} for key in ("lup", "cross", "r1")]
    if source is not None:
        for event in events:
            event["src"] = source
    assert not tools._player_takeover_input(events)


@pytest.mark.parametrize("event", [
    {"key": "cross", "down": True, "src": "player"},
    {"key": "lup", "down": True, "src": "ui"},
    {"key": "start"},
])
def test_real_player_press_still_hands_control_back(event):
    assert tools._player_takeover_input([{"key": "lup", "down": False}, event])


@pytest.mark.parametrize("event", [
    {"key": "cross", "down": True, "src": "autoplay"},
    {"key": "cross", "down": True, "src": "agent"},
    {"rpc": "inspection", "key": "cross", "src": "ui"},
    {"src": "player"},
    {"key": "", "src": "ui"},
    {"key": "cross", "down": None, "src": "player"},
    None,
])
def test_nonplayer_or_nonpress_events_do_not_request_takeover(event):
    assert not tools._player_takeover_input([event])
