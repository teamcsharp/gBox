# CP1 evidence: the local coder model on the 3090 (i9-NUC)

Measured 2026-11-10 18:44-18:50 CDT on **i9-NUC** (`NUC9i9QNX`, Windows), by the DeepSeek session. The checkpoint's
"no local model" (13:46) is stale: Ollama 0.5.7 is installed, serving on `127.0.0.1:11434`, with both coder models
already pulled. Nothing was installed or downloaded by this session; this pass **measured and left the machine as
found** (the 14b loaded).

## The environment (set, verified in the user environment)

```
OLLAMA_MODELS        D:\gBox\llm\ollama-models        (D: has 240 GB free)
CUDA_VISIBLE_DEVICES GPU-f3697ec1-9016-3424-7886-750a24ddc07a   (the RTX 3090's UUID; the 2070 is index 0)
```

The 3090 is 24,576 MiB; the checkpoint's budget is 22 GB or less in total.

## The models (as pulled; `ollama list`)

| model | size | digest |
|---|---|---|
| `qwen2.5-coder:32b` | 19,851,349,898 B (19.9 GB) | `b92d6a0bd47ee79114298de0177bf920c05a706d12633950b3936778492bef41` |
| `qwen2.5-coder:14b` | 8,988,124,298 B (9.0 GB) | `9ec8897f747e246e970bc5cfdda85d22f1123dc2e3d34978a010a75968716849` |

## The three accept outputs

**1. `ollama ps` - 100% GPU.** With the 32b loaded:

```
NAME                 ID              SIZE     PROCESSOR    UNTIL
qwen2.5-coder:32b    b92d6a0bd47e    21 GB    100% GPU     24 hours from now
```

and with the 14b loaded (the state the machine was found in, restored after the 32b measurement):

```
NAME                 ID              SIZE       PROCESSOR    UNTIL
qwen2.5-coder:14b    9ec8897f747e    10.0 GB    100% GPU     24 hours from now
```

**2. `nvidia-smi --query-compute-apps=pid,process_name,used_memory,gpu_uuid` - the runtime on the 3090:**

```
43024, C:\Users\maste\AppData\Local\Programs\Ollama\lib\ollama\runners\cuda_v12_avx\ollama_llama_server.exe, [N/A], GPU-f3697ec1-9016-3424-7886-750a24ddc07a
```

`nvidia-smi --query-gpu=index,name,memory.used,memory.total` beside it: 3090 `19634 MiB / 24576 MiB` with the 32b
loaded, `9134 MiB` with the 14b (the 2070 idles at ~2,000 MiB with the desktop).

**3. `GET /api/workers`, row `i9-NUC`** (the i9's plane, 2026-11-10 18:47 CDT):

```json
{"ollama": {"available": true, "sampled_at": 1794357954.8,
  "models": [{"name": "qwen2.5-coder:32b", "size": 19851349898, ...},
             {"name": "qwen2.5-coder:14b", "size": 8988124298, ...}]},
 "resources": {"gpus": [{"name": "NVIDIA GeForce RTX 2070", "memory_used_mb": 2007.0},
                       {"name": "NVIDIA GeForce RTX 3090", "memory_used_mb": 12002.0, "memory_total_mb": 24576.0}]}}
```

## The eval rates (`ollama run <model> --verbose`, one 40-token prompt)

| model | load | prompt eval | generation | **eval rate** |
|---|---|---|---|---|
| `qwen2.5-coder:14b` | 11.15 s | 400.00 tokens/s | 62 tokens in 1.197 s | **51.80 tokens/s** |
| `qwen2.5-coder:32b` | 21.43 s | 272.11 tokens/s | 51 tokens at 28.60 tokens/s | **28.60 tokens/s** |

Both are full-GPU (100% GPU in `ollama ps`); the 32b's 21 GB sits inside the 22 GB budget with the desktop beside it.

## The 16k context (the checkpoint's "16k, not more")

Ollama 0.5.7 serves these tags at its 2,048 default and has no `OLLAMA_CONTEXT_LENGTH` set, so two derivative tags were
created on the machine (same blobs, only a `PARAMETER num_ctx`):

```
FROM qwen2.5-coder:14b
PARAMETER num_ctx 16384
```

`ollama create qwen2.5-coder:14b-16k -f Modelfile` and the same for the 32b. `ollama show qwen2.5-coder:14b-16k
--parameters` prints `num_ctx 16384`; the 14b-16k loads at 15 GB (11,990 MiB resident on the 3090), 100% GPU, and served
39.22 tok/s on a short generation. `OLLAMA_CONTEXT_LENGTH=16384` was also set in the user environment as a default for a
future restart. Use the `-16k` tags for the lane and for the Hermes node.

## What this means for CP2 and CP3

The local coder lane has its two candidates: the 14b is ~1.8x the 32b's speed, the 32b is the better coder. CP2 (the
34-function gold set) can now be run against both on the 3090 and the better score/speed pick becomes the lane's model.
The Hermes local-node registration (the i9 kiosk, night hand-off section 1b) is a separate step and is not claimed here.
