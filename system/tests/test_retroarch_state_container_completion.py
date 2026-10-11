"""A stable asynchronous checkpoint may still have an unfinished container."""
import os
import struct
import threading
import zlib
from types import SimpleNamespace

import pytest

from gbox import adapters as A
from gbox import flycast_state as F
from gbox import tools


def rastate(mem):
    return (b'RASTATE\x01' + b'MEM ' + struct.pack('<I', len(mem)) + mem
            + bytes((-len(mem)) % 8) + b'END ' + bytes(4))


def rzip(data, codec=1):
    compress = zlib.compress if codec == 1 else pytest.importorskip('zstandard').ZstdCompressor().compress
    chunk = compress(data)
    return b'#RZIPv' + bytes([codec]) + b'#' + struct.pack('<IQI', 131072, len(data), len(chunk)) + chunk


class Clock:
    def __init__(self, callback=None):
        self.ticks = 0
        self.callback = callback

    def monotonic(self):
        return self.ticks * .1

    def sleep(self, _duration):
        self.ticks += 1
        if self.callback:
            self.callback(self.ticks)


def setup(tmp_path, monkeypatch, data, later=None):
    ad = A.RetroArchAdapter.__new__(A.RetroArchAdapter)
    ad.log_path = tmp_path / 'native.log'
    ad.log_path.write_text('old native output\n')
    ad._state_lock = threading.RLock()
    ad._slot = lambda slot: slot
    state = tmp_path / 'current.state9'
    started = 1_700_000_000_000_000_000
    monkeypatch.setattr(A.time, 'time_ns', lambda: started)

    def write(value):
        state.write_bytes(value)
        written_at = started + (clock.ticks + 1) * 100_000_000
        os.utime(state, ns=(written_at, written_at))

    clock = Clock(lambda ticks: write(later) if later is not None and ticks == 4 else None)
    monkeypatch.setattr(A.time, 'monotonic', clock.monotonic)
    monkeypatch.setattr(A.time, 'sleep', clock.sleep)

    def command(text):
        assert text == 'SAVE_STATE'
        write(data)
        with ad.log_path.open('a') as stream:
            stream.write(f'[State] Saving state "{state}", {len(data)} bytes.\n')

    ad.cmd = command
    return ad, state, clock, write


@pytest.mark.parametrize('kind', ['raw', 'rastate', 'rzip1', 'rzip2'])
def test_complete_non_flycast_state_retains_compatibility(tmp_path, monkeypatch, kind):
    mem = b'non-Flycast core state with arbitrary serializer version'
    data = {'raw': lambda: mem, 'rastate': lambda: rastate(mem),
            'rzip1': lambda: rzip(rastate(mem)), 'rzip2': lambda: rzip(rastate(mem), 2)}[kind]()
    ad, path, _clock, _write = setup(tmp_path, monkeypatch, data)
    result = ad.save_state(9)
    assert result['verified'] is True and result['path'] == str(path)
    assert result['bytes'] == len(data) and path.read_bytes() == data


@pytest.mark.parametrize('initial', ['truncated_chunk', 'zero_total', 'rastate_missing_end'])
def test_stable_incomplete_file_waits_for_actual_completed_container(tmp_path, monkeypatch, initial):
    complete = rzip(rastate(b'complete asynchronous core checkpoint'))
    if initial == 'zero_total':
        partial = bytearray(complete)
        struct.pack_into('<Q', partial, 12, 0)
        partial = bytes(partial)
    elif initial == 'rastate_missing_end':
        complete = rastate(b'complete asynchronous core checkpoint')
        partial = complete[:-8]
    else:
        partial = complete[:-5]
    ad, path, clock, _write = setup(tmp_path, monkeypatch, partial, complete)
    result = ad.save_state(9)
    assert clock.ticks >= 5  # More than two stable polls of the incomplete file.
    assert result['verified'] is True and result['bytes'] == len(complete)
    assert path.read_bytes() == complete


@pytest.mark.parametrize('malformed', ['zero_total_v2_chunks', 'zero_total_no_chunks', 'truncated_chunk',
                                     'trailing', 'empty_mem', 'empty_raw', 'missing_end'])
def test_permanently_incomplete_capture_times_out_without_verified_result(tmp_path, monkeypatch, malformed):
    complete = rzip(rastate(b'core checkpoint'))
    cases = {
        'zero_total_v2_chunks': b'#RZIPv\x02#' + struct.pack('<IQ', 131072, 0) + complete[20:],
        'zero_total_no_chunks': b'#RZIPv\x02#' + struct.pack('<IQ', 131072, 0),
        'truncated_chunk': complete[:-1], 'trailing': complete + b'extra bytes',
        'empty_mem': rastate(b''), 'empty_raw': b'', 'missing_end': rastate(b'core')[:-8],
    }
    ad, path, clock, _write = setup(tmp_path, monkeypatch, cases[malformed])
    with pytest.raises(RuntimeError, match='capture was not completed') as failure:
        ad.save_state(9)
    assert clock.monotonic() >= 12 and path.read_bytes() == cases[malformed]
    if malformed != 'empty_raw':
        assert 'last container validation:' in str(failure.value)


def test_validation_cannot_accept_a_file_changed_during_decode(tmp_path, monkeypatch):
    old = rzip(rastate(b'A' * 128))
    new = rzip(rastate(b'B' * 128))
    ad, path, clock, write = setup(tmp_path, monkeypatch, old)
    unpack = F.unpack
    calls = []

    def racing_unpack(data):
        calls.append(data)
        result = unpack(data)
        if len(calls) == 1:
            write(new)
        return result

    monkeypatch.setattr(F, 'unpack', racing_unpack)
    result = ad.save_state(9)
    assert calls == [old, new] and clock.ticks >= 3
    assert result['verified'] is True and result['bytes'] == len(new)
    assert path.read_bytes() == new


def test_open_file_identity_change_is_rejected_before_decode(tmp_path):
    path = tmp_path / 'identity.state'
    path.write_bytes(rzip(rastate(b'core')))
    expected = path.stat()
    mismatch = SimpleNamespace(**{key: getattr(expected, key) for key in
                                 ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')})
    mismatch.st_ino += 1
    with pytest.raises(ValueError, match='changed before validation'):
        A._validate_completed_state_file(path, mismatch)


def test_encoded_container_read_is_bounded_before_allocation(tmp_path, monkeypatch):
    path = tmp_path / 'oversize.state'
    path.write_bytes(rzip(rastate(b'core state')))
    monkeypatch.setattr(F, 'MAX_STATE_BYTES', 16)
    monkeypatch.setattr(F, 'MAX_RZIP_CHUNK', 8)
    with pytest.raises(ValueError, match='inspection budget'):
        A._validate_completed_state_file(path, path.stat())


def test_small_container_read_does_not_allocate_global_budget(tmp_path, monkeypatch):
    from pathlib import Path
    path = tmp_path / 'small.state'
    data = rzip(rastate(b'core state'))
    path.write_bytes(data)
    real_open = Path.open
    reads = []

    class Reader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, n):
            reads.append(n)
            return self.stream.read(n)

    monkeypatch.setattr(Path, 'open', lambda self, *a, **k: Reader(real_open(self, *a, **k)))
    A._validate_completed_state_file(path, path.stat())
    assert reads and all(0 <= n <= len(data) + 1 for n in reads)


def test_timeout_prevents_exporting_an_unfinished_checkpoint(tmp_path, monkeypatch):
    incomplete = b'#RZIPv\x02#' + struct.pack('<IQ', 131072, 0) + b'unfinished chunk'
    ad, _path, _clock, _write = setup(tmp_path, monkeypatch, incomplete)
    monkeypatch.setitem(tools.SESSIONS, 'adapter-container-capture', (ad, {'_rom_path': 'current.rom'}))
    artifacts = []
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path),
                          artifact=lambda *a, **k: artifacts.append((a, k)))
    with pytest.raises(RuntimeError, match='capture was not completed'):
        tools.state_transfer(tools.StateXIn(session_id='adapter-container-capture', op='export'), ctx)
    assert artifacts == []
