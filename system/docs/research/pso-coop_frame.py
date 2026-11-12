"""Capture a frame from the co-op session, so its state is visible rather than inferred.

The buddy launch started `gBox Dolphin` but the gameplay addresses are not mapped, so the emulator is somewhere before the field - title screen,
menus, or a dialog. A frame answers that directly. The `get_frame` tool is dispatched with `agent_use: False`, which is what made the launch job
work, and the PNG is written to disk for viewing.
"""
import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

SESSION = "bcd14c8d972940b2-c25969f531a04870"
WORKER = "bcd14c8d972940b2"
OUT = Path(r"D:\gBox\pso-ds\coop-frame.png")


def main():
    body = {"tool": "get_frame", "input": {"session_id": SESSION},
            "require_worker": WORKER, "agent_use": False}
    job = S._call("/api/jobs", "POST", body)
    print("job:", job.get("id"), job.get("state"))
    for _ in range(40):
        time.sleep(2)
        state = S._call(f"/api/jobs/{job['id']}")
        if state.get("state") in ("succeeded", "failed"):
            print("state:", state.get("state"), "| error:", str(state.get("error"))[:200])
            output = state.get("output") or {}
            print("output keys:", sorted(output))
            for key in ("png", "image", "frame", "path", "file", "b64"):
                value = output.get(key)
                if not value:
                    continue
                text = str(value)
                print(f"{key}: {text[:70]}")
                if len(text) > 500:
                    payload = text.split(",")[-1]
                    OUT.write_bytes(base64.b64decode(payload))
                    print("saved:", OUT, OUT.stat().st_size, "bytes")
                return 0
            print("no image field in the output")
            return 1
    print("timed out")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
