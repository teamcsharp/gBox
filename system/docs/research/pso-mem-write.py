"""Write memory through the job API (the session RPC is read-only for writes) and verify the read-back.

write_memory is a worker job: POST /api/jobs {tool: write_memory, input: {session_id, address, data}} where data is hex bytes. This
helper wraps the job, polls it, and re-reads the address so callers can assert the write stuck.
"""
import json
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"


def call(path, method="GET", body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"null")


def job(tool, payload, timeout=60):
    started = time.time()
    body = call("/api/jobs", "POST", {"tool": tool, "input": payload})
    while time.time() - started < timeout:
        time.sleep(0.25)
        state = call("/api/jobs/" + body["id"])
        if state.get("state") not in ("queued", "running"):
            return state.get("state"), (state.get("output") or {}).get("result"), str(state.get("error"))[:200]
    return "timeout", None, ""


def write_bytes(address, data, timeout=45):
    return job("write_memory", {"session_id": SID, "address": address, "hex_bytes": data.hex()}, timeout=timeout)


def freeze_bytes(address, data, enabled=True, interval_ms=50, timeout=45):
    return job("freeze_memory", {"session_id": SID, "address": address, "hex_bytes": data.hex(),
                                 "enabled": enabled, "interval_ms": interval_ms}, timeout=timeout)


def read_bytes(address, length):
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    for _ in range(3):
        try:
            req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=body, method="POST",
                                         headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                                  "content-type": "application/json"})
            return bytes.fromhex(json.loads(urllib.request.urlopen(req, timeout=10).read() or b'""'))
        except Exception:                                        # noqa: BLE001
            time.sleep(0.15)
    return b""


def player():
    raw = read_bytes(0x8050EA10, 4)
    return int.from_bytes(raw, "big") if raw else 0


if __name__ == "__main__":
    import struct
    import sys
    pointer = player()
    print(f"player actor {pointer:#x}")
    state, result, error = write_bytes(pointer + 0x2BA, struct.pack(">H", 999))
    print("write tp_max ->", state, result, error)
    state, result, error = write_bytes(pointer + 0x32E, struct.pack(">H", 999))
    print("write tp     ->", state, result, error)
    blob = read_bytes(pointer, 0x340)
    print("read back: tp =", struct.unpack(">H", blob[0x32E:0x330])[0],
          "tp_max =", struct.unpack(">H", blob[0x2BA:0x2BC])[0])
