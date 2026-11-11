"""CP2: run the installed reasoning model over the decompiled functions and score it objectively.

The two earlier candidates (qwen2.5-coder 14b and 32b) scored 1 role hit out of 30, which is the "below 50 %" case the checkpoint warns about.
This runs deepseek-r1:14b - a reasoning model - over the same 30 functions from `decompiles.json` and scores it the same way, so the three are
directly comparable.

Scoring is reproducible instead of judgemental:

  * `name_exact`  normalised equality with the Ghidra name (which is the gold);
  * `role_hit`    the answer shares at least one significant token with the gold name (TRAVEL, DOOR, CARD, ITEM, WARP, MENU, FLOOR, ...)
                  - the same idea the earlier scorer used, applied mechanically;
  * `wrong`       neither.

Writes `D:\\gBox\\pso-ds\\llm\\gold34-deepseek-r1-14b.json` in the same schema as the qwen files.

Usage: python cp2_run.py [limit]
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
OUT = LLM / "gold34-deepseek-r1-14b.json"

STOP = {"THIS", "FUNCTION", "FUN", "THUNK", "THE", "OF", "AND"}
PROMPT = """You are reverse-engineering a Nintendo GameCube game (Phantasy Star Online Episode I & II).
Below is one decompiled function from the game executable. Names have been stripped.

Answer with ONE json object and nothing else:
{"name": "<UPPER_SNAKE_CASE descriptive name>", "role": "<one sentence>", "confidence": <0..1>, "evidence": "<what in the code supports it>"}

```c
{c}
```"""


def normalise(name):
    return re.sub(r"[^A-Z0-9]", "", (name or "").upper())


def tokens(name):
    return {part for part in re.split(r"[^A-Z0-9]+", (name or "").upper()) if len(part) >= 4 and part not in STOP}


def ask(code, timeout=180):
    body = json.dumps({"model": MODEL, "prompt": PROMPT.format(c=code[:6000]), "stream": False,
                       "options": {"num_predict": 320, "temperature": 0}}).encode()
    request = urllib.request.Request(API + "/api/generate", data=body,
                                     headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        payload = json.loads(reply.read())
    text = payload.get("response") or ""
    text = re.sub(r"(?s).*<｜end▁of▁thinking｜>", "", text)                        # drop the reasoning preamble
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {"name": "", "role": "", "confidence": 0.0, "evidence": "no json in reply"}
    try:
        return json.loads(match.group(0))
    except Exception:                                            # noqa: BLE001
        return {"name": "", "role": "", "confidence": 0.0, "evidence": text[:200]}


def main(limit=None):
    rows = json.loads(DECOMPILES.read_text(encoding="utf-8"))
    items = list(rows.items())
    if limit:
        items = items[:limit]
    answers = []
    started = time.time()
    exact = role = wrong = scoreable = 0
    for address, row in items:
        gold = row.get("ghidra_name") or ""
        code = row.get("c") or ""
        if not code:
            continue
        try:
            answer = ask(code)
        except Exception as exc:                                  # noqa: BLE001
            answer = {"name": "", "role": "", "confidence": 0, "evidence": f"error {type(exc).__name__}"}
        model_name = answer.get("name") or ""
        hit_exact = normalise(model_name) == normalise(gold) and normalise(gold) != ""
        shared = tokens(model_name) & tokens(gold)
        hit_role = bool(shared) and not hit_exact
        scoreable += 1
        if hit_exact:
            exact += 1
        elif hit_role:
            role += 1
        else:
            wrong += 1
        answers.append({"address": address, "gold": gold, "answer": answer,
                        "exact": hit_exact, "role": hit_role, "shared": sorted(shared)})
        print(f"  {address}: gold {gold:<28} model {model_name:<28} "
              f"{'EXACT' if hit_exact else ('ROLE' if hit_role else 'wrong')}")
    seconds = time.time() - started
    report = {"model": MODEL, "functions": len(answers), "name_exact": exact, "role_hit": role,
              "wrong": wrong, "scoreable": scoreable,
              "role_rate": round((exact + role) / max(1, scoreable), 3),
              "seconds": round(seconds, 1),
              "seconds_per_function": round(seconds / max(1, len(answers)), 2),
              "answers": answers}
    OUT.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\n{len(answers)} functions: exact {exact}, role {role}, wrong {wrong}, "
          f"scoreable {scoreable}, rate {report['role_rate']}, {report['seconds_per_function']} s/function")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else None))
