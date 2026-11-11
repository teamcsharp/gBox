"""Compare the PSO live-control source hashes the worker loaded with the files on disk.

pso_live.authorize refuses every pso_controls op when any of its files hashes differently from the worker's immutable build_sources
snapshot. This prints each file's on-disk hash (CRLF-normalised sha256, the same rule the check uses) next to the worker's recorded
value, so the drifted file is visible and can be restored instead of restarting the worker.
"""
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
ROOT = Path(r"C:\_tools\gBox\system\gbox")
FILES = ("pso_live.py", "pso_rehook.py", "pso_accuracy.py", "pso_gc_live.py", "pso_gc_extras.py", "pso_gc_adventure.py",
         "pso_modes.py", "psoitems.py", "pso_loadouts.py", "tools.py", "pso_mods_tool.py", "pso_controls.py")


def call(path, timeout=40):
    request = urllib.request.Request(API + path, headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"})
    return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")


def disk_hash(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def main():
    try:
        workers = call("/api/workers")
    except Exception as exc:                                     # noqa: BLE001
        print("workers endpoint:", str(exc)[:120])
        workers = None
    if isinstance(workers, dict):
        workers = workers.get("workers") or workers.get("items") or []
    worker = None
    for entry in workers or []:
        if entry.get("worker_id", "").startswith("e731ee59"):
            worker = entry
            break
    if worker is None and workers:
        worker = workers[0]
    recorded = (worker or {}).get("build_sources") or {}
    print(f"worker: {(worker or {}).get('worker_id')}  recorded sources: {len(recorded)}")
    drifted = []
    for name in FILES:
        path = ROOT / name
        if not path.exists():
            print(f"  {name:<22} MISSING on disk")
            continue
        mine = disk_hash(path)
        theirs = recorded.get("gbox/" + name)
        status = "ok" if theirs == mine else ("no record" if theirs is None else "DRIFTED")
        if status == "DRIFTED":
            drifted.append(name)
        print(f"  {name:<22} {status:<9} disk={mine[:12]} worker={(theirs or '-')[:12]}")
    print()
    print("drifted files:", drifted or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
