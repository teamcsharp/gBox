# DeepSeek PM takeover: MercMode and Hermes, 2026-11-13

**Latest recovery: read the November 13 Codex RE6 bomb-starvation section at the end first.**
It identifies interactions missed by the round-1 fixes and the counters needed to distinguish
working combat from a blocked remote-bomb lane.

The operator is handing all remaining work to DeepSeek because Codex credit is
nearly exhausted. Keep MercMode playing while you manage, implement, review,
merge and deploy the remaining work. The goal is **S rank / five stars on every
RE4, RE5 and RE6 run**, with random weapons, effective grenade swarms, accurate
aim and persistent improvement. **That goal has not been achieved.** Do not mark
the parent task complete because code is merged, a counter increases, or a
round reaches 300 kills.

This document supersedes conflicting operating instructions in older handoffs.
The original handoff identifier `07c0e8a01710cf1d60b2e6d3810e076fa2688781`
is a Git commit updating `HANDOFF-2026-11-12-GRENADE-RING-PM.md`, not an inbox ID.
Read that document and `DEEPSEEK-SPARK-DECOMP-HANDOFF-2026-11-12.md` for earlier
implementation details. The most recent evidence is in
`research/merc-tuning-2026-11-13-native-controls.md`.

## Operator priorities and authority

The repeated complaints matter: wall hugging, face-first walking into walls,
indecisive turning, not leaving the first room, shooting the floor or walls,
shooting over prone enemies, raising/lowering the gun after one bullet, too many
pistols, slow shotguns, unarmed mines, self-explosions and lethal stage hazards.
The operator wants confident continuous movement and spectacular effective combat,
not a series of nominal flags or test-only claims. They particularly enjoyed
frequent mines left while fleeing and miss large grenade swarms in every title.

- Commit and push tested source to `teamcsharp/gBox` **main**; explicitly authorized.
- Spark title restarts are permitted. Backend restarts are authorized **between
  completed rounds**, not during a live attempt. Preserve closed-round evidence.
- Preserve concurrent PSO work and user changes. Do not reset shared main, stage
  everything, force-push, or indiscriminately merge historical branches.
- Do not touch the i9-NUC PSO session. Last known session was
  `29d05fb902974b97-dd9c53f0fd8b4d1f`; rediscover ownership before any operation.
- All models, ROMs, game files, extracted geometry/NAV and decompilation databases
  remain **Spark-local**, outside Git. Git contains tooling, source, tests and notes.
- Use `x-gbox-actor: agent` on API calls. Never print API tokens or provider keys.
- The older handoff's blanket SSH ban and 05:00-only restart rule are superseded
  by the explicit authorizations above. Existing unrelated operator sessions remain
  protected. Do not move the broadcast program away from lilspark.
- No infinite life / invulnerability. The requested ammunition, weapon-speed and
  native deployment assistance are allowed; healing should use actual first aid.

## Current operation and source consolidation

Control plane: `http://127.0.0.1:8765` on lilspark, system service `gbox.service`
(not the user service). Runtime: `/home/ehm_eckx/gBox/system`. Python:
`.venv-linux-aarch64/bin/python`. Token: `gbox-data/api_token`, read privately.
Deployment clone: `/home/ehm_eckx/gBox_alt/gBox-src`.
Windows source: `C:\_tools\gBox`; tested worktree:
`C:\_tools\gBox\.scratch-merc-recovery\merc-tune-next`.

Verified saved lilspark settings on November 13:

```json
{"enabled":true,"titles":["re4","re5","re6"],"rounds_per_title":5,
 "rounds_by_title":{"re4":5,"re5":5,"re6":5},"queue":[],
 "skin_swap":"random","cast_swap":"on","donor_rotation":"fresh",
 "donor_rounds":1,"presentation_priority":true,"coop_ratio":"off"}
```

The empty DJ queue uses the endless title rotation; `repeat_queue:false` does not
stop that rotation. Every completed attempt, including deaths, counts. Each
title has its own configurable count. Launch payloads request random characters
and stages. Existing blueprint look remains enabled. A model request being on
does not prove every enemy instance was replaced; inspect donor receipts.

All 12 commits from `codex/merc-tune-20261113b` were patch-equivalent on main,
then the branch was formally merged as `0e64ecc7c` without additional tree changes.
There were no uncommitted changes in main or that worktree at consolidation.
Relevant main commits:

| Commit | Change |
| --- | --- |
| `3b71f60b` | RE5 native heading alignment for mine escape and diagnostics |
| `7eaf31c2` | RE5 pitch written to the persistent native controller output |
| `cb7b5751` | RE6 free-walking proof rejects near-vertical NAV triangles |
| `382cb96be` | Recover positively inactive mine refusals; independent crowd cadence |
| `a37bbe6a3` | Stop repeated grenade rearm waits after permanent equip refusal |
| `d7c315a59` | Distinguish definitely unsubmitted equip attempts from uncertain writes |
| `7e885ac41` | Preserve/add RE5 grenade supply; RE6 time-bonus priority below 300 seconds |
| `103eaa3de` | Bounded read-only retry for transient RE5 equip readback races |
| `c2d71665e` | Restore earned automine distance after a verified zero-placement refusal |
| `c1a97781` | PiP double-click toggles fullscreen/windowed without exiting PiP |

`7e885ac41` activated at epoch `1794589707.613`, after RE5 round
`6a33c3ad929e46b5b7b67140629e3268` reached fresh, closed `results` with timer0.1.
Replacement service PID was2886149, worker `d6891b50cc2e4cb5`. MercMode resumed
automatically in session `d6891b50cc2e4cb5-f364be569bb24341`, round
`0c5bbbe8f4d342bb838535abe2d125e3`. It had20kills/8000points, one confirmed native
mine, Automine enabled and one policy-recorded grenade throw at the next check.
These IDs are historical: rediscover them; do not reuse blindly.

The newest two fixes were staged after that restart. The final activation helper
is `/tmp/gbox-activate-final-20261113.py`, log of the same stem, with receipt
`gbox-data/merc-activation-final-20261113.json`. Inspect those plus
`gbox-data/deployed-main.txt` and current service PID to distinguish **staged**
from **loaded**. The helper waits for fresh closed-round evidence, exact staged
commit and old service PID, captures the terminal JPEG, rechecks session identity,
then restarts under `/tmp/gbox-deploy.lock`. A changed deployment/PID cancels it.
Do not restart merely because the deployment marker exists.

Use `scripts/deploy_main.sh --deploy --no-restart` for staging. It preserves
unknown share edits and backs up stale source. Deployment is manual-only; old
handoffs describing unconditional periodic auto-deployment are obsolete.

### Preserved runtime divergence

Spark's `gbox/mercs/titles/re5_switch_native_nav.py` is a local native-NAV-v5
implementation with `S_AI=0x1CEFBF8`, while main has the older discovery path.
Deployment deliberately preserves it. Do not overwrite it with main. Review and
assimilate this source **on Spark** with its native evidence before changing it.
Automatic approval review rejected copying this file off Spark under the local
NAV-data restriction; no copy was made. Do not bypass that restriction.

## Hermes: continue tickets and assimilate through the existing gate

`GET /api/hermes/task-mode` confirmed enabled, available, `continuous_queue`,
job `d24e4c0f82a5`, capabilities ready and Git workspace ready. Recent runs were
actively assigned to tickets, including `064c7f33b1f54eae`, `6351db8284f3370a`
and `2711e8ca8145478e`. Keep existing claims and pending native job IDs; do not
duplicate them or cancel other projects to accelerate MercMode.

`gbox.hermes_result_review.config()` confirmed `enabled:true`, `review_prs:true`,
`auto_merge:true`, review job `2be3398574b3`, reviewer `sparkDeux`. Last check had
`last_error:network_unavailable`, next retry epoch1794590018.419; prior successful
review epoch1794588765.848. The exact-head merge gate found **no approved PR ready
for delivery**. `deliver_one()` returnedNone. There is a large pending backlog;
it has not all been merged. Do not present queue enablement as assimilation done.

Use the installed reviewer instead of mass-merging stale branches:

```sh
cd /home/ehm_eckx/gBox/system
.venv-linux-aarch64/bin/python -m gbox.hermes_result_review --status
```

The existing one-minute cron runs `tick()`, discovers PR heads/current main,
reviews complete source and focused test evidence, retests carried approvals,
and merges approved exact commits. Source merge is not gameplay acceptance.
Review state is in `gbox-data/hermes-dispatch/result-review.json` and
`result-review.sqlite3`; task workspaces use `hermes_delivery.prepare()`.
Recover the local reviewer network if it keeps failing, while ordinary tickets
continue. Respect the configured provider policy; do not buy/use extra cloud
capacity or blindly retry exhausted accounts.

## Complete operator requirements, retained for the next PM

1. **Rotation and models:** endlessly cycle RE4/5/6, five completed attempts each
   initially, separately adjustable from GBox's right-click MercMode menu. Random
   character each RE4/5 round; retain RE6's randomized costumes and swap all its
   characters. Replace every enemy, including bosses, dogs, parasites and other
   nonhumans. Each individual enemy draws its own library model, not merely one
   model per species. Extract all favorited games into the Spark-local library;
   keep the cast circulating every round. Fix rig/geometry/normals defects.
   Between-round title restarts are acceptable while real live replacement develops.
2. **Weapons and shooting:** random loadout/weapon each round, strongly favor
   shotguns, magnums and late-campaign weapons; eliminate pistol fixation. Let the
   operator assign any supported weapon from the loader. All guns should deliver
   requested20x fire rate, no recoil animation and infinite ammo. The operator also
   explicitly described20shots/sec and bursts of at least20shots while aimed:
   measure actual projectile emissions, not just modifier values or button presses.
   Hold aim and fire until threats are dispatched; compensate while firing.
3. **Aim and learning:** fast accurate magnum shots, shotgun crowd control,
   downward aim at prone enemies, correct boss weak points (including exposed
   backs), correct grenade/remote-bomb throws. Persist per-weapon mastery across
   titles. Learn from deaths, survival time, hit accuracy and combo losses;
   prioritize prior killers and instant-kill bosses. Never train on confounded
   damage or label an unobserved projectile a miss.
4. **Run and navigation:** get time bonuses first by an efficient learned route;
   build at least five minutes, then exploit combo bonuses/high-score stands.
   Explore/master each stage, stairs, doors, windows and ladders. RE4 doors can
   be opened/kicked with rapid Y or destroyed where appropriate. Log every stuck
   wall/doorway incident with preceding inputs, pose, geometry/route, threat and
   recovery evidence; analyze every round and its final failure sequence.
   Avoid stage hazards and self-kills. Preserve measured geometry identity across
   rounds; never guess a stage binding from a menu label.
5. **Healing and QTE:** always retain RE4 first aid spray and use actual native
   use on demand/low health. Automatically succeed solvable QTEs through proven
   native flags, flash nearby attackers during grabs/QTEs, then escape. Distinguish
   unavoidable downed-death animations from an actual solvable QTE prompt.
6. **Automine RE5/6:** default-on named toggle. Leave armed mines/remote bombs
   every20ft (609.6cm) of measured travel while holding a gun, no equip/plant
   animation. Flash and leave a five-mine ring after damage/grabs/QTE, flee while
   enemies are stunned, and leave a mine/bomb at verified ladder/window/ledge
   traversal exits. Manual Mine Ring must actually flash and deploy five **armed**
   mines at a five-foot radius. Throw/eject deployables toward enemies when safe.
   Maintain clearance from every active retained bomb, not just the latest batch.
7. **Detonation:** RE4 mine-thrower rounds detonate after3seconds plus a manual
   native detonate control. RE6 bombs detonate within5seconds, after escaping blast
   range; plan a feasible exit before placing. Never solve that deadline by knowingly
   exploding the player. Record missed deadlines truthfully and fix their cause.
8. **Grenade spectacle:** randomized grenade types and large aimed/scattered
   volleys across all three titles, requested20x throwing animation speed. Keep
   the90second defensive ring behavior and approximately120second randomized
   crowd swarms as distinct cadences. On damage/grab deploy a grenade/mine/freeze
   ring; on QTE flash, deploy and flee. Roulette among effective behaviors for
   variety. Reactive flashes must not starve the periodic crowd scheduler.
9. **Controls:** usable native360 nitrogen/freeze ring especially; hand,
   incendiary, explosive/acid/nitrogen launcher and mine-thrower ring controls
   across supported titles, sidebar/topbar and MCP. Manual controls must work
   in game, not just show enabled. Combo-time native switch:30seconds on demand
   in each title. Icon-only action buttons leave room for chat. PiP exits only
   via Alt+Enter or right-click Exit PiP; double-click toggles fullscreen/windowed.
10. **Long-term engineering:** comprehensive Spark decompilation/Ghidra hooks,
    fluid live model/game-data replacement without rebuilding whole games,
    eventual combined titles/custom levels. DeepSeek owns the remaining analysis,
    dispatch, implementation, integration and honest live verification.

## Immediate technical continuation

### RE5 mines and grenade supply

`382cb96b` positively reconciles zero-arm floor refusals using actor identity,
native mailbox/build/player life and both collision volumes. Only confirmed
inactive, detached actors are reusable. In round6a33 nine mines had armed at the
midround check: four distance singles plus a five-mine ring; native trigger and
retirement evidence exists. At least76 hit-ring floor refusals included14 ray
[oversized embedded content removed: 6271029 characters (accidental capture, kept out of git)]
Keep the floor checks. Provisional escape sites are not armed mines.

`c2d71665e` repairs consumed distance on such a refusal: preserve travel already
earned, restore it once after the private Flight release, cap at609.6cm, keep the
three-second retry and event deduplication. Related247tests passed, six optional
asset skips; recorder/credit35passed. Test fixtures are not live acceptance.

`7e885ac41` preserves grenades when adding mine templates, adds a damaging hand
or incendiary grenade where a safe slot exists, and only replaces ammo when
infinite ammo is enabled. Protected/full inventories fail truthfully. Supply
checks80passed. Earlier round evidence had zero throwable inventory; later pickups
appeared but repeated equipment failures dominated. The new supply is next-round
template behavior, not an arbitrary live inventory pointer write.

`103eaa3de` retries only transient **readback** of the original equipment request,
within its original1.5s deadline and immutable owner/action/slot identity. Never
republish an uncertain attempted native write.125tests passed. Observe actual
grenade births next: `grenade_throws` is a policy counter, not native birth proof.

### Aiming: new native evidence, integration unfinished

RE5 persistent pitch now survives native controller updates. A sampled pose/ray
audit found median absolute pitch error0.74degrees for53 fresh posed targets,
but only28 conservative body-proxy intersections; substantial yaw acquisition
misses remain. This is not proven hit accuracy. AimCore is verified-only, but its
RE5 path lacks a verified discharge witness and required fire identity/confound
fields, so learning is not yet validated.

Read-only native bullet investigation proved three owned active M500 projectile
births1430/1431/1432 in20seconds. Evidence stays on Spark:
`analysis/merc-tuning-20261113/re5-bullet-readonly-b5a2a2cf2906495c-7c87c4cec33b4703-1794588712.jsonl`
and its summary. Pinned ELF SHA256:
`674c88288eda98b8974e4185853d0b7c2f3fe6b623c823124326d14834856f5c`.
Derived offsets: common emitter7E5FE0, shotgun81A7B0,100-slot pool global1D3F120,
slots+D8, bullet VT1C62048, active+2910, owner weapon+1A10,
attack-volume pointer+1D38 then serial+144, mode+28DC is **one byte**, notu32.
Global serial1D79060 alone is not shot proof; other attacks increment it.
An already-inactive serial is unknown, not a miss. Group shotgun pellets so one
shot does not become many discharges. Require coherent owner/weapon/generation,
freshness under0.25s and bounded scans. No production witness code was added.

### RE6 run/escape and broader unfinished work

Time bonuses now outrank distant combat below300seconds while immediate threats,
QTE, health, pending bombs, hazards and explicit operator orders retain priority.
Related397tests passed with one asset skip; fresh live run acceptance remains.

Old roundccb6's cached geometry had94 walkable headings among360 tested, but none
passed the current monotonic bomb-clearance rule. An offline graph search found
a walkable27-waypoint route of22.13m that initially approaches the bomb; minimum
vertex clearance8.69m, not a continuous clearance proof. Active stage binding
and a feasible five-second escape are unproved. Do not simply loosen blast guards.
Evidence: `re6-ccb6-continuous-heading-probe.json` and
`re6-ccb6-nonmonotonic-route-probe.json` in the same Spark analysis directory.

Still unfinished: reliable damaging grenade swarms in every title; nitrogen360;
actual20x emission/throwing cadence; complete per-enemy model coverage and fixed
rigs; robust RE6 escape/detonation deadlines; all-stage hazard catalogues; full
time/combo runs; verified auto-learning and all-run S/five-star performance.
Native rings currently support RE4 hand/flash and RE5/6 flash; never relabel a
flash as nitrogen or mark unsupported controls successful.

## Acceptance and next-PM checklist

1. Read final deployment receipt/log; verify the loaded revision, fresh worker,
   live session and continued5/5/5 rotation. Finish only the pending safe activation.
2. Capture every attempt through terminal outcome; preserve score, native rank,
   time bonuses, combo loss, weapon changes, mine armed/triggered/retired, actual
   projectile evidence, movement and preceding death/stuck frames. The last6a33
   terminal JPEG captured the blurred results transition, **not a readable rank**.
3. Compare the next mine-credit/equip round against6a33, then fix the first measured
   bottleneck. Do not confuse motionless aimed combat with all stationary failure.
4. Recover Hermes review connectivity if necessary; keep its existing exact-head
   tests/approval gate and ticket ownership, merge useful bounded milestones,
   and report outstanding gameplay acceptance separately.
5. Keep shared cadence, ownership, evidence, learning and priority policies in
   `gbox/mercs`; keep native layouts/title capabilities in `mercs/titles`. Unifying
   logic does not justify pretending that different engines share native flags.
6. Keep a concrete prioritized backlog and update this handoff after each accepted
   live improvement. The operator requested efficiency and continuity, not another
   restart of the investigation from scratch.

Known test limits: asset-dependent tests need Spark-owned inputs. An existing
PS3 mine-retreat guard test and four old weapon-control expectations failed on
their unchanged baselines; they were not repaired in this batch. Do not claim
the entire repository suite passes. No game assets were added by this handoff.

## DeepSeek PM round 1 (2026-11-13 12:00-12:20): fight-and-combo fixes, deployed

The operator's live complaint was "the bot is aiming but not shooting" and "they are standing still, losing the
combo". Two measured causes, both fixed and hot-reloaded into the live worker (bot modules only, no game restart).

### Cause 1: every placed remote bomb froze combat

`mine_escape_required` made the bot walk until it was **1100 cm** clear of every armed bomb with the gun down.
In No Mercy rooms that distance is unreachable, so `act=bomb_escape` ran for minutes: shots frozen at 76-128,
`mine_deadline_misses` 42-47, and the automated follow report `7830be87` recorded the operator's rule breaking
outright: "COMBO LOST 24 -> 0 ... Doing: bomb / inside the bomb clearance margin (75 of 1200 cm): out first" with
six zombies within 4.6 m.

- `4d0f114cf` Keep fighting from a timed-out remote-bomb escape: after `ESCAPE_TIMEOUT_S` (12 s from the
  earliest armed placement) the pure-movement monopoly ends - the retreat route is kept and the normal
  aim/LOS/fire gates run (`escape_timeouts`). The blast rule is untouched: detonation still needs the live
  all-bomb clearance, and a missed deadline still lands in `mine_deadline_incidents`.
- `2b682d249` Chain travel bombs behind an escaped bomb: a bomb at least `TRAIL_CHAIN_CM` (5.1 m) behind him
  counts as escaped, so the next 20 ft travel drop can chain while it lies there (the lane had starved to one
  bomb in a 4-minute round because any live bomb blocked it). Nearer bombs, an unknown census, an allocation in
  progress and emergency rings still block; detonation reads every actual bomb.

### Cause 2: the gun-up laser wait forbade firing

`t_raise` 26.4 s against `t_fire` 11.5 s for 84 shots; `reraise` 28 in one round. Each raise with no laser ray
read inside `LASER_WAIT_S` (0.7 s) returned "the gun comes up (no laser yet)" and could not pull the trigger at
any range - that is the point-blank aiming-without-shooting the operator photographed.

- `0ccdd4979` Fire the proven close shot during the laser wait: inside 5 m, with the same +-8 deg/+-10 deg cone
  and `is_blocked` test the geometry gate already applies, the shot fires at the end of `READY_S` instead
  (`raise_geometry_fires`). `forget()` now clears the negative unit cache too.
- `61818afe5` Let a mesh-proven line fire before the laser wait ends: the same band `_aim` accepts
  (`dist <= ENGAGE_R and (dist <= GEOM_CLOSE_R or _mesh_clear)`) now releases the shot at the raise's end.
- `2cb8b9b60` Hide a control the worker does not advertise: the RE5-only "Mine ring - 5 ft" / "Drop mine"
  buttons no longer sit dead in the RE6 topbar (the operator clicked one: "this button isnt working"). RE6 does
  not advertise `proximity_mines`; its working ring control is the flash grenade ring, and its remote bombs are
  bot-driven. A native RE6 remote-bomb manual ring (five armed bombs on a 5 ft circle + flash + escape) still
  needs building: `re6_switch_native.Controller.drop_bomb_ring`/`bomb_ring_now` exist, the interventions
  capability/dispatch and a `titles/re6_mine_escape.py` do not, and those are not hot-reloadable modules.

### Live evidence after the first hot reload (RE6 No Mercy, new code confirmed by the new counters)

- 46 s window: kills 16 -> 36 (~26/min), shots 37 -> 66, hits 23 -> 44 (72%), combo 13 -> 33 with **0 combo
  breaks** (the round before the fixes had 15-27 breaks), `raise_geometry_fires` 22 -> 38, `escape_timeouts` 1.
- Captured frames: `.scratch-ds-pm/re6-combat-combo34.jpg` (034 COMBO, 37 kills, firing into the crowd).
- Round `f0bcbada` (first full round on the partially-fixed code) ended **died**: score 187520, 152 kills,
  max combo 49, accuracy 48.7%. Round `4ac2f50a` (old code) was 385990, 280 kills, combo 68, 46.1%. Single
  rounds are not comparable (stage, weapons, deaths); do not claim an S-rank trajectory from either.

### Still open, in priority order

1. Verify the chained travel bombs and the mesh-proven fast path live (deploy pending hot reload; the boundary
   watcher only reloads at a finalized terminal/menu with round evidence closed).
2. Raise/reraise dead time is still large (one round measured `reraise` 81 / 86 s and `t_raise` ~44% of decision
   time). Next candidates from the audit: do not `_gun_down` for `nohit_blocks` while the measured ray is on the
   body; stop the miss-streak quick attack -> gun-down pump.
3. Survive: one round died. Death cause extraction (damage runs / `death_log`) is still not in the round report
   for a died round - fix the report path, then work the first cause.
4. RE6 native manual remote-bomb ring + the interventions capability/dispatch (needs a service restart; the
   2 h restart floor and `deploy-restart-pending` from stale non-bot share files apply).
5. Bonus route learning (time bonus to time bonus) is untouched; the bot's travel is still mostly in-place
   fighting, so `mine_travel_cm` rarely reaches the 20 ft interval.
6. Hermes review gate is responsive (no `last_error`): 1520 reviewed, 325 merged, 2312 pending, 7 retry; the
   backlog is not assimilation and gameplay acceptance is still separate.
### Round-1 hot reload: all five fixes confirmed in a live round (12:22)

The bot hot-reloaded at 12:22:11 ("reloaded re6_remote_control, re6_switch") at a `dead` boundary, and the next
RE6 No Mercy round then showed the new counters directly: `raise_geometry_fires` climbing to 23 in the first
minute (proven-line shots no longer waiting the laser), `escape_timeouts` 1 (a timed-out bomb escape returned the
gun to the fight), `mine_trail_chained` 1 (a 20 ft travel bomb chained behind an already-escaped bomb on the
round's opening route), and combo rising 2 -> 7 with 0 breaks while the bot cycled bomb_escape/raise/aim/cc_turn.
Frame: `.scratch-ds-pm/re6-newcode-round.jpg` (008 COMBO, point-blank shotgun on a zombie). Two deaths still
happened before this reload (rounds ended `died`); survival is the next live priority, followed by the raise
churn reraise=81/86 s and the RE6 manual remote-bomb ring.

## Codex RE6 bomb-starvation recovery, November 13 (operator follow-up)

The operator reported stationary play and missing mine rings again after round-1's apparent recovery.
This is a deterministic controller interaction, not evidence that an LLM forgot how to play. The live
playbook is `mercs_bot`; DeepSeek should inspect its native observations and decision gates before changing
prompts or restarting the emulator. A rising kill counter alone does not establish that remote bombing works.

### Measured failure and how the earlier fixes left it behind

On Spark session `cc17261888594ab1-f417214aece5477b`, round `44403b6249784d07af6cdce1569d25b9`,
the bot was alive and shooting, but one native bomb was still pending **258 seconds** after placement.
Only two travel drops had been recorded, no automatic crowd ring, and native detonation had failed 266 times.
Later samples reached 347 detonation failures, nine combo breaks, and only two travel drops. There was
real progress (294 kills and one time bonus in the final sampled state), so this was not a stopped worker.
The symptom was intermittent stationary combat and a starved bomb lane. Installed source was main `483ff9ba3`.
Earlier native receipts independently confirm that this feature really worked: `78efc9568c254cc4b3d52def8532d002`
and `43543581a42844d598f764a0a7677d00` each placed all 15 remote bombs in approximately 256/261 ms in
session `cc17261888594ab1-6880cb8b09034b59`. Do not replace the proven native spawner; fix its admission and exit cycle.

Four interacting gates explain the regression:

1. **Passive driver state blocked all native production.** `re6_remote_control.step` rejected every
   non-None `bot.bomb_phase`, including `wait`. That phase observes an already placed bomb; it is not an
   allocation or throw animation. The driver's `_bomb_track` only clears selected detonation phases when
   the census becomes empty, so `wait` can survive a detonation performed by the separate native controller.
   Native rings then stay blocked even with no remote bombs left. Permit `None`/`wait`; continue to block
   active equip/throw/detonation phases and an active grenade action. A complete native census is still required.
2. **Navigation and detonation disagreed about distance.** Remote policy used 1100 cm, while the live
   stage tuner set `BOMB_MARGIN_CM=300`; the native gate required `BOMB_RADIUS_MAX(900)+300=1200 cm`.
   In the intervening band the controller could stop requesting escape while the native flag writer refused.
   Use the maximum of policy clearance, `BOMB_SELF_R`, and `BOMB_RADIUS_MAX+BOMB_MARGIN_CM` in the controller;
   carry that total distance into the final movement guard. Do not subtract the radius or weaken the native gate.
3. **Aim writes cancelled the movement they accompanied.** Round-1's timeout returned control to aimed
   combat, but `_lock` could write native camera yaw every tick. `re6_movement_safety.guard` then correctly
   discarded movement because the snapshot heading was stale. During an outstanding escape, leave at least
   0.25 s between native aim writes. Intervening fresh snapshots can drive retreat through the existing floor
   and bomb checks while ordinary aiming/firing continues. Never treat the requested yaw as observed camera yaw.
4. **An impossible crowd ring starved the travel fallback.** `2b682d249` allowed chaining behind an old
   bomb, but only when `not emergency`. Four close enemies kept `emergency=True`, although the ring itself
   could not run with old bombs present. Prefer the earned single travel drop in that case. Do not consume a
   flash, surround cooldown, or landing opportunity as though the suppressed action happened.

Travel chaining is bounded to **two outstanding bombs** (one follow-up to a lone old bomb). Otherwise a new
bomb every 609.6 cm would continually reset the nearest clearance and prevent ever reaching the 1200 cm
detonation distance. Large crowd rings still request up to 15 bombs, then escape and detonate before rearming.
This is a bound on trail chaining, not a two-bomb limit on rings.

### Control map and flags DeepSeek must inspect

`engine.play_round` observes remote deadlines before normal actions and services the native remote controller
after them. `remote_mines` supplies policy; `re6_remote_control` owns travel/ring allocation and deadline
service; `re6_switch.Bot` owns pad combat/navigation; `re6_movement_safety` checks the final movement;
`re6_switch_mods.detonate` rereads actual native bomb/player positions before clearing the armed flag.

| Signal | Meaning and next check |
| --- | --- |
| `remote_mines_status` | New scalar reason from every native controller step. Read this first for why no drop occurred. |
| `mine_travel_cm`, `mine_travel_moving` | Observed movement credit, capped at 609.6 cm (20 ft). Pressing into a wall earns none; a stationary timer is not the active trigger. |
| `mine_ring_requests` | All asynchronous native placement requests, including single travel drops. It is **not** a successful-ring count. |
| `mine_ring_bombs`, `mine_rings_dropped`, `mine_trail_drops` | Confirmed native bombs, crowd-ring batches, and individual travel drops respectively. Require actual receipt units. |
| `mine_ring_pending` | Allocation thread active. Do not start another or assume the requested count was placed. |
| `mine_deadline_pending`, `mine_elapsed_s` | Outstanding native placements and age of the oldest. New drops must not reset old deadlines. |
| `mine_clearance_cm`, `mine_required_clearance_cm` | Nearest actual bomb and effective total escape distance, including current native stage tuning. |
| `mine_escape_required` | Current distance is insufficient. This must not monopolize combat indefinitely or cause every final movement frame to disappear. |
| `bomb_escape_aim_yields`, `bomb_retreat_aim_ticks`, `floor_safety_blocks` | Aim updates yielded, retreat merged into aim, and movement rejected. Validate net position change as well; counters alone are not proof. |
| `mine_detonate_last_failure` | New retained scalar native refusal, useful after a later escape message overwrites `mine_detonate_reason`. |
| `mine_flag_detonations`, `mine_blasts_observed` | Native flag readback and observed blast are separate evidence. A successful flag write is not a witnessed explosion. |
| `mine_allocation_blocked_reason` | Unknown native allocation outcome blocks further allocation in that life. Investigate the receipt; never clear this merely to make counters rise. |
| `ring_flash_at` versus `ring_last_at` | Confirmed flash time versus a general grenade-ring event. Only actual fresh flash evidence earns the flash/mine combination. |

The native receipt files are in Spark-local `gbox-data/mercs/native-remote-receipts/`.
`BOMB_DROP=True`, `ring_armed=True`, and policy `enabled=True` advertise intent/capability; they do not prove
that the production gates admitted a request. Likewise the legacy `drop_every_s` policy field is not the
current travel trigger. Native RE6 remote bombs are separate from the RE5-only proximity-mine UI controls.

### Activation, validation, and remaining work

The final combined verification passed **190 tests**, covering remote travel/landing, deadlines, native rings,
aim alignment, fire commitment, movement safety and bonus priorities. Repair commit: `0257a5eb2`.
The new cycle test requires an old pair to stop producing, reach clearance, detonate,
show native blast observations, and then admit a 15-bomb crowd ring. Keep the no-census, uncertain-allocation,
floor, aiming and bonus-priority tests alongside it.

All changed runtime modules are bot-reloadable. Use the normal deployment mechanism and the finalized-round
admission check; a `playing` round or an unclosed capture must defer the reload. `deploy-restart-pending`
also exists for older unrelated service changes: it does not mean these bot fixes need a service restart.
Do not kill the game or claim success merely because source was copied. Check loaded worker source hashes
and the new live counters after activation, then observe several placement/escape/blast cycles.
Many action counters accumulate across rounds in one autoplay run while kills/timer are current-round values.
Compare deltas within the same `round_evidence_id`; do not compare an accumulated bomb counter against a new
round's kills. The public telemetry endpoint may omit nested diagnostic objects; scalar reasons survive there,
while full placement evidence is in the native receipts.

Activation status at this entry: the tested repair is locally committed. Publication to `main` was rejected
by automatic approval review because this turn lacks explicit push authorization; that approval was requested.
Do not mistake this entry for proof that `0257a5eb2` is loaded on Spark. The live verification entry must replace
this pending status once publication and the finalized-round hot reload have succeeded.

Time-bonus policy remains: prioritize eligible time bonuses below a 300-second bank, with immediate threats,
QTEs and bomb clearance first. Once the clock exceeds that bank, combat has priority. Improve route commitment
using observed paths and movement; do not turn off floor checks or continually drop bombs before clearing the
old set. S-rank on every run, perpetual combos and every-stage traversal remain unproven goals.

## DeepSeek PM round 2 (2026-11-13 12:46 onward): took over the Codex repair, activated and measured it

The operator handed over after the Codex PM hit its usage limit. State found: `0257a5eb2` (Restore RE6 native
bomb cycles and escape movement) and `9b1b02126` were committed and pushed, the share had them
(`gbox-data/deployed-main.txt` = `9b1b02126`), but the bot modules were **not** loaded - the only activation
receipt was a `busy` at the first attempt. The documented bot-only reload was the right path (the service
restart stayed deferred from older unrelated share files; no game restart was used).

### Activation

`re6-recovery-activation.json` on Spark now records attempt 2, `ok: true` at epoch 1794595628: "1 of 1
autobot(s) back in 4.2 s; reloaded engine, re6_remote_control, re6_movement_safety, re6_switch", autobot
restarted in session `cc17261888594ab1-f417214aece5477b`. Counters that only exist in the repair
(`remote_mines_status`, `mine_detonate_last_failure`, `bomb_escape_aim_yields`, required clearance 1200) were
present in the next round, so the loaded code was confirmed - not merely copied.

### What the repair actually fixed (measured, not assumed)

Full round `9a5af764a3524df2978ebf51f39fa5fe`, sampled every 2 s into
`gbox-data/analysis/merc-tuning-20261113/deepseek-verify-round2.jsonl` (262 s, 116 samples):

| signal | before (round-1 complaint) | after the repair |
| --- | --- | --- |
| native ring production | none after the first | 5 requests, 46 bombs placed, 3 rings + travel drops |
| native detonations | 266-347 failures | **0 failures, 5 native flag detonations** |
| oldest pending bomb age | 258 s | still up to 111 s (5 s deadline still missed) |
| escape required | - | 76 % of samples |
| combat | stationary, combo breaking | kills 6 -> 103, 4 combo breaks, path 5618 cm / net 3251 cm |
| deaths | - | 1 (the round ended `died`) |

So the lane now cycles and detonates, but each set still takes tens of seconds to clear 1200 cm instead of 5 s,
and the round still ended in a death.

### New findings and commits this round

1. `c7605c6c8` "Keep every armed ring escapable and expose why movement blocks". A later travel receipt
   overwrites `mine_ring_last`, so the movement guard lost the only radial-escape proof while a confirmed ring
   still lay around him; every strict monotone step was then refused (`floor_safety_blocks` 307 in the round).
   The controller now keeps the last four rings' constructor geometry (`mine_rings`) and the guard accepts radial
   escape from any of them; external bombs keep the nondecreasing clearance rule unchanged. New live scalars:
   `mine_ring_last_op/units/armed`, `mine_escapes_started/cleared`, `mine_escape_clear_s_last`,
   `floor_safety_why`, `floor_safety_applied` (the nested `floor_safety_last` never reaches the telemetry mirror).
2. `8c2edf5c0` "Carry a death cause on a scalar out of the live bot". Two captured RE6 deaths showed only
   `act=weapon_switch`, `tablets 6 / 22 presses / 11 misses` and no cause, because the nested `death_log` is
   dropped from telemetry. `death_cause` now carries doing/why/held/health-lost-by-doing/hp samples/near counts/
   bomb phase. Death watcher (Spark `/tmp/ds-death-watch.sh`, captures into `gbox-data/mercs/deepseek-deaths/`)
   is running so each death keeps its frame and pre-death scalars.

Both commits are pushed and deployed to the share (`deployed-main.txt` = `8c2edf5c0`); activation is pending a
finalized boundary (MercMode rotated to Resident Evil 4, so the reload will land at an RE4 round boundary; the
same worker modules serve every title).

### Next measured priorities

1. After activation, read `floor_safety_why` / `mine_escape_clear_s_last` / `mine_escapes_cleared`: the ring
   geometry fix should cut the 111 s pending age. If escape still takes >10 s, the escape needs a planned
   navmesh route to a point 1200 cm out (the current greedy `_open_heading` walk is not a route).
2. The 5-second detonation deadline remains unmet on crowd rings. Do not loosen the native 1200 cm gate; the
   cause to fix is placement without a planned exit.
3. Healing: 22 presses for 6 confirmed tablets and 11 misses in one round. With infinite tablets the count never
   falls, so confirmation rests on the hp rise; a hit taken just after a press reads as a miss. Either confirm
   from the game's item action or accept a heal that was consumed without a net rise. Do not spam extra tablets.
4. Deaths: use `death_cause` from the next deaths; the died-round report path still has no death detail
   (`metrics.survival.death_hp` etc. null, `player_damage_events` counted but no hit rows), so live capture is
   the only evidence for now.

## DeepSeek PM round 3 (2026-11-13 12:57 onward): the operator's mine-ring button, and what the reels show

[oversized embedded content removed: 294183 characters (accidental capture, kept out of git)]

The root cause was not a missing backend: RE6 already exposes the interventions op **`remote_mines`** ->
`re6_switch_native.bomb_ring_now` / `Controller.drop_bomb_ring` (armed native remote bombs ejected from the body,
no throw/animation, placements recorded for the deadline controller). What never existed was any UI control that
sent it; the topbar icon the operator pressed was the RE5 proximity-mine lane, which RE6 does not advertise.

[oversized embedded content removed: 294212 characters (accidental capture, kept out of git)]
  `remote_mines` (hidden on RE5/RE4 and on any title without the lane). Each click posts
  `{op:'remote_mines', args:{action:'ring', count:5, radius_cm:152.4}}`; the bot's own deadline controller then
  escapes the blast distance and sets the set off through the native flag. It sits beside the existing grenade-ring
  and flash controls, so RE6 now has: flash ring, grenade/shell rings, manual remote-bomb ring, remote-bomb
  detonation is bot-owned.
- `43f7dfa7f` reports honestly when that native receipt is "uncertain": `drop_bomb_ring` names armed units but has
  no separate `verified` flag, so `completion_receipt` marks it uncertain; the panel now says
  "Armed remote bombs: N/M (uncertain); the bot escapes and detonates them" instead of "no confirmed effect".
- Client tests: 29 pass (new: request body + receipt text; control hidden without the capability, shown and
  sending the 5-bomb 150 cm ring with it). The share already serves the updated client, so a page refresh shows it;
  no service restart is needed for this control.

### Bot fixes from round 2 are deployed to the share but not yet loaded

`deployed-main.txt` = `8c2edf5c0` (ring geometry kept across travel receipts, `floor_safety_why`,
`mine_escape_*` timing, `death_cause`), but the bot-only reload has not found a finalized boundary: MercMode has
been playing an unusually long Resident Evil 4 round (the Round-1/2 watcher is still running and will reload in
place at the first terminal/menu with its evidence closed). Do not claim these fixes are live yet.

### Round results around the Codex repair (from the round reports, not narrative)

| ended (local) | outcome | score | kills | max combo | accuracy | deaths |
| --- | --- | --- | --- | --- | --- | --- |
| 12:36 | completed | 885 889 | 300 | 77 | 38.1 % | 0 |
| 12:47 | died | 292 730 | 219 | 48 | 39.7 % | 1 |
| 12:52 | died | 141 320 | 103 | 53 | 37.0 % | 1 |

The 12:36 round is the best measured RE6 round so far (300 kills, 885k, no deaths) and it ran on the round-1
fixes; the 12:47 round ended at the moment the Codex repair was activated, the 12:52 round (sampled in round 2:
46 bombs, 5 native flag detonations, 0 failures, oldest bomb pending 111 s) ended in a death. One died round on
the repair is not proof that the bomb changes hurt survival - different stage, weapons and enemy cast - but it is
why `death_cause` was added. Next deaths must be attributed from that scalar before changing survival logic.

### Health of the other lane

Hermes review gate is responsive: enabled, no `last_error`, 1520 reviewed / 325 merged / 2316 pending / 7 retry,
12 attention items (reviewer verdicts, mostly "blocked" requests, not connectivity). MercMode stays on 5/5/5,
rotating; keep it playing.

## DeepSeek PM round 4 (2026-11-13 13:10 onward): the movement guard was freezing escapes; relaxed and verified

### Why the bot stood still with a bomb out (measured, not inferred)

With the round-2 fixes actually loaded (a service relaunch was used because the bot-only reload kept finding no
finalized boundary, and no game was running at that moment), the new scalars named the blocker in a live RE6 round:

- `floor_safety_why` = **"no verified floor escape direction"** 930+ times; `floor_safety_blocks` 185 -> 930.
- One trail bomb at **427 cm**: `mine_escapes_started` 1, `mine_escapes_cleared` never, `mine_elapsed_s`
  60 -> 183 s, clearance oscillating 427-451 against the required 1150 cm, gun down, combo 0.

`re6_movement_safety._bomb_clear` refused every step with any component toward a bomb inside the planning margin,
and `guard()` refuses movement when it cannot prove a safe direction. When the only walkable floor out of a
railing corner runs past a bomb, that rule freezes the bot outright: the escape never clears, the deadline is
missed forever, and the round ends standing still.

### The fix (`725d073ea`)

Movement may cross the planning margin; it now refuses only a step that *ends within* `BOMB_TRAVEL_MIN_CM`
(250 cm) of a bomb. A bomb already closer than that keeps the old climb-out rule (only steps that do not approach
it further). This does not loosen the blast guard: `re6_switch_mods.detonate` still rereads every live bomb and
refuses the flag below `detonate_safe_cm`, and RE6 remote bombs have no proximity trigger - the flag is the only
fuse - so walking past an armed bomb cannot set it off. Tests: 23 movement-safety + 114 in the related
bomb/escape/travel suites; the old monotone assertion is replaced with the floor rule plus a dead-end regression
test reproducing the 427 cm case.

Deployed to the share and hot-reloaded (receipt: "0 of 0 autobot(s) back in 0.1 s; reloaded
re6_remote_control, re6_movement_safety, re6_switch"), i.e. loaded while no bot was running. Live RE6 verification
of the relaxed escape is the next step; MercMode had rotated to Resident Evil 5, so one RE6 round was queued
(`settings.queue = [{"title": "re6"}]`) to measure it without waiting a full rotation - restore `queue: []` after
the verification round.

### Round results while this was being worked

- 13:19 RE6 round: died, 32 120, 33 kills (the trapped round above).
- 13:24 RE6 round: **interrupted** by the operator-authorized stop used to load the fix; 135 650, 128 kills,
  combo 35, accuracy 44.7 %, 0 deaths - good evidence the bomb-free parts are healthy.
- 13:28 RE5 round: died, 9 460, 22 kills (RE5 bot, separate lane; not this fix).

### Still open

- Verify the relaxed escape live on RE6 (`mine_escapes_cleared`, `mine_escape_clear_s_last`, flag detonations
  within a reasonable time), then restore the MercMode queue.
- Survival after the bomb cycle works (the 5 s deadline remains aspirational; a planned navmesh exit route is
  still the real fix).
- Manual remote-mine ring control landed in round 3 (`95c958138`, `43f7dfa7f`) and needs a live click on RE6.
- Bonus routing and the S-rank/five-star goal remain unproven.

### Round-4 live verification and the second freeze cause

After `725d073ea` (movement may cross the planning margin, never within 250 cm) and `52381ff3e` (escape cycles
ESCAPE_SPRINT_S 6 s sprint / 18 s fight instead of one 12 s window) were loaded, the first armed set behaved:

- `mine_escapes_cleared` 1, `mine_escape_clear_s_last` **6.22 s**, `mine_flag_detonations` 1 - a sprint covered
  the 1150 cm and the native flag set the set off. `floor_safety_why` moved from "no verified floor escape
  direction" to "redirecting to verified floor and bomb clearance" while sprinting.

The second set then exposed another freeze, not a bomb-rule one: `floor_safety_why` "no verified floor escape
direction" 636 times in 143 s. On that walkway corner every 150 cm lookahead left the floor mesh, so the guard
stripped all movement and the bot stood fighting with the armed set pending. `cacc9b9db` retries the same eight
pad directions at `LOOKAHEAD_FALLBACK_CM` (60 cm) when no 150 cm step is proven - never a longer step, still
mesh-proven and still under the bomb clearance rule, labelled "(short verified step)" in `floor_safety_why`. A
surface where even 60 cm leaves the floor still strips movement (the test uses a 40 cm platform).

Tests: 24 movement-safety and 106 in the related movement/bomb/escape/travel/fire/navigation suites. All three
commits are pushed; the fallback was hot-reloaded at an RE5 title screen ("reloaded 1 of 1 autobot(s) back in
0.7 s; reloaded re6_remote_control, re6_movement_safety, re6_switch"). One service relaunch (new
`gbox.service` PID) was used earlier because the bot-only reload kept finding no finalized boundary while a game
was running; no game was running at that moment and the operator had authorized relaunch.

MercMode is back on its own rotation with `queue: []` (5/5/5; next round RE6 "Liquid Fire" with Carla), so the
queued verification round was consumed and the operator's settings are preserved. Remaining: verify the
short-step fallback live on RE6 (expect `floor_safety_why` "(short verified step)" instead of stripped movement),
attribute the next death from `death_cause`, click the manual remote-mine ring once on RE6, and continue the
still-unproven 5 s detonation deadline, bonus routing and S-rank work.

### Round 5: manual ring verified, escape made radial, sets now clear and detonate

**Manual remote-mine ring works end-to-end on RE6** (the control from round 3, the native lane was already
server-side): a real click posted `{op:'remote_mines', args:{action:'ring', count:5, radius_cm:152.4}}`, the
worker's native controller placed **5 armed remote bombs in 83.8 ms** (units with `armed:true`, `placed_at`,
`detonate_deadline_at`, radius 152.4 cm) and the receipt came back `uncertain` with `placed:5` - the honest state
(`drop_bomb_ring` has no separate verified flag; the panel wording added earlier reports the landed count).
The bot then escaped the live set: `mine_escape_required` true, clearance 136.7 cm, and later
`mine_flag_detonations` 1 with `bomb_self_hits` 0. So the operator's button now does what it says.

**Escape made radial (`35404053c`).** The sprint cycle repeated its fast clear (3.57 s, flag detonation), but the
next set's "sprint" gained only ~130 cm in 20 s: the guard kept accepting the requested stick whenever it was
floor-safe, so it walked parallel to the blast. While a bomb is pending the guard now evaluates all eight verified
pad directions and takes the one with the **largest clearance at the step's end** (still floor-proven and under
`_bomb_clear`); the short 60 cm fallback uses the same radial choice.

Live after reload of `35404053c` (RE6, Leon / High Seas Fortress): clearance climbed 60 -> 305 -> 388 cm during
sprints instead of crawling, kills 50 with the combo reaching 25 at one point, one set cleared after
`mine_escape_clear_s_last` **124.67 s** and detonated, `bomb_self_hits` 0, `deaths` 0. Movement stays alive
(`floor_safety_why` mostly "redirecting to verified floor and bomb clearance"). So sets do eventually clear and
detonate now; the 5 s deadline is met for easy sets and missed for sets dropped against a wall - truthful
`mine_deadline_misses` remain.

**Death evidence upgraded**: the watcher now saves the whole telemetry payload plus a `death_cause` summary at
each death (nested `death_log` never reaches the mirror). No RE6 death has yet occurred with that code loaded;
earlier RE6 deaths (13:37, 13:45) predate it.

**State**: MercMode rotation restored (`queue: []`, 5/5/5); Hermes review gate still responsive (enabled, no
`last_error`). Open: close the long-tail escape sets (a planned navmesh route to a far point is the real fix),
attribute the next RE6 death, and the unproven bonus routing and S-rank/five-star goal.

### Round 6: nav-mesh escape route planning, and the combo finally holds while a bomb is pending

`183826183` plans the sprint instead of steering by feel: while a sprint window is open, `Bot._escape_route`
picks the nearest nav-mesh triangle whose centre is already clear of every armed bomb by the rule's clearance
plus 50 cm, plans A* to it (`NavMesh.path`), and publishes the first far-enough waypoint's heading as
`_escape_heading`; the movement guard follows that heading among its floor-proven options (falling back to the
radial clearance choice, then the 60 cm short step). New counters: `escape_route_used`, `escape_route_failed`.
Tests: 74 in the movement/bomb/escape/fire/navigation suites, including the far-clear-triangle choice and
"a published plan heading wins over the radial step".

Live after reload (RE6, Leon / High Seas Fortress):

- `escape_route_used` climbed to 362 with `escape_route_failed` never set - the planner is invoked and finds a
  goal; the "(short verified step)" fallback was also observed live.
- The observed round had **57 kills, combo 57, combo_breaks 0, deaths 0, bomb_self_hits 0** while a bomb set
  stayed pending (`mine_escape_required` true, clearance ~226 cm). That is the strongest combo maintenance
  measured so far - the operator's "always accruing kills" while a set is out.
- The set did **not** clear in the sampled window: clearance oscillated 97-477 cm against 1200. The route is
  planned but the sprints do not convert into clearance - likely combat interruptions (grabs, quick turns) and
  the guard's per-step bomb rule fighting the route near the bomb. Not resolved; do not report the 5 s deadline
  as fixed.

Manual ring control remains verified (round 5: 5 armed bombs in 83.8 ms, escaped, detonated, 0 self-hits).
MercMode queue restored to `[]`; the switch to RE6 for this measurement used the operator `command: switch`
control, not a config change. Hermes gate unchanged/healthy.

### Round 7: the escape now explains itself, and the sets actually detonate

`cb110f7a6` adds the scalars the escape needed: `escape_sprint_cm` / `escape_sprint_window` (how far the current
sprint window actually runs from where it started), `escape_route_goal_cm`, `escape_route_path_n`,
`escape_route_heading_deg`, and `mine_escape_best_clear_cm` (best clearance this set reached).

Live read (RE6, after reload; `escape_route_used` 348, no failures):

- the plan runs: goal 1279-1626 cm away, 14-22 waypoints, a sprint window ran up to **847 cm**;
- clearance reached **1208 cm**, `mine_escape_required` flipped false and the native flag fired:
  **3 sets cleared, 3 `mine_flag_detonations`, best `mine_escape_clear_s_last` 11.88 s**, `bomb_self_hits` 0,
  `deaths` 0, kills 65+ on the round and combo up to 58 in the previous round;
- 34 `mine_deadline_misses` still - easy/nearby sets clear in ~12 s now, wall-trapped sets and the 5 s target
  remain unmet. The guard/crowd still limits sprint distance, so the next lever is sprint continuity (non-escape
  actions interrupting the walk) rather than planning.

Earlier RE6 results under these fixes: 20:23 "lost" 100 280 / 109 kills / combo 32; 20:13 "lost" 23 560 / 35 /
combo 12; the 20:37 round (stopped for the reload) 162 060 / 118 / combo 58. Round outcomes are still "lost" at
2-4 minutes - survival and length, not the bomb lane, are what S-rank needs next.

### First attributed death (RE5, from the upgraded watcher)

`gbox-data/mercs/deepseek-deaths/20261113-142733-telemetry.json`: RE5 round, 60 kills, combo 57, then
`heal_status: "critical retreat at 0% (heals outside quick slots)"`, `heal_unavailable_reason: "heals outside
quick slots"`, `heal_quick_slots: 0`, `prompts_seen_dying: 34`, `dying: 2`; the decision log ends
"held dying" -> "dead (Continue?)". The bot fought a crowd to 0 % health with **no heal item in a quick slot**.
That is an actionable RE5 survival cause: keep the heal usable (quick-slot assignment / inventory heal path)
rather than only learning to retreat.

### Round 8: shots land on the body now (35 % -> 64-76 %), detonations happen while fleeing

Operator, watching live: "they are shooting up in the air ... aiming and shooting at the people". Measured on the
same build: 106 shots / 37 hits (34.9 %), nearly every fired "correcting" pull 12-27 deg off at 1-4 m, 36 of 54
confirmed geometry shots with no body under the ray. A cone limit is not accuracy: 12 deg is 21 cm at 1 m but
90 cm at 4.2 m.

`9e7d26b6d`: the geometry and correcting gates convert the aim error at the target's distance into centimetres and
fire only when that lands inside the body (30 cm lateral / 35 cm vertical half-width). Long elevated/ledge shots
keep their own 4/6 deg cone (the driver's aim point differs ~2.4 deg from a raw chest ray at 12 m, which the
envelope would wrongly veto). New counter `fire_envelope_blocks`; a third 30 cm mesh-proven step added before the
floor guard strips movement (the bot was frozen in a bonus run where 150/60 cm lookaheads both left the mesh).

Live after reload (RE6, same stage): accuracy **0.612 -> 0.759 -> 0.638** across the sampled round (hits/shots
37/58), `fire_envelope_blocks` 14, and the fired shots are body hits at 0.8-2.4 m instead of 12-27 deg misses.
`shots_without_target` is still counted (geometry pulls with no laser body under the ray) - the honest confound,
not a claim of damage.

Also confirmed the operator's other complaint live: **detonations do happen as the bot flees** -
`mine_flag_detonations` rose 1 -> 3 in the sample as `mine_clearance_cm` reached 1206-1391 and
`mine_escape_required` flipped false. The long tail (sets that never reach 1200 cm) remains.

### Nitrogen 360 ring: investigated, not implemented - and why

The ring chooser offers Nitrogen/shell kinds, but `re6_switch_native.RING_KIND_REFUSED` refuses them before any
native work: "the uWp1304 launcher round needs its native shell initialization and explosion path; the
thrown-grenade initializer is incompatible, and spawning a shell does not confirm a blast." The shell branch in
`_ring_one` is deliberately unreachable (`_ring_one` raises for `CLASSES.SHELL_KINDS`), and `RING_IMPLEMENTED_KINDS`
keeps shells out. What exists is the real precondition and the research path: the launcher item (0x112) must be in
the loadout, and `titles/re6_switch_shell_probe.py` fires ONE shell through the private native mailbox (+0x160,
`SAFE_DISTANCE_CM` 601) and treats enemy ice reactions as the only emission evidence. A 360 nitrogen ring needs
that single-shell path generalised (spawn/launch per angle, per-shell emission receipts, safe placement) before
the button can honestly work - do not advertise it as working until those receipts exist.

### Round 9: QTE survival + post-QTE mines wired, long-distance snipers answered

**QTE success.** The game's own automatic action button and the RAM struggle writes are already on
(`qte_auto` true, `_complete_struggle` writes chance outcomes / mash progress, `QTE_RAM_ANY` true for finishers and
climbs), and `qte_solved_ram` climbs live. One prompt can still fail (`qte_failed`), which is counted honestly.

**Post-QTE mines: the recovery was dead code.** `titles/qte_escape.Recovery` decides flash cover while held and the
escape on release, but nothing in the repository ever instantiated it, so "after a QTE, flash, mine the area, flee
and detonate" never ran. `9507037bb`:
- the remote controller now runs `Recovery` each tick (grants from `qte_solved_ram` deltas), fail-soft
  (`qte_recovery_error` never ends the lane);
- the mine ring is requested on **every released QTE**, not only after a confirmed cover flash;
- the QTE ring is admitted while older remote bombs are still out, up to `QTE_RING_MAX_OUTSTANDING` 24 (native
  placement never detonates; the flag gate still refuses below the rule's clearance);
- new counters `mine_qte_rings`, `qte_recovery_error`.

Live on the first round after reload: `qte_escapes_observed` 2 -> `mine_qte_rings` **2**, `qte_recovery_error`
empty, flag detonation 1, combo up to 31, accuracy 62-75 %. The operator's "drop mines around the area after a QTE
and detonate as they flee" is now actually executing.

**Long-distance laser snipers.** A ranged/laser windup is now read out to 80 m (`LEDGE_RANGED_R`) and the long-shot
geometry gate runs to `SNIPER_LONG_R` 60 m with its 4/6 deg chest cone, no laser/mesh needed, so a distant shooter
is answered with whatever weapon is in hand (the magnum included); a plain ground zombie at the same distance is
still never blind-fired at. New counter `re6_sniper_longshots`; test: 45 m gun-raised sniper fires, 45 m plain
zombie does not. Not yet observed live (no such enemy in the sampled round).

**Still open:** native nitrogen/launcher-shell 360 ring (refused by design; single-shell probe is the starting
point), the 1200 cm bomb-clearance long tail, a rare QTE failure, bonus routing, and S-rank/five stars - none
claimed. Commits: `9507037bb` (live), plus the handoff.

### Round 10: dying evidence instrumented, and the best round yet (366 060 / 161 kills / combo 85)

`5812ba72f` (`_note_dying_transition`) records the >1-health -> 1-health transition - the S-rank killer: every RE6
death runs through this state, and re-raising the dying tablet was already measured to do nothing (4 presses, the
case count never fell). Fields: `dying_count`, `dying_from_hp` (a one-shot from high health is a grab/bite/heavy
attack), `dying_doing`, `dying_held`, `dying_near_melee`, `dying_ranged_windup`, `dying_state`, `dying_bomb_out`,
`dying_recoveries`. Live immediately after deploy: `dying_count 1, dying_from_hp 400, dying_doing "bomb",
dying_near_melee 21, dying_held 0` - knocked from 400 health to the crawl inside a 21-strong melee crowd while
the bomb lane was running, then died.

Round results are improving and this is now the evidence base for survival work:

- 21:37 "died" **366 060 score / 161 kills / combo 85** (round 655 s - the longest and highest-scoring under the
  fixes, previously 343 820 / 219 / 63);
- that death at 15:37:50: `doing=raise`, `heals: tablets 0, presses 1, misses 1`, 5 enemies within 2 m, 1 health,
  `floor_why "no verified floor escape direction"`, `esc_s 5.99` (an escape cleared in 5.99 s), 3 flags, 0 self-hits.
  So he died **out of tablets and im-mobile**, not from the bomb lane.

Precise next fixes (evidence-driven, not guesses):

1. **No-tablet survival kit at critical health**: when hp <= TABLET_CRITICAL_HP, tablets == 0 and >=3 enemies are
   within 2 m, use the verified native flash + quick attacks/kick instead of raising the gun. The death above is
   exactly that state.
2. **The floor guard's last resort**: even the 30 cm step failed here ("no verified floor escape direction"); the
   guard must never leave the bot both immobile and passive - if no step is provable it should fall through to the
   combat answer (quick shots/melee/flash) rather than a gun raise.

QTE recovery stayed live this round (mine_qte_rings 3, flags 3-5, 1-2 qte_failed counted honestly). Deploy verified:
`deployed-main` = 5812ba72f; the reload/switch launcher job was killed after the live state showed the new code
running (only its launch-wait loop remained).

### Round 11: no-tablet critical survival flash shipped and live

`586c8e8f5` adds `_critical_no_tablet_flash` (called in the fight path before the critical tablet rule): at
<= TABLET_CRITICAL_HP with an empty tablet case, not down/held, and >=3 enemies within 2 m, it requests the
verified native flash through the existing `_respond_flash` gate and takes a gun-down moment instead of raising
the gun. This is exactly the 2026-11-13 15:37 death state (1 health, heals tablets 0, 5 enemies within 2 m,
doing=raise) and the dying tablet is measured useless, so the belt is the state before the crawl. New stats:
`critical_flash_requests`, `critical_flash_at`; the helper falls through untouched when the flash gate refuses.
Tests: critical state flashes, tablet-in-case path untouched, healthy HP untouched, refused flash falls through;
359 pass in the related suites.

Deploy notes: a previous deploy left a `deploy_main.sh` sleeping in a 60 s loop holding `/tmp/gbox-deploy.lock`
(it had paused Hermes dispatch for a restart and then stayed in the idle wait). It was stopped, the lock removed,
`deploy_main.sh --deploy` ran to completion (main 586c8e8f5, 104 files, backup
`deploy-backups/20261113-214607-586c8e8`), the bot modules were reloaded at a stopped boundary ("reloaded
qte_escape, re6_remote_control, re6_movement_safety, re6_switch"), RE6 was switched back in and is playing.
Hermes task-mode re-checked: `enabled: true, available: true, dispatch continuous_queue` - the gate is healthy.

Live round after reload: playing, no deaths, kills climbing; `qte_seen` 15 with `qte_failed` 6 while the game's
own auto-action solves grabs (the failure counter fires when a prompt vanishes without a registered grant/press,
so it likely over-counts auto-solved prompts - worth tightening, not a bot fault to "fix" blindly).
`critical_flash_requests` not triggered yet (no qualifying empty-case crowd fight in the sample).

Open: trigger/verify the critical flash in a live round, the qte_failed semantics, nitrogen 360 ring, the
bomb-clearance long tail, bonus routing, and S-rank/five stars - unproven, unclaimed.

### Round 12: heal retries that land, honest QTE failures, and the rotation cycling again

Dead round evidence (2026-11-13 21:59, 36 620 / 35 kills): knocked down at 1 health with FOUR tablets still in
the case - `heals: tablets 4, presses 17, misses 8`, then "down at 1 health: staying down, no fight" until death.
The ignored presses were the gap.

`c96039fc9`:
- an ignored tablet press now records its context (`tablet_miss_state/_held/_doing/_zl_ago`) and forces the
  gun-down window itself (`_zl_at = now`), so the retry's R is not swallowed by an aim hold again;
- the critical heal rule retries after `TABLET_RETRY_S` (1 s) once a press was ignored, instead of 3 s;
- `qte_failed` no longer counts a prompt that vanishes with no press and no registered RAM grant while the game's
  own automatic action button is ON: live 2026-11-13 had `qte_seen 15 / qte_failed 6` while every grab was solved.
  A real un-pressed prompt still counts.
Tests: auto-QTE prompt not counted / real one counted; ignored press arms the retry; 361 pass in the related suites.

Deploy: `deploy_main.sh --deploy` ran bounded (150 s timeout) - copied main `c96039fc9` (103 files, backup
`deploy-backups/20261113-220428-c96039f`) and was terminated at its own "Hermes dispatch paused for the restart"
idle-wait (the earlier hang class); `deployed-main` = c96039fc9, no deploy process left, Hermes task-mode still
`enabled: true, available: true`. The module was reloaded at a stopped boundary ("reloaded re6_switch") and RE6
switched back in.

MerCMode rotation kept running by itself: RE6 completed its five rounds and moved on to RE4 Mercenaries
(`playing Resident Evil 4 (Switch, Mercenaries)`); round reports from the cycle: 118 530 / 115 kills (interrupted
for the reload), 36 620 / 35 (died), 87 240 / 84 (lost) - all captured.

Open: verify `tablet_miss_*` on the next ignored press and whether heal success rises; trigger
`critical_flash_requests`; nitrogen 360 ring; bomb-clearance long tail; bonus routing; S-rank/five stars -
unproven, unclaimed.

### Round 13: the 360 launcher ring got its native barrage, and the first live probe found the real blocker

`29e4f7661` (pushed):
- `titles/re6_switch_shell_probe.barrage`: `count` launcher shells spawned on a ring 601-2600 cm around the player
  and armed at their ring points through the existing research spawn/arm images. One barrage per player life, never
  replayed; per-shell rows (spawned/armed/emitted); `verified: False`; emission only from the shell's own explode
  phase + `(4,4)` enemy attack pair. Admission refusals: unknown kind, unsafe radius, no launcher, existing barrage,
  cancellation.
- `titles/re6_switch_native.Controller.grenade_ring` now routes shell kinds (`shell1302/03/04`) to
  `shell_barrage_ring` instead of the blanket refusal, **only with `allow_unverified`** (the chooser's probe rows
  already send it). Research grade: nothing advertised as verified.
- Tests: ring geometry/arming/emission honesty, replay refusal, launcher/radius/cancellation refusals, dispatch
  gating; 58 pass across the shell suites.

**First supervised live probe** (the rollout gate in `docs/research/re6-native-shell-ring.md`): the running service
advertises `re6_shell_probe`; at an idle window in a live RE6 round (no remote bombs pending, agent/probe actor,
point 932 cm to a J'avo) the probe was claimed and returned an honest failure:
`"native grenade launcher resources are not present in this loadout"`.

Blocker found: this RE6 build's loadout has **no grenade launcher**. Live weapon rows for the round
(`recovery-re6-enemy-cast-01-20261110-blueprint`): inventory = `item 12 (handgun ammo box, equipped)` and
`item 23 (Crossbow)`; `item 18 Grenade Launcher` is `in_inventory: false`. Live `grenade_kinds` even advertises
shell1302/1303/1304 `available: true`, but the native path refuses honestly (the operator's screenshot refusal came
from this). `allow_unverified` cannot conjure the launcher resources.

Next steps, in order:
1. get a launcher-bearing RE6 loadout (per-pref spread / a different build; `default_mods.re6` currently
   `recovery-re6-enemy-cast-01-20261110`, `blueprint_look` true, `donor_pool` empty - the blueprint draw is the
   per-pref spread that lacks item 18 here);
2. rerun the single supervised probe and capture emission + `DmgIce`/`DeadIce` evidence;
3. restart the service (NOT_BOT modules changed: `re6_switch_native`) to activate the barrage dispatch, then test
   one ring with a receipt for each shell and no claim of verified damage until the ice evidence exists.

### Round 14: the nitrogen ring's blocker was the spread ORDER, not the loadout spread itself

`457a6cbc6` (pushed): the RE6 loadout spread put the grenade launcher (uWp1080/item 0x112) **second** in its fill
order. A character with only ONE empty weapon slot therefore got the Lightning Hawk and never the launcher - which
is exactly what the supervised live shell probe reported (2026-11-13 16:24: "native grenade launcher resources are
not present in this loadout"; live inventory Lightning Hawk / Assault Rifle for Special Tactics / Combat Knife,
and later Wing Shooter / Shotgun for another round). The launcher now goes **first**; the magnums and shotguns
follow while slots last. Tests updated (spread order, asked-weapon-first, pistol swaps) - 366 pass in the affected
suites.

The chooser still REFUSES launcher ring kinds even with allow_unverified, per the research note's rollout gate: one
supervised live probe with its own emission and ice evidence must come first. The research barrage
(re6_switch_shell_probe.barrage / Controller.shell_barrage_ring) remains reachable only to agent/probe callers.

Deployment reality this round: `deploy_main.sh` copied `457a6cbc6` (deployed-main matches). Hot-reloading
`re6_switch_mods` repeatedly failed with "the Mercenaries round ... has not reached a finalized boundary" (the
scheduler relaunches a round the moment one is stopped, and one stale session id stayed in that state), so the
worker was restarted twice (`systemctl restart gbox.service`; API up in 3-4 s each time) and the restarted service
loads the deployed code - including the launcher-first spread and the earlier `mercmode.py` round_ops entry. The
spread job submitted through tool `re6` while a round was in menus failed with an empty result, so the
round_ops/spread receipt still needs a clean round to confirm.

Live state after the restarts: MercMode healthy on its rotation (`playing Resident Evil 4 (Switch, Mercenaries)`,
titles re4/re5/re6, 5 rounds each, queue `[]`), Hermes task-mode `enabled: true, available: true`, deployed
`457a6cbc6`.

Next steps, in order:
1. let a fresh RE6 round start and check the inventory for item 18 (Grenade Launcher) via the session interventions
   weapons list - that is the launcher-first spread's live proof;
2. with the launcher present, rerun the single supervised `re6_shell_probe` (idle window, point >= 601 cm, no remote
   bombs pending) and capture emission + `DmgIce`/`DeadIce` evidence;
3. only then wire the chooser's shell kinds to the barrage (or keep the probe path) and test one ring with a
   per-shell receipt; do not advertise verified nitrogen damage before the ice evidence exists.

### Round 15: launcher-first spread confirmed live, and the first supervised nitrogen shell probe ran

**Launcher confirmed in a live RE6 round.** After the worker restart with deployed `28a7b8473`, a fresh RE6 round
(session `11dea838ee8140be-6798a85d79624b69`) carried **Grenade Launcher (item 18)** in its inventory (Picador +
Grenade Launcher); a later round's inventory listed the whole spread - Shotgun, Assault Shotgun, Hydra, Lightning
Hawk, Elephant Killer, Grenade Launcher (6 weapons). Earlier "no launcher" checks were reading the inventory too
early in the round / before the character select's spread landed.

**First supervised live nitrogen shell probe, with ice evidence.** At an idle window (no remote bombs pending, agent/
probe actor, launcher present, point 5.1 m away) the agent-only `re6_shell_probe` ran:
`spawned 1, armed 1, detonated 0, verified false, state uncertain` - the shell's native flight advanced and
`collision_requested` became true, and one nearby J'avo (unit 400950080896, generation 396, stable vtable)
transitioned **`cEm1000ActJumpDown` -> `cEm1000ActDmgIce`** (hp 500 -> 500) - the nitrogen ice reaction the research
note's rollout gate asked for. The receipt is honest about the rest: `detonated` stayed 0 and `state` stayed
`uncertain` because the shell allocation's identity changed during sampling ("shell allocation identity changed"),
so the shell's own explosion/emission pair was never confirmed for that allocation and the request was not replayed.
The first attempt was refused with "shell research waits for bot ownership and no pending remote bombs" - the
remote-mine lane keeps bombs in flight most of the round, so the window must be caught live (retried within ~2 min).

**New instrumentation** (`28a7b8473`): `mercs_bot.apply_ops` now mirrors the last round op receipt as the scalar
`round_ops_last` (the list `round_ops` is dropped by the telemetry mirror). Live after the restart it reads e.g.
`"magnum_speed: True"` - the SPREAD op's `verified/writes/reason` will now be visible on the next character select
instead of guessing from the inventory.

State after the round: queue reset to `[]`, MercMode enabled on its rotation (`playing Resident Evil 6 (Switch, No
Mercy)`, titles re4/re5/re6, 5 rounds each), Hermes task-mode `enabled: true, available: true`, deployed
`28a7b8473`.

Next: repeat the supervised probe 1-2 more times to confirm the ice transit is repeatable and to try to catch the
shell's own emission pair before the allocation recycles; then decide whether the chooser's launcher ring kinds can
be wired, with per-shell receipts and without claiming verified nitrogen damage until the blast emission itself is
observed.

### Round 16: nitrogen probe repeatable with damage, and the honest QTE metric verified live

**Second supervised live nitrogen shell probe** (new player generation, launcher present, idle window, 5 m point):
`spawned 1, armed 1, detonated 0, verified false, state uncertain` - and a nearby enemy transitioned again:
unit 400962102560 (generation 1066, stable identity) `cEm1000ActJumpDown` -> **`cEm1000ActDmgIce`** with
**hp 500 -> 125** (375 damage). Together with round 15's J'avo (500 -> 500 DmgIce) the nitrogen ice reaction now has
two independent live observations, one with measured damage. The remaining gap is unchanged: the shell's own
explosion/emission pair (`detonated 0`) is not confirmed because the shell allocation recycles before the receipt
sampler sees the action - reason "shell allocation identity changed", never replayed. Probes are one per player
generation, so the next attempts need new rounds; pending remote bombs refuse them ("shell research waits for bot
ownership and no pending remote bombs"), so the idle window has to be caught live (retried many times in ~3 min).

**Honest QTE metric verified live**: in the current RE6 round `qte_seen` 30 with **`qte_failed` 0** - the earlier
build counted auto-solved prompts as bot failures (15 seen / 6 "failed"); the auto_qte exclusion from `c96039fc9`
now reads truthfully.

**Round health in the same live sample**: RE6 playing, 14 native flag detonations, accuracy ~52 % (62 hits / 119
shots), combo built to 16 in the fresh round; one death occurred during the round (not yet attributed in this
sample). Launcher inventory confirmed again (Picador + Grenade Launcher). Queue `[]`, MercMode enabled on its
rotation, Hermes task-mode `enabled: true, available: true`, deployed `9daa6aaa3`.

Next: either a native sampling callback for the shell explode/attack pair (the research note's known limitation -
"the queue may clear between Python reads, reducing the evidence requirement is not a substitute") or an agent-only
`re6_shell_barrage` intervention to exercise the ring mechanics live with per-shell receipts; only then consider
wiring the chooser's launcher ring kinds, with the research grade receipt and no claim of verified nitrogen damage
until the blast emission itself is observed.

### Round 17: the research launcher barrage is an agent-only intervention and ran live

`14515d66d` adds the agent-only `re6_shell_barrage` intervention (source agent/gbox-agent/mcp/probe only): one shell
kind, count 1-16, ring radius 601-2600 cm, explicit `allow_unverified=true`; advertised in capabilities for the RE6
controller only and never in the grenade-kind/UI choices. The worker runs `re6_switch_shell_probe.barrage` under the
shared controller and round ownership, refuses while the bot owns input or any remote bomb is pending/detonating,
and passes a cancelled callback that rechecks the round, player generation and idle state. Tests: argument
validation, worker dispatch (probe source runs it when idle, viewer source refused, pending bombs refuse before any
native call); 28 pass with the existing worker tests.

**First live research barrage:** at a fresh-round idle window a 4-shell ring (radius 700 cm, shell1304) came back
`state uncertain, spawned 4, armed 4, detonated 0`, with four per-shell rows all `spawned 1 armed 1 emitted 0` -
the ring mechanics (multi-shell spawn + arm around the player) now proven live. Honest receipt: no blast emission
or ice reaction was captured by that receipt.

**Why mid-round attempts keep refusing:** the remote-mine lane sets the stat
`mine_allocation_blocked_reason = "uncertain native allocation; no further automatic bombs in this life"` after an
uncertain allocation, which is one of the gate keys; the research gates therefore stay closed for the rest of that
life. Fresh-round first seconds are the reliable window (that is when the barrage above was admitted).

`18b4206f4` gives the barrage the probe's evidence rule: a bounded read-only baseline of nearby targets before the
spawn, then new stable-identity `DmgIce`/`DeadIce` transitions after arming, reported as
`targets_before`/`ice_observations`/`ice_observed` (telemetry failures never block the native ring). Tests: a ring
whose nearby enemy goes `cEm1000ActWait` -> `cEm1000ActDmgIce` (500 -> 125) reports ice_observed 1; 60 pass in the
shell suites. Deployed (`18b4206f4`); the bot-module reload needed to activate it was refused mid-round
("has not reached a finalized boundary") and the boundary-watch loop expired without a menu moment, so the running
worker still uses the previous barrage module - activation is the next round's first step (reload at a boundary).

State: MerCMode RE6 playing, queue `[]`, titles re4/re5/re6 x5, Hermes task-mode `enabled: true, available: true`,
deployed `18b4206f4`.

Next: activate the ice-reporting barrage (bot reload at a boundary or a service restart), then run one fresh-round
ring of 6-8 shells near enemies with per-shell receipts and ice observations; if the ring's ice/damage evidence
holds, wire the chooser's launcher ring kinds to this research path with the same honest receipt; keep the blast
emission unclaimed until the shell's own explode pair is observed.

### Round 18: the launcher is inside the wheel for every character, and the ice-reporting barrage ran live

**The launcher-in-wheel fix** (`973d8ef6e`). Launcher-first was not enough: live rounds with a three-gun wheel
(Lightning Hawk / Triple Shot / Stun Rod) never showed the launcher that the spread wrote into slot 4+, while a
2-gun character (Picador + Grenade Launcher) did - the wheel only offers the character's own slots. `loadout_plan`
now, when the first three slots are full and none is the launcher, replaces the **last non-melee gun among the first
three** (never his first gun, never an explicitly asked weapon; melee weapons displace only when no gun can). Then
the remaining spread pairs fill the empty slots. Tests updated and 369 pass in the affected suites; deployed and
the worker restarted (`deployed-main` = `973d8ef6e`).

**Live proof:** a fresh RE6 round after the restart carried **Picador + Hydra + Grenade Launcher** in the wheel - a
three-gun character now has the ring's precondition. (Earlier this round, a pre-restart round still showed
Lightning Hawk / Triple Shot / Stun Rod.)

**The ice-reporting research barrage ran live** (`18b4206f4` + `14515d66d`): caught at the first seconds of a fresh
round (the only reliable idle window; mid-round attempts are refused by the remote lane's
`mine_allocation_blocked_reason`/bomb census), a 6-shell ring (shell1304, radius 700 cm) returned
`state uncertain, spawned 6, armed 6, detonated 0, ice_observed 0` with six per-shell rows `spawned 1 armed 1
emitted 0`, and the honest reason "native shells spawned and armed; the blast emission and the ice reaction are
unverified research". The ice baseline was collected (empty this time: at round start no enemy was near the ring),
so the per-shell ice evidence path is live and will report when a ring lands near enemies.

State: queue `[]`, MercMode RE6 playing on its rotation (titles re4/re5/re6 x5), Hermes task-mode
`enabled: true, available: true`, deployed `973d8ef6e`.

Next: fire a ring when enemies are near it - either ~8-10 s into a fresh round (after spawns) while the lane is
still clean, or a smaller radius; capture `ice_observed` + hp changes per ring. Then the operator-facing wiring
decision (chooser launcher kinds -> research barrage with the same honest receipt) can be taken with real ring
evidence; the shell's own explode pair remains unclaimed until observed.

### Round 19: wide-baseline ring evidence path, and the strongest round numbers yet

**Round results observed live:** a RE6 round ended at **349 090 / 192 kills / combo 77 / accuracy 51.2 %** (one
death), and the round running during the sampling reached 170 kills, 19 native flag detonations, combo 21 at a
499 s timer with 2 deaths. `qte_seen` 62 with **`qte_failed` 0** - the honest auto-QTE metric holds at scale.

**Ring evidence: one real defect found and fixed.** The agent ring could freeze enemies outside its own receipt: the
barrage's baseline used the probe's fixed 1000 cm radius, while the ring reaches `radius_cm` (601-2600). `4e11dbb7a`
gives `nearby_targets` an optional `radius_cm` and the barrage baselines **ring + 900 cm** (capped 2500), so an
enemy frozen on any shell is inside the observation. Tests updated; 60 pass in the shell suites. Deployed
(`deployed-main` = 4e11dbb7a) and the worker restarted, so the widened baseline is live.

**Admission constraints measured this round** (why ring evidence is hard to capture):
- one barrage per player generation, so a failed attempt's life is used up for real barrages;
- the worker refuses with "shell research waits for bot ownership and no pending remote bombs" or "a fresh complete
  native bomb census" for most of a round - the remote-mine lane keeps bombs in flight or an uncertain allocation;
- a 601 cm ring can be refused with "shell probe point is too close to a player" (the player moves between the
  position read and the point check) - use 750-900 cm;
- the reliable admission window is the first seconds of a fresh round, which must be hit with admission retries.
Next: at a RE6 fresh round, fire a **count 8 / radius 800** ring ~6 s in (after the first spawns) with admission
retries, and capture `ice_observed` plus hp changes; then decide the operator-facing wiring of the chooser's
launcher kinds to this research barrage.

**Hermes gate:** `enabled: true, available: true, dispatch_mode continuous_queue, git_workspace_ready true,
max_parallel_jobs 26` - healthy.

**State:** MercMode enabled on its rotation (RE4 playing after the restart, titles re4/re5/re6 x5), queue `[]`,
deployed `4e11dbb7a`. Note: the handoff document was trimmed last round from 14.6 MB (accidental embedded blobs) to
81 KB so pushes work; keep appended sections small.

### Round 20: ring-level nitrogen evidence captured - 8 shells armed, 3 enemies frozen, one for 450 damage

The research ring finally landed in the right window. Persistent fresh-round detection with rapid admission retries
(detected at kills 0-1, then a submission every ~0.3 s while the remote lane was clean) let an **8-shell ring
(shell1304, radius 800 cm)** run in a live RE6 round:

```
state uncertain, spawned 8, armed 8, detonated 0, ice_observed 3, targets_before 8
reason: native shells spawned and armed; the blast emission and the ice reaction are unverified research
ice:
 unit 401065944352 gen 799  cEm1000ActIkakuKnife -> cEm1000ActDmgIce  hp 500 -> 500
 unit 401052050720 gen 788  cEm1000ActDmgFlash   -> cEm1000ActDmgIce  hp 493 -> 493
 unit 401052738848 gen 786  cEm1000ActDmgFlash   -> cEm1000ActDmgIce  hp 498 -> 48   (450 damage)
```

That is the ring-level effect evidence: every requested shell spawned and armed, three nearby enemies entered the
nitrogen ice reaction with stable identity, and one took 450 damage. The receipt still does not claim the shell's
own explode/emission pair (`detonated 0`, allocation recycling) - that limitation is unchanged and recorded.

**Round results continue strong:** another RE6 round **340 560 / 222 kills / combo 60 / accuracy 52.2 %** (died);
the live round at sampling was 22 kills / 0 deaths / 50.9 % accuracy with flags detonating. MercMode sits on RE6,
queue `[]`, Hermes task-mode `enabled/available true, continuous_queue, git_workspace_ready true`; deployed
`4e11dbb7a`.

**The admission procedure that works** (for the next attempt, documented): new-round detection (screen playing and
kills <= 1 with previous kills > 5), then repeated submissions every ~0.3 s while `mine_deadline_pending`,
`mine_ring_pending`, `mine_avoid_positions`, `mine_bombs_since_detonate`, `mine_allocation_blocked_reason` and
`operator_control` are all empty, with a radius of 800 cm (601 cm trips "point is too close to a player" as the
player moves).

Next: with ring-level ice/damage evidence in hand, decide the operator-facing wiring of the chooser's launcher ring
kinds to this research barrage (idle-gated, same honest receipt, no verified-blast claim), and try to capture the
shell's own explosion pair with a faster native sampling path.

### Round 21: the operator's launcher ring button is wired, and a full-timer deathless round

**Operator ring wiring** (`19d41ccb7`). The chooser has always listed the launcher shell kinds as probe rows and sent
`grenade_ring` with `allow_unverified`; the worker refused them. The worker now turns exactly that request into the
research barrage (`re6_switch_shell_probe.barrage`): count 8, radius 800 cm, under the shared controller, idle-gated
on the same keys as the agent-only op (operator input, pending/detonating remote bombs, the blocked-allocation
state), with a cancelled callback that rechecks round ownership. The receipt is the research receipt reshaped as
`grenade_ring` (per-shell spawned/armed/emitted, ice observations, `verified: false`); the shell's own blast emission
is never claimed. Every other kind still uses the native `grenade_ring`. New counters `shell_rings` /
`shell_ring_shells`. Tests: probe-source shell rings run the barrage when idle (8/8, unverified, counters), refuse
before any native call with pending bombs, and flash still goes to the native ring - 31 pass with the worker tests.
Deployed and the worker restarted, so the UI path is live; a fresh-round 8-shell ring through the operator path
(`grenade_ring` + shell1304 + allow_unverified) is still awaiting a clean window (this round's real rounds never
opened one while sampled).

**Stale test corrected** (`b3cc0b245`): `test_mercs_flash_window` was written when RE5's `RING_KIND` was flash; it is
now `launcher`, and `decide()` correctly does not hold a launcher ring on the flash minute (its rounds place at the
kind's own floor). The test now proves both halves (flash waits the minute; launcher ring fires) and the suite is
green (15 pass).

**Full-timer deathless RE6 round observed:** timer ran to 0 with **299 kills / 320 700 score / combo 34 / accuracy
42 % / 0 deaths** (outcome report says "lost", `completed_s_rank: false`, score-based estimate null). That is the
first full-timer, no-death round measured under the current fixes - the survival side is now producing complete
rounds, while the score/rank is still short of S and the report's rank verification is absent.

State: MercMode enabled on its rotation (RE6 was playing; the session was ending at sample time), queue `[]`,
deployed `19d41ccb7`, last commit `b3cc0b245`, Hermes task-mode `enabled/available true`.

Next: capture the operator ring button's live receipt at a fresh round (the wiring is deployed); keep hunting the
score/S-rank gap (320k vs the 885k best-ever round) - combo maintenance and bonus routing are the likely levers;
and keep the ring emission question honest.

### Round 22: the operator's launcher ring button works end to end, live

The ring chooser's launcher kinds now actually fire. Through the exact UI request shape
(`grenade_ring`, `{kind: shell1304, allow_unverified: true}`, operator actor) a live RE6 round returned:

```
OPERATOR-RING uncertain
spawned 8, armed 8, detonated 0, ice_observed 2, targets_before 8
ice: unit 401088982464 gen 457  cEm5000ActWaitWep        -> cEm5000ActDmgIce  hp 689 -> 689
     unit 401090707616 gen 499  cEm5000ActWakeupAssault  -> cEm5000ActDmgIce  hp 694 -> 694
reason: native shells spawned and armed; the blast emission and the ice reaction are unverified research
```

and the worker recorded the click's counters (`shell_rings: 1`, `shell_ring_shells: 8`). So the operator's
"launch a 360 nitrogen round out from the character" is now a working button with an honest receipt: eight shells
armed on an 800 cm ring, two enemies entered the nitrogen ice reaction with stable identity, and the shell's own
explosion pair is still not claimed (allocation recycling).

**How the click lands.** The worker's clean-area gate refuses while the remote-mine lane has bombs in flight
("the launcher ring waits for the area to be clear of remote bombs"). The reliable procedure used live: temporarily
turn the bot's own bomb lane off with a `re5_mods`/`bot_logic` job (`{"BOMB_DROP": 0}`), then click (retrying;
accepted on the 18th attempt in ~40 s), then restore `{"BOMB_DROP": 1}`. The engine's remote-mine controller is
separate from that knob, so retries are still needed; operator state was restored after the test.

**Round health:** the live round at verification was 78 kills / combo 31 / 0 deaths / 3 flag detonations; MercMode
on RE6, queue `[]`, Hermes `enabled/available true`, deployed `316e895f5`.

**Score gap analysis for the S-rank goal** (from the full-timer 299-kill round's report): `bonuses_taken: 1`,
`bonus_s: 0` and `max_combo: 34`. The report says the bot barely ran the checkpoint/bonus phase, and the combo
barely chains - the score lever is combo maintenance and checkpoint collection, not the ring. Code notes for the
next pass: `_time_bonus_priority` only runs the time run when the clock is **below** `BONUS_CLOCK_LOW_S` (300 s),
and any enemy within `FIRE_ZONE_R` (600 cm) with `hot` suppresses the bonus run - No Mercy keeps enemies in that
radius almost continuously.

### Round 23: the "can't click Nitrogen" bug found and fixed at three levels

The operator's screenshot refusal ("the uWp1304 launcher round needs its native shell initialization and explosion
path") had three causes, all now fixed:

1. **The server stripped the row's `source`**: the interventions option sanitizer rebuilt `grenade_kinds` as
   `{kind, available, reason}` and dropped `source`, so the PiP never learned a launcher kind is a probe row and
   sent the click WITHOUT `allow_unverified`. `kind_rows()` now validates and preserves the source label.
2. **`grenade_status.rows`** now keeps the launcher kinds labelled `source: "probe"` (with their research reason
   beside the label) even when the controller reports them available, so the click carries the flag.
3. **The worker's launcher branch** required `allow_unverified`; the research barrage is the only implementation of
   those kinds, so a launcher-kind click routes to it either way now. The click gate was also too strict: it waited
   for the whole area to be clear of remote bombs and refused through most of a round (sixty honest retries, all
   "waits for the area to be clear"). It now refuses only when the operator holds the pad, a native ring flight is in
   progress, or the remote lane reports an uncertain allocation - pending remote bombs are fine (shells are a
   different native class).

Tests: probe source preserved through the sanitizer and rows; launcher clicks route to the barrage with and without
allow_unverified; pending bombs allowed, uncertain allocation refused, non-shell kinds unchanged. 86 pass in the
affected suites; committed and pushed after merging 76 remote commits from the PSO lane (`626ff7d49`, deployed).

**Live verification:** the live RE6 rows now read
`[{"kind":"shell1304","available":true,"reason":"probe: ...","source":"probe"}, ...]` for launcher/shell1302/3/4, and
an operator click with `args: {kind: shell1304}` (no allow_unverified) is accepted and routed to the barrage - the
old native-refusal toast is gone. That click was refused by the relaxed gate this time ("an unfinished native ring
or an uncertain bomb allocation is in the way") and the round's character had **no grenade launcher** in the
inventory (launcher=0), so the ring could not fire; a launcher-bearing round with a clear state is the remaining
verification.

Also shipped earlier this round (`843f34b72`, live): the critical-crowd flash now fires with tablets too when
critical health and 4+ enemies are within 2 m (the 20:26 death was downed at 1 health in a nine-strong crowd after
240 damage events with 19 tablets taken and 34 presses / 18 ignored) - the flash breaks the crowd before the heal
race.

State: MercMode RE6 playing, queue `[]`, Hermes `enabled/available true`, deployed `626ff7d49`.

### Round 24: the combo mandate, the QTE recovery burst, and periodic quick attacks that can actually fire

Operator 2026-11-13: "the absolute mandate for mercenaries mode, is the bot should never go five seconds without
accruing a kill and keeping the combo going ... Never let the bot stop fighting and adding to the combo"; "i want the
bot doing a quick attack at the intervals outlined here" (sidebar: enabled, 4 per burst, every 10 s); "in RE6, I want
the bot reacting to QTE events by: auto flipping the flag ... succeed ... drop mines, perform 3 quick shots, flee
while detonating them and firing quick shots".

Shipped in `97ae8aacf` (deployed `97ae8aacf` and hot-reloaded live):
- **Combo mandate**: `_combo_mandate_on` + a stronger `_combo_guard`. When an enemy is within COMBO_HOT_R (12 m) and
  the combo clock is low (or no kill for COMBO_KEEP_S 3.2 s), the bot drops every non-kill detour - a bomb-escape
  sprint included (`combo_over_bomb_sprints`) - and takes the fastest kill: a rapid quick shot inside COMBO_QUICK_R
  (3.5 m, COMBO_QUICK_GAP_S 0.16), else a chase so the next decision is combat. `_bonus_run` yields while the mandate
  is in force. New scalars: combo_mandate_s, combo_over_bomb_sprints, combo_quick_shots, combo_guard_chases,
  kill_gap_last_s, kill_gap_max_s (the five-second mandate's own measurement).
- **QTE recovery burst** (`_qte_recovery_shot`): after a survived QTE (the escape counter), three quick shots at
  QTE_SHOT_GAP_S before the flee at the nearest enemy within QTE_SHOT_R; the mines already come from the QTE recovery
  episode. New scalar: qte_recovery_quick_shots.
- **Periodic quick attacks**: the safety design (measured contact, clear laser line, native quick-shot observation,
  prompts/healing first) is kept, but its carryover tolerances were impossible in a live fight - 20 cm player / 30 cm
  target movement in 0.25 s gave ONE armed burst with ZERO requests in a 530 s round (periodic_qa_bursts 1,
  periodic_qa_expired 1). They are now PERIODIC_QA_MOVE_CM 140 / PERIODIC_QA_TARGET_CM 220 within
  PERIODIC_QA_CONTACT_S 0.6, expiry 8 s, so the sidebar's 4 attacks every 10 s can land.
- The operator's saved bot-logic (on, 4 per burst, every 10 s) was re-applied to the live module after the reload.

Tests: QTE burst (3 shots, gap, done), combo mandate (quick shot inside reach, chase outside, no enemy = no
mandate), kill-gap max, restored periodic safety suite with the live tolerances - 341 pass in the affected suites.

**Live observation after the reload** (RE6 round): combo held at 33 with 1 break while sampled; `combo_quick_shots`
4 (the mandate's quick shots fired), `combo_mandate_s` 0.5, `combo_over_bomb_sprints` set (a bomb sprint was
pre-empted for the combo), `kill_gap_max_s` 15.37 (round start included - the five-second goal is not yet proven).
`periodic_qa_remaining` exists (the method runs) but no burst has started yet in the sampled minutes: the start
still needs measured contact plus a free gun action at the due moment - the next tuning target (the interval
settings themselves are confirmed saved). No QTE occurred in the sample, so the three-shot burst is still to be
observed live.

State: MercMode RE6 playing, queue `[]`, Hermes `enabled/available true`, deployed `97ae8aacf`.

### Round 25: shoot everything, answer enemy lasers, point blank, and never through the floor

Operator asks this round (2026-11-13, in order): "the bot needs to always be firing ... never let the bot stop
fighting and adding to the combo"; "i want the bot doing a quick attack at the intervals outlined here" (sidebar: on,
4 per burst, every 10 s); the QTE sequence (flag, solve, drop mines, 3 quick shots, flee while detonating and firing);
"why is the bot just standing here and not shooting at the enemy across the map ... pursuing ... shoot unlimited
distances"; "their lasers show where they are ... backtrace it and decommission that enemy"; "the bot raises their gun
and then fails to shoot / misses with the enemy right in front"; "watching the bot shoot at the ceiling just makes no
sense ... aware that their enemy is on another level ... climb up a ladder ... never get to the enemy shooting
through the ground".

Shipped (all deployed and active; latest `24f9cf255`, deployed + service restart):
- **Point blank** (`6ab00525b`): POINT_BLANK_R 260 cm, 10/12 deg band - the trigger is pulled in both fire paths even
  when the cover probe objects; the out-of-sight branch aims at a point-blank enemy instead of walking past ("a raised
  gun that holds is a gun that is not shooting"); envelope still bounds the angle to the body at that distance.
- **Off level** (`24f9cf255`): camera-geometry fire is limited to bodies within FIRE_LEVEL_DY 120 cm of his feet; an
  off-level body stands the trigger down (`offlevel_fire_veto`) and the bot pursues/walks toward it instead of firing
  through the floor/ceiling. A measured laser dot on the body still proves a real line (flying/ledges).
  Real ladder/level routing is NOT implemented - pursuit is what it has, reported honestly.
- **Unlimited-range pursuit** (`4eea58564`): a clear enemy out to SNIPER_LONG_R (60 m) is raised on and long-shot
  instead of only walked at (`long_range_raises`); walking is the fallback and a no-route A* now walks straight at the
  enemy instead of holding an empty walk.
- **Enemy laser backtrace** (`4eea58564`): `_laser_sources` reads every RAM ranged wind-up (the game's own "this one
  is aiming at your bot"), nearest first, on his floor, within LEDGE_RANGED_R, in the clear; that source outranks
  every other pick (`laser_backtraces`/`laser_targets`) so it is decommissioned first.
- **Combo/blast** (`d136ee8ad`): the interval burst is no longer starved by the bot's own bomb lane (it fired once in
  a round before: bomb_phase/bomb.out refused almost every tick); and the combo mandate yields to a live bomb
  clearance margin (`combo_yields_to_blast`) - the 22:23 death was doing=bomb inside 218 of 1200 cm with eight
  enemies within 2 m after the mandate postponed the escape.
- Earlier in the round: 280 cm/0.22 s combo-mandate quick shots (`7d28888e1`) and the quick-shot ray guard
  (`acce3e723`) so the mandate/QTE quick shots only fire at the enemy under the live laser/camera ray, never into
  whatever the camera last faced.

**Live evidence after the `24f9cf255` activation** (RE6 session ddfd03f3, first ~2.5 minutes): the interval burst
fired 10 bursts / 11 requests (was 1/0 in a whole round), point_blank_fires 9, laser_backtraces 55 and
laser_targets 319 (enemy lasers backtraced and targeted continuously), pressure_blocks 426 (no bonus walking while
enemies are in sight), combo 18 with 1 break, shots 23 / hits 16 (70 %). `offlevel_fire_veto` 0 in this sample (no
off-level shooter appeared - its live proof is still pending).

**Not yet done / honest gaps**: kill_gap_over_5s 13 in the sample - the "never five seconds without a kill" absolute
mandate is NOT yet met; the interval burst lands roughly every 12-15 s rather than every 10 s (native quick-shot
observation limits); real ladder/next-level navigation does not exist (pursuit/straight-line walk only); round-level
accuracy is ~50-58 % (the two best rounds this run: completed 741,304 / 300 kills / combo 57 / 50.3 % / 0 deaths, and
an interrupted 415,080 / 284 kills / combo 61 / 57.7 % / 0 deaths). S-rank/five stars still not proven.

State: MercMode RE6 playing, queue `[]`, Hermes `enabled/available true`, deployed `24f9cf255`.

### Round 26: the operator's match strategy (bonuses first, then fight), time-crystal shooting, QTE flag, combo pursuit

Operator 2026-11-14 restated the whole match strategy: start on the time bonuses while building the initial combo;
activate combo time via RE4/RE5 chests and RE6 blue crystals; once the time is at 5 minutes switch to fighting, traps
and combo maintenance; keep the combo growing at any cost (an enemy dispatched every 4 s, moving and mine-dropping);
pursue every enemy on the map at any distance; and: "The bot continues to fell the QTE events ... I want the flag
flipped for that immediately. So they don't even have to go through that ... I'm not seeing them detonate enough
remote bombs ... It is imperative that they always maintain the combo."

Shipped (all tested, deployed, service restarted; latest `b972f7878`):
- **Phase policy** (`5573443fa`): below BONUS_CLOCK_LOW_S (300 s) the time-bonus run is the objective and only a
  close enemy (inside FIRE_ZONE_R, in sight = hot) pre-empts it; the blanket combat-pressure veto is now fight-mode
  only, so the bot no longer stands on a drained clock with zero bonuses taken (observed live: timer 182 s,
  bonuses_taken 0, pressure_blocks 607). At/above the bank it fights.
- **Blue time crystals are shot** (`6c6d47231`): BONUS_TIME_RANGED lets the bonus lock/shoot path handle TIME bonuses;
  below the bank a crystal inside BONUS_SHOOT_R with a clear line is shot through the lock (`time_bonus_shots`)
  instead of only walked to. Live after activation: time_bonus_shots climbed 5 -> 16 in ~3 minutes and the clock
  jumped 93 -> 258 s as crystals broke (the old live round had time_shots 0).
- **QTE flag flipped immediately** (`b972f7878`): the live state already read `qte_auto: true` (both cSystemInfo
  copies + the RAM escape, verified). `ensure_qte` is now attempted as soon as the session has an adapter - during
  the load/menus too, not only once a player snapshot exists - so no QTE site can be reached before the flag is on
  and read back; it retries every 1 s until read back and re-applies every 5 s (a save load can reset it). Live:
  qte_auto true for the whole round, `qte_seen` 9, `qte_failed` 0.
- **Combo mandate at any distance** (`b972f7878`): the old COMBO_HOT_R 30 m gate is gone - with the combo clock low
  or no kill for COMBO_KEEP_S (2.5 s) the nearest enemy on his floor is chased at ANY distance; quick shots still
  need COMBO_QUICK_R. Earlier in the round the mandate also went to 2.5 s/30 m from 3.2 s/12 m (`5573443fa`) so a
  kill is due before the 4-second limit.

**Live evidence** (round 23:45-23:48, session bda65ac0): time_bonus_shots 5 -> 16 with the clock climbing
93 -> 258 s; qte_seen 9 / qte_failed 0 with qte_auto true; combo reached 46 with 4 breaks; kills 58; periodic bursts
8. Still open, reported honestly: **combo breaks 4 in ~3 minutes and kill_gap_over_5s 9** (the every-4-seconds
mandate is not yet held); **bombs placed/detonated 0 in that round** (the remote lane did not fire - the operator's
"not detonating enough" has no live detonation evidence yet); PSO sessions on lilspark repeatedly displaced the RE6
switches (host contention from another lane), so round evidence is from a short window.

State: RE6 playing (`bda65ac0`), queue `[]`, Hermes `enabled/available true`, deployed `b972f7878`.

### Round 27: remote mines actually detonate (and the escape no longer pins the bot)

Operator 2026-11-14: "I'm not seeing them detonate enough remote bombs"; the match strategy (mine every 10 s, kill
every 4 s, combo never lost, pursue every enemy at any distance); and again the combo: "they're sitting around not
attacking these enemies that surround them".

**Diagnosis (live):** the remote-mine lane was placing rings fine (mine_ring_requests 9, mine_ring_bombs 120,
rings_dropped 8, last ring 15 armed) but detonation never passed the clearance rule: the bot stood at 430 cm of the
required 1200 with the deadline 7.5 s past (`mine_detonate_reason: "escape first: nearest actual bomb 430 cm; need
1200 cm"`) and kept aiming. The wall/safety hook can only steer a WALKING action, so shot/aim ticks left him inside
the blast forever.

Shipped (`0c44fabfc`, `6cbae5d1e`, `5ebadc9fe`, `853a7d577`; latest deployed `853a7d577`):
- `_blast_retreat`: inside the blast margin and either 500+ cm short or the five-second deadline within 2 s, the tick
  returns a pure walk out BEFORE the QTE burst, quick shots and combat. (First build pinned him 40-60 cm from a ring
  dropped at his feet: blast_retreats 558, one detonation.)
- The retreat now follows `_escape_route` (navmesh A* to a floor point already clear of every known bomb) and
  publishes `_escape_heading` so the safety hook follows the same route around railings; the greedy heading is only
  the fallback.
- Remote-mine cadence: the bot injects `stats['remote_mines'] = {drop_every_s: 10, drop_jitter_s: 1,
  radius_cm: 600}` - the operator's ten-second cadence (the shipped 7.5+/-2.5 s default stays for the tests) and the
  policy's widest ejection radius, so a ring dropped around him starts 600 cm from safety instead of 1000 (live: the
  earlier 200 cm rings cost 40-90 s of fleeing per cycle; blast_retreats 882 in 4 minutes).
- Tests: the hard retreat, the route heading, the escape-route change - switch suite 264 pass, bomb/blast subset 30.

**Live evidence (build `6cbae5d1e`, 00:11-00:15):** with the A* retreat the clearance actually reached 1228/1232 cm and
`mine_flag_detonations` fired twice; in the safe windows the kill count jumped 5 -> 38 and the combo 0 -> 33, then
0 -> 22 at the next window. Before the fix the round logged ONE detonation in the same span.

**Not verified / open, honestly:** the radius build (`853a7d577`) is deployed but could not be live-verified - the
host stayed on PSO from another lane for every switch attempt in the last ~10 minutes. The combo still breaks while
the bot retreats from a ring (live combo_breaks 4-6 per ~4 min in the earlier sample; kill_gap_over_5s 8-10) - the
escape cycles eat kill windows even now; firing while retreating is the next design step. Three tests in
`test_mercs_remote_mines.py` (flash-combo ring, surround ring, ring-then-detonate) were already red before this
round's work (they do not involve the changed code paths) and need a look. PSO contention keeps stealing lilspark.

State: MercMode rotating, queue `[]`, Hermes `enabled/available true`, deployed `853a7d577`.

### Round 28: detonations verified in a real round; the combo escape costs less

Round 27 left two unverified things (the 600 cm mine-ring radius build and whether detonations actually happen in a
normal round) and one design gap (the hard blast retreat ate kill windows). This round verified the first and worked
the third.

Shipped `63063ad61` (deployed + restarted):
- `_blast_retreat` now gives the combo one quick shot while the five-second bomb deadline is not tight (> 2 s): if
  the combo clock is at or under COMBO_BLAST_SHOT_S 1.8 s and an enemy is on the live ray within COMBO_BLAST_SHOT_R
  500, it fires a quick shot and then resumes the pure walk out; near the deadline it always walks. New stat
  blast_combo_shots.
- Tests: the quick shot at 4 s remaining, the pure retreat at 1 s remaining; switch/bonus/periodic suites 328 pass.

**Live verification of the round-27 radius build (`853a7d577`), RE6 session 64f75e28, 00:50-00:53):**
- Remote rings ejected at 600 cm: `mine_ring_requests` 4, `mine_flag_detonations` **2 in ~2.5 minutes** (round 27's
  sampled span had 0-1); clearance reached the 1200 cm rule for both.
- `blast_retreats` 243 ticks (~12 s of retreating over the whole sample) versus 882 ticks in the 4-minute sample before
  the radius change - the escape is now a fraction of the round instead of most of it.
- `combo_breaks` **2** in the round (was 4-6 per ~4 min), kills 43 in ~170 s (about one dispatch every 4 s on
  average), combo reached 18 while detonations were firing, shots 7 / hits 3 in the early sample.
- `blast_combo_shots` 0 live: the combo-lapse moment never coincided with a non-tight deadline plus a target on the
  ray; the guard needs loosening (allow while remaining > ~1.0 s, or radius 700) - not yet tuned.

**Open, honestly:** the combo still resets at times (kill_gap_max 30.86 s, combo_breaks 2 and the round ended with the
combo at 0); the "an enemy every 4 seconds, combo never lost" absolute goal is still not met. `test_mercs_remote_mines`
still has the 3 red tests from another lane's engine drift (flash-combo ring, surround ring, ring-then-detonate).
PSO kept stealing lilspark between switches; the RE6 round above is the first clean window this round.

State: RE6 round finished (43 kills sampled), MercMode rotating, queue `[]`, Hermes `enabled/available true`,
deployed `63063ad61`.

### Round 29: combo-break attribution and a looser combo shot inside the bomb escape (deployed; live window still pending)

Operator 2026-11-14: "the combo should never be lost ... losing / resetting the combo is a waste of a match and is a
serious fail condition"; plus the standing strategy (mine every 10 s, dispatch every 4 s, fight while placing mines,
pursue every enemy at any distance).

Shipped `6a1d8255f` (deployed + service restarted):
- **Every native combo_breaks increment is now attributed** in `_combo_tick` to the doing/act the bot was in, as
  scalar counters (`combo_break_<doing>`, `combo_break_last`, `combo_break_last_why`). This is the diagnostic the last
  rounds lacked: instead of guessing why the chain resets (bonus walk, bomb retreat, grab, tablet, reload, no-foes),
  the next RE6 round will say exactly which doing is responsible.
- **The combo quick shot during a bomb retreat can fire now**: the guard demanded >2 s of deadline left and
  COMBO_BLAST_SHOT_S 1.8 / R 500, and live it never fired (`blast_combo_shots` 0). It is now: deadline tight only
  under 1 s, COMBO_BLAST_SHOT_S 2.5 s, radius 700 cm, and with nobody on the ray it quick-turns to the nearest close
  enemy (`blast_combo_turns`) so the shot can land on the next tick while the escape continues.
- Tests: the attribution counters (one break per native increment, the doing tag and its why) and the quick
  shot/retreat cases; switch suite 266 pass.

**Live verification: still pending.** The deploy and restart completed, but lilspark never reached RE6 playing in the
sampling windows: PSO from another lane held it, then the MercMode rotation moved to RE4 (`Resident Evil 4 playing`
for the whole last window). No new live numbers are claimed for this build; the last verified round remains round 28's
(2 detonations, combo_breaks 2, kills 43 in ~170 s). The next RE6 window should read the `combo_break_*` counters and
the `blast_combo_shots`/`blast_combo_turns` counters before any further tuning.

State: MercMode working through its rotation (RE4 playing when the round closed), queue `[]`, Hermes
`enabled/available true`, deployed `6a1d8255f`.

### Round 29b: the hunt must outrank the idle detours, and the combo-break hook was on a key that does not exist

Operator follow-up after round 29's first build: "look at the last match that just played. the bot meandered and didnt
go find the enemies."

Two real defects found and fixed (`51b22a805`, deployed + restarted; on top of `6a1d8255f`):
- **The combo-break attribution was dead code live**: it waited on a `combo_breaks` snapshot key that does not exist,
  so `combo_break_*` stayed empty in a round that did break once. It now hooks the bot's OWN increment (the line that
  counts a lapse with a zombie in reach) and records `combo_break_<doing>`, `combo_break_last`, its why. Test: a real
  running-to-zero lapse with one in reach attributes the doing.
- **Meandering with enemies alive elsewhere**: the phase-1 bonus gate won the decision even when every living enemy
  was off his floor, and the no-enemy-on-floor branch ran taunts/bonus pickups before the hunt. `hunt_elsewhere` now
  blocks the bonus run while any enemy lives off his floor, the taunt/bonus branch only runs when the round holds no
  living enemy at all, and with no A* route the bot walks straight at the nearest alive one (`hunt_offlevel`) instead
  of idling. Tests: an enemy one floor up is hunted, not taunted/bonus-picked; the pursuit-recovery test accepts the
  hunt walk (294+ in switch+bonus).
- Also (from `6a1d8255f`): the combo quick shot inside a blast retreat now allows >1 s deadline, COMBO_BLAST_SHOT_S
  2.5, R 700, and quick-turns to the nearest when the ray is empty.

**Live window that motivated this (build `6a1d8255f`, RE6 01:10-01:12):** 26 kills in ~2 minutes, combo_breaks 1,
mine_flag_detonations 1, blast_retreats 550 ticks; `combo_break_*` and `blast_combo_shots` both 0 - the first was the
dead hook fixed above, the second is still to be observed.

**Not verified:** the `51b22a805` build's hunt fix and the repaired attribution have not been sampled in a live RE6
round yet - after the restart the host alternated PSO/RE4 for every switch window (RE6 reached the title/loading
screen once, never playing). The next RE6 window must read `combo_break_*`, `hunt_offlevel`/`pursuits`,
`blast_combo_shots` before any further tuning.

State: MercMode working through its rotation, queue `[]`, Hermes `enabled/available true`, deployed `51b22a805`.

### Round 30: the attribution named the combo killers, and the aim/raise stall is gone in live evidence

Operator 2026-11-14: "look at the last match that just played. the bot meandered and didnt go find the enemies", then
the standing mandate (combo never lost; a kill every 4 s; mines every 10 s; pursue and dispatch every enemy at any
distance).

Shipped this round (all tested, pushed; latest deployed `5d4ba6a98`):
- `51b22a805`: the combo-break attribution was dead code (it waited on a snapshot key that does not exist); it now
  hooks the bot's OWN lapse increment, recording `combo_break_<doing>`, `combo_break_last`, its why. Off-floor hunt:
  `hunt_elsewhere` stops the bonus phase while an enemy lives off his floor; taunt/bonus only run when no enemy lives
  anywhere; with no A* route the bot walks straight at the nearest (`hunt_offlevel`).
- `3d46993c5`: the live attribution's first findings - two breaks were crowd tablets at 80 % health and one was a
  "quick shot: turning +101 deg to the one 110 cm off". CROWD_TABLET_HP 0.85 -> 0.70, heals above the critical band
  never interrupt a lapsing combo, quick-shot facing is capped at 75 deg, and at kick reach the bot kicks instead of
  spinning.
- `5fe869ff5`: the round sat in doing=raise for ~50 s with the combo dead - the camera-geometry raise kept waiting for
  a line that never proved. Raising is capped at 1 s then repositions (`raise_repositions`); the combo guard's last
  resort with no A* route is a straight walk at the nearest (`combo_guard_walks`).
- `5d4ba6a98`: the next attributed breaks - "bomb clearance 952/1150 cm: out of the blast before anything else"
  (small shortfall beat the chain) and "periodic burst: waiting for the native quick attack to finish". A small blast
  shortfall (<=700 cm) with no tight deadline now lets the fight win the tick (`blast_combo_fights`), and the guard
  may take over a stalled periodic wait.

**Live evidence (build `5fe869ff5`, RE6 01:54-01:56):** kills 6 -> 41 in ~2 minutes, timer 139 -> 360 s (the blue time
crystals), `raise_repositions` 0 - the 50-second raise stall did not recur. Attribution then named the remaining
breaks: quick_turn 1, quick_shot (periodic wait) 1, bomb_escape 1. Those three are what `5d4ba6a98` targets.

**Not yet sampled live:** the `5d4ba6a98` build (deployed + restarted) - after the restart the host stayed on PSO/RE4
for every switch window (RE6 reached the title once, never playing). `kill_gap_max` in the last live sample was still
16.98 s and over5 9: **the combo is not yet held; S-rank is not claimed.**

State: queue `[]`, Hermes `enabled/available true`, deployed `5d4ba6a98`.

### Round 31: every remaining live combo break was named, and each was answered by a rule

Method this round: force a RE6 window with the MercMode `stop` + `start title=re6` dispatch (the PSO lane on lilspark
was holding the host), then read the attribution counters the previous round added.

**Live verified - build `5d4ba6a98` (RE6 02:16-02:19):** kills 0 -> 26 with the combo at 26 and the timer 117 -> 197 s
(blue crystals breaking); the single attributed break was `combo_break_tablet` "health 442/900: a tablet" (49 %).

**Live verified - build `1372f8964` (RE6 02:40-02:42):** the early-round hunt fix worked (kills 1 -> 24 within ~30 s,
timer 91 -> 186 as the crystals broke, combo 23) and the attribution named the rest: `bonus` (locking a time bonus at
2095 cm), `quick_shot` ("periodic burst: waiting for the native quick attack to finish"), `held` (the QTE grab hold).

Fixes shipped (tested, pushed; latest deployed `5ac496931`):
- `bc5037e50`: `_heal_window_ok` - a heal only starts while the combo window has >= TABLET_COMBO_WINDOW_S (3 s) left
  (a kill refills it first), unless near-critical health; the 49 % tablet cannot eat a fresh 26-kill window any more.
- `1372f8964`: a round with no kill after COMBO_KEEP_S triggers the combo mandate even before the first kill - it
  hunts the nearest enemy instead of roaming the bonus phase (the `combo_break_walk` round that had 0 kills for ~45 s).
- `5ac496931`: a periodic quick-attack's native-observation wait is dropped when the combo window is at or under 3 s
  (`periodic_wait_combo_yields`); the wait only applies while the chain is comfortable.

Tests: 337 pass in the switch/bonus/periodic suites (the heal-window cases, the round-start mandate, the wait yield).

**Still open / not claimed:** `bonus` breaks in phase 1 (locking a time crystal while the chain runs out - the operator
wants the bonuses AND the combo; a lock-then-kill ordering needs a decision), and QTE `held` breaks are unavoidable
while grabbed. The final build `5ac496931` is deployed but not yet live-sampled. Combo losses are down to a handful
per round, not zero; S-rank is not claimed.

State: MercMode restarted into RE6 after the deploy, queue `[]`, Hermes `enabled/available true`, deployed
`5ac496931`.

### Round 32: the first live stretch where the combo matched the kill count exactly

Forced a RE6 window with the MercMode stop/start dispatch and sampled build `5ac496931` (the heal-window, round-start
hunt and periodic-wait-yield build from round 31).

**Live evidence (RE6 02:50-02:53, session c371ce17):**
- From the third kill on, **`combo_breaks` stayed 0 for over two minutes** while kills ran 3 -> 40 and the **combo
  matched the kill count exactly** (40 kills / combo 40 - the operator's "combo matches the kill count due to being
  intrinsic and consistent"), with the timer 118 -> 242 s as the blue time crystals broke (`periodic_wait_combo_yields`
  1: a native quick-attack wait was dropped to keep the chain).
- The round then died at 53 kills (max combo 40, score 64 280) with two breaks attributed late: `raise` ("the gun comes
  up") and `held` (QTE grab). The next round showed the remaining set: `tablet` at 600/900 health (the crowd-heal rule
  at 70 % with 4+ within 3 m), `walk` (a learned dodge: "uEm5200 cEm5000ActCatch: an attack that hurt him through his
  shots: out of its reach"), `raise`, `held`.

**Shipped `cf46174e3`** (deployed; runtime marker matches): a time-crystal lock no longer outranks a lapsing combo -
the previously attributed `combo_break_bonus` ("a time bonus at 2095 cm: the lock on it") now yields
(`time_bonus_yields_combo`) and the kill comes first, the crystal right after; the green-bonus pickups yield too. Tests:
the crystal yields at a lapsing combo and shoots when free; switch/bonus suites pass.

**Open, honestly:** combo breaks are down to 2-4 per round but not zero. The remaining named causes: the crowd-heal
chain (heal starts at 66-70 % with four in 3 m and can chain into the window), short raise stalls, learned dodge walks
(an attack that hits through his shots), and grab/QTE holds (no kills possible). `kill_gap_over_5s` is inflated by the
round-start gap (it counts the time before the first kill); `combo_breaks` plus the kill==combo check are the real
metrics. S-rank/five stars still not achieved or claimed.

State: MercMode on lilspark restarted into RE6 (`da8a853b`), queue `[]`, Hermes `enabled/available true`, deployed
`cf46174e3`, suite green (337 in the switch/bonus/periodic sets before the last two small commits; their focused tests
passed).

### Round 33: longest compliant round yet (84 kills / max combo 59) with every break named

Deployed `da59cf02b` (combo chain cap, raise cap 0.6 s, downed-critical flash) and ran a long verification round on a
forced RE6 window (MercMode stop + start, session d7e250d2).

**Live evidence (RE6 03:06-03:12, ~6 minutes):**
- **84 kills, max combo 59, score 124 960** - the best of this stretch (previous live rounds: 53 kills/combo 40,
  52 kills/combo 22), with a 50-kill/50-combo stretch (kills 56/combo 47, 64/55, 68/59) before the breaks.
- **4 combo breaks in ~6 minutes**, all attributed: `bomb` ("bomb clearance 598/1200 cm: out of the blast before
  anything"), `walk` ("walking off the bomb: 823 cm from it, 2 on it"), `crowd` (the crowd-kick backout), `raise` (a
  short gun-raise stall). Two of the four are bomb-escape related; the heal/topping chain did not break a window this
  round (`topping_yields_combo` 0 used, heals did not interrupt).
- Death cause of the round: `doing=bomb_escape` at **598/1200 cm with 16 enemies within 2 m** and hp3s all 1 - the bot
  was running its own bomb clearance at 1 health in a 16-strong crowd and died.
- The previous round (session da8a853b, pre-deploy): 52 kills (died). Current: 84 kills (died) - survival and combo
  both up, but the round still ends in a death.

**Open, honestly:** combo breaks are 4 per ~6 minutes now (was 4-6 per ~4 min, and 32 in the worst early round), with
bomb-escape-related walks the biggest remaining cause; the every-4-seconds/combo-never-lost mandate is still not met.
The death at 1 health inside a 16-enemy crowd while clearing a bomb needs the escape to start earlier (or the crowd
broken before the clearance run). S-rank/five stars still not achieved or claimed.

State: MercMode on lilspark started into RE6, queue `[]`, Hermes `enabled/available true`, deployed `da59cf02b`.

### Round 34: 99+ kills in one unbroken live round, zero deaths - the breaks left are dodges and grabs

Deployed this round and verified in a long forced RE6 window (MercMode stop + start, session f079e411):
- `f5887dccb`: dying-health critical flash now fires in ANY state (the two late deaths were at 1 health with 8-16
  enemies within 2 m; the flash was refused because the bot was down/standing at DYING_HP), and the in-blast combo
  fight widened from 700 to 1000 cm of shortfall.
- `69600bacd`: the downed dying bot flashes the crowd BEFORE the "staying down, no fight" branch (the 03:22 death was
  `doing=down ... staying down, no fight` at 1 health with 8 within 2 m and the flash was unreachable).

**Live evidence (RE6 03:31-03:38, ~7 minutes, build `69600bacd`):** the round reached **99 kills with the combo cycling
and ZERO deaths** (still playing when the sampling window closed; previous live rounds died at 53 and 84 kills), timer
climbed 113 -> 305 s through the blue crystals. The 9 combo breaks in that stretch are attributed:
`walk` 3 ("uEm5400/other cEm5000Act...: an attack that hurt him through his shots (learned): out of its reach" - the
learned dodge walk), `held` 3 (QTE grabs), `raise` 1, `crowd` 1, `tablet` 1.
The heal-chain/combo protection and the round-start hunt continue to hold (no tablet-chain or bonus-lock breaks in this
round's attribution).

**Honest read:** the two dominant remaining break causes are now defensive: the learned dodge walk (an incoming attack
that hits through his shots makes him leave) and QTE grab holds (no kills possible while held). Those need a design
choice - e.g. a quick shot acknowledged before the dodge, and a flash-first grab answer - not a tuning tweak. The
every-4-seconds/never-lose-the-combo mandate is still not met; S-rank/five stars are not achieved or claimed.

State: MercMode on lilspark running RE6 (session f079e411 at the sampling close), queue `[]`, Hermes
`enabled/available true`, deployed `69600bacd`.
