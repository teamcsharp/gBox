# RE6 remote bomb deadline and escape service — 2026-11-13

The requested maximum is five seconds from placement. Detonation continues to
require the player's native position to be at least 1,100 cm from **every** owned
bomb, with valid allocations, a living player, and no held state. A missed escape
deadline is reported; it never authorizes self-detonation or changes health.

The next travel-drop revision replaces stationary timer rings with one native
armed bomb after 609.6 cm (20 feet) of measured horizontal locomotion. Wall input,
warps, duplicate snapshots and stationary aim do not accrue travel. The held gun
does not change. Flash/surrounded emergency rings retain priority. A shared native
controller lock rereads the actual bomb census before either allocation, preventing
an old empty snapshot from placing another bomb over a concurrent manual request.
Native placement receipts preserve their deadline when a delayed census still
shows an empty field, the initial throw action, or an already-started explosion.
An uncertain allocation blocks further automatic allocation for that player life.
The focused travel/deadline/native-drop suite passed 107 tests; live movement/drop
and five-second explosion acceptance remain pending deployment.

The old remote-ring rule returned before checking detonation whenever the bot's
own `bomb_phase` or grenade state was active. It recorded the request's timestamp,
discarded per-bomb placement timestamps, and synchronously allocated up to 15
bombs. The engine then replaced navigation with 2.5 seconds of backward input.
These operations could delay both escape and the native flag.

The revised service:

- Checks existing bombs before the engine's prompt branch, using a fresh clock.
  A grenade or bomb phase cannot suppress this check. QTE input retains control;
  the native detonation routine independently refuses while the player is held.
- Records each unit's generation, placed/armed confirmation time and five-second
  deadline. Native drops share these timestamps with the observer. Hand-thrown or
  externally created units without a receipt are explicitly labelled
  `first_observed_placed`; their exact earlier placement time is unknown.
- Runs one cancellable native ring batch in the background. Each allocation
  validates the player life. After two seconds, a slow batch stops adding units
  and returns an honest partial receipt. Inputs remain active during allocation.
- Gives immediate bomb escape priority over quick turns, weapon changes and
  another item operation. The route still goes through navigation/wall guards.
  It no longer becomes a fixed camera-relative backstep or stationary fighting
  decision. The ring centre supplies the escape direction, avoiding reversals
  when the nearest individual bomb changes; every actual bomb still participates
  in clearance. A safe native flag does not require releasing movement or a weapon.
- Detonates as soon as clearance permits, rather than waiting for more rings or
  a favourable crowd. A completed flag readback is distinct from the subsequent
  observed `cWpAction_wp_act_bomb`. A unit disappearing is recorded separately;
  it is not claimed as an observed explosion.

`mercs/native-remote-receipts/*.json` retains full requests and native batch
results even when the round ends before polling finishes. Flight rows include
elapsed/remaining time, deadline, clearance, pending state, refusal reason,
miss count and the last flag/blast observation. Deadline incidents retain unit
identity, placement time, player position and the refusal context, bounded to
the last 16 incidents. No uncertain allocation is replayed automatically.

Validation uses synthetic native memory and threaded controller fixtures:
native allocation/refusal, placement timestamps, partial/cancelled batches,
all-bomb clearance, prompt-only service, unchanged movement during allocation,
life changes, fresh versus incomplete census, flag/blast distinction, deadline
misses, and the deadline escape route. The focused suite includes existing RE6
bomb, fire commitment, RE5 reaction and engine round-rotation regressions.

Live acceptance remains required: verify measured placement-to-blast intervals,
escape progress, missed-deadline reasons and continued gun/control activity in a
new RE6 round after deployment. Passing synthetic checks does not establish that
every physical escape route clears 1,100 cm within five seconds.
