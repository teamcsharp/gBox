# The i9 service node: the local model on the 3090, measured (2026-11-10 night)

This is section 1b of the night hand-off ("a heavy local LLM on the 3090, serving gBox at high concurrency"). It is the
**measurement** part: what is installed, what it does under concurrency, and what the node can honestly be registered
with. The registration itself and the continuous-batching server are the open steps at the bottom.

Measured by the DeepSeek session on **i9-NUC** (`NUC9i9QNX`, Windows 11), 2026-11-10 18:47-19:02 CDT, with the operator
away (no game running; the 2070 idle at ~2 GB for the desktop).

## What is on the machine

- **Ollama 0.5.7**, serving `127.0.0.1:11434` (loopback only, as the checkpoint wants), started 14:30 by the tray app
  (`ollama app.exe` supervising `ollama.exe serve`).
- Two coder models already pulled to `D:\gBox\llm\ollama-models`:
  - `qwen2.5-coder:14b` - 8.99 GB, Q4;
  - `qwen2.5-coder:32b` - 19.85 GB, Q4 (inside the 22 GB budget with the desktop beside it: 19,634 MiB measured).
- Environment: `CUDA_VISIBLE_DEVICES` pinned to the 3090's UUID (`GPU-f3697ec1-...`), `OLLAMA_FLASH_ATTENTION=1`,
  `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_NUM_PARALLEL=2`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_KEEP_ALIVE=24h`.
- **Context**: the server has no `OLLAMA_CONTEXT_LENGTH`, and Ollama 0.5.7 serves these tags at its 2,048 default -
  too small for this repo's functions. Two derivative tags are created on the machine with the checkpoint's 16k:
  `qwen2.5-coder:14b-16k` and `qwen2.5-coder:32b-16k` (`FROM <base>` + `PARAMETER num_ctx 16384`; `ollama show --parameters`
  prints `num_ctx 16384`, and the 14b-16k serves at 15 GB / 11,990 MiB resident, 100% GPU). Use those tags for the node;
  the `OLLAMA_CONTEXT_LENGTH=16384` set in the user environment is a belt-and-braces default for a future restart (it
  applies only in Ollama versions that read it).

## Single-stream and concurrency (measured)

One prompt ("write a Python function that reverses a list"), `num_predict=32`, `temperature=0`, `stream=false`, against
the live server with `OLLAMA_NUM_PARALLEL=2`. Aggregate = all generated tokens / wall time of the batch.

| model | 1 request | 4 concurrent | 8 concurrent | 16 concurrent |
|---|---|---|---|---|
| `qwen2.5-coder:14b` | 24.5 tok/s (0.47 s eval) | 47.0 tok/s aggregate | 47.8 tok/s aggregate | 48.6 tok/s aggregate |
| `qwen2.5-coder:32b` | 28.6 tok/s (single-shot, see CP1) | 29.9 tok/s aggregate | 30.7 tok/s aggregate | not measured |

Reading it: with two slots the GPU is **compute-saturated** - aggregate throughput is flat from 4 to 16 concurrent
requests (14b ~48 tok/s, 32b ~30 tok/s); everything beyond the two slots queues, so per-stream speed falls linearly
(16 concurrent on the 14b is ~3 tok/s each) and wall time grows with the queue. That is enough for **2-way** Hermes work
(one analysis + one code task beside it), and not enough to advertise 8-16 lanes.

## The recommendation for the node

- **Model:** `qwen2.5-coder:14b` for the node's default (48 tok/s aggregate, ~24 tok/s a lane), `qwen2.5-coder:32b` for
  hard analysis/decryption reasoning at ~30 tok/s aggregate. Both are 100% GPU, no CPU spill.
- **Capacity:** register it at **`max_parallel_jobs = 2`** - the measured slot count - not 8 or 16; a larger number only
  queues work inside Ollama where Hermes cannot see it.
- **For real high concurrency** (the operator's "heavy duty with high concurrence"), Ollama is the wrong server: it runs
  two slots and its scheduler does not batch beyond them. The next step is a continuous-batching server on the same
  card - `vLLM` (needs WSL2 on this Windows box, `--max-num-seqs 8..16`, paged KV, ~0.6-0.8 GB per sequence at 16k) or
  `llama.cpp`'s `llama-server --parallel 8 --cont-batching` with the Q4 GGUF - and measure it the same way before
  promising more than two lanes.

## Registering it with gBox (the exact shape, not applied)

Hermes local nodes are `[hermes.local.nodes.<name>]` in the config (per-node live switches in
`gbox-data/hermes/local-nodes.json`). The shared `gbox.toml` must **not** carry this node - the Spark reads the same file
and would proxy an "i9" node to its own Ollama. It belongs in the i9's per-host overlay,
`system/gbox.local-i9-nuc.toml`:

```toml
[hermes.local.nodes.i9]
provider = "i9-local"                 # the custom provider name the supervisor registers
model = "qwen2.5-coder:14b-16k"       # 48 tok/s aggregate at 2 slots; the 32b-16k is the hard-reasoning alternative
upstream = "http://127.0.0.1:11434"   # this machine's Ollama
api_format = "ollama"
host_name = "i9-NUC"
shared_with_games = false             # a dedicated inference card, not the one the games render on
max_parallel_jobs = 2                 # measured slots (see above)
allow_large_tasks = true              # a dedicated local model can work bounded milestones
context_tokens = 16384
```

Two caveats before it is applied: the config overlay merges tables **one level deep**, so an overlay
`[hermes.local]` replaces the base `local` table (the block must carry every key it needs, not only `nodes`); and the
hand-off gates the node on the service-node readiness of section 1, which is a separate piece of work.

## Open steps

1. Apply the node block above on the i9 and check `GET /api/hermes/local/nodes` (the pool's view) shows it with capacity 2.
2. Serve the 32b/14b through a continuous-batching server and re-measure at 8-16 concurrent; pick the model by the CP2
   gold set, not by size.
3. Restart Ollama once to pick up the 16k context default.
