"""Native slot drift must not fabricate a saved moment or a completed capture."""
import threading
from pathlib import Path

import pytest

from gbox import adapters as A


def adapter(tmp_path, requested=0):
    ad = A.RetroArchAdapter.__new__(A.RetroArchAdapter)
    ad.log_path = tmp_path / 'emulator.log'
    ad.log_path.write_text('older unrelated output\n')
    ad._state_lock = threading.RLock()
    ad._slot = lambda slot: requested
    return ad


@pytest.mark.parametrize('actual', [0, 23])
def test_returns_actual_completed_file_and_reconciles_slot(tmp_path, actual):
    ad = adapter(tmp_path)
    state = tmp_path / ('game.state' + (str(actual) if actual else ''))
    def command(text):
        assert text == 'SAVE_STATE'
        state.write_bytes(b'actual native snapshot')
        with ad.log_path.open('a') as stream:
            stream.write(f'[INFO] [State] Saving state "{state}", 22 bytes.\n')
    ad.cmd = command
    result = ad.save_state(0)
    assert result['path'] == str(state)
    assert result['bytes'] == state.stat().st_size
    assert result['verified'] is True
    assert result['slot'] == ad.slot == actual
    assert result['requested_slot'] == 0
    assert result['slot_verified'] is (actual == 0)
    assert ('warning' in result) is (actual != 0)


def test_old_save_log_and_missing_file_cannot_complete_capture(tmp_path, monkeypatch):
    ad = adapter(tmp_path)
    state = tmp_path / 'old.state'
    state.write_bytes(b'old moment')
    ad.log_path.write_text(f'[State] Saving state "{state}"\n')
    ad.cmd = lambda text: None
    ticks = iter([0, 0, 13])
    monkeypatch.setattr(A.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(A.time, 'sleep', lambda _: None)
    with pytest.raises(RuntimeError, match='did not produce a verified save file'):
        ad.save_state(0)


def test_log_tail_reads_bounded_bytes(tmp_path):
    ad = adapter(tmp_path)
    ad.log_path.write_bytes(b'x' * 2_000_000 + b'last visible bytes')
    assert ad.log_tail(18) == 'last visible bytes'
