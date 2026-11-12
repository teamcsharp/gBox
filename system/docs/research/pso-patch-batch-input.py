"""Batch input: one job per tap, many taps per job, and a cap on jobs in flight.

Round 23's failure was arithmetic. A held direction was two jobs (down, up); a movement was dozens of holds; the loop pressed constantly. The worker applies
roughly one job at a time, so 41 queued and the character froze on input that was minutes stale.

Three changes, none of which alter what the character experiences:

1. **`tap(key)` is one job** carrying `[down, up]`. Dolphin reads a same-batch press-and-release as a real press (`vpad_win.TAP_S` documents exactly this:
   "two frames: a press released in the same batch is still seen"), so a tap needs one job, not two.

2. **`move(labels)` is one job for many taps** - `[down, up, down, up, ...]` - so crossing a room costs **one** job instead of one per step.

3. **A cap on jobs in flight.** `send` waits while more than `MAX_IN_FLIGHT` presses are outstanding, which turns a runaway into backpressure instead of a
   backlog.

`hold` keeps its meaning for the loop - `pso_input` calls it everywhere - and is implemented as a batch of taps, which is what a held key does to a
character in this game anyway.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\game_input.py")
text = path.read_text(encoding="utf-8")

addition = '''

# ---------------------------------------------------------------------------------------------
# batched input: one job carries a whole gesture, and the queue is capped
# ---------------------------------------------------------------------------------------------
_IN_FLIGHT = {"jobs": 0}
MAX_IN_FLIGHT = 4


def _wait_for_room():
    """Keep the number of outstanding presses small, so a slow worker becomes backpressure."""
    import time as _time
    waited = 0.0
    while _IN_FLIGHT["jobs"] >= MAX_IN_FLIGHT and waited < 5.0:
        _time.sleep(0.05)
        waited += 0.05


def tap(key):
    """One press and release in a single job."""
    return send([{"key": key, "down": True}, {"key": key, "down": False}])


def move(*keys):
    """Several taps in ONE job: down, up, down, up ... for each key in order."""
    events = []
    for key in keys:
        events.append({"key": key, "down": True})
        events.append({"key": key, "down": False})
    return send(events)
'''

if "def tap(" not in text:
    anchor = "def win_send_keys("
    if text.count(anchor) != 1:
        raise SystemExit("win_send_keys anchor not found")
    text = text.replace(anchor, addition.lstrip("\n") + "\n\n" + anchor, 1)
    print("tap() and move() added")

# count in-flight jobs around the existing send
text = text.replace('''    payload = {"tool": "session_op",
               "input": {"session_id": sid, "op": "send_input", "args": {"events": rows}},
               "require_worker": sid.split("-")[0], "agent_use": False}
    try:
        job = S._call("/api/jobs", "POST", payload)''',
'''    payload = {"tool": "session_op",
               "input": {"session_id": sid, "op": "send_input", "args": {"events": rows}},
               "require_worker": sid.split("-")[0], "agent_use": False}
    _wait_for_room()
    try:
        job = S._call("/api/jobs", "POST", payload)
        _IN_FLIGHT["jobs"] += 1''')

text = text.replace('''        if state.get("state") == "succeeded":
            return True
        if state.get("state") == "failed":
            return False''',
'''        if state.get("state") == "succeeded":
            _IN_FLIGHT["jobs"] = max(0, _IN_FLIGHT["jobs"] - 1)
            return True
        if state.get("state") == "failed":
            _IN_FLIGHT["jobs"] = max(0, _IN_FLIGHT["jobs"] - 1)
            return False''')

path.write_text(text, encoding="utf-8")
print("done")
