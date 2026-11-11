# CP03 bulk labelling — done (pipeline running; 82 rows labelled; the 4 % ceiling is stated, not implied)

Session identity: DeepSeek    Branch: ds-pso-cp03-labelling-20261110    Commits: this branch
Goal: 1 (decrypt / P2b), feeding CP7, CP8, CP12, CP15

## The export (CP3 step 1-2)

`system/tools/export_functions.py` (pyghidra venv) writes `D:\gBox\pso-ds\llm\functions.jsonl`, one row per function:
address, size, callers, callees, referenced strings (up to 12), and the decompiled C **address-free** (own symbol
`this_function`, callees `callee_N`) truncated to 6 KB.

The selection is CP3's own list, plus one hop of callers and callees:

| neighbourhood | found | how |
|---|---|---|
| `0x8028f508` and its callers (CP12) | seeded | by address |
| scene `n.rel` / `r.rel` loader (CP8) | **seeded** | functions referencing those strings: `801fb798` (`r.rel`), `802066bc` (`n.rel`), `80206db8` (`n.rel`; `nm.rel`) |
| `CARD*` SDK callers (CP9) | **seeded** | `PSO_GUILDCARD` / `GUILDCARD_FILE`: `801fbb7c`, `801fc564`, `801fd94c`, `801fe8a8`, `801fe938`, `802008e8` |
| the `.evt` interpreter's callers (CP7) | not matched | no function references an `.evt` string; the interpreter is reached through the set tables, so this needs CP7's own work (recorded, not hidden) |
| `TObjCityDoor_*` readers / door vtables (CP15) | not matched | the door names live in the class-registry *data* and are reached through the vtable/id dispatch, not string refs (the same finding as CP0's census) |

Export size: **82 rows** (20 seeds + one-hop callers/callees). The string scan covered 9,789 string-data entries and 651
functions that reference strings; 20 matched the patterns.

## The labeller (CP3 step 3)

`system/tools/label_functions.py`, installed to `D:\gBox\pso-ds\llm\label.py` (`--install`), asks
`127.0.0.1:11434` in JSON mode at temperature 0, appends to `labels.jsonl`, and is **resumable** (labelled addresses are
skipped). It records each answer, its seconds, and any error per row.

## Accept evidence

- `labels.jsonl` grows on its own: measured **19 → 29 rows in 20 s** while the batch ran.
- Throughput: the full batch labelled **76 rows in 169 s** = **1,621 functions/hour, 2.22 s each** (a first 6-row batch
  measured 1,913/hour at 1.88 s; the spread is model warm-up). 82 rows are labelled in total, including the CP2 subset
  rows that overlap.
- `nvidia-smi` during the batch: **RTX 3090, 12,002 MiB, 68 % utilisation** (the 14B loaded at 10 GB plus context).
- Cost: **$0.00 per label** — local model, no paid API call. Dollars per accepted label: **$0.00**.

## Labels reviewed, and what was accepted

Only rows tied to an open checkpoint were reviewed, and the rule is the one CP2 established: **a model answer is a lead,
not evidence**. Accepted as *string-proven relations* (the string is the proof; the model's label had to agree with it):

| address | string (the proof) | model label | what is now claimed |
|---|---|---|---|
| `801fb798` | `r.rel` | `RESOURCE_MANAGER` — "loading and processing resources" | the function is part of the **`r.rel`/`n.rel` scene-loader neighbourhood** (CP8) |
| `802066bc` | `n.rel` | (labelled in the batch) | same neighbourhood; `80206db8` references `n.rel` and `nm.rel` |
| `801fbb7c`, `801fc564` | `PSO_GUILDCARD` | `CHECK_AND_PROCESS_GUILDCARD`, `PROCESS_GUILDCARD` | these functions are in the **memory-card SDK (`CARD`) neighbourhood** (CP9) |

Nothing else was accepted, and no name was written into `pso_ram.py` or `pso-gc-executable.md`. The model's *role* text
was not accepted even where plausible, because the code alone did not prove it — that is exactly the 4 % gold-set
accuracy showing up in practice (e.g. `8000e334` labelled `UNKNOWN_FUNCTION`, `801e17f4` "processes game data" for the
version-banner string).

## Honest read of CP3's value

At **0.04 role accuracy** (CP02) the labels are a **browsing aid**: they give the RE session 82 pre-read rows with
strings, callers and callees attached, and they cost nothing. They are not evidence, and CP7/CP8/CP9/CP12 still need
their own decompiles. The throughput (1,600/hour) means the whole 25,981-function image is about 16 hours unattended if a
later checkpoint wants it; the script resumes, so that is a background job, not a blocker.

## Tests

No gbox tests changed (tools only). CP0 baseline unchanged: 45 failed / 1,329 passed / 132 skipped.

## Needs

- nothing from the operator;
- the `.evt` interpreter neighbourhood (CP7) and the door-reader neighbourhood (CP15) need their own static routes, since
  neither is reachable by string reference — recorded as the gap.

Next: CP4/CP5 (the lobby jump state and the Forest 1 warp), which need no model.
