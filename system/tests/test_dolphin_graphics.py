"""RE4 (G4BE08) comes up on Dolphin with AA, 16x anisotropic filtering and a raised internal resolution, on every
launch path, without touching other games or any file the operator owns.

Only argv preparation runs: no emulator, game input, global settings or real memory cards are opened.
"""
from pathlib import Path
import struct
from types import SimpleNamespace
import zlib

import pytest

from gbox import adapters, cheats, graphics
from gbox.config import Config

GFX_KEYS = ("GFX.Settings.InternalResolution", "GFX.Settings.MSAA", "GFX.Settings.SSAA",
            "GFX.Enhancements.MaxAnisotropy")


def disc(path: Path, serial: bytes) -> str:
    header = serial + bytes(0x8000 - len(serial))
    if path.suffix == '.gcz':
        first = zlib.compress(header)
        path.write_bytes(struct.pack('<IIQQII', 0xB10BC001, 0, len(first), len(header) * 2,
                                     len(header), 2) + struct.pack('<QQII', 0, len(first), 0, 0) + first)
    else:
        path.write_bytes(header)
    return str(path)


def prepare(tmp_path, monkeypatch, cls):
    adapter = cls(Config(data_dir=tmp_path / 'data'), 'gamecube')
    if cls is adapters.DolphinWinAdapter:
        exe = tmp_path / 'Dolphin-x64/gBox Dolphin.exe'
        exe.parent.mkdir()
        exe.write_bytes(b'not executed')
        monkeypatch.setattr(adapter, '_exe', lambda: exe)
        monkeypatch.setattr(adapter, '_claim_lane', lambda: 'F13')
        user = exe.parent / 'User'
        monkeypatch.setattr(adapters, '_audio_selection', lambda *args: {'chosen': {'none': True}})
    else:
        user = adapter.config.runtime / 'dolphin-user'
    monkeypatch.setattr(cheats, 'gecko_codes', lambda *args: [])
    (user / 'Config').mkdir(parents=True)
    (user / 'GameSettings').mkdir()
    global_ini = user / 'Config/Dolphin.ini'
    gfx_ini = user / 'Config/GFX.ini'
    other_ini = user / 'GameSettings/GBIE08.ini'
    global_ini.write_bytes(b'[Core]\r\nCPUThread = True\r\n')
    gfx_ini.write_bytes(b'[Settings]\r\nInternalResolution = 1\r\nMSAA = 1\r\n[Hacks]\r\nEFBToTextureEnable = True\r\n')
    other_ini.write_bytes(b'[Core]\nCPUThread = True\n[Video_Settings]\nCustom = keep\n')
    return adapter, user, (global_ini, gfx_ini, other_ini)


def gfx(argv: list[str]) -> dict:
    return dict(a.split('=', 1) for a in argv if a.startswith(('GFX.Settings.', 'GFX.Enhancements.'))
                and a.split('=', 1)[0] in GFX_KEYS)


@pytest.mark.parametrize('cls', [adapters.DolphinAdapter, adapters.DolphinWinAdapter])
@pytest.mark.parametrize('extension', ['.gcz', '.iso'])
def test_re4_launches_with_aa_af_and_raised_internal_resolution(tmp_path, monkeypatch, cls, extension):
    adapter, user, files = prepare(tmp_path, monkeypatch, cls)
    saved = {path: path.read_bytes() for path in files}
    rom = disc(tmp_path / ('Resident Evil 4 (USA) (Disc 1)' + extension), b'G4BE08')
    argv = adapter._argv(rom)
    # the Windows window is the operator's own screen (3x); the Spark's 1280x720 display shows RE4's frame about
    # 1280x983, 2x (capped at 2x)
    ir = '3' if cls is adapters.DolphinWinAdapter else '2'
    assert gfx(argv) == {'GFX.Settings.InternalResolution': ir, 'GFX.Settings.MSAA': '4', 'GFX.Settings.SSAA': 'False',
                         'GFX.Enhancements.MaxAnisotropy': '4'}
    for key, value in gfx(argv).items():          # each passes through Dolphin's command-line layer
        assert argv[argv.index(f'{key}={value}') - 1] == '-C'
    assert argv[-2:] == ['-e', rom]
    # nothing on disk changes: Dolphin's own GFX.ini / Dolphin.ini and other games' INIs are untouched
    assert all(path.read_bytes() == data for path, data in saved.items())
    # idempotent: a relaunch (MercMode hang relaunch, autoplay) asks for exactly the same settings
    assert gfx(adapter._argv(rom)) == gfx(argv)


@pytest.mark.parametrize('cls', [adapters.DolphinAdapter, adapters.DolphinWinAdapter])
@pytest.mark.parametrize('serial', [b'GMSE01', b'GRSEAF', b'GBIE08'])
def test_other_games_get_no_graphics_overrides(tmp_path, monkeypatch, cls, serial):
    adapter, user, files = prepare(tmp_path, monkeypatch, cls)
    saved = {path: path.read_bytes() for path in files}
    argv = adapter._argv(disc(tmp_path / 'other.iso', serial))
    assert gfx(argv) == {}
    own_ini = user / f'GameSettings/{serial.decode()}.ini'
    assert all(path.read_bytes() == data for path, data in saved.items() if path != own_ini)
    if own_ini in saved:                          # the launched game's INI only gains its Gecko sections
        assert own_ini.read_bytes().replace(b'\r\n', b'\n').startswith(saved[own_ini])


@pytest.mark.parametrize('cls', [adapters.DolphinAdapter, adapters.DolphinWinAdapter])
def test_saved_graphics_choice_for_re4_wins_over_the_preset(tmp_path, monkeypatch, cls):
    adapter, user, files = prepare(tmp_path, monkeypatch, cls)
    adapter.game_id = '78ab9efa2e310db4'
    # this host's Graphics panel (data_dir/graphics.json): a slower PC turned RE4 down
    graphics.save(adapter.config, adapter.game_id, {'res_scale': 150, 'aniso': 8},
                  graphics.preset_for('dolphin', 'G4BE08'))
    argv = adapter._argv(disc(tmp_path / 're4.gcz', b'G4BE08'))
    assert gfx(argv) == {'GFX.Settings.InternalResolution': '2', 'GFX.Settings.MSAA': '4', 'GFX.Settings.SSAA': 'False',
                         'GFX.Enhancements.MaxAnisotropy': '3'}


def test_capture_sessions_keep_dolphins_own_graphics(tmp_path, monkeypatch):
    adapter, user, files = prepare(tmp_path, monkeypatch, adapters.DolphinWinAdapter)
    adapter.capture_backend = {'driver': 'vulkan', 'attach': 'layer'}
    argv = adapter._argv(disc(tmp_path / 're4.gcz', b'G4BE08'))
    assert gfx(argv) == {}


@pytest.mark.parametrize('cls', [adapters.DolphinAdapter, adapters.DolphinWinAdapter])
def test_operator_game_properties_survive_the_gecko_rewrite(tmp_path, monkeypatch, cls):
    adapter, user, files = prepare(tmp_path, monkeypatch, cls)
    ini = user / 'GameSettings/G4BE08.ini'
    ini.write_text('[Video_Hacks]\nEFBToTextureEnable = False\n[Gecko]\n$Old\n04000000 00000000\n'
                   '[Gecko_Enabled]\n$Old\n[Video_Settings]\nInternalResolution = 2\n', encoding='utf-8')
    rom = disc(tmp_path / 're4.gcz', b'G4BE08')
    adapter._argv(rom)
    adapter._argv(rom)
    text = ini.read_text(encoding='utf-8')
    # gBox owns only the Gecko sections; Dolphin's game INI layer (above -C) keeps the operator's choices
    assert '[Video_Hacks]\nEFBToTextureEnable = False\n' in text
    assert '[Video_Settings]\nInternalResolution = 2\n' in text
    assert text.count('[Gecko]') == 1 and text.count('[Gecko_Enabled]') == 1 and '$Old' not in text


def test_dolphin_opts_mapping():
    assert graphics.dolphin_opts(graphics.DEFAULT) == {'GFX.Settings.InternalResolution': '1',
                                                       'GFX.Settings.MSAA': '4', 'GFX.Settings.SSAA': 'False'}
    p = graphics.DEFAULT | {'res_scale': 400, 'msaa': 'off', 'aniso': 2}
    assert graphics.dolphin_opts(p) == {'GFX.Settings.InternalResolution': '4', 'GFX.Settings.MSAA': '1',
                                        'GFX.Settings.SSAA': 'False', 'GFX.Enhancements.MaxAnisotropy': '1'}
    assert graphics.dolphin_opts(p, max_res_scale=200)['GFX.Settings.InternalResolution'] == '2'
    assert graphics.preset_for('dolphin', 'GMSE01') == {} and graphics.preset_for('rpcs3', 'G4BE08') == {}


def test_graphics_panel_shows_and_keeps_the_re4_preset(tmp_path, monkeypatch):
    from gbox import tools
    from gbox.registry import REGISTRY
    from gbox.tools import Ctx
    monkeypatch.setattr(graphics, 'gpu', lambda: {'name': 'Test GPU', 'vram_mb': 8192})
    sid = 'worker-session'
    monkeypatch.setitem(tools.SESSIONS, sid, (SimpleNamespace(name='dolphin', gecko_id='G4BE08'),
                                              {'game_id': '78ab9efa2e310db4'}))
    ctx = Ctx(Config(data_dir=tmp_path))
    run = REGISTRY['graphics'].fn
    result = run(tools.GraphicsIn(game_id='78ab9efa2e310db4', session_id=sid), ctx)['result']
    assert set(result['choices']) == {'res_scale', 'msaa', 'aniso'}
    assert result['prefs'] == {'res_scale': 300, 'msaa': 'auto', 'aniso': 16}
    # changing one control keeps the rest of the preset
    result = run(tools.GraphicsIn(game_id='78ab9efa2e310db4', session_id=sid, op='set', prefs={'aniso': 8}), ctx)['result']
    assert result['prefs'] == {'res_scale': 300, 'msaa': 'auto', 'aniso': 8}
    # another GameCube game shows the plain defaults (and launches with no overrides until saved)
    monkeypatch.setitem(tools.SESSIONS, sid, (SimpleNamespace(name='dolphin', gecko_id='GMSE01'), {'game_id': 'sunshine'}))
    result = run(tools.GraphicsIn(game_id='sunshine', session_id=sid), ctx)['result']
    assert result['prefs'] == {'res_scale': 100, 'msaa': 'auto', 'aniso': 0}
