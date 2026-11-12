"""Boot PSO from the attract loop into the field through the session's own input path.

Established:
  * `session_op` with `op: send_input` and `args: {"events": [...]}` is permitted on a session the keyboard path cannot reach;
  * `send_input(events)` is the adapter's signature - nothing else - and on Windows it first tries `remote_input` (a network gamepad, which works on a
    headless emulator) and only falls back to window keys for what the gamepad could not carry;
  * the adapter refuses with "gBox or the emulator must be active" until the gBox window is active, so the window is raised before each attempt.

The boot flow is discrete presses with a pause and a state read between them; the player pointer becoming non-zero is the moment a character exists,
which is the moment the field is loaded.
"""
import ctypes
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

SESSION = "bcd14c8d972940b2-c25969f531a04870"
WORKER = "bcd14c8d972940b2"
PLAYER = 0x8050EA10
FLOOR = 0x805D5FC0


def activate_app():
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _l):
        if not u.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(100)
        u.GetWindowTextW(hwnd, buf, 100)
        if buf.value.strip() == "gBox":
            found.append(hwnd)
        return True

    u.EnumWindows(cb, 0)
    for hwnd in found:
        u.ShowWindow(hwnd, 9)
        u.SetForegroundWindow(hwnd)
    return bool(found)


def press(key):
    body = {"tool": "session_op",
            "input": {"session_id": SESSION, "op": "send_input",
                      "args": {"events": [{"key": key, "down": True}, {"key": key, "down": False}]}},
            "require_worker": WORKER, "agent_use": False}
    created = S._call("/api/jobs", "POST", body)
    job_id = created.get("id")
    deadline = time.time() + 40
    while time.time() < deadline:
        state = S._call(f"/api/jobs/{job_id}")
        if state.get("state") in ("succeeded", "failed"):
            return state.get("state") == "succeeded", str(state.get("error") or "")
        time.sleep(1)
    return False, "timeout"


def read_state():
    try:
        pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    except Exception:                                            # noqa: BLE001
        pointer = 0
    try:
        floor = int.from_bytes(S.read_memory(FLOOR, 4), "big")
    except Exception:                                            # noqa: BLE001
        floor = None
    return pointer, floor


def main():
    print("app active:", activate_app())
    time.sleep(1.0)
    sequence = [("start", 3.5), ("a", 3.0), ("a", 3.0), ("a", 3.5), ("a", 3.5), ("a", 6.0),
                ("a", 4.0), ("a", 4.0), ("a", 4.0), ("a", 4.0), ("a", 4.0), ("a", 4.0),
                ("a", 4.0), ("a", 4.0)]
    for index, (key, pause) in enumerate(sequence):
        pointer, floor = read_state()
        print(f"step {index + 1}: player=0x{pointer:08X} floor={floor}")
        if pointer:
            print("  character exists - the field is loaded")
            return 0
        ok, error = press(key)
        print(f"  press {key}: {'ok' if ok else 'FAILED ' + error[:70]}")
        if not ok and "must be active" in error:
            activate_app()
        time.sleep(pause)
    pointer, floor = read_state()
    print(f"final: player=0x{pointer:08X} floor={floor}")
    return 0 if pointer else 1


if __name__ == "__main__":
    raise SystemExit(main())
