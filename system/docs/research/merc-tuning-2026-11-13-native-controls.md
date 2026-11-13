# Mercenaries tuning evidence, 2026-11-13

User constraints: no infinite health; randomized weapons with emphasis on shotguns and magnums; sustained aimed fire; grenade pressure; each completed attempt, including a death, counts toward five per title. Preserve time-bonus runs, safe bomb escapes, and per-round navigation/death evidence. S/five-star on every run remains an unmet goal.

## RE5 grenade stall

Recorded sessions `5f64b657540f4144-cb6248761531481d` and `5f64b657540f4144-760c2407505d4f7c` stopped making progress after one/zero kills. The latter reported native mailbox state 2 at spawn offset `0x118e820`, then lost its player and was recovered as hung. This proves an entered, unacknowledged call; it alone does not identify the engine instruction that stalled.

Code inspection found two independent defects in the parameterized grenade wrappers:

- `_spawn` passed a relative DTI offset to a native pointer argument. It now adds the verified module base.
- The explosion wrapper overwrote its item argument in x5 with a vtable load and reused caller-saved x6 after CONFIGURE. It now preserves item in w7 until the call and stores unit/update on its stack across CONFIGURE. The image remains 248 bytes and fits the existing reservation.

Unicorn executes the patched explosion wrapper with a CONFIGURE stub that destroys all caller-saved registers, at two module bases and for flash/hand item arguments. Previously installed defective class images are refused; a fresh emulator is required. Live validation remains required; hand/incendiary rings are still experimental.

## RE4 weapons and round evidence

Session `da0243a48c79458c-c2feb1ad10b14afa` verified Striker 45, Mine Thrower 54, then Striker 45 against the actual weapon object. A subsequent Broken Butterfly request became unresolved; the original failure was overwritten by generic retries, and the next life could not replace its restored native handgun. Commit `8831503f` preserves first-failure stage/life/item and permits reconciliation only with a quiescent mailbox and coherent actual/inventory/class identity. Same-life completion must match the original requested weapon; otherwise only a changed native player life can retire it. Pending native calls are never replayed.

Object item zero now means unknown for the control status, rather than rejecting the whole capability report. A death/results RAM state cannot start a new phantom round on a dark frame. Each RE4 round now publishes an evidence identity and closure marker.

## RE4 mine darts

Native pool type `0x5f`, subtypes 0/1, identifies Mine Thrower darts; rocket subtypes 2/3 are excluded. The old `0x2e5050` mine candidate is an egg path and is no longer callable as a mine probe. The dart explosion routine is `0x1b4d20`.

Automatic fuse: three seconds from first observed spawn, not a claimed exact native spawn time. A `detonate_mines` intervention is exposed through live controls/MCP and the loader button. A native wrapper rechecks pool membership, generation, player identity, gameplay/health, finite positions and blast clearance. Too-close darts defer; the wrapper explicitly returns before calling detonation. Native state 0x501 means wall release preceding explosion; 0x601 is the explosion transition. Acknowledgment proves the transition was initiated, not a kill or rendered effect.

Claims are made per dart immediately before its call. An uncertain first call cannot consume later unattempted darts. Confirmed distance refusal can retry; uncertain publication cannot. Receipts report dispatch lateness, and native power-dependent hazards inform movement. Tests cover game-thread guards, distance, partial dispatch and ABI/source reproduction. Live fuse/button receipts remain to be collected.

## Aim learning

RE6 now keeps verified learning in separate notebooks, without importing older trigger-based biases. A native cooldown rearm confirms discharge evidence; requests alone remain unconfirmed. Only settled, measured, unconfounded and identity-matched observations may teach bounded corrections. HP changes remain correlations, not proven projectile attribution. No 20-shot-per-second or S-rank success is claimed.

RE4 and RE5 now also use isolated verified notebooks. Their current hookups do not yet supply native discharge confirmation, so their trigger/HP correlations are recorded but cannot train corrections. This intentionally removes contaminated corrections while native firing evidence is developed; it is not a claim that all three titles already self-calibrate successfully.

## RE4 Waterworld route and death menu

Round `4827267cc2ed4e5c982645964dd182db`, session `7c2f3cf338a14b03-d2db519967ab407f`, died at 32 kills and 14,600 score. Its run map records 180.3 seconds, 148 m traveled, 109.1 seconds stationary, and 142.2 seconds pursuing a bonus. The route repeatedly jumped between ground-level approaches and a walkway 4,000 mm above the player. The preceding round died at 37 kills and 15,700 score. Neither has verified rank success.

The walker's shortcut test projected route waypoints onto the player's floor, so clear ground underneath an upper walkway incorrectly allowed skipping its stairs. It also popped nearby waypoints using horizontal distance alone. Route clearance now keeps the waypoint's actual height, and proximity cannot pop an upstairs waypoint. Synthetic overlapping-floor tests exercise both failures. Route-owned ticks now publish their actual action; previously the live summary retained the last fire action during long bonus runs. The movement counter also incorrectly reset the whole round whenever a normal run moved over 500 mm in one observation; its discontinuity filter now uses elapsed time and preserves previously accumulated travel.

The Continue menu was stuck on Yes while random-cast policy repeatedly sent B. Live directional input visibly selected No; A then exited. The reader now distinguishes the highlighted Yes/No words, and random-cast exits confirm only a witnessed No. Ambiguous frames do not confirm. Native first-aid receipts in this round explicitly show consumed items and HP increases; infinite health remains disabled.

RE4 rings now leave a 10 mm margin beyond their minimum radius and reanchor each ripple to the current player position. The independent distance refusal remains. This addresses live partial failures rounded as `700 cm ... minimum 700 cm`; it does not replace the game-thread mine clearance checks.

Validation: 168 tests passed with one asset-dependent skip across RE4 walker/native/aim/nav/menu suites; another 65 passed across walker, RE5 aim and the shared aim book. Live route, menu and ring results after activation still need observation. The recent RE6 Sherry round ended at 92 kills, 140,790 score and maximum combo 56, with death and rank unverified; it is progress in score, not the requested successful finish.

## Combat decisions blocked by report delivery

RE5 round `b4d6fdc0db554923ac9cbf15a19f0d7f` on Experimental Facility died at two kills and 2,400 score. Its flight evidence has an 8.095-second sampling gap and nine gaps over one second; telemetry recorded 8,093 ms of decision work. HP fell repeatedly during quick-turn instructions. The repaired native flash wrapper successfully created ten blasts without its former mailbox stall. That call still took about 3.3 seconds, so native ring latency also needs work.

Code inspection found that hurt and combo-loss follow reports performed HTTP requests with ten-second timeouts directly on the combat thread, under their module locks. Delivery now uses a bounded background queue. Each accepted report first retains local evidence with immutable round/session identity; queued, attempted, delivered, uncertain, and unsubmitted states remain distinct. Credentials are not archived. Unacknowledged POSTs are not automatically replayed, and queue pressure preserves unsubmitted evidence. A backend restart can leave queued/attempted records for later reconciliation; this is not guaranteed eventual server delivery. Detailed damage evidence remains independent of the capped coaching reports.

Decision timings now separate snapshot, screen, bot, damage/report, ring, mine, and input work. Slow cycles retain their original round identity; the flight recorder includes the preceding cycle's timings. These are wall times, not native frame-rate or CPU-utilization claims. A blocked-HTTP test proves the next combat observation can proceed before delivery completes. Tests also cover timeout uncertainty, queue pressure, failed receipt persistence, cross-round combo baselines, and timing attribution.

After activation of `4078336e`, RE6 live stats show firing/aiming while escaping bombs and no bomb self-hits observed so far. The current round still has combo breaks and unconfirmed shots. This is partial behavioral validation, not an S-rank claim.

## Completed RE6 run and positive-health game over

Rail Yard round `c3921dadc72748fc84eaf70ccf2c89d5` completed with 300 kills and 1,897,505 points. Native rank was not captured; assistance classification is unknown. The run traveled 408 m over 539.9 sampled seconds and still spent substantial time in bomb/escape behavior. Its five round-local combo breaks remain a tuning target. These figures do not certify S rank, original rules, or consistent success across titles.

The preceding Liquid Fire round `2738ce9be71d4e09ab569642c5edfb99` ended at 76 kills and 120,680 points. Its last native action was `cEm1000ActAtkFlyCatchHit_PL` with HP 900. The active `uIdGameover00` UI ended the round, but the scheduler's depleted-health-only gate rejected it and the bot recorded zero deaths. The action is context, not a confirmed attacker attribution. RE6 now carries its fresh active-list game-over witness, bound to the sampled player lifecycle, into both accounting paths. Replay loading cannot reuse that witness; HP remains the observed value. Acceptance is restricted to this title and the existing owned-session, native-playing, round-ID and timestamp checks. Validation: 426 tests passed across RE6, scheduling and engine suites.

With background delivery active (`c6249688`), RE5 The Mines round `e0544301741c4d5e8c478af55dcecad9` died at 23 kills and 7,100 points. Its flight timings show hurt-report work at most 4.23 ms, but snapshots still reached 1,782 ms and a flash ring took 3,458 ms. These are different maps from the earlier two-kill run, so the kill increase alone is not a controlled comparison. The new scalar timing mirror exposes the rich per-stage readings through the live telemetry filter as well as the saved flight data.

## Bounded RE5 time-bonus census

The snapshot's time-bonus reader traversed all 32 native unit lists, up to 1,024 objects per list, synchronously every second. It now traverses at most 64 nodes/list-head operations and checks a five-millisecond cooperative budget between operations. Vtable and next pointer share one 32-byte read. One slow transport read is still indivisible. State is isolated per memory view and reset for module, manager, player life and game-phase changes. A complete prior census stays available while discovery continues; partial results cannot remove statues, and a broken list cannot starve discoveries in later lists. This remains a temporally sampled census, not an atomic freeze of the game's objects.

Validation: 86 tests passed and one pre-existing expected failure across the scan, snapshot, bonus and navigation suites. Five bonus-give-up tests fail identically against the committed baseline; the isolated baseline replay is saved in `.scratch-merc-recovery/bonus-baseline-tests.txt`. These concern existing approach/wall recovery behavior, not the scan change, and remain to be corrected. Live latency improvement after this change is not yet measured.

Intervening RE5 attempts also failed: Ship Deck `e6e9e364bd904765892a1af4325fd1a8` at four kills/1,210 points, Public Assembly `65a650b47d9c47f680039360e301039d` at seven kills/2,290 points, and The Mines `a3a0e5ccacfc420b9366e622e7e6516d` at four kills/1,910 points. Their last reported decision-work p95 values were 661, 285 and 409 ms respectively. No across-title consistency is established.

## RE5 false danger and unbounded retreat

The Mines evidence includes repeated retreats from motions 42/32 with an inherited learned reach around 8.5 m. The title-local threat notebook still accepted damage correlations without a native attack flag, even though the shared core already required stronger evidence. New learning now requires attack evidence; walking animations cannot become windups solely from saved correlations. Verified windup motions still allow anticipatory avoidance before an attack flag appears. A continuous danger episode has one 1.8-second retreat allowance; changes of enemy or animation cannot renew it. A witnessed calm interval resets the allowance. A brief gap in danger observations does not.

Validation: 83 tests passed across windup, fighter, threat-memory and RE5 bot suites. Two older threat-selection/sky tests fail unchanged on the committed baseline (saved in `.scratch-merc-recovery/threat-baseline-tests.txt`); they remain separate issues. Native attack flags were added to the existing learning fixtures because an animation change alone is no longer accepted as attack evidence. Live behavior after activation remains to be evaluated.

The positive-health RE6 game-over path has now recorded round `afef77602bf0459c8f3fd661171e9332` as died, 89 kills/137,110 points, with `death_boundary_source=native_game_over_ui`, observed HP 600 and one round death. Native rank remains absent. The separate frame/telemetry observer expired after its hour and was restarted; permanent round evidence collection continued independently.

## RE5 flash rings beside combat

The verified RE5 flash ring now runs as one background operation while the combat loop continues to aim, fire and move. Only the verified flash path is admitted; this does not authorize concurrent explosive rings. Busy native controllers refuse instead of queueing a stale automatic request. Round/player-generation identity, native gameplay phase and cancellation are checked before attachment and between native operations. Terminal/menu/operator transitions cancel further publication. An in-flight call cannot be recalled; partial or uncertain outcomes retain their original identity and are never replayed. Receipts are archived independently of the next combat tick, including spawned projectiles whose explosion was not confirmed. Late receipts cannot add success counters to another round. Flash completion no longer requests a blind blast-avoidance backstep.

Validation: 160 tests passed across background cancellation, busy-controller admission, evidence persistence, partial publication, native ring/scatter, shared engine, RE5 snapshot and threat suites. Live timing and survival improvement remain unverified. New snapshot-stage timings separate player, laser, equipment/aim, prompt, mines, enemy census/rows, counters, navigation and bonus work. The bounded bonus scan alone did not eliminate snapshot stalls: round `a59aaaba14f04061b6ce21683f1a5470` died at two kills/600 points with decision-work p95 601 ms and a final 638 ms snapshot.

RE4 Village round `2021d885283744b986b536868ee74e73` died at 16 kills/6,070 points after 86.3 m of recorded travel and three observed clock gains totaling 90 seconds. The selected weapon was Handcannon/magnum class, but native object confirmation remained unresolved. Selected inventory and a visible weapon are not substituted for a confirmed native swap receipt. The next RE5 Ancient Ruins round `be50e703992444abaa1660d62f189948` stayed within 8.2 m of spawn during its 38.6 sampled seconds and died; its inherited false retreats are another case for the staged threat correction.

## Enemy census latency and accessible healing

The first live background-ring receipt belongs to RE5 Experimental Facility `866131cbe8f34336bea75e12fdf6cac3`: all ten native flashes confirmed, HP 1,000 before and after. That attempt died at 12 kills/7,060 points, with zero learned-threat backoffs. Its 71.2 sampled seconds included 24 seconds of mine behavior and only 3.2 seconds of firing. Snapshot work still reached 884 ms; a recorded substage assigned 390 ms to the auxiliary enemy census. That diagnostic traversal is now limited to eight units and a cooperative two-millisecond budget between units, isolated by memory/player life. Incomplete or cyclic scans never publish a partial count. The reported age distinguishes an older completed census from current enemy rows. One transport operation remains indivisible.

The round also contained a 2,218 ms grenade-rule stall: the separate scatter batch still ran synchronously. The background ring is live-verified, but the entire grenade rule is not yet free of native waits.

Recent RE5 attempts reported zero healing starts. Inspection found a concrete accessibility bug: mine template preparation could swap a spray out of a quick slot while retaining it elsewhere. Mine placement now excludes every healing quick slot from displacement. It does not add heals, replenish them, write HP, or extend the weapon-only native equip API. Inventory and healing-access diagnostics are now included in bounded flight records so future failures distinguish absent items from inaccessible ones. The particular deaths cannot yet be attributed to this bug because their old flight records omitted inventory. Validation: 88 tests passed across census slicing, healing accessibility, template composition, RE5 bot and flight recorder suites.

## RE5 scatter batches beside combat

The remaining synchronous scatter path now shares the ring's single background worker and lifecycle guards. Only verified flashes are admitted. Ring and scatter requests cannot queue behind one another; cancelled or partial native publications are archived with their original round identity. Each scatter point uses the current player position and the originally observed crowd center, preserving player clearance while combat movement continues. This does not track a crowd's subsequent motion. All-flash scatter completion also avoids the old blind explosive-escape backstep. Synchronous callers now report fired only after a confirmed receipt.

Validation: 99 tests passed across ring/scatter cancellation, partial publication, movement clearance, shared-worker admission, counter ownership and engine integration. Live latency and survival effects of this extension remain unverified. Native calls already in flight are indivisible; cancellation prevents subsequent operations, not an operation already submitted.

## Deployment interruption of RE4 Base

Audit job `48b106ff52324e38`, actor `deploy`, hot-reloaded four bot modules at 1794561325 during active RE4 gameplay. It stopped the controller, recorded `0c32d87f1e3c466dba9678b91c222750` as interrupted, and restarted the controller with `dee9ba7476a94acebafbbbdae11c65cb` under the same session/job. This was not a native new round or an autoplay time limit. The latter segment completed at 101 kills/84,980 points, but carries the wrong queued stage label, Castle, after the reload reset selection. No native result rank was observed. These segments cannot be treated as independent complete attempts or proof of a five-star result.

Hot reload now defers while a Mercenaries capture is open or gameplay/unknown state is active. It checks worker-local live state again immediately before stopping; a stale closed record cannot override active gameplay. Deferred reloads return the existing busy/retry result, which does not fall back to a service restart. Validation: 60 hot-reload tests passed, including continued control during deferral, evidence finalization and a new round appearing during admission. This guard samples state; it does not lock the native game thread.

## Crowd weapons and mine rearm deadlines

RE5's arsenal resolver returned a fixed magnum-first list even when its crowd profile requested shotguns. Crowd selection now prefers a usable shotgun for three nearby live enemies, retaining that preference for 1.2 seconds after the crowd thins. It preserves an operator weapon lock and an observed body shot already lined up with the current loaded gun. Existing held shotguns remain preferred within their family; empty or inaccessible inventory entries do not qualify. Shotgun-swap counters no longer count magnum swaps.

The mine controller renewed its rearm deadline each time it repeated the quick-slot press. Failed equipment confirmation could therefore hold the controller indefinitely. Rearm taps now use a separate cadence without moving the deadline. An enemy closing during mine equip starts a bounded retry window so combat can act before another attempt. Validation: 143 tests passed across rampage, crowd fire, mine lifecycle and weapon mastery. Native mine placement without equipment switching remains unverified; this change fixes the current controller's waiting behavior.

## Reports for repeated waypoint changes

Navigation reports now catch an A/B/A/B waypoint cycle toward the same final goal, with sustained movement commands but little displacement or goal progress. Reports retain the input, route and nearby geometry evidence; they do not claim confirmed collision. A full route endpoint is captured separately from the bounded route prefix. Stair ascent, actual waypoint arrival, changed player life/goal, missing endpoint and uncommanded stillness do not satisfy this detector. Validation: 19 navigation/flight-recorder tests passed. Live frequency and corrective route policies remain to be measured.

## Native RE4 round labels

The round recorder now captures stage and character from the first valid live MercSys sample, retaining that identity through menus and later changes to the queued selection. Reports and scheduler boundaries distinguish `native_mercsys` from the explicit `requested` fallback. This prevents a controller reload from labeling an ongoing Base attempt as queued Castle. Validation: 59 RE4 bot and boundary-wiring tests passed. A final 109-test run also passed after adding round-local resets for RE5 crowd-selection hysteresis.

## RE4 equipment recovery across native rounds

RE4 can reuse its player pointer and slot ID in the next attempt. An uncertain equipment refresh therefore remained blocked despite a completed call and a new native round. The controller now retains a terminal-to-intro-to-playing witness across bot reloads. Only a completed refresh, quiescent mailbox, coherent observed equipment and a later witnessed native round can clear that block; the original uncertain receipt is retained. Pending calls, legacy receipts without an epoch, menu transitions and capture-ID changes cannot unlock it. This permits another round's attempt; it does not establish that the original weapon swap worked.

## Direct RE5 mines and the five-mine request

The operator requests mines without equipping or animation, including a five-mine ring while escaping after a nitrogen blast. The existing direct-mine prototype passed a relative DTI where the native factory requires an absolute address. It now relocates that argument with the module base. The default ring contains five mines at 152.4 cm; explicit legacy eight-mine research requests remain supported. Native mine arming, retained weapon and continued movement still require live acceptance. Availability remains unverified until that evidence exists. Combined validation: 107 tests passed, two skipped across native equipment, proximity mines, intervention requests and live controls.

The latest request prioritizes unlocking the actual launcher effects, especially the 360-degree nitrogen ring across titles. Existing flash fallback is not nitrogen. RE5 has nitrogen ammunition; older comments claiming otherwise are incorrect. RE6's existing shell prototype uses a thrown-grenade initializer; its shell lifecycle and effect still require validation. An initial concern about allocation bounds was disproved by the native constructors: all three shell factories allocate 0x3970 bytes. The registration field 0xE5C was incorrectly described as a byte size in earlier research. The throw-specific writes are within that allocation, but this does not establish compatible field meanings or a functioning nitrogen effect.

## Compact toolbar icons

First aid, mine drop, five-mine ring, dart detonation, grenade-type selection and the flawed-behavior report now use compact SVG icons in the desktop top bar. Action names remain in accessible labels and tooltips; the type icon follows the selected ammunition. This is presentation only and does not mark unverified native effects available. The first-aid/action status painter retains icons through polling and receipts. Hidden controls remain hidden despite the icon layout's flex display.

Validation: all 26 intervention client tests passed, five desktop inline scripts parsed, icon-mode status/receipt checks passed, and an isolated 860-pixel Chromium preview was inspected. Live desktop automation could not start because its Node kernel module was missing; this preview is not a capture of the running app.

Native launcher research continues on Spark in `analysis/merc-full/re5-shell-research-20261113`. RE5 launcher fire is main+0x808980, setup +0x808ED0, registration +0x809800, shell initialization +0x7E9350 and common shell update +0x7E9640. DTIs and virtual tables were resolved from ELF relocations, not guessed raw zero entries. The native debug strings identify `WP44 LAUNCHER_ROCKET` and `WP43 Empty`; neither is nitrogen. Launcher `_N`, `_S`, `_I`, `_F`, `_L` suffixes require mapping to actual payloads before exposure. The standalone shell factory/impact prototype is not yet implemented. No mine probe was submitted in the checked attempt because it had already ended.

RE6's parameterized grenade spawn had the same relative-DTI defect as the RE5 mine prototype. Both ring/scatter calls now supply the module-relative class descriptor relocated to its absolute guest address, matching the derived wrapper's argument contract. Validation: 78 focused ring, scatter, status and intervention tests passed. The live paths remain unverified until a new receipt. RE6 native factory main+0x3BCF90 calls the DTI's allocator and preserves the returned object pointer; shell constructors +0xF59C80/+0xF5A110/+0xF5A3D0 allocate 0x3970 bytes. Targeted exports are in `analysis/merc-full/re6-shell-research-20261113`, opened with Ghidra 12.2 (the 12.1 runtime cannot read that project).

## Late aim observations and measured correction time

RE5 decisions commonly arrive 100–150 ms apart, but the correction capped every interval at 50 ms. At 150 ms cadence the configured 140 degrees/second yaw therefore corrected only about 47 degrees/second. The controller now refreshes the selected native target, player and held weapon immediately before reading camera and laser. Player life, target slot/generation, held object and gameplay phase must remain consistent. The timestamp covers the oldest geometry; reads exceeding 150 ms are rejected, not retimestamped. Accepted correction intervals retain up to 150 ms; long stalls, changed identities and failed writes reset that budget. Fire still requires observed ray/body or the existing measured shotgun criteria.

Validation: 188 focused aim, feedback, weapon-mastery, point-blank, rampage and retreat tests passed. Two target-selection smoothness failures reproduce with the committed aim module and remain separate issues. Runtime read latency, failed writes and sustained firing still require comparison after activation. The operator again observed repeated raising/lowering and too little mine placement/fleeing while these changes were awaiting activation.

## Native mine probes and oversized receipts

RE5 Prison round `46e9d44c4ff34f939f9619b29262d791` accepted direct mine probe `94827aaf-6dfb-4ef7-9f38-ce9932e65258`: native factory/resource/reset/configure/drop/ground calls completed and the mine's active flag and arming volume were observed. The legacy controller was already rearming from mine item10 to Hydra25, so that probe did not establish unchanged equipment. Its flight record does show continued aiming and movement while placement ran. A second probe, `e92217bf-7479-4c51-892b-8b541e94dd83`, armed another native mine in 850.8 ms with Hydra25 observed before and after.

Five-mine request `2f67ecce-3e12-4cba-8bb8-548b210be78c` increased the aggregate placement count from two to seven, but its detailed result was rejected by the control plane's 4,096-character receipt limit. Both prepared and deployed actor lists made the payload too large. A missing receipt is not accepted as ring success and the request was not replayed. Oversized completions now archive the complete result with session/request identity and a digest, then deliver a bounded summary. Archive errors are explicit and do not strand unrelated receipts. Native placement now also supports nonblocking controller admission and an expected player life, and records observed health/movement without attributing concurrent damage to mines.

Validation: 46 receipt/proximity tests passed, followed by 33 native-controller/proximity tests after the admission and telemetry additions. Direct mine availability remains gated pending a complete five-mine receipt and escape validation; the automatic background integration is separate work. The probe round died at 33 kills/12,290 points. Its ring interval contains a native grab and HP776→734, not proof of mine-caused damage.

## Short wall-recovery incidents

RE5 Missile Area `47294d371d3e48f1b80d600369936e76` died at 267 kills/156,490 points with 1/11 bonuses, 29 combo breaks, 39 wall detections and 13 failed recoveries. No navigation incident was generated because the title's approximately 0.4-second wall guard interrupted navigation before the shared monitor's 2.8-second window. RE5/RE6 now retain the guard's actual final-pad commands, measured displacement, player identity, goal and route before recovery changes them. The reporter records restored movement, failed recovery or interruption. It does not infer native collision or report stationary aiming as a wall.

Validation: 78 navigation/flight-recorder/wall tests passed. Live incident delivery remains to be checked after activation. RE6 Catacombs `e43bd4df202248d492a129fad2306e46` died at 177 kills/184,490 points following native `cEm1000ActAtkFlyCatchHit_PL` and prompt type8; sampled HP remained900. This is a witnessed fatal grab/QTE sequence with unproven attacker identity. No native S rank was observed in the audited rounds.

## Traversal drops and final movement priority

The operator adds: "when a character climbs a ladder or drops down a ledge or does a climb operation of jumps through a window. Leave a mine / remote bomb / do a nitrogen round ring". RE5 now admits one native mine after a named, owned traversal exits to a stable grounded action. RE6 admits one native remote bomb after native traversal exit, displacement and distinct stable floor observations, then rechecks current feet, action, mesh, weapon and existing bombs under the native controller lock. Both retain Automine, lifetime, duplicate, previous-bomb escape and uncertain-outcome guards. Requests are not counted as armed explosives. RE5 window-event wrapper coverage and RE4 traversal explosives remain open; nitrogen remains unverified and is not substituted by a renamed flash.

RE5 pending landing requests expire with their original five-second evidence and cancel on lost grounding or a new traversal. After deployment, arming observation and hazard tracking continue. RE6 ladder action-to-walk transitions have recorded-round evidence; other accepted traversal class names were verified in the executable but still need live completion observation. Validation: 135 RE5 admission/native-mine/traversal/engine-input/flight tests passed; the RE6 batch passed 426 landing, remote-bomb, firing, navigation and floor tests, followed by 107 focused tests after tightening external-bomb clearance for floor detours.

The shared engine no longer replaces a title's final checked movement with a camera-relative backward step after an explosive ring, or skips input submission on that completion tick. RE6 now requires actual native floor coverage for both segment endpoints rather than `NavMesh.locate`'s nearest-triangle recovery fallback. Its final movement guard runs after all combat/recovery rewrites, preserves combat controls, and checks the eight actual stick headings. A same-tick native camera write requires a fresh heading near a floor boundary; movement remains allowed only where the full lookahead disk is proven to contain floor. A floor detour must preserve every external bomb's configured margin along the whole segment, with monotonic departure when already inside it. Walkable lethal scene volumes still need their separate exact native catalog; floor coverage alone does not establish hazard safety.

The preceding RE5 changes (`873bbbba`, `75d335a6`) add the exact Missile Area incinerator catalog, final stage-hazard and all-mine escape guards, geometry-scoped navigation learning, and posed native-joint aiming. The old active worker `af3d25f1f3b34383` remains the baseline until the protected activation is recorded. Its Village round `1bdc96ce25874b29b9d2c6340b083d01` exposed escape completion measured only against the newest mine batch: an older mine was 251.8cm away despite reported latest-batch clearance 1504.8cm, followed by native trigger and HP342→1. That is strong temporal/geometric evidence, not native damage-owner attribution. New code is not a claim of successful live survival or S rank.

Revision `29e8a5dce82af3cd93406e96e7163a099754e7f9` was activated at 1794574127.9636672 after RE4 round `7ecedef663c84094b1bc6f7f01333316` reached results with timer zero and closed evidence. Spark service PID became712890 and worker `b445b3e9a1404bd5`; sixteen runtime files matched the staged commit. Activation evidence and the cleared, archived pending marker are in `gbox-data/merc-activation-29e8a5dc*.json`.

First new RE5 Village round `5cbf663da89a46e29ca99b2aefe1005c` exposed a further failure. Initial mine escape reached1501.6cm and returned to aiming at HP1000, seven kills. Later the final guard found no checked escape and held neutral for44.79s in the last60s of dense flight; the round died after92.2s with31kills, zero bonuses, two recorded shots/two hits, and68.5s standstill. Mine placement continued while blocked. At HP174, the player was near(-7507,100,5942), with two still-armed mines at(-7619.44,100,6011.70) and(-7619.44,100,5832.54). Native damage ownership is unproven. Archives `re5-29e8-5cbf663d-round.json` and `re5-29e8-5cbf663d-escape-audit.json` are under Spark `gbox-data/analysis/merc-tuning-20261113`. Preserving defensive combat while checking a blocked escape is now required; the initial successful clearance is not accepted as overall survival improvement.

RE4 now has a separate traversal observer backed by its exact native movement dispatcher and handler table. Completed ladder, ledge, window/fence and fall/jump movement requests five existing hand-grenade blasts with native per-blast clearance, after hit/QTE priority. This is immediate grenade defense, not persistent mine creation or nitrogen. Unknown reads and new traversals invalidate the previous uncommitted landing event. Native returned-call confirmation remains distinct from verified live effect. See `re4-traversal.md`; live RE4 landing-to-ring evidence is pending.

Before the first RE6 nitrogen research probe, admission now requires a fresh complete native bomb census under the shared controller lock, both before image preparation and immediately before shell allocation. Pending/uncertain automatic bomb work blocks the probe throughout; player clearance is checked again after the final census. The one-probe-per-player-generation rule and unverified UI status remain. No nitrogen probe was submitted in this work interval. Validation:157 broader tests and70 final focused tests passed for the atomic probe gate.

## Retained mines and blocked defensive combat

The exact Village floor replay identified a third retained hazard in the fatal
`5cbf663d` escape: old unit400574316704 at(-7078.5156,0,6470.1147), absent
from the current two-mine census. Its last captured state was active with no
trigger; disappearance does not prove explosion. Its exclusion closed the
otherwise valid eastward escape. The owned Switch s402 NAV geometry matches
the live mesh; removing that old exclusion in the replay opens three headings.

Native observations now retain a bounded, double-read class/generation/owner
retirement witness. An owned inactive or trigger witness can also retire an
escape site. Missing/partial memory, a stale census, another generation at the
same pointer, and plain absence cannot. Short flag reads are unknown rather
than false. Trigger attribution uses the same generation-qualified witness;
retirement never invents damage or kills. Validation:100 tests passed across
retirement races, native observations and blocked defense.

When all eight checked escape directions are blocked, the bot now keeps a gun
up and lets fresh native aiming feedback authorize fire. It no longer stands
neutral solely because a physical mine has no safe departure route. As soon as
a checked route opens, releasing the shot and leaving every retained hazard
take priority. This is not permission to cross a mine exclusion. The snapshot
records per-reason candidate vetoes and the defensive target for triage.

RE5 traversal detection also covers the verified native object-event wrappers
for windows and both ladder families, with exact RTTI/scene identity and
terminal phase evidence. Missing a one-frame completion flag refuses placement;
an unobserved completion is not synthesized. See `re5-traversal.md`.

## All-gun rate and current accuracy requests

The latest operator request supersedes RE6's previous ordinary-gun5x cap:
all guns should fire at20x with no recoil animation. RE6's profile and live
slider now request/permit20x. Known gun fire actions use the rate for native
animation time as well as the interval table; previously only magnums had the
animation multiplier. The known rocket launcher is no longer mistaken for a
melee weapon solely because its original interval is10seconds. Faster explicit
sniper overrides remain. Generation, weapon and action are reread before a
write, foreign time scales are preserved, and the previously owned multiplier
can be restored after changing/disabling the rate. Validation:322 existing
RE6 tests and32 new gun/race tests passed. These host-polled writes compress
recoil/pump animation; they do not prove zero animation, frame-atomic transitions
or a measured20x projectile cadence. Live verification is still required.

Additional requests remain active: roughly120-second crowd-triggered randomized
grenade scatter bursts at20x animation speed, followed by verified flash and
explosive escape tactics; accurate Garrador rear-Plaga targeting; split-second
magnum marksmanship; and persistent mastery evidence for each individual weapon
across RE4/5/6. Random choice must use actually supported effects and preserve
all-player blast clearance. Nitrogen remains unverified. The RE4 aim book's
verified-only learning lacks a discharge-confirmation feed; counting trigger
requests as hits would hide rather than fix that defect. No S-rank consistency
or complete implementation of these requests is claimed here.

## Activation, round evidence and reload recovery

Revision `5d99bb63114603ef14fbd101b3dc5fbfc62d2e58` activated after a closed
RE5 death at 1794577578.4451225. The new service PID was1284752 and worker
`025de5feea3142c4`; all25 checked changed runtime sources matched. Its RE5
round `443f46cf24f54548a8078df81609c1ae` reached a sampled49-kill combo and
22,200points, then died at1794577791.6464307 with49kills and36,340points.
It captured zero time bonuses. Sampled shotgun trigger requests
rose to63 with15.91seconds of trigger hold over60.68seconds. These are input
and outcome observations, not a native bullet count or a successful S rank.
Four native mine trigger/retirement witnesses were recorded. The durable record
contains77seconds stationary across97.6seconds. One mine was raycast14.54meters
below the player's floor but retained by the flat-distance escape test. Native
vertical blast bounds or pre-arming floor validation need investigation before
relaxing that protection. Blocked mine escape, low health and slow decisions
remained; no survival guarantee follows.

The receipt chronology separates two problems: the first blocked escape began
before that lower-floor ring, with the existing traversal mine and five floor
vetoes/three mine vetoes. After the four same-floor ring members triggered and
the traversal mine retired, the lower-floor mine remained the sole live hazard
at263cm flat clearance. It prolonged the escape problem; it did not cause the
initial stall. The native ground projection currently runs after activation and
can select a much lower surface, so pre-arming validation needs investigation.

Revision `f2b1b3f38f5237e54a5f876c338cb54db48a8a65` activated in the following
empty MercMode boundary; service PID1324645, worker`5848d136b3904c8b`.
Its crowd roulette has an independent120-second clock, verified effect
selection and owned flash-to-mine follow-ups. See `merc-crowd-roulette.md`.
RE4's per-frame20x gun guard still needs a fresh RE4 process and measured live
cadence. RE6 nitrogen remains unverified. Activation archives and round JSONL
are under Spark `gbox-data/merc-activation-*` and
`gbox-data/analysis/merc-tuning-20261113/post-5d99-round-audit.jsonl`.

The earlier RE4 attempt `6bd20871af54439dabfeb324bfff98be` froze at the
Waterworld intro: timer119.67seconds, zero kills, native dispatcher tick80949
unchanged across repeated reads. The mailbox was completed, not a proven
pending native call. Evidence is archived in `re4-frozen-6bd20871-*`; root cause
remains unresolved. MercMode moved on to RE5 after the stopped autoplay job.

The operator then requested GitHub synchronization to reload gBox. The desktop
updater now checks whether the fetched commit already equals HEAD before
refusing a merge because of local edits. Current checkouts can report current
while retaining those edits. No dirty checkout is merged by that change.
An additional reload blocker was639 old local ownership records; the read-only
inspection now accepts positive process absence/reuse while retaining the
records and refusing live, unknown or concurrently changed ownership. The
operator separately requested closing lingering Ryujinx; a fresh process
inventory subsequently confirmed that no Ryujinx process remained.

The latest aim work is described in `re4-garrador-native-weakpoint-20261113.md`
and `weapon-aim-mastery-20261113.md`: actual animated Garrador damage spheres,
conservative native shotgun/magnum discharge witnesses, and title-local weapon
partitions. RE5 still needs a verified emission feed; its static provenance is
in `re5-fire-witness-20261113.md`. Trigger requests must never substitute for
native discharge or impact evidence in the mastery database.

## Current RE6 observation before the next repair batch

Worker `e41fad8986bf40a5` loaded `c1a97781`; the newer deployment marker on
disk does not establish that its running process loaded subsequent fixes.
Session `e41fad8986bf40a5-99863222c9f348b7`, round
`ed4b38949ac6492889ae688a344b558e`, was still playing at `1794581975.107`.
The tactical sample showed 73 kills, 61,060 points, 379.91 seconds remaining
and HP 600/900. Telemetry recorded ten gun trigger requests, one aim-book hit
and one miss. This is an interim observation, not an observed result rank or
proof that those kills came from bullets.

The same sample retained 29 ring bombs across two rings, one partial ring,
32 missed bomb deadlines and five detonation failures. Its allocation gate
reported `uncertain native allocation; no further automatic bombs in this life`.
Earlier at `1794581901.149`, the known bomb placed at `1794581842.362` was
already 53.733 seconds old with only 561.5 cm clearance, below the recorded
1100 cm detonation requirement. These measurements preserve the failure and
allocation ambiguity; no missing actor or successful flag write proves a blast.
The audit issued no gameplay input, and no uncertainty gate was cleared.
The next escape/deadline repair is not active in this evidence.

Durable telemetry and JPEGs are in Spark
`gbox-data/analysis/merc-tuning-20261113/post-c1a97781-round-audit.jsonl`
and its session-named frame files. Earlier completed RE6 attempts are retained
in `pre-c1a97781-round-summary.json`; `pre-c1-re6-first-bomb-window.json`
extracts the first bomb escape failure with timestamps and held controls.
