# Checkpoint — request #1813 (90f88fd2f2494e21)

Local run on lilspark2 (2026-03-04, ~13:47 UTC). Status: **in_progress** — live driver-select
acceptance still pending. No source changes in this run (the passing fix is already published),
so this checkpoint file is the only change published now.

## Live checks performed this run (list_workers / list_sessions)
- **i9-NUC** (id 3588af119bac42ef, windows): ONLINE, idle_seconds≈9958, active_jobs=0,
  running_jobs=0 → an eligible, idle agent test PC is now available (it was OFFLINE in the
  2026-03-04T02:56Z checkpoint — state changed).
- **JAYBUILTFINALE**: offline (operator play PC — must never be used for agent tests regardless).
- **lilspark**: BUSY — running RE5 session 62189d68a8004464-4df41a6a2d5a4553
  (mod harness-uEm11-hash-em10, agent_owned=false, last_frame_age 0.0). Not usable for this
  request; do not disturb it.

## Verified in earlier runs (unchanged; not re-tested here)
- v2 cast_swap writer fix merged: worktree commit `eac0262`, draft PR #230
  (github.com/marcelo-eh/gbox/pull/230), head 90f88fd2f2494e21, lane inbox.
- RE5 build rebuilt with v2 writer: rebuild job `8307e2965bc84c82` success; build receipt
  `a7e40ca449b6409f`; artifact deployed at all 4 slots
  (010018100CD46000/exefs/main.npdm, load overlay, eden, 3467037).
- Offline tests passing: system/ tests + focused tests/test_mc_re5_writer.py (prior runs).
- Pre-fix failure mode documented: boot hang with `GFX FIFO: invalid write at 0x18`.

## Pending job IDs carried from prior runs
- NONE pending. Rebuild job 8307e2965bc84c82 completed successfully; earlier checkpoint job
  033489524c80403f completed. No live-acceptance job was started this run (no catalog entry /
  session on i9-NUC yet; see next step) — no duplicate jobs exist.

## Next acceptance step (the single remaining gap)
1. Discover the Crazy Taxi (USA) GC catalog entry (game_id, profile_id) and an i9-NUC session
   via list_sessions/worker 3588af119bac42ef.
2. Stage build `a7e40ca449b6409f` onto i9-NUC (build_local download) and launch with mod
   `cast_crazy_taxi_usa_sonic_adventure_us_82d27070`
   (parent_request_id=90f88fd2f2494e21, agent-owned session, 2% audio, i9-NUC only).
3. Verify the driver select screen renders without the GFX FIFO 0x18 hang
   (get_frame / capture_request_screenshot), select all four SA drivers, and attach screenshot
   evidence to the request.
4. Then set_request_status done with solver credit + verification evidence; otherwise stay
   in_progress.

## Constraints honored
JAYBUILTFINALE untouched; no session started on the busy lilspark; no duplicate jobs;
operator gameplay/saves protected.
