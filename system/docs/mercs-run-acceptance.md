# Mercenaries run acceptance contract (#2964, run-acceptance-v1)

`gbox/mercs/acceptance.py` is a pure, offline grader: `evaluate_run(samples, summaries, rules)` -> per-round criteria,
each `passed` / `failed` / `unknown` with evidence refs (`sample`, `line`). `recommend(state, rules)` is a pure priority
policy (QTE escape / healing > exposed nearby threat > time bonus > melee > weapon change > travel). Title rules are data
(`RE5_RULES`, `RE6_RULES`): RE5 melee kill = +5 s and no kill-counter rule; RE6's +10 s counter is only in `RE6_RULES`.

Evidence kinds are never mixed: RAM facts (score/kills/timer/hp), driver counters (`round_shots`/`round_hits` = shot
*events* and *associated* hits, not exact projectiles or hit identity), issued inputs (prompt/QTE presses) and missing
metrics (stay `unknown`; boss/headshot/combo/group/item evidence is never 0 or success). A clock rise seen in RAM beats a
driver "bonuses_taken" claim; inputs with no rise are a failed pickup. Modified runs (HP/immunity patch) are labelled and
survival is `unknown`, not ordinary-play performance. No live driver is touched; this proves nothing about gameplay gains.

## Fixture: `tests/fixtures/re5_run9_acceptance.json`
Derived from `/home/ehm_eckx/gBox_alt/scratch/re5-validation-20261021/run9/events.jsonl`
(sha256 `66b353ee6995973996a788162c467700b14373858b746caadf0e25d140f2318e`, 5324 lines); `line` = 1-based line there.

## Verified run9 facts (from the records, not from the handoff)
| | round 1 | round 2 |
|---|---|---|
| final RAM score / kills / timer | 10,860 / 23 / 0.0 (line 2294) | 10,860 / 23 / 0.0 (line 5315) |
| shot events / associated hits (round_return) | 275 / 42 | 317 / 31 |
| rank | C (needs 60,000 for S: shortfall 49,140) | same |
| clock rises observed | 0 | 0 |
| ending | timeout (clock 0) | timeout |

Notes: round 1's last tagged sample (line 2341) is the next round's reset (score 0, timer 120) and is excluded; round-1
hits read 41 in the last in-round sample and 42 only after that reset sample, so 42 is the driver's round_return value.
Score jumps not explained by +300/kill (round 1 +2,670 at t~29 s; round 2 +920 at t~59 s and +2,670 at the end) are
unattributed. Run is modified (HP 30,000, unlimited health, hit immunity). Kills 23/round and 0 time-bonus rises; the
bot reports `strategy_decision: clock expires before pickup`, 0 route arrivals, 2 routes given up in both rounds.

## Next measurable experiment
Same stage/character, ordinary HP: record `bonuses_taken` plus `timer` rises per pickup attempt and the cause of the
+2,670 jumps; target >= 1 verified RAM clock rise per round before judging S rank. The break-for-time clock rule in
`re5_ps3.py` (`BREAK_AT_S` unused) remains unimplemented and is outside this offline scope.
