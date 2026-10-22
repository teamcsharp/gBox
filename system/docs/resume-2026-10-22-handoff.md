# Resume point: 2026-10-22 handoff (operator at 96% usage; request #2962)

Written by a Hermes cron run (claude-sonnet-5-5) from read-only observation at ~16:20 UTC. It supplements
`resume-2026-10-21.md` and `resume-2026-10-21-codex.md` (read those for RE5 Mercenaries/DOA3 runtime detail).
Nothing here was verified at gameplay level. No game, save, or worker was touched by this run.

## State of Hermes (piledriving)

- Cron job `d24e4c0f82a5` "gBox inbox task mode": every 1m, no-agent, runs `gbox-work-queue.py`, last run ok.
  Queue file: `~/gBox/system/gbox-data/hermes-dispatch/work-queue.json` (1701 items). Task workspaces:
  `~/gBox_alt/gbox-hermes-tasks/<request_id>/system`.
- Current route: `gbox-sparkDeux` / `nvidia/Qwen3.8-27B-NVFP4`; `gbox-minimax/minimax-m3.1-flash:cloud` on quota
  cooldown (until epoch ~1792772311); `custom/claude-sonnet-5-5` is the working local-claude lane.
  Check `get_dispatch_feedback` before changing routes; do not retry an exhausted route.
- Queue priority is already set so operator-prioritised requests share their game, up to 3 runs (PR #850, merged).
- Hermes keeps working with no operator present; the operator's usage limit does not stop it. A resuming agent
  should NOT restart the gateway or cron ticker unless the heartbeat (`~/.hermes/cron/ticker_last_success`) is stale.

## Merged to master today (15:22-15:56 UTC)

#822/#823 autoplay relaunch keeps pad, #827 mercs_bot first-boot grace, #841 RPCS3 Windows boot, #850 queue priority.
Base for this branch: `da380f76`.

## NOT merged: 55 open draft PRs (all drafts except #815)

Almost all are Hermes-produced, tests passing per their own reports; none had independent review. I did not
mass-merge: merging 55 unreviewed PRs into master unattended risks conflicts and regressions on the operator's
play machine deploys. Recommended order for the resuming agent (review each diff, run its focused tests, then
`gh pr ready` + merge):

1. Bot/RE5 (operator's top priority, requests #3018-#3020, #2989-#2995): #872, #869, #870, #858, #854.
2. Fixes/infra: #864 (stale pad-map test), #849, #837, #829, #828, #817, #815 (non-draft: blank desktop view),
   #762.
3. Inventory/analysis (low risk, additive): #871, #868, #867, #865, #861, #860, #859, #857, #856, #853, #852,
   #848, #846, #844, #843, #842, #840, #836, #835, #834, #833, #832, #830, #826, #825, #824, #726, #691.
4. Writers (higher risk, need donor/round-trip evidence): #863, #862, #851 (**CONFLICTING**, rebase first),
   #845, #839, #838, #831, #761.
5. "Recover unmerged Hermes work" PRs (#866, #855, #819, #818, #733): diff against master first; may be stale.

## Open operator requests to resume (from list_requests)

- #3020 RE4 autoplay/learning on i9-NUC; #3019/#3018 RE5 Mercenaries bot (time bonuses, navigate when no enemies,
  no infinite life for the bot, S rank); #3012-#2998 and #3000-#3004 coaching notes (walls, doors/windows, line of
  sight, unlock all Mercs characters); #3013 Hermes maxing spark2 + minimax + claude; #3014-#3016 an unwanted
  automatic Mario boot (find what auto-launches games; operator did not request it).
- #2989-#2995 RE5 Reunion per-stage S-rank/zero-hit acceptance: needs RAM-measured rounds on i9-NUC; none met.
- ~25 "ready_to_verify" requests (Unlock on load / Character replacement readiness / DOA3 #2967): have SHAs but
  need acceptance verification before `set_request_status done`.
- Rule: agent test sessions only on i9-NUC or Spark, idle, 2% audio, never JAYBUILTFINALE (operator's PC).

## Known blockers

- RE5 live code activation needs an owned maintenance drain + gbox.service restart (see 2026-10-21 doc);
  the deployed fixes are not live until then. Never clear another owner's drain marker.
- Computer Use kernel.js missing: no desktop UI acceptance.
- Quota: minimax cooldown; recurring `quota` lessons in dispatch feedback.

## Next acceptance step for this request (#2962)

Review and merge the PRs above in the listed order (needs a reviewer with merge authority), then re-run
`gh pr list --state open` and update this doc. This request remains in_progress: the "everything merged in master"
part is not done.
