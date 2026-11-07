# RE5 (Switch) cast-inverted: why the 14-archive overlay "hangs in the loader"

Research note, 2026-11-06. Game `52d15709be0fda1a` (Resident Evil 5, title id `010018100CD46000`), node `lilspark`,
emulator Eden (the `eden-linux` AppImage gBox extracted; the same LayeredFS code as Citron). Operator premise: the
14-archive overlay `cast-inverted` hangs in the loader forever, while the one-file build `em10only1857` (uEm10.arc,
96,073,163 bytes) reaches the title screen — so the hang must come from the combination of archives, a pair, or a
total-size / file-count threshold.

**Result: the premise does not hold.** The archive set is not the trigger, and there is no minimal hanging set to
find. Byte-identical overlay content produced both verdicts on the same night, and the *one-archive* build
(`em10only1857`, 96 MB) stalls in exactly the same place as the 14-archive build. The hang is an intermittent,
content-independent boot stall in the emulator, at ~2.65 s, at the second NVDRV GPU channel — before the first frame.

## Method

Harness: `~/gBox_alt/re4-lab/cast_bisect2.py` (the working `cast_bisect.py` plus evidence capture; the verdict rule is
unchanged: 960×540 grey JPEG of `/api/sessions/<id>/frame.jpg`, TITLE SCREEN when mean 20–28 and std 45–52), and
`cast_trial.py` (same rule, 10 s sampling, plus process/log telemetry and a gdb dump on a stall). Both stop only
sessions of game id `52d15709be0fda1a`, configure MercMode `enabled=false` on `lilspark`, write through
`switch_mods op=write`, and launch with `mod=<build>`.

`MODE=existing` launches a build as it stands (no write), which is how `cast-inverted` and `em10only1857` were tested
unchanged.

The emulator's own log is `<runtime>/eden-linux/data/eden/log/eden_log.txt` (Info level; the per-session
`logs/eden-<pid>.log` files are always empty). It records `PatchRomFS` and `ApplyLayeredFS`, so every run also proves
whether the overlay was applied.

## Every build tested

Verdict "LOADS" = title fingerprint reached. "STALLED" = still black at ≥80 s with the emulator process alive.
Same content, same night, different outcomes are what this table is about.

| # | build (name launched) | archives | bytes | verdict | s to title | when / note |
|---|---|---|---|---|---|---|
| 1 | `bs-base13` (written) | 13, all except uEm10 | 295,422,724 | LOADS | 30 | baseline the task asked for |
| 2 | `bs-all14` (written) | all 14 | 391,495,887 | LOADS | 30 | title screen checked visually |
| 3 | `cast-inverted` (existing) | all 14 | 391,495,887 | **STALLED** | — | 8/8 samples identical black, 240 s |
| 4 | `cast-inverted` (existing) | all 14 | 391,495,887 | LOADS | 30 | same bytes as #3, 6 min later |
| 5 | `cast-inverted` (existing) | all 14 | 391,495,887 | LOADS | 20 | trial, 10 s sampling |
| 6 | `cast-inverted` (existing) | all 14 | 391,495,887 | LOADS | 10 | loop trial 1 |
| 7 | `cast-inverted` (existing) | all 14 | 391,495,887 | **STALLED** | — | black at +10…+40 s, then the control plane was restarted under it |
| 8 | `cast-inverted` (existing) | all 14 | 391,495,887 | LOADS | 20 | loop trial 3 |
| 9 | `cast-inverted` (existing) | all 14 | 391,495,887 | LOADS | 10 | loop trial 4 |
| 10 | `cast-inverted` (existing) | all 14 | 391,495,887 | LOADS | 10 | loop trial 5 |
| 11 | `cast-inverted` (existing) | all 14 | 391,495,887 | LOADS | 10 | loop trial 6 |
| 12 | `em10only1857` (existing) | 1 (uEm10) | 96,073,163 | **STALLED** | — | the build the premise calls "loads fine"; gdb bt captured |
| 13 | `em10only1857` (existing) | 1 (uEm10) | 96,073,163 | LOADS | 20 | same bytes as #12, minutes later |

Totals: `cast-inverted` 7 LOADS / 2 STALLS in this session (the earlier session at 19:08 also ran the full 305 s
watch, which is consistent with a third stall, but its frames were not kept so it is not counted);
`em10only1857` 1 LOAD / 1 STALL. Overlay size ranges from 96 MB to 391 MB and every size both loads and stalls.

Builds that were written are new names only (`bs-base13`, `bs-all14`); `cast-inverted` and `em10only1857` were never
rewritten, only launched.

## What a stall looks like

Same signature in #3, #7 and #12, regardless of how many archives are in the overlay:

- Frames freeze black: 3263-byte uniform JPEG, mean 0.0 / std 0.0 for `cast-inverted`; mean 2.5 / std 5.4 for
  `em10only1857` (a dark screen, not a black one). All samples byte-identical.
- The emulator is **alive and busy**: RSS ~7.2–7.3 GB, ~113–140 % CPU, 65–66 threads, no coredump, no segfault in
  `dmesg`. It is not a crash and not an idle deadlock.
- Eden's log stops mid-line at ~2.65 s and never advances again (7995–7996 lines, last stamped line `[   `). The last
  complete lines are the **second** NVDRV GPU channel:

  ```
  [   2.650127] Service.NVDRV <Info> core/hle/service/nvdrv/devices/nvhost_gpu.cpp:430:ChannelSetTimeout: called, timeout=0X266
  [   2.650304] Service.NVDRV <Warning> core/hle/service/nvdrv/devices/nvhost_gpu.cpp:164:SetErrorNotifier: (STUBBED) called, offset=0, size=1000, mem=14
  ```
- A boot that loads passes the same point and then continues: `mem=20` channel at 2.60 s, `mem=14` at 2.65 s, ACC/AM/SET
  calls at 2.60–2.65 s, `SDLSinkStream: Opening SDL stream 2/3` at 3.0 s, NVDEC/VIC at 11.7–12.1 s, title at 10–30 s.
  A stalled boot never reaches the audio streams or NVDEC.
- The overlay is applied either way: both stalled boots log
  `ApplyLayeredFS: RomFS: LayeredFS patches applied successfully` at ~2.5 s. The mod is not rejected, and RomFS
  patching is cheap and size-independent — `PatchRomFS` → `ApplyLayeredFS` took **10–15 ms for the 391 MB overlay**,
  because LayeredFS is a VFS layer, not a copy. There is therefore no total-byte threshold mechanism to find, and the
  measurements agree: 295 MB loads, 391 MB loads, 96 MB stalls too.
- The gdb backtrace at the stall (`re4-lab/bt_em10only1857_1794016387.txt`) is **inconclusive**: the binary is stripped
  and every frame prints `?? ()`, with almost all 65 threads reported at one common address (a futex/syscall park).
  It does establish that the Vulkan worker/present/pipeline threads and both `SDLAudioP2/P3` streams existed, so the
  stall is not "audio never opened" and not "renderer never created". Naming the blocked call needs an unstripped
  build or a `perf`/`eu-stack` capture with symbols.

## What the data rules out

- **A specific accomplice archive, a pair, or the 13 non-uEm10 set.** The 13-archive baseline loads; the 1-archive
  build stalls; the same 14-archive build does both. Nothing about the set predicts the verdict.
- **A total-size threshold.** 96 MB stalls; 295 MB and 391 MB load. RomFS layering costs 10–15 ms at 391 MB.
- **A file-count threshold.** 1 file stalls; 14 files load.
- **A bad archive in `cast-inverted`.** Its 14 files are byte-identical to `bs-all14`, which loaded; the same folder
  loaded in 7 of its 9 launches. No pending edits, no backups, no truncated files (sizes match the source exactly).

## What it costs to be wrong about this

The original conclusion was reached from single HANGS verdicts. At the observed rate (~2 stalls in 9 launches of
`cast-inverted`, 1 in 2 of the 96 MB build) a one-shot verdict is close to a coin flip, so a bisect over archives
"finds" whichever subset happened to be tested during a stall. That is how the 14-archive set came to be blamed.

Environment note, because it invalidated one trial and can invalidate others: `gbox.service` was restarted at
19:41:11 (stop-sigterm timed out, systemd SIGKILLed the cgroup, including the emulator and the encoder). Trial #7 was
cut short by that. The encoder also cycled (`returncode=251`) whenever the screen was frozen, which is a useful
secondary signal but not a cause. The node shares one NVIDIA GPU with ComfyUI, ollama and ffmpeg; the stalls are
consistent with a GPU-side boot race, but nothing in this data proves it.

## What the cast-swap generator should change

`gbox/skin_swap.py: cast_swap_build` is what wrote this overlay (the `characters op=cast_swap` path for a Switch
title routes through `switch_mods.character_use`, which has no RE5/RE6 model writer yet). It is not at fault: its 14
archives layer correctly and play on most launches, and its own comment — "a PLAYER taking an enemy model builds and
never produces a session" — deserves a re-test, because a build that "never produces a session" is exactly what a
single unlucky launch looks like here.

Recommended changes, in order:

1. **Do not add archive-count or total-byte gates to `cast_swap_build`.** Both are disproven above; a gate would only
   shrink the cast for no reason. Keep emitting all 14 archives.
2. **Make the verifier require repetition.** A `HANGS` verdict must be reproduced N times (3 is enough at the observed
   rate: p ≈ 0.03 for three false stalls) before it is attributed to a build, and each retry must be a fresh launch,
   not a longer watch. The current "8 samples × 30 s once" rule cannot distinguish a stall from a bad build.
3. **Add a boot watchdog with one automatic relaunch.** If no frame is presented by ~90 s (or Eden's log has not
   passed `Nvdec: Created nvdec`), stop the title and relaunch the same build. Every stalled launch in this session
   was followed by a launch of the same bytes that reached the title in 10–30 s, so a single retry is a real fix for
   the operator-visible symptom, independent of the root cause.
4. **Record the stall signature per run** (`eden_log.txt` copied beside the session, plus "last stamped line" and
   "was `Nvdec` created") so a future bisect can tell a stall from a slow load without a human watching frames.
5. **Keep the overlay as an overlay.** Nothing here argues for baking archives in or for shrinking the cast; the
   failure mode is emulator boot, not data.

## Reproducing

```bash
# on the Spark
cd ~/gBox_alt/re4-lab
MODE=existing SAMPLES=8 python3 -u cast_bisect2.py cast-inverted      # launch a build unchanged, 4 min watch
MODE=existing python3 -u cast_trial.py em10only1857 110              # 10 s sampling + gdb dump on a stall
python3 -u cast_trial.py bs-all14 110                                # build-free launch of a written build
```

Artifacts on the Spark: `re4-lab/results.jsonl` (cast_bisect2 runs), `re4-lab/trials.jsonl` (cast_trial runs incl.
per-sample means, log sizes and pids), `re4-lab/bt_*.txt` (gdb), `re4-lab/edenlog_*.txt` (Eden log per run),
`re4-lab/bisect_*.jpg` / `trial_*.jpg` (the frames the verdicts were made from).
