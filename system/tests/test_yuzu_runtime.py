from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import adapters, yuzu_runtime as Y
from gbox.config import Config, EmulatorConfig


def test_debug_config_preserves_other_settings_and_original(tmp_path):
    path = tmp_path / 'qt-config.ini'
    original = b'[Renderer]\nbackend=1\n[Debugging]\nuse_gdbstub=false\nother=kept\n[Controls]\nbutton=a\n'
    path.write_bytes(original)
    Y.set_debug_config(path, port=43210)
    text = path.read_text()
    assert 'use_gdbstub=true' in text and 'gdbstub_port=43210' in text
    assert 'backend=1' in text and 'other=kept' in text and 'button=a' in text
    assert text.index('gdbstub_port=') < text.index('[Controls]')
    assert path.with_name('qt-config.ini.gbox-debug-original').read_bytes() == original
    Y.set_debug_config(path, port=6543, enabled=False, dump_nso=False)
    assert 'use_gdbstub=false' in path.read_text() and 'dump_nso=false' in path.read_text()
    assert path.with_name('qt-config.ini.gbox-debug-original').read_bytes() == original


def test_debug_config_refuses_shared_or_outside_runtime(tmp_path):
    cfg = SimpleNamespace(runtime=tmp_path / 'runtime', data_dir=tmp_path / 'data')
    path = tmp_path / 'outside' / 'user/config/qt-config.ini'
    path.parent.mkdir(parents=True)
    path.write_text('[Debugging]\n')
    with pytest.raises(ValueError, match='private local'):
        Y.private_debug_config(path.parents[2] / 'yuzu.exe', cfg)
    with pytest.raises(ValueError, match='private local'):
        Y.private_debug_config(Path('//server/shared/yuzu.exe'), cfg)


def test_switch_input_translates_only_known_controls():
    assert Y.input_events([{'key': 'A', 'down': True}, {'key': 'lup', 'down': False}]) == [
        {'key': 'c', 'down': True}, {'key': 'w', 'down': False}]
    with pytest.raises(ValueError, match='Unknown Switch'):
        Y.input_events([{'key': 'F4', 'down': True}])


def test_yuzu_explicit_executable_and_debug_flag(tmp_path, monkeypatch):
    exe = tmp_path / 'yuzu.exe'
    cfg = Config(emulators={'switch': EmulatorConfig(adapter='yuzu', executable=str(exe))})
    monkeypatch.setattr(adapters, 'HOST_OS', 'windows')
    ad = adapters.for_game({'platform': 'switch'}, cfg, debug=True)
    assert ad._exe() == exe and ad.debug is True
    assert ad.get_capabilities()['read_memory'] == 'unsupported'


def test_yuzu_launch_shows_nonminimized_window_before_publishing(tmp_path, monkeypatch):
    from gbox import gamepads
    exe = tmp_path / 'yuzu.exe'
    exe.write_bytes(b'test')
    cfg = Config(data_dir=tmp_path / 'data', emulators={
        'switch': EmulatorConfig(adapter='yuzu', executable=str(exe))})
    ad = adapters.YuzuAdapter(cfg)
    calls = []
    proc = SimpleNamespace(pid=123, poll=lambda: None)
    monkeypatch.setattr(adapters, 'HOST_OS', 'windows')
    monkeypatch.setattr(gamepads, 'sdl2_xbox_guid', lambda _: None)
    monkeypatch.setattr(gamepads, 'emulator_environment', lambda env: env)
    monkeypatch.setattr(adapters, 'capture_start', lambda: 'shown-without-activation')
    monkeypatch.setattr(adapters, 'hidden_start', lambda: pytest.fail('Minimized windows cannot satisfy readiness'))
    monkeypatch.setattr(adapters.subprocess, 'Popen', lambda argv, **kw: calls.append(kw) or proc)
    monkeypatch.setattr(adapters, 'keep_offscreen', lambda pid: calls.append({'parked': pid}))
    monkeypatch.setattr(adapters, '_pid_window', lambda pid: 7)
    monkeypatch.setattr(adapters, '_examine_ok', lambda *args: False)
    out = ad.launch_game('owned.nsp')
    assert calls[0]['startupinfo'] == 'shown-without-activation'
    assert calls[1] == {'parked': 123}
    assert out['pid'] == 123 and out['validation'] == 'window_open; gameplay not yet verified'


def test_arm64_disassembly_for_switch():
    from gbox.debug import CPUS, disassemble
    assert CPUS['switch'] == 'arm64'
    assert disassemble('arm64', bytes.fromhex('c0035fd6'), 0x7100000000)[0]['mnemonic'] == 'ret'
