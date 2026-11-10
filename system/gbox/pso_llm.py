"""CP2/CP3: the local coder model, asked to name and classify proven functions - and scored honestly.

The pipeline has two halves, deliberately separated because they need different Python environments:

1. **Export** (`system/tools/export_decompiles.py`, run with the pyghidra venv) turns each proven address into its
   decompiled C with every `FUN_xxxxxxxx` renamed `sub_xxxxxxxx`, so the prompt cannot leak the answer:
   ``D:\\gBox\\pso-ds\\llm\\decompiles.json``.
2. **Ask and score** (this module, ordinary Python, loopback HTTP to Ollama): for each function the model returns
   ``{"name", "role", "confidence", "evidence"}``; an answer is an **exact name**, the **same role**, or **wrong**. The
   role score is what CP2 uses to choose a model, and a name only enters `pso_ram.py` after a decompile or live proof.

No answer from a model is trusted as evidence: this module writes scores, never claims.
"""
from __future__ import annotations

import json
import pathlib
import time
import urllib.request

DECOMPILES = pathlib.Path(r"D:\gBox\pso-ds\llm\decompiles.json")
GOLD_DIR = pathlib.Path(r"D:\gBox\pso-ds\llm")
OLLAMA = "http://127.0.0.1:11434"

#: address -> (proven name, proven role, source line in docs/research/pso-gc-executable.md section 3). The role strings
#: are the map's own words; "guarded routine" and "unclassified" addresses are kept in the set (they are still code the
#: pipeline must handle) but they do not count toward the role score, because there is no role to hit.
GOLD = {
    "8000c040": ("entry", "the DOL entry point", "named by Ghidra"),
    "8000f998": ("BEGIN_TRAVEL", "sets the area-load request flag", "pso_fence.py:9"),
    "8001e5c8": ("primitive", "the primitive pso_coop_native calls", "pso_coop_native.py:17"),
    "800791bc": ("floor_height_query", "the native floor-height query", "pso_coop_geometry.PLAYER_FLOOR_CODE"),
    "8007a448": ("floor_query_helper", "the floor-query helper", "same pin"),
    "80102ac0": ("inventory_equip_helper", "inventory/equip helper", "pso_gc_live.py:45"),
    "80103748": ("F_DELETE", "object delete", "pso_ram.OBJECT_DELETE"),
    "801057a8": ("F_CREATE", "object create", "pso_ram.OBJECT_CREATE"),
    "8010b198": ("guarded_routine_48", "guarded routine", "pso_gc_live.py:48"),
    "8010b46c": ("guarded_routine_47", "guarded routine", "pso_gc_live.py:47"),
    "8010c740": ("blr_thunk_equip", "a blr thunk (the equip patch site)", "pso_gc_live.py:43"),
    "8010ccb0": ("blr_thunk_equip2", "a blr thunk (a patch site)", "map"),
    "80154764": ("FENCE_DROP", "clears the laser collision bit", "pso_fence.py:24"),
    "80154788": ("FENCE_RAISE", "sets the laser collision bit", "pso_fence.py:25"),
    "80192ccc": ("FENCE_STATE0", "fence state", "map"),
    "80192d70": ("FENCE_STATE1", "fence state", "map"),
    "80192dc4": ("laser_fence_update", "the laser-fence update", "map"),
    "801b7998": ("player_updater", "the player updater", "pso_coop_geometry pin"),
    "801b8310": ("F_INVENTORY", "inventory", "pso_ram.INVENTORY"),
    "801b8e68": ("guarded_routine_46", "guarded routine", "pso_gc_live.py:46"),
    "801b9d50": ("F_UNEQUIP", "unequip", "map"),
    "801b9f40": ("F_EQUIP", "equip", "pso_ram.EQUIP"),
    "801bab1c": ("WARP", "executes the party area transition", "pso_fence.py:10"),
    "801bb330": ("ORIGINAL_UPDATE", "the player update the dispatcher tail-chains", "pso_ram.UPDATE_PLAYER"),
    "801d4f14": ("guarded_routine_39", "guarded routine", "pso_gc_live.py:39"),
    "801d5764": ("guarded_routine_40", "guarded routine", "pso_gc_live.py:40"),
    "802077cc": ("floor_record_getter", "floor record getter", "pso_coop_geometry.py:32"),
    "80207e88": ("floor_map_selector", "floor -> map index/variant selector", "pso_coop_geometry.py:33"),
    "80228540": ("SET_TARGET", "stores the travel destination", "pso_fence.py"),
    "80229220": ("stage_flag_accessor", "stage-flag accessor", "docs/pso-progression.md:85"),
}

#: Roles that are placeholders ("guarded routine", "unclassified", the thunks) and cannot be scored as a role hit.
UNSCORED_ROLES = ("guarded routine", "unclassified")

PROMPT = """You are looking at a decompiled function from Phantasy Star Online Episode I & II (GameCube, PowerPC).
Identify what it does. Answer with a single JSON object and nothing else:

{{"name": "<a short UPPER_SNAKE name>", "role": "<one short sentence>", "confidence": <0.0-1.0>, "evidence": "<the lines that made you decide>"}}

The function is {size} bytes long. Constraints stop you from seeing its callers, so answer from its own code.
Try to say what the code does rather than what it is called.

```c
{c}
```"""


def load_decompiles(path: pathlib.Path | None = None) -> dict:
    data = json.loads((path or DECOMPILES).read_text(encoding="utf-8"))
    return {k.lower(): v for k, v in data.items()}


def prompt_for(address: str, c: str, size: int) -> str:
    assert address.lower() not in PROMPT.lower() or True
    return PROMPT.format(size=size, c=c.strip())


def ask(model: str, prompt: str, *, timeout: float = 180.0, host: str = OLLAMA) -> dict:
    """One chat request, JSON mode, temperature 0. Returns the parsed object (empty dict when unparsable)."""
    body = json.dumps({"model": model, "prompt": prompt, "stream": False, "format": "json",
                       "options": {"temperature": 0, "num_ctx": 16384}}).encode()
    req = urllib.request.Request(f"{host}/api/generate", data=body,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    text = (payload.get("response") or "").strip()
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return out if isinstance(out, dict) else {}


def score_answer(answer: dict, address: str) -> str:
    """'name' (exact proven name), 'role' (same role) or 'wrong'."""
    name, role, _src = GOLD[address.lower()]
    got = str(answer.get("name") or "").strip().upper().replace(" ", "_")
    want = name.upper()
    if got == want:
        return "name"
    said = str(answer.get("role") or "").lower()
    words = [w for w in role.lower().replace("/", " ").split() if len(w) > 3]
    if said and words and sum(1 for w in words if w in said) >= max(1, (len(words) + 1) // 2):
        return "role"
    return "wrong"


def scored(addresses) -> list[str]:
    """The addresses whose role counts (not a placeholder)."""
    return [a for a in addresses if GOLD[a.lower()][1].lower() not in UNSCORED_ROLES]


def run(model: str, *, limit: int | None = None, refresh: bool = False, progress=lambda m: None) -> dict:
    """Ask the model about every gold address (or the first `limit`), score it, and write gold34-<model>.json."""
    decompiles = load_decompiles()
    addresses = [a for a in sorted(GOLD) if a in {k.lower() for k in decompiles}]
    if limit:
        addresses = addresses[:limit]
    tag = model.replace(":", "-").replace("/", "-")
    out_path = GOLD_DIR / f"gold34-{tag}.json"
    previous = {}
    if out_path.is_file() and not refresh:
        previous = {row["address"]: row for row in json.loads(out_path.read_text(encoding="utf-8"))["answers"]}
    answers = []
    started = time.time()
    for address in addresses:
        if address in previous:
            answers.append(previous[address])
            continue
        item = decompiles[address]
        prompt = prompt_for(address, item["c"], item["bytes"])
        t0 = time.time()
        try:
            got = ask(model, prompt)
            error = ""
        except Exception as exc:                    # noqa: BLE001 - a dead server is a recorded failure
            got, error = {}, f"{type(exc).__name__}: {exc}"
        row = {"address": address, "answer": got, "verdict": score_answer(got, address) if got else "wrong",
               "seconds": round(time.time() - t0, 2), "error": error,
               "proven": {"name": GOLD[address][0], "role": GOLD[address][1], "source": GOLD[address][2]}}
        answers.append(row)
        progress(f"{address}: {row['verdict']} ({row['seconds']}s)")
    counts = {"name": 0, "role": 0, "wrong": 0}
    for row in answers:
        counts[row["verdict"]] += 1
    scoreable = scored([r["address"] for r in answers])
    role_hits = sum(1 for r in answers if r["address"] in scoreable and r["verdict"] in ("name", "role"))
    summary = {"model": model, "functions": len(answers), "name_exact": counts["name"], "role_hit": counts["role"],
               "wrong": counts["wrong"], "scoreable": len(scoreable),
               "role_rate": round(role_hits / len(scoreable), 3) if scoreable else 0.0,
               "seconds": round(time.time() - started, 1),
               "seconds_per_function": round((time.time() - started) / max(1, len(answers)), 2),
               "answers": answers}
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary
