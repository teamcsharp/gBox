# Request #4793 (9da51c80f3714e03) — "Why did RE6 (PS3) load on the operator's PC?"

Investigation by hermes (local run, lilspark2 / Qwen3.8), 2026-11-06.

## Operator question (chat, 2026-10-27 21:52 UTC)
"Also why did RE6 for PS3 load on the computer I'm on? It's frozen on the
title screen and not doing anything."

Chat context: Hermes session on a Windows machine
(cwd C:\_tools\gBox\.claude\worktrees\hermes-reviewer\system, pid 77324, user ehm_eckx).
Operator's gBox worker (config env GBOX_OPERATOR_WORKER): **JAYBUILTFINALE** (play PC).

## Verified findings (evidence from live gBox session history)

1. **gBox's RE6 is the Xbox 360 build, not a PS3 game.**
   - game_id 115f9cdbba115432, title_id `01002A000CD48000` (Xbox 360 ID format).
   - Runs through the **Eden** emulator adapter (Linux), per session details.

2. **Only RE6 sessions in recent gBox history ran on lilspark (the Spark), never on JAYBUILTFINALE.**
   - Session `24d0ac272adc4744-b368daf903dc4f83`: started 2026-11-06 17:22:07 UTC,
     ended, worker_name=lilspark, staged_on=lilspark, display :98, pid 3675963.
   - Session `24d0ac272adc4744-00b1e90e08e54872`: started 2026-11-06 17:30:39 UTC,
     ended, worker_name=lilspark, staged_on=lilspark, display :98, pid 3744897.
   - Both: boot_attempts=1, boot_failures=[], boot_watch {after_s:12.6, frames:3, watched:true},
     ready=guest_memory, validation="guest memory mapped and the boot drew changing frames;
     gameplay not yet verified".
   - These are agent-launched job_re6 runs on the Spark (today), unrelated to the operator's PC.

3. **No RE6 / RPCS3 / PS3 session appears among the ~38 most recent gBox sessions
   (newest-first list from list_sessions include_ended).**
   Current live session at time of writing: RE4 (dolphin, "Resident Evil 4 (USA, disc 1)"),
   lfa 0.0 — no RE6 running anywhere.

4. Conclusion within the inspectable window: **gBox did not launch RE6 on the
   operator's PC.** gBox has no PS3 RE6 at all. A RE6 window frozen on the title
   screen on JAYBUILTFINALE (if seen there on 2026-10-27) was not a gBox session —
   most likely a locally installed non-gBox emulator/instance (or a misidentified
   platform: gBox's RE6 is the Xbox 360 build). A title-screen freeze in such a
   local instance is a local problem, not a gBox regression or session leak.

## Evidence gaps / dependency
- Session archive predating the ~38-session inspectable window (i.e. 2026-10-27) was
  not reachable: the MCP list_sessions dump is truncated at 200KB, and direct HTTP
  to 127.0.0.1:8765 (/api/sessions) returns `{"detail":"bad token"}` — a gBox API
  token is required, which this run does not hold.
- Exact next step: re-run with a valid gBox API token (or a session-archive export)
  to list JAYBUILTFINALE sessions around 2026-10-27 and confirm no RE6 launch there;
  alternatively the operator confirms the window title/app name of the frozen RE6
  instance (gBox sessions show the game title + emulator name in the window).

## State
- No pending jobs from this run; no jobs started. Both RE6 sessions above are ended.
- No source changes for this request (diagnostic). Operator PC and games untouched.
- Request left **in_progress** until the Oct-27 archive check is completed.
