"""CP3: label exported PSO functions against the local model, unattended.

The CP3 guide asked for this script in ``D:\\gBox\\pso-ds\\llm\\``; the repository copy is the reviewed one and is what
``--install`` copies there. It is resumable: a row whose address is already in ``labels.jsonl`` is skipped, so the process
can be stopped and restarted at any time.

    python system/tools/label_functions.py --limit 20          # a measured batch
    python system/tools/label_functions.py --until-done        # leave it running

Every label is a *lead*, not evidence: the model measured 0.04 role accuracy on the gold set (CP02), so nothing here
enters `pso_ram.py` or `pso-gc-executable.md` without a decompile or live proof.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import time
import urllib.request

LLM_DIR = pathlib.Path(r"D:\gBox\pso-ds\llm")
FUNCTIONS = LLM_DIR / "functions.jsonl"
LABELS = LLM_DIR / "labels.jsonl"
OLLAMA = "http://127.0.0.1:11434"
MODEL = "qwen2.5-coder:14b"

PROMPT = """A decompiled function from Phantasy Star Online Episode I & II (GameCube, PowerPC).
Answer with one JSON object and nothing else:
{{"name": "<short UPPER_SNAKE name>", "role": "<one sentence>", "confidence": <0.0-1.0>, "evidence": "<what in the code decided you>"}}

What is known about it: it is {size} bytes; callers: {callers}; callees: {callees}; strings it references: {strings}.
Names are hidden on purpose. Say what the code does, not what it is called.

```c
{c}
```"""


def ask(model: str, prompt: str, *, timeout: float = 240.0) -> dict:
    body = json.dumps({"model": model, "prompt": prompt, "stream": False, "format": "json",
                       "options": {"temperature": 0, "num_ctx": 16384}}).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/generate", data=body, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    try:
        out = json.loads(payload.get("response") or "")
    except json.JSONDecodeError:
        return {}
    return out if isinstance(out, dict) else {}


def labelled() -> set[str]:
    if not LABELS.is_file():
        return set()
    return {json.loads(line)["address"] for line in LABELS.read_text(encoding="utf-8").splitlines() if line.strip()}


def prompt_for(row: dict) -> str:
    return PROMPT.format(size=row["size"], callers=", ".join(row["callers"][:8]) or "none",
                         callees=", ".join(row["callees"][:8]) or "none",
                         strings="; ".join(row["strings"][:8]) or "none", c=row["c"].strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--limit", type=int, default=0, help="stop after this many new labels (0 = all)")
    ap.add_argument("--until-done", action="store_true")
    ap.add_argument("--install", action="store_true", help="copy this script to D:\\gBox\\pso-ds\\llm\\label.py")
    args = ap.parse_args()
    if args.install:
        LLM_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(__file__, LLM_DIR / "label.py")
        print(f"installed to {LLM_DIR / 'label.py'}")
        return 0
    rows = [json.loads(line) for line in FUNCTIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
    done = labelled()
    todo = [r for r in rows if r["address"] not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(rows)} rows, {len(done)} labelled, {len(todo)} to do with {args.model}", flush=True)
    started = time.time()
    with LABELS.open("a", encoding="utf-8") as out:
        for i, row in enumerate(todo, 1):
            t0 = time.time()
            try:
                got = ask(args.model, prompt_for(row))
                err = ""
            except Exception as exc:                 # noqa: BLE001 - a dead server is recorded
                got, err = {}, f"{type(exc).__name__}: {exc}"
            rec = {"address": row["address"], "model": args.model, "answer": got, "error": err,
                   "seconds": round(time.time() - t0, 2), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            out.write(json.dumps(rec) + "\n")
            out.flush()
            if i % 10 == 0 or i == len(todo):
                elapsed = time.time() - started
                rate = i / elapsed * 3600 if elapsed else 0
                print(f"  {i}/{len(todo)} labelled, {rate:.1f} functions/hour, "
                      f"{elapsed / i:.2f} s each", flush=True)
    print(f"done: {len(todo)} labels in {time.time() - started:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
