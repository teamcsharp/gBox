# Pine Radio / ComfyUI handoff: share Spark with gBox

## Message to give the Pine Radio project

> Please add a cooperative gBox compute window on Spark. Preserve live audio/radio playback, saved jobs and operator sessions. During that window, pause admission of new nonessential image/video generations and other large GPU jobs; let existing work finish and save its state. Release unused ComfyUI checkpoints and idle model residents through the owning application's supported mechanism. Do not kill processes or unload models serving an active request. Aim to make at least **48 GiB of MemAvailable** available before a larger gBox coding model trial, retain **16 GiB for the OS, radio and other services**, and admit only **one GPU-heavy job across the participating projects at a time**. If radio cannot maintain reliable playback under those limits, report the measured requirement and postpone the trial. When the window ends, return the paused queues to their prior state. Please report MemAvailable, swap activity, GPU utilization, loaded models and radio underruns before and after.

This is a proposed coordination policy, not a cross-project lock that gBox already enforces. Pine Radio and ComfyUI must implement or explicitly honor it. No services were stopped or reconfigured by this change. Do not commit unrelated changes in the Pine Radio checkout.

## Observed on 2026-10-14

Read-only Spark inspection: about 121.7 GiB total RAM, 15.8 GiB available, 20.9 GiB swap occupied and 96% GB10 utilization. Three Ollama residents included `gpt-oss:20b` and two small Gemma variants. This is a momentary snapshot, not attribution of the load to Pine Radio or ComfyUI. Occupied swap alone does not prove current paging; measure `vmstat 1` during the trial.

Ollama is installed on Spark. Installed coding options include `qwen2.5-coder:3b` (1.8 GiB weights), `qwen2.5-coder:7b` (4.4 GiB), and `qwen2.5-coder:32b` (18.5 GiB). `gpt-oss:20b` is already the configured Spark helper baseline. Many larger models are stored on disk; that does not mean they fit alongside active workloads. The JAYBUILTFINALE loopback Ollama service was unreachable during inspection; i9 availability is not yet verified. Updated worker inventories expose each machine's installed models without loading them.

## Model selection and acceptance

- Keep the existing Spark `gpt-oss:20b` baseline until measured comparisons justify changing it. First compare the already installed `qwen2.5-coder:32b` on real gBox function reconstruction tasks during an exclusive compute window.
- An optional coding candidate is [`qwen3-coder:30b`](https://ollama.com/library/qwen3-coder), approximately 19 GB of weights. It is not currently installed. Trial it only after the resource window is established; model choice is not a claim that it is best for this workload. The 480B variant needs at least 250 GB memory and does not fit this Spark.
- On 8 GB desktop GPUs, start with [`qwen2.5-coder:3b`](https://ollama.com/library/qwen2.5-coder:3b), around 1.9 GB of weights, for short evidence reviews. Try 7B only when measured free VRAM leaves space for context and the desktop. These are specialist helpers, not replacements for the full coding agent.

Compare identical saved function/evidence bundles, structural checks and reviewer verdicts. Record model digest, prompt/output tokens, wall time, RAM/VRAM peak and verified corrections. A model's own PASS is not verification. Choose the model with useful verified results per unit time within the measured resource envelope; step down if paging, audio glitches or poor latency appear.

## Ollama settings for the owning project to review

Use explicit context sizes: 8K for the new bounded helper; start larger Spark coding trials at 32K and measure before increasing. Full coding-agent tasks may need 64K or more and should remain on the existing main route. Context and parallel calls increase memory use. See [Ollama context guidance](https://docs.ollama.com/context-length).

For a dedicated compute window, consider `OLLAMA_NUM_PARALLEL=1` and `OLLAMA_MAX_LOADED_MODELS=1`; these are daemon-wide settings, so coordinate all users before applying them. `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0` may reduce context memory if supported, with an accuracy tradeoff. Changing service environment requires a coordinated restart. See [Ollama FAQ](https://docs.ollama.com/faq). Do not restart a shared daemon during active requests.

The new helper requests `keep_alive:0` for its own calls, limits output and does not issue stop/unload requests for other models. Keep Ollama bound to loopback on each worker; gBox dispatches authenticated jobs rather than exposing an unauthenticated LAN model server. Enforce local-only operation with the daemon's supported cloud-disable configuration if required. See [chat request options and token counts](https://docs.ollama.com/api/chat).

## gBox preference and operating limits

Preferences → **Idle Ollama assistance** lists registered PCs, loopback availability, installed model names, an opt-in checkbox, model weight budget, context/output limits and free-RAM reserve. Disabled by default, remembered by worker name across reconnects. There are no automatic model downloads, installations or changes to Pine Radio/ComfyUI.

The `ollama_assist` tool provides `status` and `analyze`. The orchestrator can submit small evidence reviews to a ready opted-in worker with `require_worker` and `agent_use:true`. The normal queue records the job/result; `ollama-analysis.json` records the prompt, answer, model digest and actual Ollama prompt/output token counters. This assists decompilation reasoning; Ghidra still performs the disassembly/decompilation and native validation remains required. This does not automatically move an arbitrary running Spark job between machines.

Suggested initial helper preferences, after a resource window is available:

| Machine / model | Weight budget | Free RAM reserve | Context |
| --- | ---: | ---: | ---: |
| 8 GB desktop GPU / coder 3B | 3 GiB | 8 GiB | 8192 |
| Spark / existing gpt-oss 20B | 16 GiB | 16 GiB | 8192 |
| Spark / coder 32B trial | 24 GiB | 16 GiB | 8192 |

These small helper contexts are for individual function reviews, not repository-wide agents. Increasing the model budget reserves more headroom; it does not change quantization or limit Ollama's actual allocation.

New work waits for Gaming mode to be off, no human game, five minutes of Windows input inactivity, current resource samples and CPU/GPU below the existing 70% admission budget. RAM must cover the selected weight budget, 2 GiB estimated overhead and the configured reserve. Dedicated GPUs need weights plus at least 1 GiB free VRAM. These are conservative admission estimates, **not hard OS memory or utilization caps**; context allocation may exceed them.

One helper call runs at a time per worker, with at most two minutes per streamed work unit. It checks the operator/policy between streamed chunks, closes the request when interrupted, and has a 15-second read timeout while waiting for a chunk. It does not cancel other applications' inference. A normal idle PC does no work until there is an actual evidence-review job; no synthetic busywork is generated. Backend/worker updates are required before these preferences can take effect.
