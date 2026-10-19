# Model trials on lilspark2

The Tasks providers view exposes five installed recipes: Qwen3.8 Flash Next
FP4, Qwen3-Coder-Next FP8, GLM-5.3 Flash NVFP4, Nemotron 3 Super 120B NVFP4,
and Nemotron 3.5 Bolt 74B-A9B 24GB. These are candidates, not measured rankings.

The current endpoint is `http://10.89.1.225:8000/v1`. The logical Hermes route
remains `sparkDeux` / `gbox-sparkDeux` so existing task pins and history survive.
The physical host name is `lilspark2`. Recipes live in
`~/spark-vllm-docker/recipes` on that machine.

1. **Prepare** builds or locates the recipe's image and downloads its weights.
   This can consume substantial disk space and time. It does not stop inference.
2. **Start trial** drains current inference, retains the original container and
   launches the recipe in single-node mode with 64k context. Native tool calls
   and a follow-up tool response must pass before Hermes is connected. A failed
   remote launch restarts the original container and its retained launch script.
3. **Use if already running** validates the selected model at the endpoint and
   updates Hermes without restarting vLLM. Use this after switching models with
   the Spark recipe tools yourself.

Model switches preserve the operator's concurrent task setting and scheduler
capacity. Assess completed work, tests, failed calls, queue latency and KV memory. The
proxy records the model actually serving each call, even when an older task is
pinned to a previous model. A completed call is not a completed inbox task.
Use the same bounded tasks and acceptance tests when comparing models; keep
DeepSeek result review and ZAI supervision enabled.

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
`qwen-coder`, `glm-flash`, `nemotron-super`, `nemotron-bolt`.
