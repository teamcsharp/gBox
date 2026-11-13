"""One instance only, by an OS-level exclusive file lock (race-proof against the python shim)."""
import msvcrt
import os
import pathlib

_HANDLES = {}


def acquire(lock: pathlib.Path) -> bool:
    """Take an exclusive OS lock on `lock`; False when another live process holds it.

    The handle stays open for the process lifetime, so the kernel releases the lock on exit - there is no stale-file
    window to race against.
    """
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock, "a+b")
    except OSError as error:
        print(f"could not open the lock file: {error}", flush=True)
        return False
    try:
        handle.seek(0)                       # "a+b" opens at end-of-file: locking from there locks a DIFFERENT byte
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print(f"another instance already holds {lock.name} - exiting", flush=True)
        handle.close()
        return False
    _HANDLES[str(lock)] = handle
    try:
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()).encode("ascii"))
        handle.flush()
    except OSError:
        pass
    return True


def release(lock: pathlib.Path) -> None:
    handle = _HANDLES.pop(str(lock), None)
    if handle is None:
        return
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    try:
        handle.close()
    except OSError:
        pass
