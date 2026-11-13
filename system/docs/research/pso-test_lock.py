"""Prove the OS-level lock excludes a second process, then report.

Two processes are started: the first holds the lock for six seconds, the second tries to take it while the first is alive. The second must be refused. Then a third attempt after the
first releases must succeed - a lock that never frees would be as bad as one that never holds.
"""
import pathlib
import subprocess
import sys
import time

BASE = r"C:\Users\maste\AppData\Roaming\uv\python\cpython-3.11.11-windows-x86_64-none\python.exe"
LOCK = pathlib.Path(r"D:\gBox\pso-ds\test.lock")
HOLDER = """
import sys, pathlib, time
sys.path.insert(0, r'C:\\_tools\\gBox\\.tmp')
import singleton
lock = pathlib.Path(r'D:\\gBox\\pso-ds\\test.lock')
print('holder acquired:', singleton.acquire(lock), flush=True)
time.sleep(6)
print('holder releasing', flush=True)
singleton.release(lock)
"""
TRIER = """
import sys, pathlib
sys.path.insert(0, r'C:\\_tools\\gBox\\.tmp')
import singleton
print('trier acquired:', singleton.acquire(pathlib.Path(r'D:\\gBox\\pso-ds\\test.lock')), flush=True)
"""

if __name__ == "__main__":
    if LOCK.exists():
        LOCK.unlink()
    holder = subprocess.Popen([BASE, "-c", HOLDER], stdout=subprocess.PIPE, text=True)
    time.sleep(2)
    trier = subprocess.run([BASE, "-c", TRIER], capture_output=True, text=True, timeout=30)
    print("while the holder is alive ->", trier.stdout.strip() or trier.stderr.strip()[-200:])
    holder.wait(timeout=30)
    after = subprocess.run([BASE, "-c", TRIER], capture_output=True, text=True, timeout=30)
    print("after the holder exits   ->", after.stdout.strip() or after.stderr.strip()[-200:])
    if LOCK.exists():
        LOCK.unlink()
