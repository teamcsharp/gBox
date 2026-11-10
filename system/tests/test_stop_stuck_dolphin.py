import subprocess, sys, time, threading
from gbox import adapters


class HangingDbg:
    def __init__(self):
        self.ev = threading.Event()

    def close(self):
        self.ev.wait(30)          # a debugger socket on a dialog-blocked emulator never answers


def test_stop_not_blocked_by_hanging_debugger():
    ad = adapters.StandaloneAdapter.__new__(adapters.StandaloneAdapter)
    ad.proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    ad.dbg, ad.stream, ad.display = HangingDbg(), None, None
    t = time.monotonic()
    res = ad.stop_game()
    assert ad.proc.poll() is not None and res["returncode"] is not None
    assert time.monotonic() - t < 8
    ad.dbg.ev.set()
