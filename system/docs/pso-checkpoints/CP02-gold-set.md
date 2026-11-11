# CP02 gold set — done (both models measured; neither is a namer)

Session identity: DeepSeek    Branch: ds-pso-cp02-gold-set-20261110    Commits: this branch
Goal: 1 (decrypt / P2b)

## The gold set

`docs/research/pso-gc-executable.md` §3's table has **30 rows**, not 34 (the guide says 34; the map's own table is the
record and it has 30 addresses — recorded rather than padded). All 30 were exported from the Ghidra project
`D:\gBox\ghidra-pso\PSO` (program `/pso_v3.elf`) with pyghidra, each function's decompiled C.
**Names are stripped address-free**: the function's own symbol becomes `this_function`, every callee becomes
`callee_1`, `callee_2`… in order of appearance. Verified: **no prompt contains an address or a `FUN_` name** for any of
the 30. Output: `D:\gBox\pso-ds\llm\decompiles.json` (`system/tools/export_decompiles.py`).

## The asker/scorer

`gbox/pso_llm.py`: `GOLD` (address → proven name, role, source), `prompt_for`, `ask` (Ollama `/api/generate`, JSON
format, temperature 0, 16k context), `score_answer` (exact name / same role / wrong), `run` (writes
`D:\gBox\pso-ds\llm\gold34-<model>.json`). Placeholder roles ("guarded routine", the thunks) stay in the set but are
**excluded from the role rate** (25 of 30 scoreable). A dead server is recorded per function, never raised.
Tests: `tests/test_pso_llm.py` **7 passed**.

## The two scores (full 30, `temperature 0`)

| model | size | name exact | role hits | wrong | role rate | seconds/function | total |
|---|---|---|---|---|---|---|---|
| `qwen2.5-coder:32b` | 20.3 GB | 0 | 1 | 29 | **0.04** (1/25) | **23.50** | 705 s |
| `qwen2.5-coder:14b` | 9.0 GB | 0 | 1 | 29 | **0.04** (1/25) | **2.73** | 82 s |

**Both are far below the guide's ~50 % bar.** The one hit is the same function for both (`8000f998`, BEGIN_TRAVEL — the
two-instruction flag write is readable from its code alone). Neither model names a single function exactly.

## Five example answers (two right-ish, three wrong)

| address | proven | 14B answer | 32B answer | verdict |
|---|---|---|---|---|
| `8000f998` | BEGIN_TRAVEL — sets the area-load request flag | `SET_FLAG` — "sets a flag at a specific memory address" | `SET_FLAG` — "sets a flag at an offset from a base address" | **role** (both) |
| `80103748` | F_DELETE — object delete | `HANDLE_EVENT` — "handles an event by calling various functions" | `PROCESS_PARAM_AND_CALL` | wrong (both) |
| `801b8310` | F_INVENTORY — inventory | `CHECK_AND_CALL` — "checks a condition and calls another function" | `CHECK_AND_CALL` | wrong (both) |
| `801bab1c` | WARP — executes the party area transition | `HANDLE_INPUT` | `CHECK_AND_PROCESS` | wrong (both) |
| `80228540` | SET_TARGET — stores the travel destination | `SET_TARGET`-style store named as a setter but scored wrong (the C shows the write; the *destination* meaning is not in it) | similar | wrong (both) |

## The decision

The guide says below about 50 % on roles: *keep the model only for summaries and candidate lists; no name it proposes
enters `pso_ram.py` without a decompile or live proof.* That is the decision, recorded:

- **Chosen model: `qwen2.5-coder:14b`** — the same role rate as the 32B, **8.6× faster** per function (2.73 s vs
  23.50 s) and 11 GB smaller, which leaves room for Dolphin beside it on the 3090.
- **Neither is used to name anything.** They are used for summaries, candidate lists and cross-checks (CP3), with the
  rule that a name reaches `pso_ram.py` only after a decompile or live proof.

## What this means for CP3

CP3's bulk labelling now has a measured ceiling: at 4 % role accuracy the labels are not evidence, they are leads for
the RE session to check. That is still useful (the pipeline in `gbox/pso_llm.py` can label thousands of functions
unattended at about 2.7 s each on the 14B), and CP3's evidence file will say exactly that rather than implying
accuracy. If a stronger local model arrives later, `run(model)` re-scores the same gold set in 82 s.

## Needs

- nothing from the operator; the pulls are done and the server is configured;
- the 32B is kept on `D:` (20.3 GB) as the second data point, or can be removed; the `ollama ps` keep-alive is 24 h.

Tests: `test_pso_llm.py` 7 passed; CP0 baseline unchanged (45 failed / 1,329 passed / 132 skipped).

Next: CP3's labelling pipeline with the 14B, and the evidence states the 4 % ceiling plainly.
