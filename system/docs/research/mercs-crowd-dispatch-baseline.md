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
