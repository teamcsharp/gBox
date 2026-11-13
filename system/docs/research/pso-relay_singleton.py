"""One relay only: refuse to start when another is already injecting.

Every `Start-Process` added another relay, and each one reads the same controller and injects the same events into the same session - so a single press reached the game **twice**. For a
directional press that is mostly harmless, but for a tap it can register two actions, and it doubles the input rate for no benefit.

The guard: a lock file holding the owner's PID. On startup the relay reads it and, if that PID is a live process, exits immediately. Liveness is tested with `OpenProcess` through `ctypes`
rather than `os.kill(pid, 0)`, because on Windows the latter can terminate the process it is asked about.

The lock is released on exit, and a stale lock (dead PID) is simply overwritten.
"""
import ctypes
import os
import pathlib
import sys

LOCK = pathlib.Path(r"D:\gBox\pso-ds\relay.lock")

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259


def alive(pid: int) -> bool:
    """True when `pid` is a running process (never signals it)."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def acquire() -> bool:
    """Take the lock, or False when another live relay holds it."""
    try:
        if LOCK.exists():
            holder = int((LOCK.read_text(encoding="utf-8") or "0").strip() or "0")
            if holder and holder != os.getpid() and alive(holder):
                print(f"another relay is already running (pid {holder}) - exiting", flush=True)
                return False
    except (OSError, ValueError):
        pass
    try:
        LOCK.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass
    return True


def release() -> None:
    try:
        if LOCK.exists() and LOCK.read_text(encoding="utf-8").strip() == str(os.getpid()):
            LOCK.unlink()
    except OSError:
        pass


if __name__ == "__main__":
    if not acquire():
        sys.exit(0)
    try:
        import controller_relay

        controller_relay.main()
    finally:
        release()
