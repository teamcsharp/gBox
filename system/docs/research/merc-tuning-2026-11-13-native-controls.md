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
