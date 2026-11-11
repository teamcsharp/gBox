"""Discover the running PSO session at runtime instead of hardcoding it.

Every restart creates a new session id (this round: e731ee594dde4a89-6c1e217607b64801), which broke every script that had the old one
baked in. This resolves the session, the Dolphin pid and the game window on demand, and caches them briefly.
"""
import json
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:18765"   # the desktop service owns the emulator and relays session actions; 8765 is the worker mirror
PSO_TITLE = "phantasy star online"
_cache = {"at": 0.0, "session": None}


def _call(path, method="GET", body=None, timeout=40):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(API + path, data=data, method=method,
                                     headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                              "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")


def running(max_age=5.0):
    """(session_id, pid, title) for the running PSO session, or None."""
    if time.time() - _cache["at"] < max_age and _cache["session"]:
        return _cache["session"]
    try:
        sessions = _call("/api/sessions")
    except Exception:                                            # noqa: BLE001
        return _cache["session"]
    for session in sessions or []:
        if session.get("state") != "running":
            continue
        if PSO_TITLE not in str(session.get("title", "")).lower():
            continue
        found = (session.get("session_id"), (session.get("detail") or {}).get("pid"), session.get("title"))
        _cache.update({"at": time.time(), "session": found})
        return found
    return None


def session_id():
    found = running()
    if not found:
        raise RuntimeError("no running PSO session")
    return found[0]


def pid():
    found = running()
    if not found:
        raise RuntimeError("no running PSO session")
    return found[1]


def rpc(op, args=None, timeout=40):
    body = {"op": op, "args": args or {}}
    return _call(f"/api/sessions/{session_id()}/rpc", "POST", body, timeout=timeout)


def controls(op, fields=None, timeout=90):
    import uuid
    body = {"op": "pso_controls", "args": {"command_id": str(uuid.uuid4()), "expires": time.time() + 5,
                                          "input": {"session_id": session_id(), "op": op, **(fields or {})}}}
    return _call(f"/api/sessions/{session_id()}/rpc", "POST", body, timeout=timeout)


def read_memory(address, length):
    result = rpc("read_memory", {"address": address, "length": length})
    try:
        return bytes.fromhex(result or "")
    except Exception:                                            # noqa: BLE001
        return b""


def job(tool, payload, timeout=180):
    body = _call("/api/jobs", "POST", {"tool": tool, "input": payload})
    started = time.time()
    while time.time() - started < timeout:
        time.sleep(0.5)
        state = _call("/api/jobs/" + body["id"])
        if state.get("state") not in ("queued", "running"):
            return state.get("state"), (state.get("output") or {}).get("result"), str(state.get("error"))[:300]
    return "timeout", None, ""


if __name__ == "__main__":
    print(json.dumps(running(), default=str))
