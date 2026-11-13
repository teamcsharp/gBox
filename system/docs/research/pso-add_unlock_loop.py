"""Keep the current floor unlocked while playing - flip the switches with its mind, continuously.

The operator's requirement is exact: *"I want it to just unlock doors as I walk up to them"*. Not "press A and hope", not "walk to a switch 12 units away and stand there".

`unlock_floor()` does it the requested way: read the floor the character is standing on from `0x805D5FC0`, and if that floor's 32-byte stage-flag group (`0x80515CC8 + floor*32`) is not already
all `0xFF`, write it and **verify the read-back**. Doors recompute from those flags every frame, so the floor's doors are open the moment the write lands - no proximity, no target, no press.

Verified standalone:

```
floor unlock at start: floor 1 unlocked
[  0] floor 1 already open
*** CROSSED: room 14 -> 11 at step 1 ***
```

Note the floor: last round's arming logged `floor 0` because it read the pointer while still in the city. Reading it **inside the loop** means the write lands on whichever floor the character
is actually on, which is the whole point of "as I walk up to them".

So `play()` calls it on a cadence, and logs whenever the floor changes so the unlock is visible in the run log.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

HELPER = '''
def unlock_floor(pad: Pad) -> str:
    """Set every stage flag for the floor the character is standing on, and verify it.

    Doors recompute their open state from this array every frame (pso_coop_gates: "native_state (+0xAC) is futile -
    it is recomputed each frame FROM this flag"), so this opens them without a button or a target.
    """
    raw = call("/api/sessions/%s/rpc" % pad.sid,
               {"op": "read_memory", "args": {"address": STAGE_FLAG_GROUP_PTR, "length": 4}}, "POST")
    try:
        floor = int.from_bytes(bytes.fromhex(raw), "big")
    except Exception:                                      # noqa: BLE001
        return "no floor"
    if not 0 <= floor < STAGE_FLAG_GROUPS:
        return f"floor {floor} out of range"
    address = STAGE_FLAG_BASE + floor * STAGE_GROUP_SIZE
    full = bytes([255] * STAGE_GROUP_SIZE)
    raw_group = call("/api/sessions/%s/rpc" % pad.sid,
                     {"op": "read_memory", "args": {"address": address, "length": STAGE_GROUP_SIZE}}, "POST")
    try:
        group = bytes.fromhex(raw_group)
    except Exception:                                      # noqa: BLE001
        group = b""
    if group == full:
        return f"floor {floor} already open"
    job = call("/api/jobs", {"tool": "write_memory", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "address": address, "hex_bytes": full.hex()}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(8):
        time.sleep(0.3)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            break
    time.sleep(0.2)
    check = call("/api/sessions/%s/rpc" % pad.sid,
                 {"op": "read_memory", "args": {"address": address, "length": STAGE_GROUP_SIZE}}, "POST")
    try:
        ok = bytes.fromhex(check) == full
    except Exception:                                      # noqa: BLE001
        ok = False
    return f"floor {floor} {'unlocked' if ok else 'write failed'}"


'''

anchor = "STAGE_FLAG_BASE = 0x80515CC8"
if text.count(anchor) != 1:
    raise SystemExit("STAGE_FLAG_BASE anchor count: %d" % text.count(anchor))
if "def unlock_floor(" not in text:
    # put the helper before the constants' first user (arm)
    text = text.replace(anchor, HELPER.lstrip("\n") + anchor, 1)
    print("unlock_floor() added")

# call it on a cadence inside play()
old = """        if stuck >= 2:"""
new = """        unlock_counter += 1
        if unlock_counter % 12 == 0:
            result = unlock_floor(pad)
            if result != last_unlock:
                log(f"  doors: {result}")
                last_unlock = result

        if stuck >= 2:"""
count = text.count(old)
print("play cadence anchor count:", count)
if count != 1:
    raise SystemExit("play anchor not unique")
text = text.replace(old, new, 1)

old_decl = "    unproductive, walked_out = 0, 0"
new_decl = "    unproductive, walked_out = 0, 0\n    unlock_counter, last_unlock = 0, \"\""
if text.count(old_decl) == 1:
    text = text.replace(old_decl, new_decl, 1)
    print("play counters added")

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
