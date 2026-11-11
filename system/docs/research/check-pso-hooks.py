"""Report from live RAM whether the always-hit and crit-always hooks are installed on the running PSO (reads only)."""
import json
import sys
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")

from gbox import pso_accuracy, pso_crit                           # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
LOCAL = "http://127.0.0.1:18765"
SID = "aa4ba9c970e14266-2950d100ac9d4f7f"


def read(address: int, length: int) -> bytes:
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    req = urllib.request.Request(f"{LOCAL}/api/sessions/{SID}/rpc", data=body, method="POST",
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    reply = json.loads(urllib.request.urlopen(req, timeout=10).read() or b'""')
    return bytes.fromhex(reply) if isinstance(reply, str) else b""


def main():
    print("always-hit hook (pso_accuracy)")
    for site, _bad, cave, original in pso_accuracy.SITES:
        patch = pso_accuracy.PATCHES[site]
        live = read(site, len(patch))
        state = "PATCH (active)" if live == patch else ("original" if live == original else f"other {live.hex()}")
        print(f"  site {site:#010x}: {state}; cave {cave:#010x}")
    meta = read(pso_accuracy.CAVE, len(pso_accuracy.METADATA))
    print(f"  metadata: {meta!r} {'owned' if meta == pso_accuracy.METADATA else 'not installed'}")
    print("crit-always hook (pso_crit)")
    live = read(pso_crit.SITE, 4)
    state = ("PATCH (active)" if live == pso_crit.PATCH
             else "original" if live == pso_crit.SITE_ORIGINAL else f"other {live.hex()}")
    print(f"  site {pso_crit.SITE:#010x}: {state}")
    header = read(pso_crit.HEADER, len(pso_crit.METADATA))
    print(f"  header {pso_crit.HEADER:#010x}: {'owned' if header == pso_crit.METADATA else 'not installed'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
