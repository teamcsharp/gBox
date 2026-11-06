
## Inbox tickets: two defects fixed (and one left named)

The newest inbox entries were **my own failed builds** filed as auto reports, and they were unhelpful in two ways.

**1. The game was lost.** The ticket said

```
Game: unknown game (game_id: ?)
Failed job: 402dfaea2c1e4eb8        <- whose input.game_id IS 78ab9efa2e310db4
```

`server.req_auto_mod_failure` read the game from the *session*, and a build has no session. It now falls back to the failed
job's own `input.game_id` (and the catalog, when the store has the entry). Verified by re-filing against that job: the ticket
now reads `Game: 78ab9efa2e310db4 (game_id: 78ab9efa2e310db4)` instead of `unknown`.

**2. The de-duplicating path never corrected an existing ticket.** The same POST returned the *old* report unchanged, because
the `existing` branch only merged character/target fields. It now fills `game_id`/`game` when missing, rewrites the body's
`Game:` line and the title's " in unknown game" suffix. Verified live: the title went from "failed in unknown game" to
"failed in 78ab9efa2e310db4".

**3. "Not in the collection" for a library that is still loading.** My build failed right after a restart and was reported as
`'sonic' isn't in the collection yet: run characters op=extract first (have: )` - an empty "have" list, which sends the operator
off to extract a character that is already there. `characters.use` now distinguishes the two cases:

```
library_entries: 0    -> "the character library returned no entries - the index is probably still loading (a restart clears
                          it while it is re-read). Try again in a minute; if it stays empty the library root is wrong."
library_entries: N    -> "isn't in the collection yet: run characters op=extract first (have: ...)"
```

Left named, not fixed: the game shows as its **id** rather than its title, because the store lookup for the catalog entry
returns nothing for that id - the id is actionable and the title is cosmetic, so this is a follow-up rather than a blocker.
## The inbox's real signal: a measured RE5 Switch regression, fixed and closed

Triage of 8,862 requests (1,114 open, 1,691 in progress, 6,047 done) found no mass duplicate - the backlog is mostly stale
conversation, in groups of two to four. What mattered was one report from the learning gate:

```
Bot change made RE5 Switch worse: a human decides
score 47,961 -> 13,078 per round (median 26,705 -> 11,705, p 0.016) over 8 rounds after the restart at 11-06 03:31
```

The change live at 03:31 was `1caf9a35`, which cut the roster-calibration walk's press budget from `CALIBRATE_PRESSES = 40` to
`CYCLE_MAX_PRESSES = 14`. That walk exists to reach the **right-hand end** of the character select, because the stall there is
what teaches the true roster size; with a 14-press budget it gave up mid-roster and confirmed whatever character it had reached,
so rounds began as the wrong character.

Reverted that part only - calibration keeps its own budget as a hard ceiling, a known roster still gives up a locked entry at 14 -
and kept the other two fixes from that commit (`MercModeIn.cast_swap`, the cast_swap/skin_swap feature gates). The ticket is
closed with the reasoning attached, and `test_re5_switch_cycle` passes 7, including a new test that the calibration walk may pass
the locked-entry budget.

The gate will re-measure on the live rotation; that is the verification, not a claim.