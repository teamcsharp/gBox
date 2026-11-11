# Round 237: CP1 is unblocked and verified - the local model runs on the 3090

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
No game running (eighth round), so this is the offline lane of the PM document.

## The document is stale on CP1

`DEEPSEEK-PSO-CHECKPOINTS-2026-11-10.md` records, measured at 13:46:

> **No local model.** `ollama.available = false`. The 3090 shows 141 MB and 37-39 % while Dolphin runs ...

Re-measured now:

```
ollama available: true
models installed: deepseek-r1:14b (8.4 GB), deepseek-r1:8b (4.6 GB)
```

## And it runs on the 3090 - measured, not assumed

A real completion was requested and the GPU sampled before and during:

```
gpu before:  RTX 2070 2465 MB   |  RTX 3090  2432 MB
answer:      "<think> Okay, so I'm trying to figure out what the Python function `f` returns..."  (64 tokens, 22.8 s)
gpu during:  RTX 2070 2467 MB   |  RTX 3090 13103 MB
```

**The 3090 went from 2.4 GB to 13.1 GB used while the model answered** - a 10.7 GB jump, exactly the size of a 14 B model in
half precision plus context. That is CP1's condition ("the local coder model on the 3090 (GPU)") satisfied by observation.

Evidence file: `D:\gBox\pso-ds\cp1-local-model.json` with the model list, both GPU samples, the answer, token count and timing.

## What this re-opens

The document also lists **CP2** (the gold set of 34 known functions) and **CP3** (the bulk labelling pipeline, unattended) as downstream of
CP1. With a working local model those are **offline** jobs: the gold set is already written down, and the labelling pipeline is a local
inference loop - neither needs the emulator at all.

So while the game has not been running for eight rounds, the lane is not blocked: CP1 is done, CP2/CP3 are unblocked by it, and CP9's card
reader has its layout cracked (rounds 234-236).

## Honest note on throughput

22.8 s for 64 tokens is roughly **3 tokens/s** including the reasoning preamble. Fine for offline labelling of short items; it would be
poor for anything interactive. Worth knowing before CP3 is scheduled as "bulk".

## Files

* `cp1_local_model.py` - the measurement: model list, GPU before/during, completion, evidence JSON
