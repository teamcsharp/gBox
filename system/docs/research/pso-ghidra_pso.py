"""Put the local Ghidra on PSO's main executable and report what it finds.

Available locally and mostly idle: Ghidra 12.1.4 + `pyghidra-venv`, an RTX 3090 (24 GB) and an RTX 2070, 16 threads, and Ollama (now running) with `deepseek-r1:14b`.

`pso_v3.elf` is PSO's main executable (4.99 MB) - the actual code the game runs - so `ghidra_bridge op=open` on it is the real "decrypt this game" step: the same binary
that was extracted from `sys/main.dol`, in the form the bridge reads.

The job runs on the worker (local CPU), which is the point: use the machine rather than guessing from memory addresses.
"""
import json
import time

from pso_pad import call

ELF = r"D:\gBox\pso-ds\pso_v3.elf"
PROCESSOR = "PowerPC:BE:32:Gekko"


def submit(payload: dict, worker: str = "", wait: float = 120.0) -> dict:
    body = {"tool": "ghidra_bridge", "input": payload}
    if worker:
        body["require_worker"] = worker
    job = call("/api/jobs", body, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    if not job_id:
        return {"submitted": False, "answer": job}
    print("  job:", job_id)
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(2)
        row = call("/api/jobs/" + job_id)
        state = row.get("state")
        if state in ("succeeded", "failed", "cancelled"):
            return {"submitted": True, "state": state, "error": row.get("error"),
                    "output": (row.get("output") or {}).get("result")}
    return {"submitted": True, "state": "timeout"}


if __name__ == "__main__":
    import os
    print("elf:", ELF, "| exists:", os.path.isfile(ELF),
          "| size:", os.path.getsize(ELF) if os.path.isfile(ELF) else 0)

    rows = call("/api/workers")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    worker = next((row["id"] for row in rows if row.get("online")), "")
    print("worker:", worker)

    print("\nghidra_bridge status:")
    print(" ", json.dumps(submit({"op": "status"}, worker, wait=40))[:400])

    print("\nghidra_bridge open (this is the analysis - it takes a while):")
    result = submit({"op": "open", "binary_path": ELF, "processor": PROCESSOR}, worker, wait=300)
    print(" ", json.dumps(result)[:900])
