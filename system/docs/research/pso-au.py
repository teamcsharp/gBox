"""Set Ultimate every session, and give a teleport time to settle before judging it.

Two fixes:

1. **Ultimate is not actually on.** The launch config says
   `{"difficulty": "ultimate", "difficulty_index": 3}` but the game's own difficulty global at `0x805D5550` reads
   **0** - Normal. It is live memory, so it does not survive a relaunch, and the objective now explicitly asks for the
   entire game on Ultimate. So `arm()` writes 3 and verifies it, alongside the weapons.

2. **The relocation was judged too fast.** `write_memory` demonstrably works - a direct write of `x+20` moved the
   character exactly 20 units - so the loop's same-height relocation was landing, and then the character was tested for
   movement only 0.8 s later. Physics needs a moment to settle the character after its position is set, so a move that
   had actually worked could read as a failure and the next offset would be tried needlessly. The settle time is now
   explicit.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

# --- 1. Ultimate --------------------------------------------------------------------------------------------------
if "def set_ultimate(" not in text:
    HELPER = '''
DIFFICULTY_GLOBAL = 0x805D5550      # 0 normal, 1 hard, 2 very hard, 3 ultimate


def set_ultimate(pad: Pad) -> str:
    """Force Ultimate and verify it - the objective asks for the whole game on Ultimate, and this is live memory."""
    import struct as _struct

    before = call("/api/sessions/%s/rpc" % pad.sid,
                  {"op": "read_memory", "args": {"address": DIFFICULTY_GLOBAL, "length": 4}}, "POST")
    try:
        current = int.from_bytes(bytes.fromhex(before), "big")
    except Exception:                                      # noqa: BLE001
        current = None
    if current == 3:
        return "already Ultimate"
    job = call("/api/jobs", {"tool": "write_memory", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "address": DIFFICULTY_GLOBAL,
                                       "hex_bytes": _struct.pack(">I", 3).hex()}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(8):
        time.sleep(0.3)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            break
    time.sleep(0.2)
    after = call("/api/sessions/%s/rpc" % pad.sid,
                 {"op": "read_memory", "args": {"address": DIFFICULTY_GLOBAL, "length": 4}}, "POST")
    try:
        now = int.from_bytes(bytes.fromhex(after), "big")
    except Exception:                                      # noqa: BLE001
        now = None
    return f"{current} -> {now}" + ("  (Ultimate)" if now == 3 else "  (DID NOT STICK)")


'''
    anchor = "def arm(pad: Pad) -> None:"
    if text.count(anchor) != 1:
        raise SystemExit("arm anchor count: %d" % text.count(anchor))
    text = text.replace(anchor, HELPER.lstrip("\n") + anchor, 1)
    print("set_ultimate() added")

old_tail = "    log(f\"  gates: {open_all_gates(pad)}\")"
new_tail = ("    log(f\"  difficulty: {set_ultimate(pad)}\")\n"
            "    log(f\"  gates: {open_all_gates(pad)}\")")
if text.count(old_tail) == 1:
    text = text.replace(old_tail, new_tail, 1)
    print("arming now sets Ultimate")

# --- 2. settle time after a teleport ------------------------------------------------------------------------------
old_settle = """                if not teleport(pad, hx + dx, hy, hz + dz):
                    continue
                before_move = state(pad).get("player") or {}"""
new_settle = """                if not teleport(pad, hx + dx, hy, hz + dz):
                    continue
                time.sleep(1.2)                     # let the game settle the character before judging the move
                before_move = state(pad).get("player") or {}"""
if text.count(old_settle) == 1:
    text = text.replace(old_settle, new_settle, 1)
    print("teleport now settles for 1.2 s before the movement test")
else:
    print("settle anchor count:", text.count(old_settle))

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
