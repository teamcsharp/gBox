"""CP1 check: does the local coder model actually answer, and does it run on the 3090?

The PM document records "No local model. ollama.available = false" as measured at 13:46 on 2026-11-10. This re-measures it and provides the
evidence CP1 needs: a real completion from the model, plus the GPU memory and utilisation before/during/after, so "on the 3090" is observed
rather than assumed.

Writes D:\\gBox\\pso-ds\\cp1-local-model.json.
"""
import json
import subprocess
import sys
import time
import urllib.request

API = "http://127.0.0.1:11434"
OUT = r"D:\gBox\pso-ds\cp1-local-model.json"
PROMPT = ("In one sentence, what does this Python function return?\n\n"
          "def f(xs):\n    return [x for x in xs if x % 2 == 0]\n")


def tags():
    with urllib.request.urlopen(API + "/api/tags", timeout=10) as reply:
        return json.loads(reply.read())


def gpu():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15).stdout
        rows = []
        for line in out.strip().splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) >= 5:
                rows.append({"index": int(parts[0]), "name": parts[1], "used_mb": int(parts[2]),
                             "total_mb": int(parts[3]), "util": int(parts[4])})
        return rows
    except Exception as exc:                                      # noqa: BLE001
        return [{"error": str(exc)[:120]}]


def generate(model, prompt, timeout=180):
    body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"num_predict": 64, "temperature": 0}}).encode()
    request = urllib.request.Request(API + "/api/generate", data=body,
                                     headers={"content-type": "application/json"}, method="POST")
    started = time.time()
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        payload = json.loads(reply.read())
    return payload, time.time() - started


def main():
    report = {"api": API, "measured_at": round(time.time(), 1)}
    models = tags().get("models") or []
    report["models"] = [{"name": m.get("name"), "size_gb": round((m.get("size") or 0) / 2**30, 1)} for m in models]
    print(f"models installed: {[m['name'] for m in report['models']]}")
    if not models:
        report["result"] = "no models installed"
        print(report["result"])
        return 2
    before = gpu()
    report["gpu_before"] = before
    print(f"gpu before: {[(g['name'], g.get('used_mb')) for g in before]}")
    name = models[0]["name"]
    try:
        payload, elapsed = generate(name, PROMPT)
    except Exception as exc:                                      # noqa: BLE001
        report["result"] = f"generate failed: {type(exc).__name__}: {str(exc)[:160]}"
        print(report["result"])
        return 2
    during = gpu()
    report["gpu_during"] = during
    answer = (payload.get("response") or "").strip()
    report["answer"] = answer[:400]
    report["elapsed_s"] = round(elapsed, 1)
    report["eval_count"] = payload.get("eval_count")
    report["eval_duration_ms"] = round((payload.get("eval_duration") or 0) / 1e6, 1)
    print(f"answer ({elapsed:.1f}s, {payload.get('eval_count')} tokens): {answer[:200]}")
    print(f"gpu during: {[(g['name'], g.get('used_mb')) for g in during]}")
    busiest = max(during, key=lambda g: g.get("used_mb", 0))
    report["busiest_gpu"] = busiest.get("name")
    ok = bool(answer) and payload.get("eval_count")
    report["result"] = "local model answers" if ok else "empty answer"
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=1))
    print("wrote", OUT, "|", report["result"])
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
