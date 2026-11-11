"""Run the GC mod verification matrix, but only while the operator is NOT playing.

Polls the operator lock and starts the mutating-op pass the moment the operator has been idle for the full 3 seconds; if they resume
mid-pass it pauses between ops. This is how the mod compatibility gets verified without ever fighting the operator.

Usage: gc_mod_verify_when_idle.py [--timeout-hours 8]
"""
import json
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import gc_mod_matrix                                               # noqa: E402
import pso_operator                                                # noqa: E402

LOG = r"D:\gBox\pso-ds\gc-mod-verify.log"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def wait_idle(timeout=8 * 3600.0):
    started = time.time()
    log("waiting for the operator to put the controller down")
    while time.time() - started < timeout:
        if not pso_operator.operator_active():
            return True
        time.sleep(1.0)
    return False


def main(timeout_hours=8.0):
    if not wait_idle(timeout_hours * 3600.0):
        log("operator never went idle; giving up")
        return 2
    log("operator idle - running the mutating-op verification")
    rows = []
    for op in gc_mod_matrix.BENIGN:
        if pso_operator.operator_active():
            if not wait_idle(1800.0):
                log("operator came back; stopping")
                break
        row = gc_mod_matrix.run(op, gate=True)
        log(f"  {op:<18} {row['classification']:<12} {row.get('detail', '')[:120]}")
        rows.append(row)
    for op in ("give", "multi_equip", "discard", "legendary", "enemy_drops"):
        if pso_operator.operator_active():
            if not wait_idle(1800.0):
                log("operator came back; stopping")
                break
        row = gc_mod_matrix.run(op, gate=True)
        log(f"  {op:<18} {row['classification']:<12} {row.get('detail', '')[:120]}")
        rows.append(row)
    counts = {}
    for row in rows:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    log(f"done: {counts}")
    with open(r"D:\gBox\pso-ds\gc-mod-verify.json", "w", encoding="utf-8") as handle:
        json.dump({"rows": rows, "summary": counts}, handle, indent=1)
    log("wrote D:\\gBox\\pso-ds\\gc-mod-verify.json")
    return 0


if __name__ == "__main__":
    hours = 8.0
    if "--timeout-hours" in sys.argv:
        hours = float(sys.argv[sys.argv.index("--timeout-hours") + 1])
    raise SystemExit(main(hours))
