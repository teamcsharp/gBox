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
misses and62 results outside61cm floor tolerance, some3ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œ11m below the player.
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

### The "Mine ring ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â· 5 ft" button on RE6 is fixed in the client (no restart)

The root cause was not a missing backend: RE6 already exposes the interventions op **`remote_mines`** ->
`re6_switch_native.bomb_ring_now` / `Controller.drop_bomb_ring` (armed native remote bombs ejected from the body,
no throw/animation, placements recorded for the deadline controller). What never existed was any UI control that
sent it; the topbar icon the operator pressed was the RE5 proximity-mine lane, which RE6 does not advertise.

- `95c958138` adds a **"Remote mine ring ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â· 5 ft"** topbar control, shown only where the worker advertises
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