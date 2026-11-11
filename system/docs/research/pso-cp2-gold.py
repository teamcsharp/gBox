"""CP2 done properly: score a model against the PROVEN roles from the executable doc, not against FUN_ names.

`pso-gc-executable.md` section 3 lists addresses whose identity was proven by byte-exact guards, and gives each a role label
(`BEGIN_TRAVEL`, `F_CREATE`, `F_DELETE`, `F_EQUIP`, `WARP`, the floor-query native, the laser-fence update, ...). Those labels are the gold.
The decompiles file is keyed by the same addresses, so the model can be asked for a name and role from the stripped C and scored directly.

This prints the gold table, the coverage in `decompiles.json`, and (with `--run`) asks the model for each covered function and writes
`gold34-<model>.json` in the same schema the earlier candidates used.
"""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

DOC = Path(r"C:\_tools\gBox\system\docs\research\pso-gc-executable.md")
LLM = Path(r"D:\gBox\pso-ds\llm")
DECOMPILES = LLM / "decompiles.json"
API = "http://127.0.0.1:11434"
MODEL = "deepseek-r1:14b"

PROMPT = """You are reverse-engineering a Nintendo GameCube game (Phantasy Star Online Episode I & II).
One decompiled function follows; its name was stripped.

Reply with ONE json object and nothing else:
{"name": "<UPPER_SNAKE_CASE name>", "role": "<one sentence>", "confidence": <0..1>, "evidence": "<code evidence>"}

```c
__CODE__
```"""


def gold_table():
    text = DOC.read_text(encoding="utf-8", errors="replace")
    start = text.find("| address | Ghidra function |")
    if start < 0:
        return {}
    rows = {}
    for line in text[start:].splitlines():
        match = re.match(r"\|\s*`0x([0-9A-Fa-f]{8})`\s*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|", line)
        if not match:
            continue
        address = match.group(1).lower()
        what = match.group(5).strip()
        label = ""
        backticked = re.findall(r"`([A-Z][A-Z0-9_]{2,})`", what)
        if backticked:
            label = backticked[0]
        else:
            clean = re.sub(r"[`*]", "", what).strip()
            label = clean[:60]
        rows[address] = {"label": label, "description": what[:120],
                         "ghidra": re.sub(r"[`]", "", match.group(2)).strip()}
    return rows


def tokens(text):
    return {part for part in re.split(r"[^A-Z0-9]+", (text or "").upper())
            if len(part) >= 4 and part not in {"THIS", "FUNCTION", "FUN", "THUNK", "WHAT", "WITH"}}


def ask(code, timeout=200):
    body = json.dumps({"model": MODEL, "prompt": PROMPT.replace("__CODE__", code[:6000]),
                       "stream": False, "options": {"num_predict": 300, "temperature": 0}}).encode()
    request = urllib.request.Request(API + "/api/generate", data=body,
                                     headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        payload = json.loads(reply.read())
    text = payload.get("response") or ""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {"name": "", "role": "", "confidence": 0, "evidence": "no json"}
    try:
        return json.loads(match.group(0))
    except Exception:                                            # noqa: BLE001
        return {"name": "", "role": "", "confidence": 0, "evidence": text[:160]}


def main(argv):
    gold = gold_table()
    decompiles = json.loads(DECOMPILES.read_text(encoding="utf-8"))
    covered = [address for address in gold if address in decompiles]
    print(f"gold rows in the doc: {len(gold)}")
    print(f"covered by decompiles.json: {len(covered)}")
    for address in sorted(gold):
        mark = "yes" if address in decompiles else " - "
        desc = gold[address]["description"].encode("ascii", "replace").decode()
        print(f"  {address}  {mark}  {gold[address]['label']:<32} {desc[:60]}")
    if "--run" not in argv:
        return 0
    answers = []
    started = time.time()
    exact = role = wrong = 0
    for address in sorted(covered):
        entry = gold[address]
        code = decompiles[address].get("c") or ""
        try:
            answer = ask(code)
        except Exception as exc:                                  # noqa: BLE001
            answer = {"name": "", "role": "", "confidence": 0, "evidence": f"error {type(exc).__name__}"}
        model_name = (answer.get("name") or "").upper()
        shared = tokens(model_name) & tokens(entry["label"])
        hit_exact = bool(tokens(model_name)) and tokens(model_name) <= tokens(entry["label"])
        hit_role = bool(shared) and not hit_exact
        if hit_exact:
            exact += 1
        elif hit_role:
            role += 1
        else:
            wrong += 1
        answers.append({"address": address, "gold": entry["label"], "answer": answer,
                        "exact": hit_exact, "role": hit_role, "shared": sorted(shared)})
        verdict = "EXACT" if hit_exact else ("ROLE" if hit_role else "wrong")
        print(f"  {address} gold {entry['label']:<28} model {model_name:<28} {verdict}")
    seconds = time.time() - started
    report = {"model": MODEL, "functions": len(answers), "name_exact": exact, "role_hit": role, "wrong": wrong,
              "scoreable": len(answers), "role_rate": round((exact + role) / max(1, len(answers)), 3),
              "seconds": round(seconds, 1), "seconds_per_function": round(seconds / max(1, len(answers)), 2),
              "answers": answers, "gold_source": "pso-gc-executable.md section 3"}
    out = LLM / f"gold34-{MODEL.replace(':', '-')}.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\n{len(answers)} scored: exact {exact}, role {role}, wrong {wrong}, rate {report['role_rate']}, "
          f"{report['seconds_per_function']} s/function -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
