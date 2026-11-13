"""Make the endless loop self-sufficient: re-apply the gear every cycle, and stop NPC locks.

Two things a fresh session needs, learned the hard way this round:

1. **Equipment is session-scoped.** `pso_mods give` writes into live memory, so a relaunched game has none of it - DARK FLOW, the 1234 HP and the Scape Doll all vanish. A
   cycle that does not re-apply them plays an unarmed level-5 character, which is what "it can't fight" looked like.

2. **NPC conversations lock movement completely.** The character stood still at 8 HP with an NPC saying "Ah, I miss her..." and neither A (which advances dialogue) nor six B
   presses freed it - the position never changed. `pso_mods` supports **`walk_through`**, which is the setting that makes geometry (and therefore a conversation trigger) not
   stop it.

So `endless.py` gains an `arm()` step that runs once per cycle after the character exists:

    walk_through on    - cannot be body-blocked or conversation-locked
    give DARK FLOW + equip, give TSUMIKIRI J-SWORD + equip
    survival on        - virtual Scape Doll, native revival on death

Each call is a mutation, so each is attempted once and its result recorded; nothing is retried blindly.
"""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("endless.py compiles BEFORE")

if "def arm(" in text:
    print("already has arm()")
    raise SystemExit(0)

# the arming helper, inserted before play()
ARM = '''
def mods(pad: Pad, payload: dict, wait: float = 45.0) -> dict:
    """One pso_mods mutation, single attempt."""
    job = call("/api/jobs", {"tool": "pso_mods", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, **payload}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    if not job_id:
        return {"state": "rejected", "error": str(job)[:120]}
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(1.5)
        row = call("/api/jobs/" + job_id)
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            return {"state": row.get("state"), "error": row.get("error"),
                    "output": (row.get("output") or {}).get("result")}
    return {"state": "timeout"}


def arm(pad: Pad) -> None:
    """Make this cycle's character able to play: unblockable, armed, and unable to stay dead.

    A relaunched session starts with none of this, because equipment lives in live memory rather than on the worker.
    """
    log("arming: walk_through, best weapons, survival")
    for payload in ({"op": "walk_through", "on": True},
                    {"op": "give", "code": "009d00", "equip": True},      # DARK FLOW
                    {"op": "give", "code": "003200", "equip": True},      # TSUMIKIRI J-SWORD
                    {"op": "survival", "on": True}):                      # virtual Scape Doll
        answer = mods(pad, payload)
        log(f"  {payload['op']} {payload.get('code', '')}: {answer.get('state')} "
            f"{str(answer.get('error'))[:70]}")


'''

anchor = "# ---- play ------------------------------------------------------------------------------------------------------------"
if text.count(anchor) != 1:
    raise SystemExit("play section anchor count: %d" % text.count(anchor))
text = text.replace(anchor, ARM + anchor, 1)

old_call = """            if not ensure_in_game(pad):
                log("could not get into the world this cycle; relaunching")"""
new_call = """            if not ensure_in_game(pad):
                log("could not get into the world this cycle; relaunching")"""
if text.count(old_call) != 1:
    raise SystemExit("boot call anchor count: %d" % text.count(old_call))

# arm right after the character is confirmed in the world
old_play = """            while live_sessions():
                outcome = play(pad, seconds=45)"""
new_play = """            arm(pad)

            while live_sessions():
                outcome = play(pad, seconds=45)"""
if text.count(old_play) != 1:
    raise SystemExit("play call anchor count: %d" % text.count(old_play))
text = text.replace(old_play, new_play, 1)

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("endless.py compiles AFTER - arm() runs once per cycle")
