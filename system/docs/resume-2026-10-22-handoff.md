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

## Status update — 2026-10-24 20:0x UTC (Hermes cron, local run on sparkDeux)

The Hermes queue piled the merge wave through overnight. Verified live against GitHub this run
(`gh pr view <n> --json state,mergedAt` per PR):

- **Merged to main:** #872, #869, #870, #858, #854, #864, #849, #837, #829, #828, #815, #762, #871, #868, #867,
  #865, #861, #860, #859, #857, #856, #853, #852, #848, #846, #844, #843, #842, #840, #836, #835, #834, #833,
  #832, #830, #825, #824, #726, #863, #862, #845, #839, #838, #831, #761, #866, #855, #733 — 47 of the 55.
  Batch #1113/#1121 at 2026-10-24 18:58:25Z, plus #828 (10-23 09:06Z), #762/#726/#761/#733 (10-24 19:58:30Z),
  and the 10-22 merges (#815 16:41Z, #869 16:44Z, #872 17:09Z, #854 17:00Z, #870 17:15Z, #849 17:13Z,
  #858 17:22Z). #874 (this doc) merged as main commit `c8fcd312e3bc` at 18:58:25Z.
- **Closed unmerged (2026-10-24 ~19:19Z, presumably superseded by the recovery-PR merges #866/#855/#733):**
  #826 (MVC2 PNG-first sprite export), #851 (MVC2 DC lossless round trip), #819 (recovery of #1641).
- **Still open (2):**
  - #691 — RE3 GC unlock static analysis (request #2038); DRAFT, mergeable CLEAN.
  - #818 — DOA3 unlock-on-load research profile (request #2087); DRAFT, **CONFLICTING** — needs a rebase.
- The original "everything merged in master" criterion is now met for all 53 PRs that landed on main; only
  #691 and #818 remain open, and #818's conflict should be resolved by the owner of that investigation
  (DOA3/RE3 research lanes, not this request's scope).
- `ready_to_verify` from `list_requests` at this run: #3349, #3348, #3345, #3281, #3052, #3037, #3035, #3030,
  #3019, #3012, #3011, #3009, #3008, #3007, #3003, #3002, #2999, #2984, #2975, #2967, #2966, #2962 (this),
  #2961, #2950, #2925. Live acceptance on idle workers (i9-NUC/Spark, 2% audio) is still the gating step
  for those before `set_request_status done`.
- Next step for a resuming agent: rebase/finish #818 if that lane resumes; otherwise close #691/#818 as
  superseded by the merged recovery PRs; then run live acceptance for the `ready_to_verify` list on an idle
  worker and flip each to done with evidence.
