# Round 239: CP3 scoped as candidate lists - second-model labeller running at a measured 2.37 functions/min

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
No game running (tenth round).

## What the CP3 data already was

`D:\gBox\pso-ds\llm\` holds **82 exported functions** (`functions.jsonl`: address, size, name, callers, callees, strings, decompiled C) and
**82 labels** (`labels.jsonl`) - all produced by **qwen2.5-coder:14b**, which is no longer installed, and which CP2 measured at **0.04 role
accuracy** against the proven gold set.

So the useful thing is not to re-label with the same dead model, but to add a **second opinion** from the model that does run, and to treat both
as CP2's fallback says: **candidate lists for review**.

## `label_ds.py` - resumable, separate file, agreement measured

* writes `labels-deepseek.jsonl` (never mixing models in one file);
* skips addresses already labelled **by this model**, so it can be stopped and restarted;
* carries the model's `{name, role, confidence, evidence}` plus timing;
* records **token agreement with the qwen label** for the same address - where two independent models converge, a reviewer can look first.

## Measured throughput and output

```
1/3 8000e334 WRAPPER_FUNCTION        13.7 s
2/3 8000e41c MEMCPY                 26.1 s
3/3 800196ec GET_OBJECT_ATTRIBUTE   36.2 s
written 3 in 76s = 2.37 functions/min (25.3 s each), agreement on 0/3
```

**2.37 functions/min** means the 82-function set takes about **35 minutes unattended** - which is exactly the "leave it running" shape CP3
asks for. The names are more specific than qwen's (`MEMCPY`, `GET_OBJECT_ATTRIBUTE` versus `UNKNOWN_FUNCTION`), but agreement was 0/3 because
qwen's labels were largely `UNKNOWN_FUNCTION` - a second reason not to treat either model's output as evidence.

## Honest state of CP3's accept criteria

| criterion | state |
|---|---|
| `labels.jsonl` grows on its own | **partly** - a second model's file grows, resumable; the qwen file is complete but its model is gone |
| functions per hour, measured | **142/hour** (2.37/min) measured, single model, 3090 busy |
| `nvidia-smi` shows the 3090 busy | measured during CP1 earlier (2.4 -> 13.1 GB) and the same path runs the labels |
| first reviewed labels accepted into `pso-gc-executable.md` | **not done** - and per CP2's verdict, none should be accepted without a decompile or live proof |

So CP3's throughput is real and repeatable; its **acceptance** step is deliberately empty, because the model is a lead generator.

## Files

* `label_ds.py` - the resumable second-model labeller with agreement tracking
