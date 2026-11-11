# CP01 the local coder model on the 3090 — partial (the 14B is up and measured; the 30-32B candidates pending)

Session identity: DeepSeek    Branch: ds-pso-cp01-local-model-20261110    Commits: this branch
Goal: 1 (decrypt / P2b)

## What was found first (the doc was written at 13:46)

Ollama **is** installed on the i9 (`C:\Users\maste\AppData\Local\Programs\Ollama\ollama.exe`, client 0.5.7) — it was
simply not running, and `ollama.available` read false because the server was down. There are **two** GPUs:
`NVIDIA GeForce RTX 2070` (`GPU-7ba78a18-…`, 8 GB) and `NVIDIA GeForce RTX 3090`
(`GPU-f3697ec1-9016-3424-7886-750a24ddc07a`, 24,576 MiB, **0 MiB used** before this step). `D:` had 253.8 GB free.

## Steps taken

1. `setx` for `OLLAMA_MODELS=D:\gBox\llm\ollama-models`, `OLLAMA_HOST=127.0.0.1:11434`,
   `CUDA_VISIBLE_DEVICES=GPU-f3697ec1-9016-3424-7886-750a24ddc07a`, `OLLAMA_FLASH_ATTENTION=1`,
   `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=2`, `OLLAMA_KEEP_ALIVE=24h`.
2. Restarted the Ollama app so the server inherits them. The first restart kept the old env (the tray app re-spawned the
   server with `C:\Users\maste\.ollama\models`); killing the app **and** the server and starting `ollama app.exe` from a
   shell that exports the new values worked — the server log then shows
   `CUDA_VISIBLE_DEVICES:GPU-f3697ec1-9016-3424-7886-750a24ddc07a`, `OLLAMA_FLASH_ATTENTION:true`,
   `OLLAMA_KEEP_ALIVE:24h0m0s`, and the models path on `D:`.
3. Pulled `qwen2.5-coder:14b` (the doc's fallback) to validate the whole path before spending 20 GB on a bigger one:
   **9.0 GB**, landing in `D:\gBox\llm\ollama-models` (8.37 GB on disk).

## Accept evidence (verbatim)

`ollama ps`:

```
NAME                 ID              SIZE       PROCESSOR    UNTIL
qwen2.5-coder:14b    9ec8897f747e    10.0 GB    100% GPU     24 hours from now
```

`nvidia-smi --query-compute-apps=pid,process_name,used_memory,gpu_uuid --format=csv` (the relevant row; the 2070's rows
are the desktop's own apps):

```
28180, C:\Users\maste\AppData\Local\Programs\Ollama\lib\ollama\runners\cuda_v12_avx\ollama_llama_server.exe, [N/A], GPU-f3697ec1-9016-3424-7886-750a24ddc07a
```

`nvidia-smi --query-gpu=name,uuid,memory.used --format=csv`:

```
NVIDIA GeForce RTX 2070, GPU-7ba78a18-c298-f7f2-d4c1-d3de4d3a6c9b, 1702 MiB
NVIDIA GeForce RTX 3090, GPU-f3697ec1-9016-3424-7886-750a24ddc07a, 9134 MiB
```

(The per-process memory column is `[N/A]` on this Windows driver; the GPU-level 9,134 MiB is the model's footprint.)

`GET /api/workers` row `i9-NUC`:

```
{"available":true,"sampled_at":1794342848.95,"models":[{"name":"qwen2.5-coder:14b","size":8988124298,
 "digest":"9ec8897f747e246e970bc5cfdda85d22f1123dc2e3d34978a010a75968716849"}]}
```

`ollama run qwen2.5-coder:14b --verbose` on "write a Python function that reverses a linked list, code only":

```
total duration:       8.0594221s
load duration:        6.3084666s
prompt eval count:    43 token(s)
prompt eval duration: 213ms
prompt eval rate:     201.88 tokens/s
eval count:           84 token(s)
eval duration:        1.532s
eval rate:            54.83 tokens/s
```

## Model table

| model | size | state | tokens/s |
|---|---|---|---|
| `qwen2.5-coder:14b` | 9.0 GB (10.0 GB loaded) | **pulled, 100% GPU, 24 h keep-alive** | **54.83** |
| a 30B MoE coder at Q4 (about 19 GB) | — | not pulled yet | — |
| a 32B dense coder at Q4 (about 20 GB) | — | not pulled yet | — |

The 14B leaves about 12 GB of the 3090 free, so Dolphin (0.2 GB) and a bigger model can coexist; CP2 wants the candidate
with the best role hit rate, so the 30-32B pulls are the next step. `ollama.available` is now `true`, so the plane's
telemetry has caught up.

## Tests

No gbox tests touched by this checkpoint (environment only). The CP0 baseline stands: 45 failed / 1,329 passed /
132 skipped on `8032491f`.

## Needs

- the 30-32B candidate pulls (about 20 GB each) before CP2 can score two models;
- nothing from the operator for the 14B path;
- `/api/workers` has no per-GPU `memory_used_mb` field in this build, so that criterion is evidenced from `nvidia-smi`
  directly (stated rather than glossed).

Next: pull one 30-32B coder, then CP2's gold set (34 functions) on both models.

## The second candidate, the concurrency, and the 16k context (2026-11-10 18:45-19:05, the night session)

This supersedes the "not pulled yet" rows above: both candidates are now on the machine and measured.

| model | size | loaded | single-shot | aggregate at 4 / 8 / 16 concurrent |
|---|---|---|---|---|
| `qwen2.5-coder:14b` | 9.0 GB | 100% GPU | 51.8 tok/s | 47.0 / 47.8 / 48.6 tok/s |
| `qwen2.5-coder:32b` | 19.9 GB | 100% GPU | 28.6 tok/s | 29.9 / 30.7 / (not run) tok/s |

With `OLLAMA_NUM_PARALLEL=2` the card is compute-saturated: aggregate throughput is flat from 4 to 16 concurrent
requests and everything beyond the two slots queues, so the honest node capacity is **2 lanes** (the operator's 8-16
lanes need a continuous-batching server - see `system/docs/i9-service-node.md`).

The context is also fixed: Ollama 0.5.7 serves these tags at 2,048 by default, so two derivative tags were created with
the checkpoint's 16k - `qwen2.5-coder:14b-16k` and `qwen2.5-coder:32b-16k` (`PARAMETER num_ctx 16384`; the 14b-16k loads
at 15 GB / 11,990 MiB, 100% GPU, 39.2 tok/s). `OLLAMA_CONTEXT_LENGTH=16384` is set in the user environment as a
future-restart default.

`GET /api/workers` does carry the per-GPU memory in this build - `resources.gpus[]` with `memory_used_mb` (3090:
12,002 MiB with the 14b-16k loaded) - so that accept criterion is read from the plane now, not only from `nvidia-smi`.
