"""Pull a model through ollama's HTTP API - the CLI on this machine is too old to talk to its own server.

The running ollama server answers on 11434, but the `ollama` command reports "Please download the latest version", so `ollama pull` cannot be used. The
API does the same job: POST /api/pull with {"name": ...} streams newline-delimited progress objects.

The campaign needs qwen2.5vl:7b - the PSO route planner model - which is not installed (only deepseek-r1:14b and 8b are).
"""
import json
import sys
import time
import urllib.request

API = "http://127.0.0.1:11434"
MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5vl:7b"
LOG = r"D:\gBox\pso-ds\ollama-pull.log"


def main():
    body = json.dumps({"name": MODEL, "stream": True}).encode()
    request = urllib.request.Request(f"{API}/api/pull", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
    print(f"pulling {MODEL}", flush=True)
    last = ""
    with urllib.request.urlopen(request, timeout=3600) as response, open(LOG, "a", encoding="utf-8") as handle:
        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:                                    # noqa: BLE001
                continue
            if event.get("error"):
                print("ERROR:", event["error"][:200], flush=True)
                return 1
            status = event.get("status", "")
            if event.get("total"):
                done = event.get("completed", 0)
                percent = 100.0 * done / max(1, event["total"])
                note = f"{status} {percent:5.1f}%"
            else:
                note = status
            if note != last:
                print(note, flush=True)
                handle.write(note + "\n")
                handle.flush()
                last = note
            if status == "success":
                print("pull complete", flush=True)
                return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
