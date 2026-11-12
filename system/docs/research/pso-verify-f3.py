"""Verify the F3 change landed, and whether the autobot is playing right now."""
import json
import struct
import sys
import time
import pathlib
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
PLAYER = 0x8050EA10
POS = 0x38


def rpc(sid, op, args):
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions/%s/rpc" % sid,
        data=json.dumps({"op": op, "args": args}).encode(), method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=25).read() or b'""')


def position(sid):
    pointer = int(rpc(sid, "read_memory", {"address": PLAYER, "length": 4}), 16)
    if not (0x80000000 <= pointer < 0x81800000):
        return None
    return struct.unpack(">fff", bytes.fromhex(rpc(sid, "read_memory", {"address": pointer + POS, "length": 12})))


if __name__ == "__main__":
    page = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html").read_text(encoding="utf-8", errors="replace")
    media = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-media.js").read_text(encoding="utf-8", errors="replace")
    print("index F3 sends start:", "op: 'start', source: 'F3'" in page)
    print("index F3 toggle gone:", "op: 'toggle', source: 'F3'" not in page)
    print("media F3 sends start:", "op:'start',source:'F3'" in media)
    print("media F3 toggle gone:", "op:'toggle',source:'F3'" not in media)

    sid = S.session_id()
    a = position(sid)
    time.sleep(3.0)
    b = position(sid)
    if a and b:
        moved = abs(b[0] - a[0]) + abs(b[2] - a[2])
        print("\npos:", tuple(round(v, 1) for v in a), "->", tuple(round(v, 1) for v in b))
        print("moved in 3s:", round(moved, 2), "units ->", "THE BOT IS PLAYING" if moved > 0.3 else "idle")
