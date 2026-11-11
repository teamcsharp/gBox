"""Fix the CP2 prompt budget for a reasoning model: the answer must survive the thinking preamble.

deepseek-r1 spends most of its output on reasoning before the JSON, so `num_predict: 300` cut it off and every answer parsed as empty (30/30
"wrong" at 9.49 s/function). Two changes: a much larger budget, and the answer extracted from the LAST json object in the reply (which is the
one after the reasoning, unlike the first).

Usage: python cp2_fix.py [limit]
"""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

LLM = Path(r"D:\gBox\pso-ds\llm")
DECOMPILES = LLM / "decompiles.json"
API = "http://127.0.0.1:11434"
MODEL = "deepseek-r1:14b"
DOC = Path(r"C:\_tools\gBox\system\docs\research\pso-gc-executable.md")

PROMPT = """GameCube game (Phantasy Star Online Ep I & II) decompiled function, name stripped.

Reply with ONE json object and nothing else, at the end:
{"name": "<UPPER_SNAKE_CASE>", "role": "<one sentence>", "confidence": <0..1>, "evidence": "<code evidence>"}

```c
__CODE__
```"""


def gold_table():
    text = DOC.read_text(encoding="utf-8", errors="replace")
    start = text.find("| address | Ghidra function |")
    rows = {}
    if start < 0:
        return rows
    for line in text[start:].splitlines():
        match = re.match(r"\|\s*`0x([0-9A-Fa-f]{8})`\s*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|", line)
        if not match:
            continue
        what = match.group(5).strip()
        backticked = re.findall(r"`([A-Z][A-Z0-9_]{2,})`", what)
        rows[match.group(1).lower()] = backticked[0] if backticked else re.sub(r"[`*]", "", what).strip()[:50]
    return rows


def ask(code, timeout=300):
    body = json.dumps({"model": MODEL, "prompt": PROMPT.replace("__CODE__", code[:6000]), "stream": False,
                       "options": {"num_predict": 1500, "temperature": 0}}).encode()
    request = urllib.request.Request(API + "/api/generate", data=body,
                                     headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        payload = json.loads(reply.read())
    text = payload.get("response") or ""
    objects = re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.S)
    for candidate in reversed(objects):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict) and parsed.get("name"):
                return parsed, text
        except Exception:                                        # noqa: BLE001
            continue
    return {"name": "", "role": "", "confidence": 0, "evidence": "no json"}, text


def main(limit=5):
    gold = gold_table()
    decompiles = json.loads(DECOMPILES.read_text(encoding="utf-8"))
    covered = [address for address in sorted(gold) if address in decompiles][:limit]
    print(f"scoring {len(covered)} of {len(gold)} gold functions against {MODEL}")
    started = time.time()
    answers = []
    for address in covered:
        code = decompiles[address].get("c") or ""
        answer, raw = ask(code)
        answers.append({"address": address, "gold": gold[address], "answer": answer})
        print(f"  {address} gold {gold[address]:<28} model {answer.get('name', ''):<30} "
              f"reply {len(raw)} chars")
    elapsed = time.time() - started
    print(f"{len(answers)} answered in {elapsed:.0f}s ({elapsed / max(1, len(answers)):.1f} s/function)")
    out = LLM / "gold34-deepseek-r1-14b-probe.json"
    out.write_text(json.dumps({"model": MODEL, "answers": answers,
                               "seconds_per_function": round(elapsed / max(1, len(answers)), 1)}, indent=1),
                   encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 5))
