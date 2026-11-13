"""One relay only: an OS-level exclusive lock, so the python shim's double start cannot both inject."""
import pathlib
import sys

import singleton

LOCK = pathlib.Path(r"D:\gBox\pso-ds\relay.lock")

if __name__ == "__main__":
    if not singleton.acquire(LOCK):
        sys.exit(0)
    try:
        import controller_relay

        controller_relay.main()
    finally:
        singleton.release(LOCK)
