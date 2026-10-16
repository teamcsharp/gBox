from types import SimpleNamespace

from gbox import adapters


def _user32(foreground):
    return SimpleNamespace(GetForegroundWindow=lambda: foreground)


def test_focus_free_hotkeys_send_while_another_app_is_in_front():
    # hidden_ok=True are Dolphin's global F13-F15 chords: safe to send no matter which
    # window is in front (HotkeysRequireFocus=False, BackgroundInput=True), so a
    # save-before-switch no longer fails with "gBox or the emulator must be active".
    other_app = 0xCAFE
    assert adapters._win_input_in_front(_user32(other_app), root=None, hidden_ok=True) is True


def test_pad_input_still_requires_the_emulator_window_in_front():
    # Regular pad input (hidden_ok=False) must never type into another app.
    other_app = 0xCAFE
    assert adapters._win_input_in_front(_user32(other_app), root=None, hidden_ok=False) is False


def test_emulator_window_in_front_satisfies_both_paths():
    root = 0xBEEF
    assert adapters._win_input_in_front(_user32(root), root=root, hidden_ok=False) is True
    assert adapters._win_input_in_front(_user32(root), root=root, hidden_ok=True) is True


def test_no_foreground_window_never_sends():
    # A locked screen / secure desktop reports no foreground window: never send there.
    assert adapters._win_input_in_front(_user32(0), root=None, hidden_ok=True) is False
