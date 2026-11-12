"""Fire and forget: submit the press job and return, instead of waiting for a receipt the bot does not need.

Measured: `session_op` jobs are accepted and eventually succeed, but not inside `send`'s four-second window, so `send` returned False and the loop treated
every press as failed - the character stopped moving while the jobs were in fact being applied. A press is not a request whose answer the bot needs; it
only needs to be delivered in order, which the job queue already guarantees.

So `send` submits and returns True immediately. The order of presses is preserved by the queue, a failure to submit returns False, and no time is spent
waiting - which also stops the loop from stalling for four seconds per key.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\game_input.py")
text = path.read_text(encoding="utf-8")

start = text.find("def send(")
end = text.find("def win_send_keys(")
if start < 0 or end < 0:
    raise SystemExit("send() block not found")

body = '''def send(events, attempts=2):
    """Submit the press as a session_op job and return without waiting for it.

    The queue preserves order, so a press only needs delivering. Waiting was actively harmful: jobs take longer than a frame, and treating a slow job as
    a failed press stopped the character from moving while the presses were being applied anyway.
    """
    import session as S
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
        S._call("/api/jobs", "POST", payload)
        return True
    except Exception:                                             # noqa: BLE001
        return False


'''
text = text[:start] + body + text[end:]
path.write_text(text, encoding="utf-8")
print("send is now fire-and-forget")
