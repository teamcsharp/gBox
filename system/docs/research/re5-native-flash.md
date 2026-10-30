# RE5 Switch native flash: 2026-10-30

Exact build `EBFFDB223149A725A93CD9B60979F6AA`, Linux ARM64 Citron NCE.
The controller constructs a native flash at the player and executes its real
explosion callback on the player update thread. It does not equip a grenade,
open inventory, send controller events, or wait for a throw animation.

## Native evidence

Research receipt `re5-native-flash-effect-trial-1793341004543014415.json`
on Spark (`gBox_alt/scratch/agent`) used owned PID 1007077, birth
1793337989.93, Sheva Normal player generation 9. Native flash `uWp08`
generation 10626 spawned exactly at the sampled player position. Its native
exploded flag became true and two enemies entered `cEm10ActDmgFlash`,
including the Majini that had been holding the player. Equipped selection
and inventory were preserved; the original player vtable was restored.
This is live research evidence; production API acceptance is recorded separately.

### Deployed production API acceptance

PR1597 merged as `49db6aebcb53f876ab66b5c7205236f0e65a1381` and deployed to
Spark. Sheva Cos1, generation1, session `5cb6330c56514413-079bf401635a4f94`:
20 distinct requests produced20 confirmed native explosions in2325ms, native
calls25.6-195.3ms. Seven enemies were observed in DmgFlash. Inventory selection
was unchanged and original vtable restored. Receipt on Spark:
`re5-production-flash-1793342443371018469.json`.

The cold first click took1848.8ms overall/1139.9ms native. PR1598 (merge
`424dfc4aa742601414ba04c1ad94aac5aade6e57`) therefore installs and allocates
native dispatch before advertising capability, with no projectile or effect.
After deployment/restart, Jill Cos2 with no inventory flash confirmed the first
click in442.5ms overall/120.4ms native. The next20 requests all confirmed in
2505.1ms; inventory and original vtable remained intact. Receipts:
`re5-production-flash-1793342949121516917.json` and
`re5-production-flash-1793342975883739932.json`.

These are measured runs, not a universal latency guarantee. The broader request
for20 grenades in two seconds remains unfinished. Ticket6102's repeatable native
RE5 flash hook is completed, audit220617; umbrella5972 remains open.

An earlier prototype requested held-weapon action 15 (`wp_act_bomb`). That
animation alone did NOT cause the required flash. It is not the shipped path.

Native construction calls `main+1C21C0` with `sItem` at `1CF1408`, flash DTI
`1D71538`, line 10. It initializes position, rotation and player ownership,
then waits for native resource/action initialization. Detonation calls
`60D6D0(unit,1,0,0x108,1)`, requests the bomb's native `+24CC` bit 0,
and runs `uWp08` callback `820E50`. Its base update `806B80` creates
hit volumes, effects and sound and publishes `+28A0`. Flash-specific processing
also runs. A return value alone is insufficient: Python requires the same
allocation, owner, generation and native exploded flag afterward.

The native wrapper requires initialized scheduler and hit-volume resources.
Flash motion resources may legitimately be null, as verified against the
native resource table. No inventory flash requirement or invented pointer is used.

## Installation and lifetime guards

Checked-in C/ARM64 source, ABI tests and instruction images are in
`gbox/mercs/native/re5_ebffdb22`. Run `bash build.sh <output-directory>` on
ARM64 Linux with binutils, GCC and clang. It runs three native ABI tests and
checks exact reproduction of every image.

All ten Mercenaries player class vtables are pinned from this executable.
Only the actual 149 methods are cloned, excluding adjacent resource data.
Bootstrap temporarily changes the player update dispatch and allocates a private
4096-byte table/mailbox using the game's allocator. Integer/FP inputs and the
original update are preserved. Native dispatch checks owner and 64-bit player
generation and atomically consumes each call once.

Process birth, executable signature, player life, phase, health, class methods,
projectile generation/owner and exact code checksums are verified. New code is
installed only into zero padding through the verified HostMemory backing file,
with the owned emulator stopped briefly. Different occupied bytes refuse.
Later clicks reuse the private mailbox without stopping the game. No uncertain
call is replayed. A lost projectile permits a new click only after completed-call
and original-vtable verification.

## Integration and limits

The existing durable intervention queue, PiP/web button and MCP
`game_intervention` detect this controller. `game_mod` flash operations share
the same adapter/controller lock. Readiness is tied to the current player/round;
stale requests expire. `queued` is not successful detonation.

Python regression validation: 49 tests across native RE5, interventions and
RE5 mod routing, including preparation without effects. All three ARM64 ABI tests pass, including non-Chris bootstrap,
generation mismatch, refusal/replay and preserved player state.

This does not deliver Merc3D/RE4 VR flashes, arbitrary weapon construction,
all-QTE bypass, mine/grenade roulette or map-click enemy diversion. Those
requirements remain open. Class tables are pinned for all ten characters;
that does not claim live gameplay acceptance for every character.
