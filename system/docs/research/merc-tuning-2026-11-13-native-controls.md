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
