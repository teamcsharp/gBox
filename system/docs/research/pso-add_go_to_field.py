"""Make the endless loop leave the city for a field, where there is anything to complete.

The loop was cycling correctly but *playing* in Pioneer 2: `played 45s, 9 travel steps` forever against **20 NPCs and no enemies** - the city has no doors to open and nothing to
fight, so "completion" was never possible there. Every field it ever reached had been reached by hand.

The way out is already known from the corridor work:

* the city's warp door is `TObjCityDoor_Warp (254.0, 25.0)`;
* writing the platform centre `(360, 0, 26)` does **not** land on it - the raised disc is not walkable and the game corrects the position ~25 units away;
* a search of the corridor's safe cells found the trigger is the specific cell **`(361.2, 0, 28.8)`**, three units north of centre, where A warps;
* a field is unmistakable: the city has ~31 entities, a field 80-130 with `kind: "gate"` entries.

So `endless.py` gains `go_to_field()`: if the current room looks like the city, write the warp cell, press A, and confirm the entity count jumped. Fields are also where
enemies and `TODoorCave02` doors live, which is what completion needs.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

if "def go_to_field(" in text:
    print("already has go_to_field")
    raise SystemExit(0)

HELPER = '''
WARP_CELL = (361.2, 0.0, 28.8)      # the cell that actually triggers the city warp (found by searching Corridor.safe)


def go_to_field(pad: Pad) -> bool:
    """Leave the city for a field, where there are enemies and doors to progress through.

    The city has ~31 entities and no enemies; a field has 80+ and `gate`-kind entries. Writing the warp platform's centre does not land on the warp because the raised disc is
    not walkable, so the specific trigger cell is used instead.
    """
    now = state(pad)
    player = now.get("player") or {}
    entities = now.get("entities") or []
    if len(entities) > 60 and any(str(e.get("kind")) == "gate" for e in entities):
        return True                                     # already in a field

    import struct
    pointer = player.get("ptr")
    if not pointer:
        return False
    log(f"in the city ({len(entities)} entities) - warping to a field")
    job = call("/api/jobs", {"tool": "write_memory", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "address": int(pointer, 16) + 0x38,
                                       "hex_bytes": struct.pack(">fff", *WARP_CELL).hex()}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(12):
        time.sleep(1)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            break
    time.sleep(1.5)
    tap(pad, "a")
    time.sleep(5)
    after = state(pad)
    count = len(after.get("entities") or [])
    gates = [e for e in (after.get("entities") or []) if str(e.get("kind")) == "gate"]
    log(f"after the warp: {count} entities, {len(gates)} gates")
    return count > 60


'''

anchor = "def arm(pad: Pad) -> None:"
if text.count(anchor) != 1:
    raise SystemExit("arm anchor count: %d" % text.count(anchor))
text = text.replace(anchor, HELPER.lstrip("\n") + anchor, 1)

old = """            arm(pad)

            while live_sessions():"""
new = """            arm(pad)
            if not go_to_field(pad):
                log("could not reach a field this cycle - playing where we are")

            while live_sessions():"""
if text.count(old) != 1:
    raise SystemExit("arm call anchor count: %d" % text.count(old))
text = text.replace(old, new, 1)

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("endless.py compiles AFTER - go_to_field runs after arming each cycle")
