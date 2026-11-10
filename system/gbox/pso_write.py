"""Verified live-memory writes for the PSO lane, on top of gBox's audited `write_memory` job.

Two things this module exists to enforce, both learned the hard way on the i9-NUC (2026-11-10):

1. **Writes do not go through the session RPC.** ``/rpc`` answers ``read-only, reset, pause/resume and debug_* ops
   only; edits go through the write_memory job``. The job takes ``{session_id, address, hex_bytes}``, returns its own
   verification (``verified``, ``via``), and records ``rollback_hex`` -- so a caller can always put the bytes back.
2. **Jobs are gated on five minutes without operator input.** Every press resets that clock, so a write issued right
   after a movement test sits ``queued`` with
   ``admission_wait.reason = "Waiting for five minutes without operator input."`` A caller must expect to wait, and must
   not mistake ``queued`` for a failure.

The module deliberately does no I/O of its own: ``job`` is a callable that submits a job dict and returns its record,
and ``read`` is a ``read_memory`` callable. That keeps the verification rules testable without an emulator.
"""
from __future__ import annotations

import struct

BE_FLOAT = ">f"


class WriteError(RuntimeError):
    """A write was refused, was not acknowledged, or did not survive being read back."""


def submit(job, session_id: str, address: int, data: bytes) -> dict:
    """Submit one write and return the job record."""
    if not data:
        raise WriteError("refusing to write zero bytes")
    return job({"tool": "write_memory",
                "input": {"session_id": session_id, "address": int(address), "hex_bytes": data.hex()}})


def wait(job_status, job_record: dict, *, timeout_s: float = 420.0, sleep=None) -> dict:
    """Block until the job finishes; returns the final record. ``queued`` is expected (the five-minute gate), not an error."""
    import time as _time
    sleep = sleep or _time.sleep
    waited = 0.0
    record = job_record
    while record.get("state") in ("queued", "running") and waited < timeout_s:
        sleep(5.0)
        waited += 5.0
        record = job_status(record["id"])
    return record


def verify(record: dict) -> bytes:
    """The rollback bytes of an acknowledged write; raises when the game did not acknowledge it."""
    if record.get("state") != "succeeded":
        raise WriteError(f"write job ended {record.get('state')!r}: {str(record.get('error'))[:200]}")
    out = (record.get("output") or {})
    result = out.get("result") or out
    if not result.get("verified"):
        raise WriteError(f"the write was not acknowledged: {result}")
    return bytes.fromhex(result.get("rollback_hex") or "")


def write_bytes(read, job, job_status, session_id: str, address: int, data: bytes, *,
                timeout_s: float = 420.0, sleep=None, check_after: bool = True) -> dict:
    """Write, wait, and prove the new bytes are there. Returns ``{address, wrote, before, after}``."""
    before = read(address, len(data))
    record = wait(job_status, submit(job, session_id, address, data), timeout_s=timeout_s, sleep=sleep)
    wrote_back = verify(record)
    if check_after:
        after = read(address, len(data))
        if after != data:
            raise WriteError(f"{address:#x}: wrote {data.hex()} but read back {after.hex()}")
    else:
        after = None
    return {"address": address, "wrote": data.hex(),
            "before": wrote_back.hex() if wrote_back else before.hex(),
            "after": None if after is None else after.hex(),
            "verified": True}


def write_float(read, job, job_status, session_id: str, address: int, value: float, **kwargs) -> dict:
    """Write a big-endian float (PSO's position/rotation fields are BE floats at actor+0x38..0x44)."""
    return write_bytes(read, job, job_status, session_id, address, struct.pack(BE_FLOAT, float(value)), **kwargs)


def write_position(read, job, job_status, session_id: str, actor: int, x: float, y: float, z: float, **kwargs) -> dict:
    """Write x, y, z in one job (three floats at actor+0x38, the layout `pso_ram.position` reads)."""
    return write_bytes(read, job, job_status, session_id, actor + 0x38,
                       struct.pack(">3f", float(x), float(y), float(z)), **kwargs)


def restore(read, job, job_status, session_id: str, address: int, rollback_hex: str, **kwargs) -> dict:
    """Put back the bytes a previous write reported as its rollback."""
    return write_bytes(read, job, job_status, session_id, address, bytes.fromhex(rollback_hex), **kwargs)
