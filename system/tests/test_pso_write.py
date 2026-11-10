"""gbox.pso_write: the audited write path, its five-minute gate and its verification, without an emulator."""
import struct

import pytest

from gbox import pso_write as W


class Machine:
    """A tiny model of the game's memory plus the job queue (queued until a gate opens)."""

    def __init__(self, memory: dict[int, bytes], gate_polls: int = 2):
        self.memory = dict(memory)
        self.gate = gate_polls
        self.jobs = {}
        self.n = 0
        self.polls = 0

    def read(self, address, length):
        return self.memory[address][:length]

    def submit(self, job):
        assert job["tool"] == "write_memory"
        self.n += 1
        jid = f"job{self.n}"
        self.jobs[jid] = {"id": jid, "state": "queued", "input": job["input"]}
        return self.jobs[jid]

    def status(self, jid):
        self.polls += 1
        record = self.jobs[jid]
        if record["state"] == "queued":
            if self.polls < self.gate:
                return record
            data = bytes.fromhex(record["input"]["hex_bytes"])
            addr = record["input"]["address"]
            before = self.memory[addr]
            self.memory[addr] = data + before[len(data):]
            record["state"] = "succeeded"
            record["output"] = {"result": {"verified": True, "via": "process memory",
                                           "rollback_hex": before[:len(data)].hex()}}
        return record


def test_a_write_that_lands_is_verified_and_its_rollback_kept():
    m = Machine({0x1000 + 0x38: b"\x00" * 12})
    out = W.write_position(m.read, m.submit, m.status, "sid", 0x1000, 1.0, 2.0, -3.0,
                           sleep=lambda _s: None)
    assert out["verified"] is True
    assert struct.unpack(">3f", m.memory[0x1000 + 0x38]) == (1.0, 2.0, -3.0)
    assert out["before"] == "00" * 12
    assert out["after"] == struct.pack(">3f", 1.0, 2.0, -3.0).hex()


def test_a_queued_job_is_waited_out_not_treated_as_a_failure():
    """The five-minute gate: a write right after pad input sits queued, and that is normal."""
    m = Machine({0x1000: b"\x00" * 4}, gate_polls=3)
    out = W.write_float(m.read, m.submit, m.status, "sid", 0x1000, 5.5, sleep=lambda _s: None)
    assert out["verified"] is True
    assert struct.unpack(">f", m.memory[0x1000])[0] == 5.5
    assert m.polls == 3


def test_a_write_the_game_does_not_acknowledge_raises():
    m = Machine({0x1000: b"\x00" * 4})
    m.status = lambda jid: {"id": jid, "state": "succeeded", "output": {"result": {"verified": False}}}
    with pytest.raises(W.WriteError, match="not acknowledged"):
        W.write_bytes(m.read, m.submit, m.status, "sid", 0x1000, b"\x01\x02", sleep=lambda _s: None)


def test_a_write_the_game_keeps_rewriting_raises():
    """The room field is game-derived: the write is acknowledged and then immediately overwritten."""
    m = Machine({0x1000: b"\x00\x29"})
    m.status = lambda jid: {"id": jid, "state": "succeeded",
                            "output": {"result": {"verified": True, "rollback_hex": "0029"}}}
    with pytest.raises(W.WriteError, match="read back"):
        W.write_bytes(m.read, m.submit, m.status, "sid", 0x1000, b"\x00\x0a", sleep=lambda _s: None)


def test_a_failed_job_reports_its_error():
    m = Machine({0x1000: b"\x00" * 4})
    m.status = lambda jid: {"id": jid, "state": "failed", "error": "worker is gone"}
    with pytest.raises(W.WriteError, match="worker is gone"):
        W.write_bytes(m.read, m.submit, m.status, "sid", 0x1000, b"\x01", sleep=lambda _s: None)


def test_zero_bytes_are_refused_and_restore_puts_back_the_rollback():
    m = Machine({0x1000: b"\x11\x22\x33\x44"})
    with pytest.raises(W.WriteError, match="zero bytes"):
        W.submit(m.submit, "sid", 0x1000, b"")
    out = W.restore(m.read, m.submit, m.status, "sid", 0x1000, "11223344", sleep=lambda _s: None)
    assert out["verified"] is True and m.memory[0x1000] == b"\x11\x22\x33\x44"
