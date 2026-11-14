"""Save a frame of the running session to a JPEG, so the game can be looked at instead of only read.

    python pso-frame.py                 # D:\\gBox\\pso-ds\\bounded\\game-frame.jpg
    python pso-frame.py --out shot.jpg

Why: /api/sessions/{sid}/frame.jpg is the same image the operator's stream shows. Reading it settled a question memory
could not - the Dolphin window is a blank white rectangle while the game logic runs normally (player moves, frame
counter advances), which is why the stream looks empty.

Set GBOX_API to point at the app the worker registered with (default http://127.0.0.1:8765).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import urllib.request

BASE = os.environ.get("GBOX_API") or "http://127.0.0.1:8765"
TOKEN = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token").read_text().strip()


def call(path: str, timeout: float = 30) -> bytes:
    req = urllib.request.Request(BASE + path, headers={"authorization": "Bearer " + TOKEN})
    return urllib.request.urlopen(req, timeout=timeout).read()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="save a frame of the running session")
    parser.add_argument("--out", default=r"D:\gBox\pso-ds\bounded\game-frame.jpg")
    parser.add_argument("--session", default="")
    args = parser.parse_args(argv)
    sid = args.session
    if not sid:
        rows = json.loads(call("/api/sessions"))
        live = [r for r in rows if r.get("state") in ("running", "starting")]
        if not live:
            print("no running session")
            return 1
        sid = live[0]["session_id"]
    image = call(f"/api/sessions/{sid}/frame.jpg")
    out = pathlib.Path(args.out)
    out.write_bytes(image)
    print(f"{sid}: wrote {out} ({len(image)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
