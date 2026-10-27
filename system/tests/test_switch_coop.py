"""Split screen in a Switch session on a Linux node (gbox.switch_coop, SwitchLinuxAdapter / CitronLinuxAdapter): Player
2's keyboard pad in a co-op launch's own config folder, Player 2's input path, and the controller applet's dialog
(docs/research/switch-coop-bot.md). Fixtures only: no live two-player run yet."""
from types import SimpleNamespace

import pytest

from gbox import adapters, provision, switch_coop
from gbox.config import Config
from gbox.registry import Unsupported
from gbox.yuzu_runtime import SWITCH_KEYS
from gbox.gamepads import YUZU_KEYBOARD_BUTTONS

# Player 1's keyboard pad as Citron stores it (live, the Spark's Citron home 2026-10-27): its Qt codes, the sticks'
# WASD / IJKL / Shift and the motion keys 7 / 8; Citron's default hotkeys
P1_CODES = set(YUZU_KEYBOARD_BUTTONS.values()) | {87, 65, 83, 68, 73, 74, 75, 76, 16777248, 55, 56}
HOTKEY_KEYSYMS = {"F2", "F4", "F5", "F6", "F8", "F9", "F10", "F11", "Escape", "minus", "equal"}


def cfg(tmp_path, **kw) -> Config:
    return Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache", **kw)


def citron(tmp_path):
    exe = tmp_path / "citron-dist" / "AppRun"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n")
    return adapters.CitronLinuxAdapter(cfg(tmp_path, switch_citron_appimage=str(exe.parent)))


def ensured(ad, monkeypatch):
    """_ensure with the real settings writer and co-op step; no provisioning, no LayeredFS selection."""
    monkeypatch.setattr(ad, "_provision", lambda progress=None: {})
    monkeypatch.setattr(ad, "select_overlay", lambda: {"selection": "original"})
    ad.nce, ad.debug, ad.port = True, False, 43210
    ad._ensure()
    return ad


# --- Player 2's keys -------------------------------------------------------------------------------------------------

def test_player_twos_keys_are_their_own():
    keysyms = [k for k, _ in switch_coop.P2_KEYS.values()]
    codes = [c for _, c in switch_coop.P2_KEYS.values()]
    assert len(set(keysyms)) == len(keysyms) and len(set(codes)) == len(codes)
    assert not set(keysyms) & set(SWITCH_KEYS.values())          # never one of Player 1's keys
    assert not set(keysyms) & HOTKEY_KEYSYMS                     # never one of Citron's hotkeys
    assert not set(codes) & P1_CODES
    for keysym, code in switch_coop.P2_KEYS.values():           # letters / digits: the Qt code is the uppercase ASCII
        if len(keysym) == 1:
            assert code == ord(keysym.upper())
    # every pad name a Switch bot presses has a Player 2 key (the sticks, the face buttons, the triggers, the d-pad)
    need = {"a", "b", "x", "y", "l", "r", "zl", "zr", "plus", "minus", "dup", "ddown", "dleft", "dright",
            "lup", "ldown", "lleft", "lright", "rup", "rdown", "rleft", "rright"}
    assert need <= switch_coop.P2_KEYS.keys()


def test_controls_connect_player_two_and_write_every_binding():
    values = switch_coop.controls()
    assert values["player_1_connected"] == "true" and values["player_1_type"] == "0"
    for name in switch_coop.BUTTONS:
        code = switch_coop.P2_KEYS.get(name, (None, 0))[1]
        assert values[f"player_1_button_{name}"] == f'"toggle:0,code:{code},engine:keyboard"'
    assert values["player_1_button_home"].endswith('code:0,engine:keyboard"')         # unbound, never P1's default
    assert "up:toggle$00$1code$089$1engine$0keyboard" in values["player_1_lstick"]   # y
    assert "right:toggle$00$1code$052$1engine$0keyboard" in values["player_1_rstick"]  # 4
    assert values["player_1_motionleft"] == values["player_1_motionright"] == '"toggle:0,code:0,engine:keyboard"'
    assert not any(k.startswith("player_0_") for k in values)    # Player 1 is never rewritten


def test_config_check_survives_the_emulators_own_rewrite():
    text = "[Controls]\n" + "\n".join(f"{k}={v}" for k, v in switch_coop.controls().items()) + "\n"
    assert switch_coop.config_ok(text)[0]
    # Citron saves its config at boot in its own field order: the check reads fields, not bytes
    reordered = text.replace('"toggle:0,code:53,engine:keyboard"', '"engine:keyboard,code:53,toggle:0"')
    assert switch_coop.config_ok(reordered)[0]
    assert not switch_coop.config_ok(text.replace("player_1_connected=true", "player_1_connected=false"))[0]
    wrong = text.replace("code:53,", "code:67,")                  # P2's A on P1's C
    assert switch_coop.config_ok(wrong) == (False, "Player 2's a binding differs from gBox's Player 2 keys")


def test_a_launch_asks_for_split_screen_explicitly():
    assert switch_coop.players_requested({"coop": {"players": 2, "mode": "operator_bot"}}) == 2
    assert switch_coop.players_requested({"mercmode": {"random_stages": True, "coop": "bots"}}) == 2
    assert switch_coop.players_requested({"mercmode": {"random_stages": True}}) == 1
    assert switch_coop.players_requested({"coop": {"players": "2"}}) == 1
    assert switch_coop.players_requested(None) == 1


# --- per-launch config -----------------------------------------------------------------------------------------------

def test_a_solo_launch_keeps_the_shared_config_and_never_connects_player_two(tmp_path, monkeypatch):
    ad = ensured(citron(tmp_path), monkeypatch)
    shared = provision.citron_linux_home(ad.config) / "config"
    assert ad.env["XDG_CONFIG_HOME"] == str(shared)
    text = provision.citron_linux_config(ad.config).read_text()
    assert adapters.ini_get(text, "Controls", "player_1_connected") is None
    assert not (provision.citron_linux_home(ad.config) / switch_coop.COOP_DIR).exists()


def test_a_coop_launch_reads_its_own_copy_with_player_two(tmp_path, monkeypatch):
    ad = citron(tmp_path)
    shared_ini = provision.citron_linux_config(ad.config)
    shared_ini.parent.mkdir(parents=True)
    (shared_ini.parent / "custom").mkdir()
    (shared_ini.parent / "custom" / "010018100CD46000.ini").write_text("[Renderer]\nx=1\n")
    shared_ini.write_text("[Controls]\nplayer_0_button_a=\"toggle:0,code:67,engine:keyboard\"\n")
    ad.coop_players = 2
    ensured(ad, monkeypatch)
    root = provision.citron_linux_home(ad.config) / switch_coop.COOP_DIR
    xdg = ad.env["XDG_CONFIG_HOME"]
    assert xdg.startswith(str(root)) and xdg != str(provision.citron_linux_home(ad.config) / "config")
    own = (switch_coop.Path(xdg) / "citron" / "qt-config.ini").read_text()
    assert switch_coop.config_ok(own)[0]
    assert adapters.ini_get(own, "Renderer", "backend") == "0"                   # this launch's settings came along
    assert 'code:67' in adapters.ini_get(own, "Controls", "player_0_button_a")   # Player 1 as it was
    assert (switch_coop.Path(xdg) / "citron" / "custom" / "010018100CD46000.ini").is_file()
    shared = shared_ini.read_text()
    assert adapters.ini_get(shared, "Controls", "player_1_connected") is None     # the node's config never gets P2
    # back to one player: the shared folder again, the copy removed
    ad.coop_players = 1
    ad._ensure()
    assert ad.env["XDG_CONFIG_HOME"] == str(provision.citron_linux_home(ad.config) / "config")
    assert not any(root.iterdir())


def test_the_launch_records_player_two_for_its_own_process(tmp_path, monkeypatch):
    ad = citron(tmp_path)
    ad.coop_players = 2
    ensured(ad, monkeypatch)
    started = []
    monkeypatch.setattr(switch_coop, "watch_applet", lambda a, alive: started.append(alive))
    ad._stopped = False
    ad.proc = SimpleNamespace(pid=900, poll=lambda: None)
    ad._coop_started()
    status = ad.teammate_pad_status()
    assert status["verified"] is True and status["requires_relaunch"] is False and status["keys"]["a"] == "5"
    assert len(started) == 1 and started[0]() is True             # the applet watcher runs for this process
    ad.proc = SimpleNamespace(pid=901, poll=lambda: None)         # another process (a restart not yet recorded)
    assert ad.teammate_pad_status()["verified"] is False and started[0]() is False
    solo = citron(tmp_path / "solo")
    ensured(solo, monkeypatch)
    solo._stopped, solo.proc = False, SimpleNamespace(pid=902, poll=lambda: None)
    solo._coop_started()
    assert solo.teammate_pad_status()["verified"] is False and len(started) == 1


def test_stop_removes_the_sessions_copy(tmp_path, monkeypatch):
    ad = citron(tmp_path)
    ad.coop_players = 2
    ensured(ad, monkeypatch)
    xdg = switch_coop.Path(ad.env["XDG_CONFIG_HOME"])
    assert xdg.is_dir()
    monkeypatch.setattr(ad, "_signal", lambda sig: 0)
    monkeypatch.setattr(adapters, "_kill_tree", lambda p: None)
    ad.proc = None
    ad.stop_game()
    assert not xdg.exists()


# --- Player 2's input ------------------------------------------------------------------------------------------------

def coop_ready(tmp_path, monkeypatch):
    ad = citron(tmp_path)
    ad.coop_players = 2
    ensured(ad, monkeypatch)
    monkeypatch.setattr(switch_coop, "watch_applet", lambda a, alive: None)
    ad._stopped, ad.proc = False, SimpleNamespace(pid=900, poll=lambda: None)
    ad._coop_started()
    return ad


def test_player_two_input_types_player_two_keys(tmp_path, monkeypatch):
    ad = coop_ready(tmp_path, monkeypatch)
    sent = []
    monkeypatch.setattr(ad, "_xdo", lambda *a: sent.append(list(a)))
    out = ad.send_input_player([{"key": "zl", "down": True, "player": 2}, {"key": "lup", "down": True},
                                {"key": "ZL", "down": False}, {"key": "start", "down": True}], player=2)
    assert out == {"sent": 4, "player": 2}
    assert sent == [["keydown", "p", "keydown", "y", "sleep", "0.06", "keyup", "p", "keydown", "semicolon"]]


@pytest.mark.parametrize("rows, player, why", [
    ([{"key": "a", "down": True}], 1, "only address Player 2"),
    ([{"key": "a", "down": True, "player": 1}], 2, "only address Player 2"),
    ([{"key": "a", "down": True}, {"key": "cross", "down": True}], 2, "no key for 'cross'"),
    ([{"key": "a", "down": "yes"}], 2, "Invalid Player 2 button state"),
    ([{"key": "a"}] * 129, 2, "exceeds its bound"),
])
def test_a_bad_player_two_batch_sends_nothing(tmp_path, monkeypatch, rows, player, why):
    ad = coop_ready(tmp_path, monkeypatch)
    sent = []
    monkeypatch.setattr(ad, "_xdo", lambda *a: sent.append(a))
    with pytest.raises(Unsupported, match=why):
        ad.send_input_player(rows, player=player)
    assert sent == []


def test_no_player_two_input_without_a_verified_coop_launch(tmp_path, monkeypatch):
    ad = ensured(citron(tmp_path), monkeypatch)                # a solo launch
    ad._stopped, ad.proc = False, SimpleNamespace(pid=903, poll=lambda: None)
    ad._coop_started()
    sent = []
    monkeypatch.setattr(ad, "_xdo", lambda *a: sent.append(a))
    with pytest.raises(Unsupported, match="no verified Player 2 controller"):
        ad.send_input_player([{"key": "a", "down": True}])
    assert sent == []


def test_player_one_input_never_types_a_player_two_event(tmp_path, monkeypatch):
    ad = coop_ready(tmp_path, monkeypatch)
    sent = []
    monkeypatch.setattr(ad, "_xdo", lambda *a: sent.append(list(a)))
    ad.send_input([{"key": "a", "down": True, "player": 2}, {"key": "b", "down": True}])
    assert sent == [["keydown", "x"]]


def test_prepare_takes_effect_at_the_next_restart_or_now_when_asked(tmp_path, monkeypatch):
    ad = citron(tmp_path)
    restarts = []
    monkeypatch.setattr(ad, "restart_title", lambda **kw: restarts.append(kw) or {"restarted": True})
    out = ad.prepare_teammate_pad(player=2)
    assert ad.coop_players == 2 and out["prepared"] is True and out["verified"] is False and restarts == []
    assert "next restart" in out["reason"]
    out = ad.prepare_teammate_pad(player=2, restart=True)
    assert restarts == [{"wait": False}] and out["restart"] == {"restarted": True}
    ad.prepare_teammate_pad(player=2, enabled=False)
    assert ad.coop_players == 1
    with pytest.raises(Unsupported):
        ad.prepare_teammate_pad(player=1)


# --- the controller applet -------------------------------------------------------------------------------------------

class Display:
    def __init__(self):
        self.windows, self.calls = [], []

    def out(self, *args):
        assert args == ("search", "--onlyvisible", "--name", switch_coop.APPLET_NAME)
        return "\n".join(self.windows)

    def xdo(self, *args):
        self.calls.append(args)


def test_the_applet_dialog_is_focused_and_confirmed(tmp_path):
    ad, d = SimpleNamespace(), Display()
    ad._xdo_out, ad._xdo = d.out, d.xdo
    assert switch_coop.accept_applet(ad, now=0.0) == 0 and d.calls == []
    d.windows = ["4194310"]
    assert switch_coop.accept_applet(ad, now=1.0) == 1
    assert d.calls == [("windowfocus", "4194310"), ("key", "Return")]
    assert switch_coop.accept_applet(ad, now=1.5) == 0            # still up: pressed again only after APPLET_RETRY_S
    assert switch_coop.accept_applet(ad, now=3.1) == 1
    d.windows = []
    switch_coop.accept_applet(ad, now=4.0)
    state = switch_coop.public(ad._coop_applet)
    assert state["seen"] == 1 and state["presses"] == 2 and state["accepted"] == 1 and state["left"] == 0


def test_a_dialog_that_will_not_close_is_left_and_reported(tmp_path):
    ad, d = SimpleNamespace(), Display()
    ad._xdo_out, ad._xdo = d.out, d.xdo
    d.windows = ["7"]
    for i in range(switch_coop.APPLET_MAX_PRESSES + 3):
        switch_coop.accept_applet(ad, now=i * 10.0)
    assert len([c for c in d.calls if c[0] == "key"]) == switch_coop.APPLET_MAX_PRESSES
    assert switch_coop.public(ad._coop_applet)["left"] == 1
