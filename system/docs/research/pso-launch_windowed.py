"""Launch a normal (windowed) PSO session and check whether input reaches it.

The headless co-op session cannot be driven: `remote_input` is RetroArch's network gamepad and Dolphin has no such port, so every send falls back to
`win_send_keys` on a process that has no window and vanishes.

A **windowed** session is different - it has a window, and `send_input`'s fallback is exactly `win_send_keys` on that window. So a normal launch (no
`pso_coop`) should be drivable through `session_op send_input`, and if it is, the boot sequence and then the bot can be run without the operator having
to do anything.

The launch payload is the same one that succeeded before, minus `pso_coop`, dispatched with `require_worker` and `agent_use: false`. After the launch it
waits for the emulator's window, sends one harmless key, and reports whether the character or the floor moved - which is what proves the path.
"""
import ctypes
import json
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

WORKER = "bcd14c8d972940b2"
KEEP = ("game", "mod", "keep_session", "keep_sessions", "boot_timeout_s", "debug", "examine", "local_build_ok")


def launch():
    rows = S._call("/api/jobs")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    source = next((row for row in rows if row.get("tool") == "launch_game" and row.get("state") == "succeeded"), None)
    if not source:
        raise SystemExit("no previous successful launch payload to copy")
    original = dict(source.get("input") or {})
    payload = {key: original[key] for key in KEEP if key in original}
    payload.pop("pso_coop", None)
    print("payload keys:", sorted(payload))
    body = {"tool": "launch_game", "input": payload, "require_worker": WORKER, "agent_use": False}
    created = S._call("/api/jobs", "POST", body)
    job_id = created.get("id")
    deadline = time.time() + 300
    while time.time() < deadline:
        state = S._call(f"/api/jobs/{job_id}")
        if state.get("state") in ("succeeded", "failed"):
            print("launch:", state.get("state"), "| error:", str(state.get("error"))[:200])
            return (state.get("output") or {}).get("session_id")
        time.sleep(3)
    return None


def windows_for(pid):
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _l):
        if not u.IsWindowVisible(hwnd):
            return True
        owner = ctypes.c_ulong()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            buf = ctypes.create_unicode_buffer(120)
            u.GetWindowTextW(hwnd, buf, 120)
            found.append((hwnd, buf.value[:40]))
        return True

    u.EnumWindows(cb, 0)
    return found


if __name__ == "__main__":
    session_id = launch()
    print("session:", session_id)
    if not session_id:
        raise SystemExit(1)
    time.sleep(20)
    try:
        print("pid:", S.pid())
        print("windows:", windows_for(S.pid()))
    except Exception as exc:                                      # noqa: BLE001
        print("pid/window lookup failed:", str(exc)[:120])
    try:
        print("floor:", int.from_bytes(S.read_memory(0x805D5FC0, 4), "big"))
    except Exception as exc:                                      # noqa: BLE001
        print("floor read failed:", str(exc)[:100])
