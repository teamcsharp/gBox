# RE5 Reunion policy and round evidence

`gbox/mercs/titles/re5_strategy.py` is a pure decision module. It orders opportunities;
the title adapter still owns validated RAM reads, navigation, inventory controls,
prompt handling and the laser obstruction gate. It cannot fire, heal, write RAM,
or guarantee S rank. Tests exercise policy decisions without starting an emulator.

## Sources checked on 2026-10-21

Berserker's own [Reunion guide](https://gamefaqs.gamespot.com/ps3/980166-resident-evil-5-gold-edition/faqs/59792),
especially Mercenary Basics, says to preserve the chain over optional melee and
detours. Melee **kills** add five seconds; clearing all 150 enemies converts
remaining seconds at 300 points each. Combo chests provide no extra benefit at
combo 50+. These are Reunion rules, not the original mode's scoring formula.

SepticTank's first-person [leaderboard guide](https://residentevilforums.forumotion.com/t3924-mercenaries-reunion-guide-to-leaderboard-runs-re5)
supports postponing bosses for a larger combo, collecting time, and preserving
the chain when a melee would take too long. It also discusses flash use against
parasites and organizing items for quick access. Its claimed final-kill bonus
differs from Berserker's table, so this policy does not encode exact combo awards.
Late boss kills are an optional scoring optimization; nearby danger takes priority.

Berserker's [original RE5 guide](https://gamefaqs.gamespot.com/ps3/929198-resident-evil-5/faqs/56737)
describes grenades for emergency crowds and distinguishes their deployment from
proximity bombs. This supports conditional item use, not a universal explosive
routine or imported original-mode score formula. Mine placement and blast safety
must come from the adapter's observations.

The [official RE6 manual](https://game.capcom.com/manual/bio6/en/page-61.html)
assigns ten seconds to counter kills. That is **RE6**, and no such bonus is credited
by this RE5 policy. An answered QTE alone is not a melee kill or a time award.

## Integration contract

The functions consume existing snapshot fields: player `hp`, `hp_max`, `pos`;
round `timer`, `combo`, `combo_timer`, `recovery_active`; and enemy `hp`, `pos`.
Invalid or missing timing/health prevents optional detours. Coordinates are guest
centimetres. `exposed=True` must mean measured exposure; a camera cone, nearby
position or loaded actor alone is insufficient. Explicit `is_boss` requires a
verified class source; high maximum HP does not establish it.

| API | Result and caller responsibility |
|---|---|
| `close_exposed_threat(snap)` | Detects only live, explicitly exposed foes within the configured radius. |
| `detour_decision(snap, eta, at_bonus=False, ...)` | `Decision(allowed, reason, action)`; ETA is travel to pickup. Add route safety, kind, known gain and immediate-threat evidence. |
| `detour_allowed(...)` | Boolean wrapper for an existing route gate. |
| `melee_allowed(snap, eta=..., prompt_verified=..., lethal=..., ...)` | ETA includes approach and kill animation. Mandatory escape/recovery prompts bypass optional melee policy. |
| `target_priority(snap, target, ...)` | Higher scores sort first. Does not authorize firing; retain the actual obstruction/exposure gate. |
| `item_decision(snap, available, ...)` | Caller supplies verified usable names `heal`, `flash`, `grenade`, `mine`, plus explicit safety/opportunity evidence. No new inventory-ID guesses. |
| `evaluate_round(observed)` | Round-local observations, derived rates, missing fields and invalid values. Never an invented aggregate success score. |

The newest operator priority is explicit: dispatch a close exposed enemy before
optional travel, melee setup, head alignment, group optimization or boss delay.
Every such target receives a dominant distance-ordered priority. Mandatory healing
and escape/recovery remain ahead of optional scoring. The adapter must also apply
that ordering before optional weapon changes, which this module does not perform.
Enemies that are blocked or unknown can be acquisition/navigation candidates;
neither state authorizes a shot. Awareness covers currently observed actors only.

## Tuning versus facts

All `Policy` values are adjustable controller choices: 350 cm critical radius,
one-second combo reserve, .75-second pickup allowance (.35 when already there),
15-second urgent clock, 40% healing threshold, boss delay until combo 120, and
five-second optional item trip. These are not recovered engine constants or
claims that every map can safely follow one route. A reachable urgent time bonus
may break a combo to avoid timeout; a nearby exposed threat still interrupts it.
Time gain must exceed travel cost when that gain is known. Long-term route planning
and profitable spawn relocation remain adapter responsibilities.

## Evidence and evaluation

Pass **one round's** counters, never lifetime totals. Missing data stays missing.
`end_reason` supplies survival outcome; only a supplied `result_rank` from an
observed completed result can establish `s_rank_observed`. A score-derived HUD
rank is not a confirmed result. Death with a large score is not an S-rank round.

The evaluator retains `bonus_s`, `bonuses_taken`, `clock_jumps`, `kills_seen` and
`shots_s` separately as proxies. A clock jump is not attributed melee time;
disappearing pickups are not confirmed acquisitions; presses/finishers are not
confirmed melee kills; laser-zone `headshots` are not independently confirmed
`headshot_hits`. Supply explicit `boss_kills`, `group_kills`, `time_bonus_pickups`,
`melee_kills`, `qte_successes`, `heals_confirmed`, acquisition/use counters and
`radius_clears` only when observed. Rates describe observed events, not hidden
bullets or unobserved enemies. Added time is useful when it enables further
measured kills/score; elapsed duration alone receives no reward.

Run `python -m pytest -q tests/test_re5_strategy.py` from `system` for the policy
regressions. Live performance and wiring require separate integration validation.

## Wired controller behavior

The Reunion driver now budgets bonus detours against the remaining combo window
and clock. A close threat cancels optional travel and weapon changes. Among close
foes, a measured exposed target is dispatched first, nearest first; otherwise the
nearest unblocked actor becomes an acquisition target. The firing gate still
requires the current laser endpoint to overlap the enemy. Ordinary melee setup
yields to another close attacker; mandatory escape/recovery prompts retain priority.
The tactical map carries observed enemy health, distance and clear/blocked/unknown
shot-path status. Awareness includes the loaded RAM actors, not unspawned enemies.

The driver publishes round-local evaluation with missing evidence explicitly listed.
The item and lethal-melee policy APIs remain preparation for verified controls;
their existence does not establish grenade/mine use, boss classification or QTE
completion. No perfect-score, S-rank or measured 80-shots-per-second claim is made.

Verified operator modifier choices persist through the round randomizer. The
random-weapon request uses the existing single-owner D-pad path, confirms the
actual in-hand item, and briefly preserves that choice. It selects an available
loaded quick-slot gun, not an arbitrary newly constructed campaign weapon. Rockets
and all sniper rifles become random magnums in the next spawn template; an existing
rocket/rifle switches to a loaded quick-slot magnum when one is available.

## Sight gate and navmesh pursuit (no standing at walls)

Operator, 2026-10-21: "If the person stands still ... what is there to see?" The baseline scoreboard
([re5-scoreboard.md](re5-scoreboard.md)) measured 48-102 idle seconds per round, 40-80 of them with the laser dot
on a wall: the combat layer was handed Majini it could not see ("front candidate; visibility unconfirmed").

`re5_ps3.Bot` now fights from where the player stands only Majini **in sight**: within `SIGHT_R`, and either within
`PURSUE_NEAR` (2 m) or with open floor between them on the stage's own navmesh (`NavMesh.floor_segment`, or a navmesh
route at most `SIGHT_BEND` x the straight line; floor_segment alone called 4 of 5 nearly straight live routes closed).
Close foes, bonus-route threats and the combat target are all drawn from that set, so a Majini behind a wall neither
cancels a time-bonus route nor draws the gun.

With nobody in sight the bot **pursues**: it walks the navmesh route to the reachable Majini with the shortest route
among the six nearest (`_pursuit_target`, re-chosen each second), gun down, through `_follow` (ladders, drops,
stall handling) without writing pursuit outcomes into the stage's route-learning record. While fighting, the laser
decides: the dot stopping short of him or at the muzzle (`_laser_view` "short" / "wall") for `BLOCKED_VIEW_S`, or
`UNSIGHTED_S` of laser-up time without the dot on him, leaves him out of sight for `PURSUE_S` (`_lost_sight`) and the
pursuit takes over. Time without a laser (the gun coming up) is not counted. The tactical map shows the pursuit route
(phase `pursue`); telemetry carries `pursuits`, `unsighted` and `sight`.

Tests: `tests/test_re5_mercs.py` (`u_mesh` wall, corner straight route, dot short / at a wall / never on him,
laser-view classes). Live validation requires the deployed worker (see the PR).
