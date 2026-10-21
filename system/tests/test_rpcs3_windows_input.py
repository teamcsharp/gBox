"""Bot input for RPCS3 on Windows (gbox.adapters.RPCS3Adapter): a launch a bot drives (LaunchIn.pad = "keyboard", or a
demo / autoplay launch) starts RPCS3 with --input-config gbox-keyboard, and send_input posts the keyboard pad's keys to
the game window. Normal Play keeps the operator's controller (Default.yml) and has no send_input."""
from types import SimpleNamespace

import pytest

from gbox import adapters, provision
from gbox.config import Config
from gbox.registry import Unsupported

OPERATOR_PAD = 'Player 1 Input:\n  Handler: XInput\n  Device: "XInput Pad #1"\n'


@pytest.fixture
def launch(tmp_path, monkeypatch):
    """RPCS3Adapter.launch_game with the Windows-only parts stubbed: returns (adapter, argv of the RPCS3 it started)."""
    home = tmp_path / "rpcs3"
    pad = home / "config" / "input_configs" / "global" / "Default.yml"
    pad.parent.mkdir(parents=True)
    pad.write_text(OPERATOR_PAD)                                     # the operator's own controller config
    started = []
    monkeypatch.setattr(provision, "ensure_rpcs3", lambda *a, **k: None)
    monkeypatch.setattr(provision, "rpcs3_free_home", lambda cfg: home)
    monkeypatch.setattr(provision, "_rpcs3_busy", lambda home: False)
    monkeypatch.setattr(adapters, "keep_offscreen", lambda *a, **k: None)
    monkeypatch.setattr(adapters, "hidden_start", lambda: None)
    monkeypatch.setattr(adapters, "_audio_release", lambda ad: None)
    monkeypatch.setattr(adapters, "_kill_tree", lambda proc: None)
    monkeypatch.setattr(__import__("gbox.graphics", fromlist=["x"]), "prefer_gpu", lambda exe: None)
    monkeypatch.setattr(adapters.subprocess, "Popen",
                        lambda argv, **k: started.append(argv) or SimpleNamespace(pid=4321, poll=lambda: None))

    def run(**attrs):
        ad = adapters.RPCS3Adapter(Config(data_dir=tmp_path / "data"))
        for k, v in attrs.items():
            setattr(ad, k, v)
        detail = ad.launch_game(str(tmp_path / "game" / "PS3_GAME" / "USRDIR" / "EBOOT.BIN"))
        return ad, started[-1], detail
    run.home, run.started = home, started
    return run


def test_normal_play_keeps_the_operators_controller(launch):
    ad, argv, detail = launch()                                      # the operator's Play: no pad flag, no demo
    assert "--input-config" not in argv and argv[1] == "--no-gui"
    assert "send_input" not in ad.supported and ad.get_capabilities()["send_input"] == "unsupported"
    assert detail["pad"] == "the operator's controller"
    assert (launch.home / "config" / "input_configs" / "global" / "Default.yml").read_text() == OPERATOR_PAD
    with pytest.raises(Unsupported, match="operator's controller"):
        ad.send_input([{"key": "cross", "down": True}])


@pytest.mark.parametrize("attrs", [{"input_pad": "keyboard"}, {"demo": True}])
def test_bot_launch_starts_rpcs3_with_the_keyboard_pad(launch, attrs):
    ad, argv, detail = launch(**attrs)
    i = argv.index("--input-config")
    assert argv[i + 1] == "gbox-keyboard" and argv[-1].endswith("EBOOT.BIN") and i < len(argv) - 2
    kb = launch.home / "config" / "input_configs" / "global" / "gbox-keyboard.yml"
    assert kb.read_text() == adapters.RPCS3_KEYBOARD_INPUT                  # the Linux sessions' layout
    assert "    Cross: X\n" in kb.read_text() and "  Handler: Keyboard\n" in kb.read_text()
    assert (launch.home / "config" / "input_configs" / "global" / "Default.yml").read_text() == OPERATOR_PAD
    assert ad.get_capabilities()["send_input"] == "supported"
    assert "send_input" not in adapters.RPCS3Adapter.supported               # per session, never the class
    assert detail["pad"].startswith("keyboard pad")


def test_load_state_relaunch_keeps_the_sessions_pad(launch):
    ad, _, _ = launch(input_pad="keyboard")
    state = launch.home / "savestates" / "BLUS30491" / "BLUS30491_1.SAVESTAT"
    state.parent.mkdir(parents=True)
    state.write_bytes(b"state")
    assert ad.load_state()["loaded"] == state.name
    argv = launch.started[-1]
    assert argv[argv.index("--input-config") + 1] == "gbox-keyboard" and argv[-1] == str(state)
    op, _, _ = launch()                                              # an operator session relaunches with their pad
    op.load_state()
    assert "--input-config" not in launch.started[-1]


def test_send_input_posts_the_bound_keys_to_the_game_window(tmp_path, monkeypatch):
    ad = adapters.RPCS3Adapter(Config(data_dir=tmp_path))
    ad.keyboard_pad = True
    posted, sleeps = [], []
    monkeypatch.setattr(ad, "_game_window", lambda: 0xBEEF)
    monkeypatch.setattr(ad, "_post_key", lambda h, vk, down, extended=False: posted.append((h, vk, down, extended)))
    monkeypatch.setattr(adapters.time, "sleep", lambda s: sleeps.append(s))
    out = ad.send_input([{"key": "cross", "down": True}, {"key": "lup", "down": True}, {"key": "up", "down": True},
                         {"key": "start", "down": True}, {"key": "select", "down": True}, {"key": "b", "down": False},
                         {"key": "home", "down": True}, {"key": "x", "down": True, "player": 2}])
    assert [p[0] for p in posted] == [0xBEEF] * 6                    # every key to the game window itself
    assert [(vk, down, ext) for _, vk, down, ext in posted] == [
        (ord("X"), True, False),      # Cross = X
        (ord("W"), True, False),      # left stick up = W
        (0x26, True, True),           # D-pad up (RetroPad "up") = VK_UP, an extended key (not the keypad's 8)
        (0x0D, True, False),          # Start = Return
        (0x20, True, False),          # Select = Space
        (ord("X"), False, False)]     # RetroPad b = the bottom button = Cross: released
    assert sleeps == [0.06]                                          # a down + up in one batch is held a moment
    assert out == {"sent": 6, "skipped": ["home"]}                   # not a PS3 button; player 2 is left out


def test_wm_key_lparam_matches_the_keyboards_own():
    assert adapters.wm_key_lparam(0x2D, True) == 0x002D0001          # X down: repeat 1, scan code 0x2D
    assert adapters.wm_key_lparam(0x2D, False) == 0xC02D0001         # X up: previous-state + transition bits
    assert adapters.wm_key_lparam(0x48, True, extended=True) == 0x01480001   # Up arrow: extended bit
    assert adapters.wm_key_lparam(0x3C, False) == 0x1 | 0x3C << 16 | 0xC0 << 24   # what _hotkey posted for F2
