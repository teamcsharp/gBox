# Handoff — the Mercenaries grenade ring (PM takeover), 2026-11-12

Written at the end of three working rounds in one session on `main` (HEAD `2dd6adc1`). Everything below is either a
live receipt from the operator's Spark (`lilspark`) or a file/commit; where something is not done it says so and says
what to do next.

## The task (the operator's words)

The session goal:

> "get the grenade launcher ring feature in RE 4 / 5 / 6 operating every 1.5 minutes and able to be deployed in any
> merc mode match across titles using the status bar in pip mode. I want to be able to choose any sort of 360
> protective deployment of any sort of grenade launcher shell or grenade type. In RE4 have the bot spraying a 360 ring
> of mine thrower rounds during the match"

And the follow-ups that arrived during the work:

> "In Resident Evil 4, if a boss character shows up on screen, have the bot pull out a magnum or a shotgun and unload
> on them relentlessly … neutralize the boss until their HP is zero on sight each and every time" (done, live).
> "also if a chainsaw boss approaches the character. Do a 360 grenade launcher 10 round nitrous blast freezing the
> immediate enemies … If a boss is preparing to hit the character with a kill animation, defend them with a 360
> grenade nitrous blast" (the rule exists; the RE4 version is the mine ring; RE6's Nitrogen shell path is blocked).
> "I need the character models being used for all of the characters and all of the RE titles changing across every
> game, every match. I want to see different characters from the library. I want to see more sonic people" (NOT done;
> diagnosis + plan below).
> "the bot needs randomized weapons each and every match" (RE4 has it; RE5/RE6 do not draw a new gun per match yet).
> "get Merc Mode back broadcasting … PSO keeps taking over" (done: the program is pinned to the MercMode session).

## Where it stands, requirement by requirement

| requirement | state | evidence |
|---|---|---|
| RE4: a 360 ring of mine-thrower rounds during the match | **working, live** | `mine_ring_shots 30`, `mine_ring_starts 4`, "ring complete: 10 darts" in session `feb0d0f84514404c-343ae06b6e2149ac`; the Mine Thrower is put in hand by the mods' verified swap (`weapon_given "Mine Thrower" verified=True`) |
| RE4: the ring runs every 1.5 minutes | **working** | `MINE_RING_EVERY_S = 90`; `MINE_RING_CLOCK` keeps the clock in the worker process so a MercMode relaunch between rounds does not restart it; 3 completed sweeps in one session |
| RE4: the ring defends against a chainsaw boss | **working** | `_mine_ring_step` pulls the ring early (45 s min gap) when a `chainsaw`/boss enemy is within 10 m; the boss lock reports `boss_target_key salvador` |
| All titles: the ring fires by itself every 90 s | **RE4 yes; RE5/RE6 rule yes, native blast no** | RE5/RE6 read `ring_armed true` and take the periodic decision; RE6's *launcher shell* ring stalls in the native call (`heap state 2, off 0x18f2bc0`), RE4's native harness never ticks (see Blockers) |
| PiP status bar deploys a ring in any Merc match | **RE4 verified live; RE6 flash 10/10 confirmed; RE5 flash live earlier** | after the restart, the RE4 session's "Mine" button was posted through the API and the bot swept **ten darts with the Mine Thrower verified in hand** (`mine_ring_starts 1, mine_ring_shots 10, "ring complete: 10 darts"`); on RE6 a `grenade_ring flash` click produced `state confirmed, detonated 10`; the "Mine" click on RE4 is served by the bot (scheduled receipt), not the dead harness |
| Choose any shell / grenade type | **chooser complete, every built kind selectable** | all eight kinds are offered; a kind built on the title's native path but without a live receipt is labelled "(probe)" and its click carries `allow_unverified` (the launcher and its three shells on RE6), so nothing is greyed out except what the title truly does not build |
| The ring ejects at least 10 ft from him | **done** | `grenade_ring`'s default inner and safe floor are 305 cm, and both native controllers' `RING_INNER_DEFAULT_CM`/`RING_SELF_CLEAR_CM` are 305 with a hard floor (a caller cannot ask for a closer flash; explosive kinds keep their 600 cm floor) |
| RE4: boss neutralized (magnum/shotgun, until dead) | **working, live** | `boss_kills 2`, `boss_released "killed"`, `boss_shots 59` on a 6500-health Salvador; `re4_switch_mods._boss_weapon` puts a magnum/shotgun in hand on sight |
| Broadcast stays on MercMode, not PSO | **done** | `POST /api/broadcast/program {"session_id": <merc session>}` pins the program; the hub follows the rotation's relaunch to the next agent-owned session. The pin RESETS on a `gbox.service` restart (mode goes back to `auto`) — re-pin after any restart |

## Blockers (with the root cause already measured)

1. **RE4 native harness is dead on this build.** `re4_harness_selftest` on a playing round returns `attached_after
   true` but `ticks_before 0, ticks 0`: the clone sits on the player's vtable but the game never calls the transform
   slot the clone redirects, so every native blast call times out (`native completion uncertain`). Do not spend more
   on the current hook; either find the slot this build actually calls per frame (a fresh tracing experiment) or keep
   using the weapon-path ring (which works).
2. **RE6 launcher shell spawn stalls.** After the loadout spread fix (below) the shell ring passes the inventory check
   and then the native class-spawn call times out with `heap state 2, off 0x18f2bc0`. State 2 is "the callback ran and
   stalled"; `re6_switch_native.recover_completed_call` refuses to recover state 2, so that round's rings are dead.
   Next: (a) give `recover_completed_call` a stalled-mailbox path (state 2 older than ~20 s → restore the manager
   pointer, clear, resume), and (b) test whether the shell DTI is the right class for the spawn image (the shell path
   was never live-verified). A flash fallback for RE6 would at least keep a ring every 90 s while this is explored.
3. **RE4's native flash/hand ring** is offered by the status (attach-on-demand promotion) but will time out as in (1);
   the operator's working RE4 ring is the mine kind.

## What was built (commits on `main`, oldest first)

| commit | what |
|---|---|
| `3b292089` | RE4 boss neutralization: boss identity from the stage set list + health, a boss lock until HP 0, no retreat/melee/hop from a boss, magnum/shotgun on sight, the 90 s "nitrous" defence decision (RE6 Nitrogen shell, flash on RE4/RE5) |
| `0f0580e7` | ring status: a controller that attaches its harness on demand is *offered*, not refused (only kinds the title says are built) |
| `7af1f0d0` | the round ops run before `re6_switch.fast_start` — the launcher loadout spread had been skipped on every burst-started round (the "launcher is not in this inventory" ring failures); failures/receipts are now in the live stats |
| `f278ffaf` | RE4: a declined ring rule names its map id vs `RING_TITLES`; the probe kinds are no longer advertised by the attach promotion |
| `26fd6808` | **the RE4 mine-thrower ring**: `Bot._mine_ring_step` (10 headings, 36° apart, aim/body-turn/ZR, 4 s arm window, 20 s budget) + `WEAPON_ASK` + the mods' verified in-hand swap + stats (`mine_ring_*`) |
| `c5256047` | a weapon request never outlives its ring/round/run (force/clear paths, live-round gate, test isolation) |
| `ef4efe04` | evidence doc: round 2 live receipts |
| `09c8b685` | the 90 s clock lives in the worker process (`MINE_RING_CLOCK`) so a relaunch does not restart it |
| `91d77af9` | the interventions status names all eight ring kinds |
| `2dd6adc1` | PiP **Mine** button on RE4 → the bot's mine ring (`stats["mine_ring_force"]`), bot-served status row, honest scheduled receipt |
| `d4cb129b` | the ring ejects ≥10 ft from him (305 cm inner + hard floor, radius raised with it) and every built kind is selectable as a "(probe)" that clicks with `allow_unverified` |

Evidence doc: `system/docs/research/re4-boss-neutralization.md` (both rounds, live numbers, the selftest finding).

## Operating it (the PM will need this)

* Deploy: push to `origin/main`; the Spark's cron runs `deploy_main.sh --deploy --no-restart` + a bot reload every 15
  minutes. Bot modules (`gbox/mercs/**`, `re4switch_bot`, `mercs_bot`) hot-reload; **native controllers, `interventions`
  and anything else in `hot_reload.NOT_BOT` need one `sudo -n systemctl restart gbox.service`** (the operator accepts
  this; it closes the current emulator and MercMode relaunches).
* Known hazard fixed this session: the Spark's `gbox/hot_reload.py` was a stale **share edit** that no deploy would
  overwrite (it lacked `gbox.re4switch_bot` in its allow-list, so the RE4 bot could never reload). It was backed up to
  `gbox/hot_reload.py.bak-20261112-share-edit` and replaced with main's file, then the service was restarted. If a bot
  module ever refuses to reload again, check for a share edit before blaming the code.
* The broadcast pin resets on restart: re-pin with
  `POST /api/broadcast/program {"session_id": <live MercMode session id>}` (from `/api/sessions`, the agent-owned
  Resident Evil one).
* Verify a ring: `GET /api/autoplay/telemetry/{sid}` → stats `mine_ring_starts/shots/decision` (RE4 weapon ring) or
  `ring_armed/ring_decision/rings_deployed/ring_kind_fired` (the rule/native rings). A PiP click:
  `POST /api/sessions/{sid}/interventions {"op":"grenade_ring","request_id":"<uuid>","args":{"kind":"mine"}}` on RE4
  (needs the restart above), or `{"kind":"flash"}` on RE5/RE6.
* Control-plane token: `system/gbox-data/api_token` locally was valid against `http://10.89.1.246:8765` this session.

## The other asks still open (diagnosed, not built)

**Characters change every match + more Sonic.** Three concrete blockers were found and are the whole job:
1. `mercmode.launch_block` sends `random_characters`/`random_stages` but **nothing reads them** — that is why RE4
   confirms "Leon / Village" every round and the model never changes. Fix: draw a character+stage per round where the
   launch is built (the bots already honour an explicit `selection`: `re4switch_bot.selection_of`, `mercs_bot.play`).
2. `cast_weights` (the Sonic sliders) is validated and stored but **unused**, and the HTTP `MercModeIn` model rejects
   it (`Extra inputs are not permitted`) — add it to the model and consume it in the donor/franchise draw
   (`re5_donor_pool` already maps donors to franchises, Sonic first; `donor_swap._candidates` is where a draw happens).
3. RE4 and RE6 donor pools each hold **one build** (only RE5 has in-service redraw, `donor_swap.REDRAW_TITLES`). More
   builds must be authored offline (RE4: `re4_switch_models.cast_pool`; RE6: the cast/donor writers), Sonic-weighted,
   then indexed by `python -m gbox.donor_fit_audit --write`.
A cheap first win: fix (1) alone makes every match show a different *native* character (the model varies only where the
donor build dresses the slot).

**Random weapons per match.** RE4 already draws a random max-level weapon every round (`mods_weapon_given`). RE5/RE6
have loadout-level randomisers but no per-match draw; add one to their `round_ops`/launch path (the same selection
mechanism as the character draw).

**The defensive Nitrogen ring.** The rule is in (`grenade_ring.decide`: chainsaw boss ≤10 m, boss ≤4.5 m, wind-up
≤15 m, ten rounds, kind `nitrous` → `shell1304` where present, flash otherwise). On RE4 it is the mine ring; on RE6 it
is blocked by the native shell stall above; on RE5 it resolves to the flash (verified path) and should be checked live.

## Tests

`python -m pytest tests` runs large; the affected gates used this session:
`test_re4_boss` (18), `test_re4_switch_fight`, `test_re4_switch_brain`, `test_re4_switch_mods`, `test_mercs_combat`,
`test_re4switch_bot`, `test_re4_native`, `test_re4_native_controls`, `test_mercs_grenade_ring`,
`test_mercs_grenade_status`, `test_merc_interventions` (all green except three failures that also fail at the
pre-change commit: `test_low_life_turns_and_runs_from_the_nearest` (test-order), `test_re4s_shot_tolerance_is_the_
target_classs_own_width`, and `test_mercs_flash_window`'s minute test — verify them against `git stash` before
"fixing"). JS: `node tests/stream-interventions.test.cjs` 22/22.

## The one-line state

**RE4's 360 ring is real and running every 90 s in live matches (mine thrower, 10 darts, boss-killing) and the PiP's
Mine button deploys it on demand (verified: ten darts, thrower in hand); the ring now ejects at least 10 ft from him
and every built grenade kind is selectable (probes click with allow_unverified, RE6's flash ring confirmed 10/10);
RE6's launcher-shell spawn and RE5's native blast still stop in the native layer, and the character/Sonic rotation is
diagnosed but not built.**

The goal is left **active** for the next owner.
