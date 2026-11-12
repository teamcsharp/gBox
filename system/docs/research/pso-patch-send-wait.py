"""Wait for the press to be processed, so the queue cannot run away.

Fire-and-forget was right about the receipt being unnecessary and wrong about the rate. Measured: with the bot submitting two jobs per held key, the queue
reached **35 pending session_op jobs** - minutes of stale input - and the character appeared frozen at a constant distance because every press it made was
still waiting behind a backlog.

So `send` waits for its own job to finish, with a **20 second** ceiling instead of the old four. That serialises presses to the rate the worker can actually
process, which is what the character experiences anyway: a press that has not been applied is not a press.

A job that fails or times out returns False, and the caller is unaffected.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\game_input.py")
text = path.read_text(encoding="utf-8")

start = text.find("def send(")
end = text.find("def win_send_keys(")
if start < 0 or end < 0:
    raise SystemExit("send() block not found")

body = '''def send(events, attempts=2):
    """Submit the press and wait for it, so the job queue cannot run away.

    Returns True only when the job succeeded. The wait ceiling is generous because a queued press is still applied; the point is to keep the caller in step
    with the worker rather than to give up early.
    """
    import session as S
    import time as _time
    rows = [{"key": str(event.get("key")), "down": bool(event.get("down"))} for event in events
            if event.get("key")]
    if not rows:
        return False
    try:
        sid = S.session_id()
    except Exception:                                             # noqa: BLE001
        return False
    payload = {"tool": "session_op",
               "input": {"session_id": sid, "op": "send_input", "args": {"events": rows}},
               "require_worker": sid.split("-")[0], "agent_use": False}
    try:
        job = S._call("/api/jobs", "POST", payload)
    except Exception:                                             # noqa: BLE001
        return False
    job_id = job.get("id")
    deadline = _time.time() + 20.0
    while _time.time() < deadline:
        try:
            state = S._call(f"/api/jobs/{job_id}")
        except Exception:                                         # noqa: BLE001
            return False
        if state.get("state") == "succeeded":
            return True
        if state.get("state") == "failed":
            return False
        _time.sleep(0.08)
    return False


'''
text = text[:start] + body + text[end:]
path.write_text(text, encoding="utf-8")
print("send waits again, with a 20 s ceiling")
