# Model trials on lilspark2

The Tasks providers view lists the installed single-Spark recipes as model
profiles. These are candidates, not measured rankings: Qwen3.8 Flash Next FP4,
Qwen3-Coder-Next FP8, GLM-5.3 Flash NVFP4 (held: cluster only), Nemotron 3
Super 120B NVFP4, Nemotron 3.5 Bolt 74B-A9B 24GB, Ornith 1.5 35B-A3B NVFP4,
Laguna S 2.1 NVFP4 (RedHatAI) and Ornith 1.5 122B GGUF (held: llama-server).

The current endpoint is `http://10.89.1.225:8000/v1`. The logical Hermes route
remains `sparkDeux` / `gbox-sparkDeux` so existing task pins and history survive.
The physical host name is `lilspark2`. Recipes live in
`~/spark-vllm-docker/recipes` on that machine; the ones gBox owns are kept in
`system/hermes/spark2-recipes` and installed there (as new `gbox-*.yaml` files;
a differing file is copied to `~/.local/state/gbox-model-trials/recipe-backups`
first) by every Prepare and Start trial, through the dedicated SSH management
identity. Edit them in the repo, not on the Spark.

1. **Prepare** installs gBox's recipes, builds or locates the recipe's image and
   either downloads its weights or, for checkpoints the operator placed under
   `~/models`, checks that every shard the index names is present and has the
   Hub's size. This can consume substantial disk space and time. It does not
   stop inference.
2. **Start trial** drains current inference, retains the original container and
   launches the recipe in single-node mode with its full context and the KV
   cache filled (per-profile settings below). Native tool calls and a follow-up
   tool response must pass before Hermes is connected. A failed remote launch
   restarts the original container and its retained launch script. A retained
   container the operator stopped by hand is neither drained nor restored.
3. **Use if already running** validates the selected model at the endpoint and
   updates Hermes without restarting vLLM. Use this after switching models with
   the Spark recipe tools yourself, or after serving a GGUF with llama-server.

The route's context becomes what the server advertises (`max_model_len` on
`/v1/models`), with the profile's figure as the fallback; there is no 64k cap.

## Maxing one GB10

The operator wants lilspark2 filled: the whole KV cache, whatever the task
count. Every profile therefore launches with `--gpu-memory-utilization 0.88`
(0.90 for Laguna), the model's own maximum context, and enough sequences for
all Hermes jobs to decode in one batch. Each shipped recipe explains its
numbers in its comments. Measured means read from vLLM's startup log on
lilspark2; the rest are estimates from the same accounting (budget minus
weights, non-torch memory and peak activation).

| Profile | Recipe | Weights | Context | KV cache | Sequences | Notes |
|---|---|---|---|---|---|---|
| qwen-coder | gbox-qwen3-coder-next-fp8 (shipped) | 75.5 GiB (measured) | 262144 | ~20 GiB, ~1.5M FP8 tokens (at 0.80: 13.3 GiB, 998k, measured) | 64, 8192 batched | the running model; 42 % prefix hits, KV 29-52 % used before the change |
| ornith-35b | gbox-ornith-1.5-35b-a3b-nvfp4 (shipped) | 22 GiB (publisher) | 262144 | ~75 GiB, ~6M tokens (publisher at 0.75: 61 GiB, 5.1M) | 64, 8192 batched | MTP K=1, Marlin NVFP4 MoE; ~90 tok/s single stream, 330-390 aggregate at 8 (publisher) |
| laguna-s | gbox-laguna-s-2.1-nvfp4 (shipped) | 92.9 GiB (49 shards, verified) | 262144 | ~7-8 GiB, ~300k tokens | 16, 4096 batched | RedHatAI keeps 8 expert layers in BF16, 22 GiB more than poolside's 71 GB NVFP4; 13-15 tok/s single stream (poolside) |
| qwen-flash | qwen3.8-flash-next-nvfp4-solo (upstream) | b12x, PLE on disk | 262144 | recipe default at 0.88 | 8, 4096 batched (recipe) | untested at 0.88 |
| nemotron-super | nemotron-3-super-nvfp4 (upstream) | ~62 GiB | 262144 | ~35 GiB at 0.88 (estimate) | 32 (recipe) | |
| nemotron-bolt | nemotron-3.5-bolt-24gb (upstream) | 24 GB class | recipe "auto": fitted to the KV cache | | 32, 8192 batched (recipe) | DFlash draft |
| ornith-122b | ornith-1.5-122b-gguf.sh (held) | 79.7 GB GGUF (UD-Q4_K_XL) | 262144 per slot | ~25 GiB q8_0 for 8 slots | 8 slots | llama-server; see below |

Laguna is the tight one: 262144 needs 6.3 GiB of KV for a single request. If
vLLM reports the cache too small at startup, the recipe's comments say what to
lower. poolside's own `poolside/Laguna-S-2.1-NVFP4` (71 GB) would leave about
30 GiB of KV on the same box.

## Ornith 1.5 122B GGUF

`unsloth/Ornith-1.5-122B-GGUF` (UD-Q4_K_XL, three shards, 79.7 GB) cannot be
served by the vLLM image on lilspark2: it has no `gguf` package and vLLM's
GGUF loader does not cover the Qwen3.5-MoE hybrid architecture. The plan in
`system/hermes/spark2-recipes/ornith-1.5-122b-gguf.sh` serves it with
llama.cpp's `llama-server` (built once on lilspark2 with CUDA 13 for sm_121):
8 slots of 262144 tokens, q8_0 KV cache with flash attention, every layer on
the GPU, the GGUF's own chat template for XML tool calls, reasoning split into
`reasoning_content`, served on port 8000 under the Hub id. Its OpenAI-compatible
`/v1` works with gBox's proxy and probe unchanged. The profile is held (no
Prepare or Start): stop the vLLM container, run the script, then press Use if
already running. Before the first start, confirm the download finished and the
three shard sizes match the Hub listing; do not interrupt a running download.
Ollama (installed on lilspark2, inactive) is the fallback engine, with
`OLLAMA_NUM_PARALLEL` and a gBox node in `api_format = "ollama"`.

Model switches preserve the operator's concurrent task setting and scheduler
capacity. Assess completed work, tests, failed calls, queue latency and KV memory. The
proxy records the model actually serving each call, even when an older task is
pinned to a previous model. A completed call is not a completed inbox task.
Use the same bounded tasks and acceptance tests when comparing models; keep
DeepSeek result review and ZAI supervision enabled. The sparkDeux route sends
`enable_thinking=false` on every call; Ornith and Laguna honour it and answer
without a thinking block unless the node's `enable_thinking` is switched on.

The installed GLM recipe is cluster-only. NVIDIA documents approximately
166 GiB of VRAM for this checkpoint, exceeding lilspark2's 128 GB shared memory.
Its controls are held with this reason; reducing context does not make its
weights fit. This controller never borrows the prime Spark for cluster inference.
Source: https://huggingface.co/nvidia/GLM-5.3-Flash-FP4-Local

State lives in `hermes-dispatch/model-trials.json`; successful connection
receipts retain model, time, token usage and validation latency. Remote build
and launch logs remain in `~/.local/state/gbox-model-trials/<job-id>.log`.
An interrupted busy job is held for inspection rather than silently restarted.
Inspect its process, containers and endpoint before clearing its state.
Operator enable switches survive switching. Preparation is separate from
startup; presence of a recipe alone does not prove its weights are downloaded.

Enable the controls by setting `enabled: true` and the currently running
recipe container name in the local `model-trials.json`. The existing dedicated
SSH management identity must be configured. The API uses the existing
`POST /api/hermes/local/models/action` with actions `trial_prepare`,
`trial_start`, or `trial_adopt` and `model` equal to one of `qwen-flash`,
`qwen-coder`, `glm-flash`, `nemotron-super`, `nemotron-bolt`, `ornith-35b`,
`laguna-s`, `ornith-122b`.
