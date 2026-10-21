# Codex follow-up to the 2026-10-21 resume point

Continue to use [the original handoff](resume-2026-10-21.md) for addresses, session ownership rules, and the seven
Hermes tickets. This follow-up records additional work; it does not mark those tickets complete.

## Prepared changes

- **DOA3 disk use, ticket #2967:** [draft PR #783](https://github.com/teamcsharp/gBox/pull/783), commit
  `86fa7ec416bb6ed6ce51f833be119c5f964dabaf`. Completed mod metadata identifies unchanged disc assets to hard-link.
  Modified assets and the restored XBE remain private; missing metadata or unavailable hard links fall back to copies.
  Native, writer and routing tests: 65 passed on Spark. Existing play views are not migrated or deleted by this patch.
- **RE5 combat, health and traversal, tickets #2964-2966:** changes and regression tests in this branch. See
  [the live audit](re5-round-metrics.md). Restart time was counted as bonus time, Continue presses as deaths, and
  damage observations contaminated landed-shot counts. The observed run did not establish hourglass collection,
  reliable 100% accuracy, or S rank. The operator subsequently observed a real time bonus; preserve that progress.
  Confirmed laser hits now fire immediately, verified rapid mode holds the trigger, and cover causes retargeting.
  A living-player health guard follows respawns, including a mid-round autoplay restart. It refills HP but is not
  a verified no-stagger or scripted-death immunity hook. Weapon policies and remaining gaps are documented in
  [the weapon research](re5-weapon-strategy.md). Navigation fixes handle ramps, directed drops, unavailable routes
  and crossing attempts interrupted by combat. These changes still require live acceptance after activation.
- **Hermes:** the seven prioritized handoffs were excluded by the automated-ticket filter. A narrow source fix
  admits dated, explicitly prioritized agent handoffs while retaining ownership and admission rules. Spark 2 was
  at 96% GPU use with queued work; increasing concurrency is not supported by that evidence. Its recurring
  600-second interruptions were correlated with the caller's context-compression ceiling, not a stale worker.
- Local development worktrees: `C:\_tools\gBox\.wt-resume-doa3-disc` and
  `C:\_tools\gBox\.wt-resume-re5-metrics`. Prepared task workspaces on Spark are
  `~/gBox_alt/gbox-hermes-tasks/fac48292f27a491a` and `~/gBox_alt/gbox-hermes-tasks/fbd3d36f4d28479d`.

## Live blockers and cleanup

The RE5 session from the original handoff remained active and agent-owned during the initial read-only audit.
The i9 became occupied by another agent's Call of Duty DS session; leave it alone.
Its admission guard was blocking background work because of CPU use and then recent operator input.

The following `file_mod op=delete_build` jobs were queued only on `i9-NUC`, with actor `agent`, for the obsolete
test mod caches explicitly named in the handoff. The existing tool checks running-session usage and path containment.
Check their status before retrying; queue submission is not proof of deletion.

| Mod cache | Job ID |
|---|---|
| `doa3_cast_test` | `0e94af6ba6464877` |
| `doa3_cast_t1` | `ba5313c0da63496b` |
| `doa3_cast_t2` | `4c8230f0094b42d0` |
| `doa3_cast_t3` | `e08539d0047a4737` |
| `doa3_cast_t4` | `97cd8aa1352d44ad` |
| `doa3_cast_t5` | `34a76f2932744156` |
| `doa3_cast_t6` | `3742b1eb21a14204` |

`doa3_cast_sonic_s4` was preserved. These jobs remove mod caches; they do not remove the separate old native-play
build directories listed in the original handoff. Those directories were not deleted: i9 SSH timed out and the
existing Windows share paths were unavailable. No disk reclamation is claimed until the jobs complete.

## Remaining threads

After review/deployment, verify corrected RE5 metrics, health readback, sustained kills, cover avoidance, a real pickup
and a complete round. Continue scoped/projectile weapon and true immunity-hook verification. Once the i9 is available,
finish its disk cleanup and verify DOA3 Survival plus the
Sonic cast. Keep screensaver workers limited to `JAYBUILTFINALE` until Survival plays.

The coaching review confirmed items 1–5 in `docs/coaching.md` remain incomplete. Its existing compact/coach tests
passed 23/23; no coaching implementation was changed here. Spark2 model trials still require the operator's Prepare
and Start trial action. No model service or capacity setting was changed.
