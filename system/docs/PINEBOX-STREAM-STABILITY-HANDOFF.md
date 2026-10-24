# Pine Box / gBox stream stability handoff

Observed 2026-10-24 on lilspark. Give this document and [pinbox_gbox.md](../pinbox_gbox.md) to the Pine Box agent. The request is stable gameplay with emulator audio, not a new DJ/on-air selection. Do not publish or change Pine's station state merely to test a feed.

## Findings and limits

- A gBox PiP recovery path could replace a freshly held frame with an older cached poster. Commit `6ab96919` captures the currently displayed PiP frame before reconnecting and rejects older asynchronous poster completions. Tests include an actual browser MJPEG reconnection. This fixes that specific flash-back path; it is not proof that all transport jitter is resolved.
- The frozen RE5 death frame during this handoff coincided with an intentional between-round gBox service activation. There was temporarily no running emulator. A held picture marked **Reconnecting** does not mean gameplay is advancing. Normal cold launches and service restarts need honest reconnect/source status.
- Activation also exposed overlapping ROM-preparation requests hiding a successful fresh receipt with an older pending one. The real new-worker receipt was restored, without inventing readiness or launching a second emulator. Preserve newer completed preparation data when updating queued-request metadata.
- At diagnostic timestamp `1792819721`, with no running gameplay session or broadcast encoder, the Spark reported **GPU 96%**, **RAM 86.4%**, and about **17.8 GB available RAM**. The process listing showed ComfyUI using approximately **53,487 MiB GPU-accounted memory**, multiple Ollama model servers and substantial Python/uvicorn CPU work. These are competing workloads; the sample does not prove the cause of every earlier stall. Lowering Pine's bitrate alone cannot fix absent gameplay or GPU starvation.
- Current gBox broadcast configuration was **1280×720, 30 fps, H.264 libx264, 2500 kbit/s, audio auto, maximum three encoders**. No active encoder was present in that particular sample. Do not report that three were consuming resources.

## Instructions to give the Pine Box agent

> Connect to gBox centrally on lilspark using the existing server-side credential and stable program/PC channel. Follow `system/pinbox_gbox.md`. Keep one long-lived gameplay decoder and one shared upstream feed; do not reconnect on a five-second metadata poll, session-title change, failed status read or thumbnail refresh. Use the independent gameplay media gateway, preserve the latest decoded frame during a genuine disconnect, and never overwrite it with an older cached image. Rejoin live media after reconnect rather than replaying an accumulated historical backlog. Keep emulator audio and Gameplay volume separate from DJs, SFX and station videos. Measure source frames, encoder output and actual decoded-frame progress together before declaring stability fixed.

Apply these concrete constraints:

1. Pine running on Spark host networking uses `GBOX_URL=http://127.0.0.1:8765`; other machines use LAN `http://10.89.1.246:8765` or tailnet `http://100.74.95.59:8765`. Browser listeners use Pine's authenticated same-origin relay. Keep the upstream view token server-side.
2. Follow `/api/broadcast/program` or `/api/broadcast/pc/spark1` across titles. For Pine's browser stage use `/api/gbox/hls?k=program` or `k=pc-spark1`, not a repeatedly recreated session-specific JPEG/MJPEG connection. Native ingest can use the stable channel's `.ts` path. Do not add an encode per viewer or a second decode just to build thumbnails.
3. Confirm `gbox-pine-media.service` is serving public media on **8097** and studio media on **18098**, separate from Pine's main station loop. Studio UI remains **8096**, original tune-in door **127.0.0.1:18097**. Large station JSON/inference must not block playlist or segment admission. Keep cache coalescing and bounded upstream download concurrency.
4. Preserve the installed buffered HLS settings initially: **7.5 seconds contiguous startup/resume buffer, eight-segment live target, bounded 24-second / 16 MiB player buffer**; central playlist retains 12 segments plus 12 recently referenced segments. Do not replace this with aggressive low-latency resets. Reconnect only on a measured transport/media failure, cancel obsolete retries on recovery, and keep attachment counts stable across healthy metadata polls.
5. Show only the selected gameplay decoder. Use low-rate still thumbnails for other channels. Release hidden stage/tab decoders. Avoid full-rate preview grids, duplicate OBS/ffmpeg transcodes and capture/AI loops in the listener path.
6. Coordinate workload priority with the operator: defer ComfyUI generation, extra local model inference and nonessential analysis during gameplay broadcasting, preferably moving those jobs to Spark2. Do not indiscriminately kill unrelated processes. Pine should batch/cache expensive station work and reduce background analysis frequency. Preserve DJ audio processing and separate mixer levels.
7. Start with the existing **720p30 / 2.5 Mbit/s** shared encoder. If CPU/encode measurements still identify saturation after duplicate work is removed, test **960×540 at 30 fps, 1500–2000 kbit/s** as a fallback. Change the central `[broadcast]` configuration through the managed deployment path, not the viewer URL or a new per-client encoder. Do not assume NVENC is available or faster on this machine; test the installed encoder first. Record the quality/latency tradeoff and roll back if there is no improvement.

## Required diagnosis and acceptance report

Capture a common timestamp and selected channel/session for these layers:

| Layer | Evidence | Interpretation |
|---|---|---|
| Emulator/capture | `/api/sessions/<sid>/stream/health`, native game progress, frame sequence/age | If source frames stop, investigate emulator/capture, ownership or host load; player buffering cannot create missing gameplay. |
| Central broadcast | `/api/broadcast`, `/api/broadcast/feeds`, encoder frames/bytes, source identity and errors | Advancing source with stalled encoder output isolates the encode/relay layer. A slate/no-session state is not live video. |
| Pine/player | `GBoxTune.state()` gameplay state, decoder attachments, stalls, buffer ahead, media time, segment statuses/timings | Advancing encoder with a stopped playhead isolates gateway/network/player behavior. Healthy polls must not repeatedly attach decoders. |
| Host/network | CPU/GPU/RAM pressure, selected route, segment transfer latency and loss | Compare idle and competing-workload intervals. Distinguish direct LAN/tailnet routing from an indirect/relayed path. |

Verify sustained playback for **at least 15 minutes**, with actual LAN and Tailscale listener paths, real emulator audio, one normal MercMode title change and one controlled recovery. Report startup latency, longest stall, stall/attachment counts, source/encode/decode rate and whether displayed media moves backward. Test an AI-workload pause separately to establish whether contention explains the observed jitter. Do not claim seamless 24/7 performance from a unit test or an HTTP 200 response.

The gBox desktop PiP currently uses its session stream; changing Pine's player alone does not change that desktop transport. Keep desktop reconnect and session-lineage fixes in the acceptance checks as well.
