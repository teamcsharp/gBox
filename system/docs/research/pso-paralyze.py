"""Paralyze enemies for training - position-pinned, using the profile for coordinates.

Two corrections to the first attempt, both from measurement:

* **`read_memory` does not return bytes** - its result is `{address, length, sha256}` only, deliberately, so a raw read
  cannot be used to learn an actor's position. The first version therefore wrote nothing at all.
* **the profile already carries what is needed**: every entity comes back with `x`, `y`, `z` and `ptr`, so the pin can
  write the coordinates it already knows. **No read is required.**

Mechanism: rewrite `0x038` (x, y, z as three big-endian floats) with the actor's own position on every cycle. Anything
the AI does to move is overwritten before it can travel, so the actor stays put - a real paralysis in effect, needing no
unknown constant from the AI code.

The action-state word at `0x326` is still exposed through `set_action_state` for when a stun value has been identified,
because that is the *authentic* freeze and will also play the stun animation. But the pin is the guaranteed one, and a
training tool that silently does nothing would waste the operator's time the way the earlier "unbreakable boxes" did.
"""
import struct
import time

X = 0x38
ACTION_STATE = 0x326


def _write(pad, address, data, call):
    job = call("/api/jobs", {"tool": "write_memory", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "address": address, "hex_bytes": data.hex()}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    if not job_id:
        return False
    for _ in range(12):
        time.sleep(0.25)
        row = call("/api/jobs/" + job_id)
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            return row.get("state") == "succeeded"
    return False


def enemies(state):
    return [e for e in (state.get("entities") or [])
            if str(e.get("kind")) == "enemy" and e.get("ptr") and float(e.get("hp") or 0) > 0]


def pin(pad, entity, call):
    """Hold one actor at the position the profile reports for it."""
    pointer = int(entity["ptr"], 16)
    return _write(pad, pointer + X,
                  struct.pack(">fff", float(entity.get("x") or 0),
                              float(entity.get("y") or 0),
                              float(entity.get("z") or 0)), call)


def set_action_state(pad, entity, value, call):
    """Write the action-state halfword that selects an actor's animation/AI branch (the authentic freeze)."""
    return _write(pad, int(entity["ptr"], 16) + ACTION_STATE, struct.pack(">H", value & 0xFFFF), call)


def room(pad, call):
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}


def paralyze(pad, call, seconds=6.0, action_state=None):
    """Freeze every enemy in the current room for `seconds`.

    Returns a report so the caller can see what happened: how many were pinned, how many pin writes landed, and - the
    part that matters - whether any of them still moved.
    """
    state = room(pad, call)
    targets = enemies(state)
    if not targets:
        return {"targets": 0, "note": "no enemies with a pointer in this room"}

    if action_state is not None:
        for entity in targets:
            set_action_state(pad, entity, action_state, call)

    start_positions = {id(e): (float(e.get("x") or 0), float(e.get("z") or 0)) for e in targets}
    writes = 0
    end = time.time() + seconds
    while time.time() < end:
        live = enemies(room(pad, call))
        if not live:
            break
        for entity in live:
            if pin(pad, entity, call):
                writes += 1
        time.sleep(0.1)

    final = enemies(room(pad, call))
    drift = 0.0
    for entity in final:
        key = id(entity)
        if key in start_positions:
            ax, az = start_positions[key]
            drift = max(drift, ((float(entity.get("x") or 0) - ax) ** 2
                                + (float(entity.get("z") or 0) - az) ** 2) ** 0.5)
    return {"targets": len(targets), "pin_writes": writes, "still_alive": len(final),
            "max_drift": round(drift, 1), "frozen": drift < 3.0,
            "action_state": action_state}
