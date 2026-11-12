"""Route input through the session_op JOB, because the session RPC refuses send_input.

Measured on the live session:

```
S.rpc("send_input", {...})  ->  422
{"detail": "read-only, reset, pause/resume and debug_* ops only; edits go through the write_memory job"}
```

So the RPC endpoint accepts only read-only, reset, pause/resume and debug operations. `send_input` is **not** one of them, which means **every press the bot
has attempted since round 8 was rejected before it ever became a key** - and `send` swallowed the failure in its retry loop, so the bot looked like it was
pressing while nothing was sent.

The path that works is a `session_op` job, verified earlier in this session (`session_op send_input` returned `succeeded`):

```python
POST /api/jobs {"tool": "session_op",
                "input": {"session_id": sid, "op": "send_input", "args": {"events": rows}},
                "require_worker": <worker>}
```

`send` now submits that job and waits for it, returning True only when the job actually succeeded. A failed job returns False instead of silently
pretending the press happened.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\game_input.py")
text = path.read_text(encoding="utf-8")

start = text.find("def send(")
end = text.find("def win_send_keys(")
if start < 0 or end < 0:
    raise SystemExit("send() block not found")

body = '''def send(events, attempts=2):
    """Deliver input as a session_op job: the RPC endpoint refuses send_input.

    Returns True only when the job succeeded, so a rejected press is visible to the caller instead of being swallowed.
    """
    import session as S
    import time as _time
    rows = [{"key": str(event.get("key")), "down": bool(event.get("down"))} for event in events
            if event.get("key")]
    if not rows:
        return False
    sid = S.session_id()
    worker = sid.split("-")[0]
    payload = {"tool": "session_op",
               "input": {"session_id": sid, "op": "send_input", "args": {"events": rows}},
               "require_worker": worker, "agent_use": False}
    try:
        job = S._call("/api/jobs", "POST", payload)
    except Exception:                                             # noqa: BLE001
        return False
    job_id = job.get("id")
    for _ in range(40):
        try:
            state = S._call(f"/api/jobs/{job_id}")
        except Exception:                                         # noqa: BLE001
            return False
        if state.get("state") == "succeeded":
            return True
        if state.get("state") == "failed":
            return False
        _time.sleep(0.1)
    return False


'''
text = text[:start] + body + text[end:]
path.write_text(text, encoding="utf-8")
print("send now submits a session_op job")
