
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
## Following up on the regression: what the gate can and cannot tell us yet

`GET /api/mercs/learning` today:

```
RE5 Switch (010018100CD46000)  62 rounds/24h, 0.968 deaths/round
  gate: flagged    p 0.016  score 47,961 -> 13,078 per round        <- the report being fixed
  gate: confounded p 1.0    "the next change went live before 8 rounds"
RE6 Switch                      gate: better   score 41,198 -> 142,448; kills/min 18.1 -> 25.6
RE5 PS3                         gate: kept     no clear change in score, kills/min or deaths
```

The "confounded" verdict is **correct, not a bug**: my own fix is the next change, so it supersedes the pending judgement of
the one before it. The gate judges a change on the title's first eight rounds after it goes live, and this title runs ~2.6
rounds an hour, so the verdict on the fix is about three hours away. There is nothing to tune here - it is the system working
as designed, and I would rather say "waiting" than claim a recovery.

Verified in the meantime:

```
deployed file  gbox/mercs/titles/re5_switch.py:164  CALIBRATE_PRESSES = 40
               same file:1476  budget = CALIBRATE_PRESSES if calibrating else CYCLE_MAX_PRESSES
service        restarted 17:14:55 CST, after the deploy
```

The older flag (from the 10-27 window, deaths 0.20 -> 0.90) is closed as superseded: later RE5 Switch changes went live and were
judged since, and the live flag was the 11-06 one.

## Worth noting for the next batch of bot work

RE5 Switch sits at **0.968 deaths per round** - the bot dies roughly once every round - and RE5 PS3 at 1.0. That is the number
that would move the score more than any single select fix; it is a combat-survival problem, not a menu problem.
## A library that was still loading filed a ticket that sent the operator the wrong way (2026-11-07)

Two open tickets said `Auto report: characters use failed ... Failure: 'sonic' isn't in the collection yet: run
characters op=extract first (have: )`. Both were filed for jobs whose stored record reads:

```
state   succeeded
result  {"character": "sonic", "status": "not_in_collection",
         "message": "'sonic' isn't in the collection yet: run characters op=extract first (have: )"}
```

That is not a failed job and not a missing character: `(have: )` lists **no** library entries, i.e. the index was
still being re-read after a control-plane restart. The library holds 1446 entries today (58 Sonic-family), so the
ticket's advice - "extract first" - would have extracted a character that was already there.

The app files a ticket for any characters job it sees fail, and a `not_in_collection` answer arrives as a normal
(successful) result, so nothing downstream could tell a loading index from a real gap. `characters.py` had already
been fixed to answer the empty case with its own status and a "the index is probably still loading" message, but that
only improved the words in the ticket.

`gbox/server.py` now refuses to mint the ticket at all. `_library_not_ready()` reads the failed job's stored result:

| result | verdict |
|---|---|
| `status` is not `not_in_collection` | real failure, file it |
| `not_in_collection` with no `library_entries` key (an older answer, or the index was loading) | transient, no ticket |
| `not_in_collection` with `library_entries` 0 | transient, no ticket |
| `not_in_collection` with a populated library | **real gap**, file it - the character genuinely is absent |

The route answers `{"ok": true, "transient": true, "reason": ...}` without a ticket number, and the app already
renders that as a plain message (`report?.data?.number` is absent, so no "#N" is shown).

Both stale tickets are closed as `done` with that explanation attached. Committed as `81db2c9b`, deployed to the
Spark and the service restarted; covered by
`tests/test_auto_mod_failure.py::test_a_library_that_was_still_loading_files_no_ticket` (3 cases: the old answer with
no count, an explicit zero, and a populated library that really is missing the character).