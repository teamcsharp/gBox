"""Only one supervisor may run: a lock file with the owner's pid, cleared when that process is gone.

Twice now two supervisors were alive at once (`Count: 2` from the process query), which means two loops racing to drive the same game if one ever
appears - two bots pressing the same pad, each fighting the other's movement. For a goal whose whole point is playing unattended "without fail", that is
an obvious way to fail.

The lock is deliberately simple and self-healing: the file holds the owner's pid; a start checks whether that pid is still alive and, if not, takes the
lock. A stale lock therefore never blocks a restart after a crash, and no cleanup is needed by hand.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\supervisor.py")
text = path.read_text(encoding="utf-8")

if "SUPERVISOR_LOCK" in text:
    print("lock already present")
else:
    guard = '''SUPERVISOR_LOCK = Path(r"D:\\gBox\\pso-ds\\supervisor.lock")


def claim_lock():
    """True when this process owns the supervisor lock; exits when another live supervisor holds it."""
    try:
        if SUPERVISOR_LOCK.exists():
            owner = SUPERVISOR_LOCK.read_text(encoding="utf-8").strip()
            if owner.isdigit() and int(owner) != os.getpid():
                # is that process still alive?
                import ctypes
                handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(owner))
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                    print(f"supervisor {owner} is already running - this one exits", flush=True)
                    return False
        SUPERVISOR_LOCK.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except Exception:                                            # noqa: BLE001
        return True


'''
    anchor = "def log("
    if text.count(anchor) != 1:
        raise SystemExit("log() anchor not found")
    text = text.replace(anchor, guard + anchor, 1)

    # claim at start
    marker = 'if __name__ == "__main__":'
    if text.count(marker) == 1:
        text = text.replace(marker, marker + '\n    if not claim_lock():\n        raise SystemExit(0)\n', 1)
    path.write_text(text, encoding="utf-8")
    print("supervisor now claims a lock at start")
