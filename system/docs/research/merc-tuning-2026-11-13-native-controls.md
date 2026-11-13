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
