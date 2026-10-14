import ctypes
from types import SimpleNamespace

import pytest

from gbox import adapters, tools


def user32(foreground=10, foreground_pid=100):
    def pid(hwnd, output):
        output._obj.value = foreground_pid
        return 1
    return SimpleNamespace(GetForegroundWindow=lambda: foreground, GetWindowThreadProcessId=pid)


def test_dolphin_hotkeys_accept_gpu_host_without_accepting_other_apps(monkeypatch):
    monkeypatch.setattr(tools, '_exe_name', lambda pid: 'gbox.exe')
    assert adapters._win_input_in_front(user32(), 20, True)
    assert adapters._win_input_in_front(user32(), None, True)
    assert not adapters._win_input_in_front(user32(), 20, False)
    monkeypatch.setattr(tools, '_exe_name', lambda pid: 'notepad.exe')
    assert not adapters._win_input_in_front(user32(), 20, True)
    assert not adapters._win_input_in_front(user32(0), None, True)
    assert adapters._win_input_in_front(user32(), 10, False)


@pytest.mark.parametrize('visible', [True, False])
def test_save_chord_reaches_dolphin_without_focusing_offscreen_window(monkeypatch, visible):
    sent, focused, sleeps = [], [], []
    u = user32()
    u.GetAncestor = lambda *_: 20
    u.AttachThreadInput = lambda *args: focused.append(args)
    u.SetFocus = lambda *args: focused.append(args)
    u.SendInput = lambda count, packet, size: sent.append((packet._obj.ki.wScan, packet._obj.ki.dwFlags)) or 1
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(user32=u, kernel32=SimpleNamespace()), raising=False)
    monkeypatch.setattr(adapters, '_pid_window', lambda pid: 20 if visible else None)
    monkeypatch.setattr(tools, '_exe_name', lambda pid: 'gbox.exe')
    monkeypatch.setattr(adapters.time, 'sleep', sleeps.append)
    seq = [{'key': k, 'down': down} for k, down in [('Control_R', True), ('Shift_R', True),
          ('F13', True), ('F13', False), ('Shift_R', False), ('Control_R', False)]]
    assert adapters.win_send_keys(42, seq, hidden_ok=True) == {'sent': 6}
    assert len(sent) == 6 and focused == []
    assert 0.1 not in sleeps  # no ten-second foreground wait while gBox itself is active


def test_background_hotkey_mode_cannot_type_ordinary_keys(monkeypatch):
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(user32=None, kernel32=None), raising=False)
    with pytest.raises(ValueError, match='only gBox Dolphin hotkeys'):
        adapters.win_send_keys(42, [{'key': 'a'}], hidden_ok=True)


def test_switching_to_another_app_releases_only_injected_modifiers(monkeypatch):
    sent = []
    u = user32()
    u.GetAncestor = lambda *_: 20
    def send(count, packet, size):
        sent.append((packet._obj.ki.wScan, packet._obj.ki.dwFlags))
        return 1
    u.SendInput = send
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(user32=u, kernel32=SimpleNamespace()), raising=False)
    monkeypatch.setattr(adapters, '_pid_window', lambda pid: 20)
    monkeypatch.setattr(adapters, '_win_input_in_front', lambda *a: not sent)
    result = adapters.win_send_keys(42, [{'key': 'Control_R', 'down': True}, {'key': 'F13', 'down': True}], hidden_ok=True)
    assert result['sent'] == 1 and result['stopped']
    assert sent == [(0x1d, 0x0009), (0x1d, 0x000b)]  # Ctrl down, then cleanup Ctrl up; no F13 in another app


def test_interrupted_dolphin_hotkey_does_not_wait_for_a_save_file(monkeypatch, tmp_path):
    from gbox.config import Config
    ad = adapters.DolphinWinAdapter(Config(data_dir=tmp_path), 'gamecube')
    ad.proc = SimpleNamespace(pid=42)
    monkeypatch.setattr(adapters, 'win_send_keys', lambda *a, **kw: {'sent': 0, 'stopped': 'focus changed'})
    monkeypatch.setattr(ad, '_wait_state', lambda *a: pytest.fail('must fail before waiting for a save that cannot arrive'))
    with pytest.raises(RuntimeError, match='interrupted'):
        ad.save_state()
