# RE5 cast-inverted hang: NOT an archive problem (2026-11-06)

## What we thought

The `cast-inverted` overlay (14 archives, ~391 MB) hung at load while `em10only1857` (1 archive, 96 MB) loaded fine.
The obvious hypothesis: one of the other 13 archives, or the total size/count, triggers the hang. A bisect was started
to find the minimal hanging set.

## What the bisect actually proved

**The premise does not hold.** There is no minimal hanging set because the hang is nondeterministic and emulator-side.

| build | archives | bytes | verdict | notes |
|---|---|---|---|---|
| 13 non-uEm10 | 13 | 295,422,724 | LOADS at 30 s | baseline the task said to report if it loaded |
| bs-all14 | 14 | 391,495,887 | LOADS at 30 s | fresh build, title screen confirmed (mean 23.8 / std 48.8) |
| cast-inverted (unchanged) | 14 | same | HANGS | 8/8 samples identical black (mean 0.0), 240 s |
| cast-inverted (unchanged, minutes later) | 14 | same | LOADS at 30 s | then 4 more launches: all LOADS at 10-20 s |

Byte-identical 14-archive content produced both HANGS and LOADS. Content is not sufficient to cause the hang.

## Emulator-side evidence (Eden's own log)

From `<runtime>/eden-linux/data/eden/log/eden_log.txt` (NOT the empty per-session log):

- **On a load:** PatchRomFS 2.53 s → ApplyLayeredFS applied successfully → ACC/AM/SET/HID 2.6 s → SDL audio streams
  3.0 s → NVDEC/VIC 11.7-12.1 s → title screen ~20-30 s.
- **On a hang:** log stops mid-line at 2.647 s, right after `nvhost_gpu ChannelSetTimeout/SetErrorNotifier` and before
  the first draw; nothing more for 240 s. Emulator process alive, ~113% CPU, 7.3 GB RSS → spinning, not a lock deadlock
  and not a crash (no coredump, no dmesg segfault). ApplyLayeredFS had already reported success in the hanging boot too,
  so LayeredFS applied the 14 files correctly.
- RomFS patch cost is size-independent (15 ms for 391 MB), so a total-size threshold has no mechanism.

## Likely cause

The Spark is shared with ComfyUI, ollama, and ffmpeg on the same NVIDIA GPU. The stall happens mid-GPU init
(`nvhost_gpu ChannelSetTimeout`) and is consistent with GPU/display state contention on a shared node. The pre-restart
runs had hangs; the 6 post-restart launches all loaded — possibly coincidence, possibly the restart cleared GPU state.

## What this means for cast_swap

1. **Do not gate cast_swap on archive count or total bytes.** There is no content threshold.
2. **Do not bisect on a single HANGS verdict.** The verdict is nondeterministic at roughly 1-in-3. Any bisect needs
   multiple launches per build and a statistical threshold, not a binary pass/fail.
3. **The generator is probably fine.** The overlay builds correctly; the hang is an emulator/GPU scheduling issue on
   a shared node. If it recurs, investigate Eden's GPU init path or isolate the Spark's GPU from other workloads.
4. **The handoff's "bisect the rest" recommendation is superseded.** The 97 MB uEm10 overlay loads on its own AND as
   part of the full 14-archive set. The combination is not the problem.

## Status

Subagent still attempting to catch a stall with gdb attached for the exact blocked stack. Final doc with full numbers
pending. This note records the key finding so the next round does not re-bisect a phantom.
