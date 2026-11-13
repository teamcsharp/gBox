"""Open every door on the floor by setting its flag - permanently part of arming.

The operator's instruction was to *flip those flags with its mind via ram*, and `pso_coop_gates.py` explains why that works: the barrier does not store "open" anywhere writable, it
recomputes **from the stage-flag array every frame** ("native_state (+0xAC) is futile - it is recomputed each frame FROM this flag"). So the flag *is* the switch.

```
STAGE_FLAG_BASE      = 0x80515CC8     # 18 groups (floors 0..17) x 32 bytes, MSB-first
STAGE_FLAG_GROUP_PTR = 0x805D5FC0     # holds the current floor == group index
STAGE_GROUP_SIZE     = 32
```

Measured on this session: the pointer read **1** (Forest), the group at `0x80515CE8` was **all zeros**, and writing 32 bytes of `0xFF` came back **VERIFIED** - all 256 flags set. A room
whose doors are all open is a room the bot cannot get stuck behind.

So `arm()` now opens the floor's gates once per session, alongside the weapons. That is the difference between walking to a door and pressing A at it, and simply walking through it.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

HELPER = '''
STAGE_FLAG_BASE = 0x80515CC8
STAGE_FLAG_GROUP_PTR = 0x805D5FC0
STAGE_GROUP_SIZE = 32


def open_all_gates(pad: Pad) -> str:
    """Set every stage flag for the current floor - the door recomputes from these each frame.

    Returns a short description of what happened, for the arm log.
    """
    raw = call("/api/sessions/%s/rpc" % pad.sid,
               {"op": "read_memory", "args": {"address": STAGE_FLAG_GROUP_PTR, "length": 4}}, "POST")
    try:
        floor = int.from_bytes(bytes.fromhex(raw), "big")
    except Exception:                                  # noqa: BLE001
        return "could not read the floor"
    address = STAGE_FLAG_BASE + floor * STAGE_GROUP_SIZE
    before = call("/api/sessions/%s/rpc" % pad.sid,
                  {"op": "read_memory", "args": {"address": address, "length": STAGE_GROUP_SIZE}}, "POST")
    try:
        already = bytes.fromhex(before)
    except Exception:                                  # noqa: BLE001
        already = b""
    if already and all(byte == 0xFF for byte in already):
        return f"floor {floor}: gates already open"
    job = call("/api/jobs", {"tool": "write_memory", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "address": address,
                                       "hex_bytes": ("ff" * STAGE_GROUP_SIZE)}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(10):
        time.sleep(0.4)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            break
    time.sleep(0.4)
    after = call("/api/sessions/%s/rpc" % pad.sid,
                 {"op": "read_memory", "args": {"address": address, "length": STAGE_GROUP_SIZE}}, "POST")
    try:
        ok = bytes.fromhex(after) == b"\\xff" * STAGE_GROUP_SIZE
    except Exception:                                  # noqa: BLE001
        ok = False
    return f"floor {floor}: {'all gates open' if ok else 'flag write did not stick'}"


'''

anchor = "def arm(pad: Pad) -> None:"
if text.count(anchor) != 1:
    raise SystemExit("arm anchor count: %d" % text.count(anchor))
if "def open_all_gates(" not in text:
    text = text.replace(anchor, HELPER.lstrip("\n") + anchor, 1)
    print("open_all_gates() added")

old = """    ARMED_SESSIONS.add(pad.sid)"""
new = """    log(f"  gates: {open_all_gates(pad)}")
    ARMED_SESSIONS.add(pad.sid)"""
if text.count(old) == 1:
    text = text.replace(old, new, 1)
    print("arming now opens the floor's gates")
else:
    print("arm tail anchor count:", text.count(old))

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
