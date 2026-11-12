"""Make pso_input.hold a single batched job instead of two.

Every movement in the play loop goes through `hold`, and it used to call `send` twice - once for down, once for up - so one step of the character cost two
jobs. It now calls the batched path once, which carries both events in one job; the character does the same thing and the worker sees half the work.

`hold` keeps its signature and its meaning for callers: press, wait, release. What changes is only how many jobs that costs.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\pso_input.py")
text = path.read_text(encoding="utf-8")

start = text.find("def hold(")
if start < 0:
    raise SystemExit("hold() not found")
end = text.find("\ndef ", start + 1)
end = len(text) if end < 0 else end

body = '''def hold(key, seconds=0.3):
    """Hold a key for `seconds`. Costs ONE input job: both events travel in the same batch.

    A same-batch press-and-release is still seen by the emulator, so the job carries down and up together and the caller's wait is what gives the hold its
    duration on screen.
    """
    if not allowed():
        return False
    ok = G.send([{"key": key, "down": True}, {"key": key, "down": False}])
    time.sleep(max(0.0, float(seconds)))
    return ok

'''
if "def hold(" in text:
    text = text[:start] + body + text[end:]
    path.write_text(text, encoding="utf-8")
    print("hold is now a single job")
else:
    print("hold not found")
