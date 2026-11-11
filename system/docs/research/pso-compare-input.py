"""Compare input paths: ask the worker to send a START press (adapter path) and see whether the menu opens.

My external win_send_keys calls are being ignored while the screen looks normal; the worker has its own send_input, which reports the
route it used. If the worker's path works, movement can be driven through it instead.
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_gbox_app as cap                                     # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"


def call(path, method="GET", body=None, timeout=90):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"null")


def job(tool, payload, timeout=90):
    started = time.time()
    body = call("/api/jobs", "POST", {"tool": tool, "input": payload})
    while time.time() - started < timeout:
        time.sleep(0.8)
        state = call("/api/jobs/" + body["id"])
        if state.get("state") not in ("queued", "running"):
            return state.get("state"), (state.get("output") or {}).get("result"), str(state.get("error"))[:200]
    return "timeout", None, ""


def main():
    print("runtime:", json.dumps(job("session_op", {"session_id": SID, "op": "query_runtime"})[1], default=str)[:300])
    state, result, error = job("session_op", {"session_id": SID, "op": "send_input",
                                              "args": {"events": [{"key": "start", "down": True},
                                                                  {"key": "start", "down": False}]}})
    print("worker send_input start:", state, result, error)
    time.sleep(1.5)
    cap.main()
    state, result, error = job("session_op", {"session_id": SID, "op": "send_input",
                                              "args": {"events": [{"key": "up", "down": True}]}})
    print("worker send_input up down:", state, result, error)
    time.sleep(1.2)
    state, result, error = job("session_op", {"session_id": SID, "op": "send_input",
                                              "args": {"events": [{"key": "up", "down": False}]}})
    print("worker send_input up up:", state, result, error)
    time.sleep(0.5)
    cap.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
