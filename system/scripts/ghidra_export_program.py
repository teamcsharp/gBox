#!/usr/bin/env python3
"""Resume a complete discovered-function export on Spark, without occupying GBox's shared analysis bridge.

Run with the PyGhidra interpreter and GHIDRA_INSTALL_DIR set. Existing projects are opened by project/program name;
--analyze explicitly opts into further analysis. Each batch emits coverage and checkpoints through Bridge.export.
An exclusive export lock prevents two writers. Failed functions get bounded longer retries, then remain explicit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gbox.ghidra_bridge_server import Bridge


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--program", required=True)
    parser.add_argument("--export-dir", required=True, type=Path)
    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--batch-seconds", type=float, default=120)
    parser.add_argument("--function-seconds", type=int, default=30)
    parser.add_argument("--retry-seconds", type=int, default=120)
    parser.add_argument("--retry-attempts", type=int, choices=range(1, 5), default=2,
                        help="maximum total attempts per failed function, including prior runs (default: 2)")
    parser.add_argument("--max-payload-mb", type=int, default=None,
                        help="16..512 MiB native decompiler result limit; useful for large-function retries")
    args = parser.parse_args()
    if args.max_payload_mb is not None and not 16 <= args.max_payload_mb <= 512:
        parser.error('--max-payload-mb must be 16..512')
    if not args.binary.is_file():
        parser.error("binary must be the original analyzed executable on this worker")
    args.export_dir.mkdir(parents=True, exist_ok=True)
    import fcntl
    with (args.export_dir / ".export.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with args.binary.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        bridge = Bridge()
        try:
            info = bridge.open(project_dir=args.project_dir, project_name=args.project_name,
                               program_name=args.program, analyze=args.analyze)
            bridge._check_target(str(args.binary.resolve()), digest)
            if args.max_payload_mb is not None:
                from ghidra.app.decompiler import DecompileOptions
                decompiler = bridge._decompiler()
                options = decompiler.getOptions() or DecompileOptions()
                options.setMaxPayloadMBytes(args.max_payload_mb)
                if not decompiler.setOptions(options):
                    raise RuntimeError('native decompiler refused the requested payload limit')
            print(json.dumps({"event": "opened", "at": time.time(), "program": info}), flush=True)
            while True:
                result = bridge.export(args.export_dir, limit=args.batch_size, budget_s=args.batch_seconds,
                                       function_timeout_s=args.function_seconds)
                print(json.dumps({"event": "batch", "at": time.time(), **result}), flush=True)
                if result["complete"]:
                    break
            if result["error"] or result["timeout"]:
                while True:
                    manifest = json.loads((args.export_dir / "_manifest.json").read_text(encoding="utf-8"))
                    failures = sum(row['state'] in ('error', 'timeout') and row.get('attempts', 0) < args.retry_attempts
                                   for row in manifest['outcomes'].values())
                    if not failures:
                        break
                    result = bridge.export(args.export_dir, limit=min(10000, failures), budget_s=3000,
                                           function_timeout_s=args.retry_seconds, retry_failed=True,
                                           retry_below_attempts=args.retry_attempts)
                    print(json.dumps({"event": "retry", "at": time.time(), **result}), flush=True)
                    if not result.get('attempted_this_batch'):
                        raise RuntimeError('retry pass made no progress; export remains incomplete')
            print(json.dumps({"event": "finished", "at": time.time(), **result}), flush=True)
            return 0 if result["all_success"] else 2
        finally:
            bridge.close()


if __name__ == "__main__":
    raise SystemExit(main())
