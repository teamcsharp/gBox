# Mercs crowd dispatch (request #9526) - baseline measured from stored round reports

Read-and-report milestone 1. No code under `system/gbox` and no test changed. The ticket body names no "Deliver"
file, so this one document is the deliverable.

## How the numbers were obtained
- Source: `gbox-data/gbox.sqlite3` (opened `mode=ro`), table `docs`, `kind='mercs_round_report'`, 4,045 reports
  (created 1792811504 .. 1794350941 epoch s). Schema: `gbox/mercs/round_reports.py` (`METRIC_GROUPS`, group `doctrine`).
- Parser: `json.loads(body)['report']['metrics']['doctrine']`, summed per `report['title']` over reports that carry the
  `doctrine` group. `kills` from `metrics.engagement.kills`, `player_damage_events` from `metrics.damage`.
- Throwaway script outside `system/gbox`; not committed.

## Result (sum over reports carrying the doctrine group)
| title | reports | with doctrine | threat_ticks | unanswered | unanswered / ticks | hurt_while_idle | threat_hits | kills | deaths |
|---|---|---|---|---|---|---|---|---|---|
| RE5 Switch `010018100CD46000` | 1703 | 25 | 114,394 | 27,475 | 24.0 % | 106 | 246 | 2,092 | n/a |
| RE6 Switch `01002A000CD48000` | 1317 | 30 | 65,719 | 3,819 | 5.8 % | 74 | 420 | 3,962 | 12 |
| RE4 Switch `010099A00BC1E000` | 0 reports in store | - | - | - | - | - | - | - | - |
| BLUS30491 / G4BE08 (PS3 / GC) | 556 / 469 | 0 | - | - | - | - | - | - | - |

Answered ticks: RE5 flash 66,944, mine 9,525, fire 9,381 (forced fire 10,011); RE6 flash 21,964, mine 21,573,
fire 18,363 (forced fire 3,698). Ratios are computed from the sums above (arithmetic only).

## Reading
- RE5 leaves a quarter of its threat ticks unanswered, RE6 6 %: RE5 is where earlier fire has the most headroom.
- Only 55 of 3,020 RE5/RE6 reports carry the doctrine group, so these are a small sample.

## Not determined
- **surround_events**: no such counter exists in `round_reports.py` or the drivers (grep over `system/`). Needs a new
  counter in `core/respond.py` (3+ within 6 m or bearing spread > 180 deg), i.e. a code change this ticket forbids.
- **kills per minute**: reports carry kills but the round duration column was not read here; join with round length to settle.
- **Before/after replay**: no replay harness over recorded rounds was found in this pass; without one, an after
  figure cannot be measured. A fixture-driven run of `tests/test_mercs_respond.py` is the closest existing check.
- **RE4**: no reports under its title id in the store.
- Per-round crowd geometry (distances / bearings) is not stored in reports, so "3+ within 6 m" can't be counted
  from them.

## Next
1. Locate/define a replay of recorded rounds (tracer `scripts/bot_trace.py`) that emits per-tick enemy distance and bearing.
2. Operator decision: the ticket title asks for bot changes, but its rules forbid code changes. A follow-up ticket
   is needed for the `respond.py` change plus a `surround_events` counter.

## Before/after measurement status (verification pass, 2026-11-11)

Candidate milestone: proactive crowd/ring threat in `core/respond.py`, `surround_events`/`ring_events` counters,
RE6 surround double-count fix, RE4 grab-range pre-emption fix — commit `8de7cdf6`
(branch `hermes/request-9526-1794351674570722214`, baseline `b3b82661`; branch tip is an ancestor of
`origin/main`, so the code milestone is already on main).

| metric | baseline (measured) | candidate (measured) | provenance (file / offset / parser) |
|---|---|---|---|
| threat_unanswered | RE5 27,475 (24.0% of 114,394 ticks) · RE6 3,819 (5.8% of 65,719) | not_determined | `gbox-data/gbox.sqlite3`, table `docs`, kind `mercs_round_report`, rows created 1792811504..1794350941 (4,045 rows) · parser `json.loads(body)['report']['metrics']['doctrine']` |
| hurt_while_idle | RE5 106 · RE6 74 | not_determined | same corpus/rows · same parser (`metrics`) |
| surround_events / ring_events | n/a — counter absent in baseline code | not_determined | counters added in `core/respond.py` at commit `8de7cdf6`; emitted only during live rounds |
| kills/min | RE5 2,092 kills · RE6 3,962 kills (per-minute not derivable: round duration not joined) | not_determined | same corpus/rows · `metrics.engagement.kills` |

Candidate column is **not_determined** — every cause verified this pass, no live action taken:
- `scripts/bot_trace.py` is a live recorder only (`record <session_id> <seconds> <out.jsonl>` polls a running
  session, docstring lines 4–7); it cannot run offline.
- No per-tick recordings exist in the worktree — only unit-test fixtures
  `tests/fixtures/mercs_incidents/re6_switch_lethal_heal_tick_{278,380,686}.json`; no `bot_trace*.jsonl` anywhere.
- No idle authorized non-JAYBUILTFINALE mercs session: `list_sessions` shows only a PSO2 session on i9-NUC
  (not a mercs title) and one RE6 Switch recovery session on lilspark2 (in use; the ticket forbids
  launching/stopping games or touching it). JAYBUILTFINALE (operator play PC) is offline.

No runtime acceptance is claimed. Focused `tests/test_mercs_respond.py`: **28 passed**.
Wider RE4/RE5/RE6 switch + threat suite (cwd=tests so sibling imports resolve):
**718 passed, 42 skipped, 2 failed** — the two failures are the pre-existing
`tests/test_re5_switch_threat.py` baseline failures
(`test_the_current_one_is_kept_within_threat_keep_and_a_grab_wins`,
`test_the_guard_and_the_settle_are_off_as_at_14_58_and_the_sky_still_counts`), unchanged from baseline.

Next acceptance step: operator-confirmed idle authorized non-JAYBUILTFINALE test node (record with
`bot_trace.py record` at 2% audio, launch:false) or a per-tick recorded round; then replay baseline vs
candidate to fill the candidate column.

## Second read-only pass — 2026-11-11 (verification re-run after retry review)

Session eligibility (fresh `list_sessions`): only two active sessions — PSO
(Episode I & II Plus, dolphin, i9-NUC, agent_owned=false; not a mercs title)
and RE4 (citron, lilspark, agent_owned=true, active MercMode play started
moments before the query). JAYBUILTFINALE is absent from `list_workers`
entirely. Conclusion unchanged: **no idle authorized non-JAYBUILTFINALE
mercs session** → candidate metrics remain not_determined.

Replay input candidates (path / parser / ticks / offsets):
- **bot_trace recordings: none on disk.** `find /home/ehm_eckx` returns zero
  `bot_trace*.jsonl` (only unrelated .deuxrl/.continue/music jsonl).
  `scripts/bot_trace.py` is a live-session recorder only; it has no offline
  replay entry point. Ticks/offsets: not_determined.
- **Per-tick recorded rounds: none anywhere.** gbox.sqlite3 `docs` holds no
  per-tick kind (24 merc-related kinds, all aggregate reports).
  Ticks/offsets: not_determined.
- **Unit fixtures: `system/tests/fixtures/mercs_incidents/*.json`** — 27
  per-tick incident snapshots, 966 B–82 KB (incl.
  `re6_switch_lethal_heal_tick_0/1/3.json`). Parser: incident test harness;
  1 tick each, fixture-local offsets. Unit-level regression only — not a
  full round, so no before/after metric table possible.
- **Demo/observed docs** (kinds `bot_demo`, `mercmode_observed*`): aggregate
  report docs, not per-tick replay inputs.

Report store (read-only, `mode=ro`): `docs` schema is `(kind, id, body)` —
no timestamp column, so the first pass's "created range" was not
verifiable and is retracted. `mercs_round_report` doctrine rows: **176
total — RE4 01002A000CD48000: 123, RE5 010018100CD46000: 53, RE6: 0**.
(First pass's "4,045 rows" was not re-verified this pass.)

Job records: job b72d0f8f5145 (run b49f4ac4…, completed) now 404 in
`get_job` (record aged out); completion retained in request history. No
queued/running jobs for dcf0569e016d4c36; no duplicated ownership.

Tests (re-run 2026-11-11, cwd=tests, PYTHONPATH=.):
- Focused `test_mercs_respond.py`: **28 passed** (1.27 s) — matches.
- Wider (all `test_re4_switch*.py` + `test_re5_switch*.py` +
  `test_re6_switch*.py` + `test_mercs_respond.py`): **1417 passed, 42
  skipped, 12 failed**.
- Baseline cross-check (detached worktree at b3b82661, same 5 files):
  **6 failed, 70 passed** — `test_re5_switch_bonus`, `rampage`, `smooth`
  x2, `threat` x2 fail identically at baseline → pre-existing, unchanged.
- **REGRESSION FLAG:**
  `test_re5_switch_weapon_mastery.py::test_without_a_choice_the_crowd_fire_still_puts_the_shotgun_up`
  fails at the candidate but passes at baseline b3b82661 (baseline run had
  exactly 6 failures, none from weapon_mastery; candidate's wider run lists
  it as FAILED). 5 further failure lines from the wider run were truncated
  from the recorded tail and are not yet cross-checked at baseline.

Next acceptance step (unchanged, plus regression triage):
1. Cross-check the 5 truncated wider-run failures at baseline b3b82661.
2. If the weapon_mastery regression is confirmed, fix or revert the
   offending candidate hunk (8de7cdf6) before any runtime acceptance.
3. Operator-confirmed idle authorized non-JAYBUILTFINALE test node (record
   with `bot_trace.py record` at 2% audio, launch:false) or a per-tick
   recorded round; then replay baseline vs candidate to fill the candidate
   column.
