#!/bin/bash
# Ornith 1.5 122B (unsloth GGUF, UD-Q4_K_XL) on one DGX Spark with llama-server.
#
# Why not vLLM: the vllm-node image on lilspark2 has no `gguf` package and vLLM's
# GGUF loader covers dense Llama/Qwen2-style models, not the Qwen3.5-MoE hybrid
# (gated-delta linear attention plus MoE) this checkpoint is. llama.cpp serves it
# natively, with an OpenAI-compatible /v1 (chat completions with tool calls and
# a reasoning field), so gBox's proxy and the "Use if already running" action
# work against it unchanged. Ollama (installed on lilspark2, service inactive)
# is the same engine with less control over slots and context; keep it as the
# fallback: `ollama create` from the first shard, OLLAMA_NUM_PARALLEL=8,
# gBox node api_format "ollama".
#
# Checkpoint: ~/models/ornith-122b/UD-Q4_K_XL/Ornith-1.5-122B-UD-Q4_K_XL-0000{1,2,3}-of-00003.gguf
#   Hub sizes: 10,942,929 + 49,971,099,680 + 29,731,729,056 bytes (79.7 GB).
#   Check before the first start (the download must be complete and not running):
#     pgrep -af 'hf download' ; ls -l ~/models/ornith-122b/UD-Q4_K_XL/
#   and compare with https://huggingface.co/api/models/unsloth/Ornith-1.5-122B-GGUF/tree/main/UD-Q4_K_XL
#   The unsloth UD-Q4_K_XL quant (dynamic 4-bit, important tensors at higher
#   precision) is the largest that leaves room for a useful KV cache on 121.7 GiB:
#   about 74 GiB of weights, 2-3 GiB of compute buffers, 5 GiB for the OS, which
#   leaves about 40 GiB for KV. Q5/Q6 would take 90-100 GB and starve the cache.
#
# Build llama.cpp once (CUDA 13 and cmake are on lilspark2; GB10 is sm_121):
#   git clone https://github.com/ggml-org/llama.cpp ~/llama.cpp
#   cmake -S ~/llama.cpp -B ~/llama.cpp/build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=121 -DCMAKE_BUILD_TYPE=Release
#   cmake --build ~/llama.cpp/build --config Release -j 16 --target llama-server
#   (10-20 minutes. Check the model loads: ~/llama.cpp/build/bin/llama-server --version)
#
# Serve (stop the vLLM container first; both want the memory and port 8000):
#   docker stop -t 30 <gbox-trial container>      # retained; `docker start` + its /workspace/exec-script.sh brings it back
#   ~/gBox-recipes/ornith-1.5-122b-gguf.sh         # or wherever this file was copied
#
# Settings:
#   -c 2097152 -np 8: llama-server divides --ctx-size between its parallel
#     slots, so 8 slots of 262144 tokens (the model's max_position_embeddings)
#     need 2,097,152. With q8_0 KV only the 1-in-4 full-attention layers hold
#     the sequence (about 12 KB per token), about 25 GiB of the 40 available;
#     the linear-attention layers keep a fixed state per slot.
#   -ctk q8_0 -ctv q8_0 --flash-attn on: 8-bit KV cache (llama.cpp's FP8-like
#     option) needs flash attention; halves KV bytes against f16.
#   -ngl 999 : every layer on the GPU (unified memory, nothing to offload).
#   -b 4096 -ub 2048: prompt batch and micro-batch; 10B active parameters
#     prefill a 30k Hermes prompt in a few seconds.
#   --jinja: the GGUF's own Qwen3.5 chat template, which llama.cpp recognises
#     for XML tool calls and returns as OpenAI tool_calls;
#   --reasoning-format deepseek: <think> blocks go to reasoning_content, as
#     vLLM's qwen3 parser does. gBox sends enable_thinking=false per call.
#   --alias unsloth/Ornith-1.5-122B-GGUF: the model id gBox's probe asks for
#     (profile ornith-122b). --port 8000 is the sparkDeux upstream.
#   --cache-reuse 256: prefix reuse across Hermes calls that resend prompts.
#   --no-mmap is deliberately absent: with unified memory, mapping the file
#     lets the OS page cache and the GPU share the weights.
#
# After it serves (curl -s localhost:8000/v1/models), press "Use if already
# running" for Ornith 1.5 122B in Tasks > providers. gBox validates a native
# tool call and the tool-response follow-up before Hermes is pointed at it.
set -euo pipefail
MODEL="${MODEL:-$HOME/models/ornith-122b/UD-Q4_K_XL/Ornith-1.5-122B-UD-Q4_K_XL-00001-of-00003.gguf}"
BIN="${LLAMA_SERVER:-$HOME/llama.cpp/build/bin/llama-server}"
exec "$BIN" -m "$MODEL" --alias unsloth/Ornith-1.5-122B-GGUF \
  --host 0.0.0.0 --port "${PORT:-8000}" \
  -ngl 999 -c "${CTX_TOTAL:-2097152}" -np "${SLOTS:-8}" \
  -ctk q8_0 -ctv q8_0 --flash-attn on \
  -b 4096 -ub 2048 --cache-reuse 256 \
  --jinja --reasoning-format deepseek \
  --metrics
