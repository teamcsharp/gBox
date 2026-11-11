# Round 196: the barrier test moved the character to a map edge and froze it there

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Live: session `e731ee594dde4a89-cae9dad929a34d17`, character returned to Pioneer 2, randomizer running (cycles 2 of the new run)

## Measured

A barrier-directed walk (goal `TOBarrierEnergy01` at (221, 493)) started from the Forest 1 spawn, moved the character north to
**(450.8, 10.4, 582.1)** - near the area's northern edge - and then **every key stopped moving it**: the walker logged
`no direction moves` fourteen times in a row, with `hp` 10, `floor` 1.

So the pattern from round 194 repeats at a second location: once the character reaches a slope/edge, PSO ignores all four stick
directions (nothing moves, no menu, normal control state). B does not clear it; only a respawn moves it.

## Where this leaves CP17

Two blockers, both now measured:

1. **The zone is gated** - `TOBarrierEnergy01` (221, 493), `TLazerFenceSw` (526, 33) and `TObjDoor` (253, 92)/(53, 290) enclose the
   start region; the switches are far away. The walk cannot leave until a gate opens.
2. **Slopes/edges trap the character** - reaching one stops all movement, and the only recovery is a two-step respawn
   (town -> Forest 1 -> B x2), which returns to the spawn and gives up any progress.

Until both are handled, a "walk to the door" run cannot be completed by a feedback walker alone. The next honest step is not another
walk attempt: it is to understand the gate (which switch, or which attack, drops `TOBarrierEnergy01`) and to avoid slopes by using the
collision graph's height data (walk only cells whose floor is flat, `pso_walk.cells` knows the triangle flags and `psomap` computes
cell heights).

## Stable

- randomizer: running again after its own safe stop, `cycles: 2`, `Equipment randomized`;
- CP18: done (Dragon HP 0/1300 from RAM, entity despawned);
- input paths: external keys work once the character is off a pad; worker `send_input` works always.
