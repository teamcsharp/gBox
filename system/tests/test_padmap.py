"""Controller maps (2026-10-20): the operator right-clicks a button on the controller picture and maps it; N64 plays
with the N64 stick on the left stick and the C buttons on the right stick by default, natively and streamed.

Native RetroArch window: the map becomes the core's remap file (RetroArch's input_remapping_load_file format) and the
N64 cores' standard layout is pinned in the core options. Streamed: the right stick reaches RetroArch's network RetroPad.
"""
import socket
import struct
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gbox import adapters, gamepads, graphics, padmap, provision
from gbox.config import Config, EmulatorConfig
from gbox.server import create_app

# RetroArch configuration.c input_remapping_load_file: the .rmp names, in RETRO_DEVICE_ID_JOYPAD_* / analog-bind order
RA_KEY_STRINGS = ["b", "y", "select", "start", "up", "down", "left", "right", "a", "x", "l", "r", "l2", "r2", "l3", "r3",
                  "l_x+", "l_x-", "l_y+", "l_y-", "r_x+", "r_x-", "r_y+", "r_y-"]


def _rmp(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = int(v.strip().strip('"'))
    return out


def test_families_and_validation():
    assert {padmap.family(p) for p in ("n64", "N64", "n64dd", "Nintendo 64", "Nintendo - Nintendo 64")} == {"n64"}
    assert padmap.clean("n64", {"r": "rup", "rup": "r", "b": "b"}) == {"r": "rup", "rup": "r"}      # identity dropped
    with pytest.raises(ValueError, match="not a control"):
        padmap.clean("n64", {"rz": "b"})
    with pytest.raises(ValueError, match="not an input"):
        padmap.clean("n64", {"b": "c_up"})
    with pytest.raises(ValueError):                                     # other consoles map their buttons only
        padmap.clean("snes", {"b": "rup"})
    assert padmap.clean("snes", {"b": "a", "a": "b"}) == {"b": "a", "a": "b"}


def test_rmp_default_n64_layout_is_identity_in_retroarch_ids():
    ids = _rmp(padmap.rmp_text("n64", {}))
    assert len(ids) == 24
    for i, name in enumerate(RA_KEY_STRINGS):                          # every control drives itself
        key = f"input_player1_btn_{name}" if i < 16 else f"input_player1_stk_{name}"
        assert ids[key] == i, key
    # the explicit default the operator asked for: C buttons = right stick, N64 stick = left stick
    assert ids["input_player1_stk_r_y-"] == 23 and ids["input_player1_stk_l_x+"] == 16
    assert padmap.rmp_text("n64", {}).startswith(padmap.MARK)


def test_rmp_c_up_on_rb_swaps_with_the_right_stick():
    ids = _rmp(padmap.rmp_text("n64", {"r": "rup", "rup": "r"}))
    assert ids["input_player1_btn_r"] == 23                            # RB -> right analog up (RARCH_ANALOG_RIGHT_Y_MINUS)
    assert ids["input_player1_stk_r_y-"] == 11                         # right stick up -> R (RETRO_DEVICE_ID_JOYPAD_R)
    assert ids["input_player1_btn_b"] == 0
    snes = _rmp(padmap.rmp_text("snes", {"b": "a", "a": "b"}))
    assert snes == {**{f"input_player1_btn_{n}": i for i, n in enumerate(RA_KEY_STRINGS[:16])},
                    "input_player1_btn_b": 8, "input_player1_btn_a": 0}   # no stick lines for a buttons-only console


def test_apply_writes_the_core_remap_where_retroarch_looks(tmp_path):
    remaps, core = tmp_path / "remaps", tmp_path / "cores" / "parallel_n64_libretro.dll"
    # RetroArch's config_load_remap: <input_remapping_directory>/<library_name>/<library_name>.rmp
    f = padmap.apply_retroarch(remaps, core, "n64", {"r": "rup", "rup": "r"})
    assert f == remaps / "ParaLLEl N64" / "ParaLLEl N64.rmp"
    assert _rmp(f.read_text())["input_player1_btn_r"] == 23
    # the server unreachable at launch: the last written map stays
    assert padmap.apply_retroarch(remaps, core, "n64", None) == f and _rmp(f.read_text())["input_player1_btn_r"] == 23
    # reset: the default layout written out
    padmap.apply_retroarch(remaps, core, "n64", {})
    assert _rmp(f.read_text())["input_player1_btn_r"] == 11
    # first launch without the server: the default layout, never nothing
    g = padmap.apply_retroarch(tmp_path / "fresh", tmp_path / "mupen64plus_next_libretro.dll", "n64dd", None)
    assert g == tmp_path / "fresh" / "Mupen64Plus-Next" / "Mupen64Plus-Next.rmp" and _rmp(g.read_text())["input_player1_btn_r"] == 11


def test_other_consoles_get_a_file_only_while_they_have_a_map(tmp_path):
    info = tmp_path / "RetroArch" / "info"
    info.mkdir(parents=True)
    (info / "snes9x_libretro.info").write_text('display_name = "Nintendo - SNES / SFC (Snes9x - Current)"\ncorename = "Snes9x"\n')
    remaps, core = tmp_path / "remaps", tmp_path / "cores" / "snes9x_libretro.dll"
    f = padmap.apply_retroarch(remaps, core, "snes", {"b": "a", "a": "b"}, info_dirs=(info,))
    assert f == remaps / "Snes9x" / "Snes9x.rmp" and _rmp(f.read_text())["input_player1_btn_b"] == 8
    assert padmap.apply_retroarch(remaps, core, "snes", {}, info_dirs=(info,)) is None and not f.exists()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text('input_player1_btn_b = "8"\n')                       # the operator's own remap (RetroArch menu)
    padmap.apply_retroarch(remaps, core, "snes", {}, info_dirs=(info,))
    assert f.read_text() == 'input_player1_btn_b = "8"\n', "a file gBox didn't write is never removed"
    padmap.apply_retroarch(remaps, core, "snes", {"y": "x", "x": "y"}, info_dirs=(info,))
    assert f.read_text().startswith(padmap.MARK)                       # gBox's map wins, the operator's file is kept once
    assert f.with_name("Snes9x.rmp.gbox-original").read_text() == 'input_player1_btn_b = "8"\n'
    assert padmap.apply_retroarch(remaps, tmp_path / "unknown_libretro.dll", "snes", {"b": "a"}) is None
    # the .info next to the core works too (a core library name gBox doesn't know)
    (tmp_path / "cores" / "info").mkdir(parents=True)
    (tmp_path / "cores" / "info" / "mesen_libretro.info").write_text('corename = "Mesen"\n')
    assert padmap.core_library(tmp_path / "cores" / "mesen_libretro.dll") == "Mesen"
    assert padmap.core_library("D:/gBox/runtime/cores/parallel_n64_libretro.dll") == "ParaLLEl N64"


def _adapter(tmp_path, monkeypatch, platform, host="windows"):
    monkeypatch.setattr(adapters, "HOST_OS", host)
    monkeypatch.setattr(provision, "ARCH", "x86_64")
    monkeypatch.setattr(gamepads, "retroarch_driver", lambda exe: "sdl2")
    monkeypatch.setattr(provision, "retroarch_exe", lambda cfg: tmp_path / "retroarch.exe")
    monkeypatch.setattr(graphics, "get", lambda cfg, game_id: {})
    monkeypatch.setattr(graphics, "retroarch_opts", lambda prefs, exe_dir: {})
    return adapters.RetroArchAdapter(EmulatorConfig(adapter="retroarch", executable="retroarch", core="parallel_n64"),
                                     config=Config(data_dir=tmp_path), platform=platform)


@pytest.mark.parametrize("host", ["windows", "linux"])
def test_n64_core_options_pin_the_standard_layout(tmp_path, monkeypatch, host):
    ad = _adapter(tmp_path, monkeypatch, "n64", host)
    co = ad.config.runtime / "retroarch" / "core-options.cfg"
    co.parent.mkdir(parents=True, exist_ok=True)
    co.write_text('parallel-n64-alt-map = "enabled"\nmupen64plus-u-cbutton = "C1"\nreicast_enable_rttb = "enabled"\n')
    ad._write_cfg()
    lines = co.read_text().splitlines()
    for key, value in adapters.N64_INPUT_OPTS.items():
        assert [l for l in lines if l.startswith(key + " ")] == [f'{key} = "{value}"']
    assert 'parallel-n64-alt-map = "disabled"' in lines and 'mupen64plus-u-cbutton = "C4"' in lines
    assert 'reicast_enable_rttb = "enabled"' in lines
    before = co.read_text()
    _adapter(tmp_path, monkeypatch, "psx", host)._write_cfg()
    assert co.read_text() == before                                    # other consoles leave the N64 options alone


def test_windows_session_reads_remaps_from_gboxs_folder_and_writes_the_map(tmp_path, monkeypatch, capsys):
    ad = _adapter(tmp_path, monkeypatch, "n64")
    text = ad._write_cfg().read_text()
    remaps = ad.config.runtime / "retroarch" / "remaps"
    for line in (f'input_remapping_directory = "{remaps}"', 'auto_remaps_enable = "true"', 'input_remap_binds_enable = "true"',
                 'input_remap_sort_by_controller_enable = "false"', 'remap_save_on_exit = "false"',
                 'notification_show_remap_load = "false"'):
        assert line in text
    ad.pad_map = {"r": "rup", "rup": "r"}                              # fetched at launch (tools._launch_game)
    ad._write_pad_remap(str(tmp_path / "cores" / "parallel_n64_libretro.dll"), str(tmp_path / "retroarch.exe"))
    assert _rmp((remaps / "ParaLLEl N64" / "ParaLLEl N64.rmp").read_text())["input_player1_btn_r"] == 23
    # an agent's capture session never uses the operator's map, and writes none
    ad2 = _adapter(tmp_path / "cap", monkeypatch, "n64")
    ad2.capture_backend = {"ra_cfg": {}, "core_options": {}}
    text2 = ad2._write_cfg().read_text()
    assert 'auto_remaps_enable = "false"' in text2
    ad2._write_pad_remap("parallel_n64_libretro.dll", "retroarch.exe")
    assert not (ad2.config.runtime / "retroarch" / "remaps").exists()


def test_linux_sessions_keep_retroarchs_remap_settings(tmp_path, monkeypatch):
    ad = _adapter(tmp_path, monkeypatch, "n64", "linux")
    text = ad._write_cfg().read_text()
    assert "input_remapping_directory" not in text                     # streamed: this page maps the pad, not RetroArch
    ad.pad_map = {"r": "rup", "rup": "r"}
    ad._write_pad_remap("parallel_n64_libretro.dll", "retroarch")
    assert not (ad.config.runtime / "retroarch" / "remaps").exists()


def test_right_stick_and_c_buttons_reach_the_network_retropad(monkeypatch):
    monkeypatch.setattr(adapters, "HOST_OS", "linux")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
        sk.bind(("127.0.0.1", 0)); sk.settimeout(2)
        a = object.__new__(adapters.RetroArchAdapter)
        a.remote_port, a.display, a.trigger_hotkeys, a.proc = sk.getsockname()[1], SimpleNamespace(name=":99"), False, None
        sent, rest = a.remote_input([{"key": "rup", "down": True}, {"key": "rup", "down": False}, {"key": "rright", "down": True},
                                     {"key": "cdown", "down": True}, {"key": "lleft", "down": True}])
        msgs = [struct.unpack("<iiiiH2x", sk.recv(64)) for _ in range(5)]
    assert (sent, rest) == (5, [])
    # struct remote_message {port, device = RETRO_DEVICE_ANALOG (5), index (1 = right stick), id (0 = x, 1 = y), state}
    assert msgs == [(0, 5, 1, 1, (-0x7FFF) & 0xFFFF), (0, 5, 1, 1, 0), (0, 5, 1, 0, 0x7FFF), (0, 5, 1, 1, 0x7FFF),
                    (0, 5, 0, 0, (-0x7FFF) & 0xFFFF)]


def test_controller_map_routes_round_trip_and_reach_the_worker(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")
    app = create_app(cfg)
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    assert client.get("/api/controller-maps").json()["maps"] == {}
    assert client.get("/api/controller-maps/n64").json() == {"platform": "n64", "map": {}, "sticks": True}
    r = client.post("/api/controller-maps/Nintendo 64", json={"map": {"r": "rup", "rup": "r", "b": "b"}})
    assert r.status_code == 200, r.text
    assert r.json() == {"platform": "n64", "map": {"r": "rup", "rup": "r"}, "sticks": True}
    assert client.get("/api/controller-maps").json()["maps"] == {"n64": {"r": "rup", "rup": "r"}}
    assert client.get("/api/controller-maps/n64dd").json()["map"] == {"r": "rup", "rup": "r"}      # one N64 controller
    assert client.post("/api/controller-maps/n64", json={"map": {"r": "c_up"}}).status_code == 422
    assert client.post("/api/controller-maps/snes", json={"map": {"b": "rup"}}).status_code == 422
    assert client.post("/api/controller-maps/!!", json={"map": {}}).status_code in (404, 422)
    assert any(e["action"] == "controller_map.set" for e in app.state.store.audit_for("n64"))
    # the worker's launch fetch
    monkeypatch.setattr("httpx.get", lambda url, headers=None, timeout=None: client.get(url.replace("http://plane", ""), headers=headers))
    assert padmap.fetch("http://plane", {}, "n64") == {"r": "rup", "rup": "r"}
    assert padmap.fetch("", {}, "n64") is None
    monkeypatch.setattr("httpx.get", lambda *a, **kw: (_ for _ in ()).throw(OSError("down")))
    assert padmap.fetch("http://plane", {}, "n64") is None             # the server unreachable: None, never an error
    assert client.post("/api/controller-maps/n64", json={"map": {}}).json()["map"] == {}
    assert client.get("/api/controller-maps").json()["maps"] == {}     # reset = the default layout again
