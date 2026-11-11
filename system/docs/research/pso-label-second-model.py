"""CP3: label the exported functions with the installed reasoning model, as a second opinion.

The existing labels.jsonl was produced by qwen2.5-coder:14b, which is no longer installed, and CP2 measured that model at 0.04 role accuracy
against the proven gold set. So a second model's labels are useful exactly as CP2's fallback describes: **candidate lists for review**, never
accepted names.

This writes its own file (`labels-deepseek.jsonl`) so the two models are never mixed, skips addresses already labelled by this model (so it is
resumable and can be left running), and reports throughput plus the agreement between the two models per function - which is itself a useful
signal: where two independent models converge on the same tokens, a reviewer can look there first.

Usage: python label_ds.py [limit]
"""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

LLM = Path(r"D:\gBox\pso-ds\llm")
FUNCTIONS = LLM / "functions.jsonl"
EXISTING = LLM / "labels.jsonl"
OUT = LLM / "labels-deepseek.jsonl"
API = "http://127.0.0.1:11434"
MODEL = "deepseek-r1:14b"

PROMPT = """A decompiled function from Phantasy Star Online Episode I & II (GameCube, PowerPC).
Reply with ONE json object and nothing else, at the end:
{"name": "<short UPPER_SNAKE name>", "role": "<one sentence>", "confidence": <0.0-1.0>, "evidence": "<what in the code decided you>"}

Known: {size} bytes; callers {callers}; callees {callees}; strings {strings}. Names are hidden on purpose.

```c
{c}
```"""

STOP = {"THIS", "FUNCTION", "FUN", "THE", "AND", "UNKNOWN", "UNDEFINED"}


def rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def tokens(text):
    return {part for part in re.split(r"[^A-Z0-9]+", str(text).upper()) if len(part) >= 4 and part not in STOP}


def ask(row, timeout=300):
    prompt = (PROMPT.replace("{size}", str(row.get("size")))
              .replace("{callers}", str(row.get("callers"))[:200])
              .replace("{callees}", str(row.get("callees"))[:200])
              .replace("{strings}", str(row.get("strings"))[:300])
              .replace("{c}", (row.get("c") or "")[:5000]))
    body = json.dumps({"model": MODEL, "prompt": prompt, "stream": False,
                       "options": {"num_predict": 1200, "temperature": 0}}).encode()
    request = urllib.request.Request(API + "/api/generate", data=body,
                                     headers={"content-type": "application/json"}, method="POST")
    started = time.time()
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        payload = json.loads(reply.read())
    text = payload.get("response") or ""
    answer = None
    for candidate in reversed(re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.S)):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict) and parsed.get("name"):
                answer = parsed
                break
        except Exception:                                        # noqa: BLE001
            continue
    return answer or {"name": "", "role": "", "confidence": 0, "evidence": "no json"}, time.time() - started


def main(limit=10):
    functions = rows(FUNCTIONS)
    previous = {row["address"]: row for row in rows(EXISTING) if row.get("answer")}
    done = {row["address"] for row in rows(OUT)}
    todo = [row for row in functions if row["address"] not in done][:limit]
    print(f"functions {len(functions)}, already labelled by {MODEL}: {len(done)}, batch {len(todo)}")
    started = time.time()
    agreed = 0
    written = 0
    with OUT.open("a", encoding="utf-8") as handle:
        for index, row in enumerate(todo, 1):
            try:
                answer, seconds = ask(row)
            except Exception as exc:                             # noqa: BLE001
                answer, seconds = {"name": "", "role": "", "confidence": 0,
                                   "evidence": f"error {type(exc).__name__}"}, 0.0
            qwen = previous.get(row["address"], {}).get("answer") or ""
            qwen_tokens = tokens(qwen)
            model_tokens = tokens(answer.get("name", ""))
            shared = sorted(model_tokens & qwen_tokens)
            if shared:
                agreed += 1
            record = {"address": row["address"], "model": MODEL, "answer": answer,
                      "seconds": round(seconds, 2), "at": time.strftime("%Y-%m-%dT%H:%M"),
                      "qwen_agreement": shared}
            handle.write(json.dumps(record) + "\n")
            handle.flush()
            written += 1
            print(f"  {index}/{len(todo)} {row['address']} {answer.get('name', '')[:34]:<34} "
                  f"{seconds:5.1f}s shared-with-qwen {shared}")
    elapsed = time.time() - started
    rate = written / max(0.001, elapsed) * 60
    print(f"\nwritten {written} in {elapsed:.0f}s = {rate:.2f} functions/min "
          f"({elapsed / max(1, written):.1f} s each), agreement on {agreed}/{written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 10))
