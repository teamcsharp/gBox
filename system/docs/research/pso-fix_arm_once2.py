"""Arm once per session: remember the session after a successful arm, and only skip that one."""
import pathlib
import py_compile

ENDLESS = pathlib.Path(r"C:\_tools\gBox\.tmp\endless.py")
text = ENDLESS.read_text(encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles BEFORE")

# 1. the set
if "ARMED_SESSIONS" not in text:
    text = text.replace('TELEPORT_ATTEMPTS = {"count": 0}',
                        'TELEPORT_ATTEMPTS = {"count": 0}\nARMED_SESSIONS: set = set()      # armed once per session: re-giving fills the inventory', 1)
    print("ARMED_SESSIONS declared")

# 2. the guard
old_doc = '''    A relaunched session starts with none of this, because equipment lives in live memory rather than on the worker.
    """
    log("arming: walk_through, best weapons, survival")'''
new_doc = '''    A relaunched session starts with none of this, because equipment lives in live memory rather than on the worker.
    But this runs every cycle and the cycle reuses a live session, so re-arming re-gives the same three weapons into the
    same inventory until every give fails with "Not enough inventory slots" and the character is left unarmed.
    """
    if pad.sid in ARMED_SESSIONS:
        log("already armed this session - skipping (re-giving fills the inventory)")
        return
    log("arming: walk_through, best weapons, survival")'''
if text.count(old_doc) == 1:
    text = text.replace(old_doc, new_doc, 1)
    print("guard added")
else:
    print("guard anchor count:", text.count(old_doc))

# 3. remember it after the loop finishes
old_tail = '''        log(f"  {payload['op']} {payload.get('code', '')}: {answer.get('state')} "
            f"{str(answer.get('error'))[:70]}")'''
new_tail = '''        log(f"  {payload['op']} {payload.get('code', '')}: {answer.get('state')} "
            f"{str(answer.get('error'))[:70]}")
    ARMED_SESSIONS.add(pad.sid)'''
if text.count(old_tail) == 1:
    text = text.replace(old_tail, new_tail, 1)
    print("session remembered after arming")
else:
    print("tail anchor count:", text.count(old_tail))

ENDLESS.write_text(text, encoding="utf-8")
py_compile.compile(str(ENDLESS), doraise=True)
print("compiles AFTER")
