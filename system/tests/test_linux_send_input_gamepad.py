"""#1153: linux RetroArch sessions deliver pad buttons over the network gamepad, not only xdotool keys."""
import socket
import struct
from types import SimpleNamespace

from gbox import adapters


def _adapter(port, hotkeys=False):
    a = object.__new__(adapters.RetroArchAdapter)
    a.remote_port, a.display, a.trigger_hotkeys, a.proc = port, SimpleNamespace(name=":99"), hotkeys, None
    return a


def test_linux_pad_buttons_use_network_gamepad_and_keys_fall_back_to_xdotool(monkeypatch):
    calls = []
    monkeypatch.setattr(adapters, "HOST_OS", "linux")
    monkeypatch.setattr(adapters.subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw["env"]["DISPLAY"])))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
        sk.bind(("127.0.0.1", 0)); sk.settimeout(2)
        a = _adapter(sk.getsockname()[1], hotkeys=True)
        out = a.send_input([{"key": "start", "down": True}, {"key": "start", "down": False},
                            {"key": "lup", "down": True}, {"key": "F1", "down": True}, {"key": "r2", "down": True}])
        msgs = [struct.unpack("<iiiiH2x", sk.recv(64)) for _ in range(3)]
    assert out == {"sent": 5, "network_gamepad": 3}
    assert msgs == [(0, 1, 0, adapters.RETROPAD_ID["start"], 1), (0, 1, 0, adapters.RETROPAD_ID["start"], 0),
                    (0, 5, 0, 1, (-0x7FFF) & 0xFFFF)]
    # a raw keysym and the R2 fast-forward hotkey still go to the session display as keys
    assert calls == [(["xdotool", "keydown", "Scroll_Lock", "keydown", adapters.PAD_KEYS[1]["r2"], "keydown", "F1"],
                      ":99")] or calls == [(["xdotool", "keydown", "Scroll_Lock", "keydown",
                                             adapters.PAD_KEYS[1]["r2"], "keydown", "F1"], ":99")]


def test_linux_without_gamepad_port_keeps_xdotool_path(monkeypatch):
    calls = []
    monkeypatch.setattr(adapters, "HOST_OS", "linux")
    monkeypatch.setattr(adapters.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    out = _adapter(None).send_input([{"key": "start", "down": True}, {"key": "start", "down": False}])
    assert out == {"sent": 2}
    assert calls == [["xdotool", "keydown", "Return", "sleep", "0.06", "keyup", "Return"]]
