# CP02 gold set — partial (pipeline built and measured on the 14B; the 32B run waits on the pull)

Session identity: DeepSeek    Branch: ds-pso-cp02-gold-set-20261110    Commits: this branch
Goal: 1 (decrypt / P2b)

## The gold set

`docs/research/pso-gc-executable.md` §3's table has **30 rows**, not 34 (the guide says 34; the map's own table is the
record and it has 30 addresses — recorded rather than padded). All 30 were exported from the Ghidra project
`D:\gBox\ghidra-pso\PSO` (program `/pso_v3.elf`) with pyghidra, each function's decompiled C.
**Names are stripped address-free**: the function's own symbol becomes `this_function`, every callee becomes
`callee_1`, `callee_2`… in order of appearance (a first version renamed them `sub_<address>`; verified now that **no
prompt contains any address or `FUN_` name for all 30**).

Output: `D:\gBox\pso-ds\llm\decompiles.json` (30 entries) via `system/tools/export_decompiles.py`.

## The asker/scorer

`gbox/pso_llm.py`: `GOLD` (address → proven name, role, source), `prompt_for`, `ask` (Ollama `/api/generate`, JSON
format, temperature 0, 16k context), `score_answer` (exact name / same role / wrong), `run` (writes
`D:\gBox\pso-ds\llm\gold34-<model>.json` with per-function answers, verdicts, seconds, and the summary).
Placeholder roles ("guarded routine", the thunks) are in the set but **excluded from the role rate** (25 of 30 are
scoreable). A dead server is recorded per function, never raised.

Tests: `tests/test_pso_llm.py` (7) — the gold set's shape, exact/role/wrong scoring, no address in the prompt, a run
writing honest counts, and a dead server recorded. **7 passed.**

## First measurement: `qwen2.5-coder:14b`, 6 functions (a validation subset)

| address | proven | verdict | the model's answer |
|---|---|---|---|
| `8000c040` | entry | wrong | `PROCESS_GAME_STATE` — "handles game state processing" |
| `8000f998` | BEGIN_TRAVEL | **role** | `SET_FLAG` — "sets a flag at a specific memory address" |
| `8001e5c8` | primitive | wrong | `FETCH_VALUE` |
| `800791bc` | floor-height query | wrong | `PROCESS_COLLISIONS` |
| `8007a448` | floor-query helper | wrong | `HANDLE_INPUT_AND_PROCESS` |
| `80102ac0` | inventory/equip helper | wrong | `CALL_CALEE_1` |

Summary: 0 exact names, 1 role hit of 6 (**0.167**), 5 wrong, **3.93 s/function** (first call 14.7 s including load;
the rest 1.3–2.7 s). The 14B's answers are plausible-from-the-code but not the proven roles — well below the guide's
~50 % bar, so on this evidence it is a *summariser/candidate-list* model, not a namer.

## Still open

- `qwen2.5-coder:32b` is still downloading (26.9 GB on `D:` at the time of writing; the model is about 20 GB on top of
  the 14B's 8.4 GB). When it lands: the full 30 × 2 run, the two scores, the chosen model and five example answers go
  into this file and `gold34-<model>.json` for each.
- The scaffold and the 14B subset are committed here so the measurement is not lost if the session ends.

## Tests

`test_pso_llm.py` 7 passed. No other suites touched. CP0 baseline unchanged (45 failed / 1,329 passed / 132 skipped).

## Needs

- the 32B pull to finish (no operator action);
- then the full run, which is 30 × about 4 s ≈ 2 min per model plus load.

Next: finish the pull, run both models over all 30, score, pick the model, and continue to CP3 with the winner.
