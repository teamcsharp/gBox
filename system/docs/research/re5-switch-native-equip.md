# RE5 native weapon-change requests

GBox tickets 6104 and 6106 request switching weapons without opening inventory.
The Switch build EBFFDB223149A725A93CD9B60979F6AA uses native action 20 for this:
the player action table is at +1B38, requested action at +1B40, pending byte at
+1B4C, current action at +1B60, and target inventory grid at +3F70. Native action
init/update/apply at main+96B000 / 96B430 / 96B900 reaches 7AB380, which performs
the game's hand/model lifecycle. The action vtable is main+1C7F598.

The writer validates the build, playing phase, native owner/context, player and
weapon generations, slot identity, item class, idle motion, pending action and
request overrides. Preparation cells are checked before each write; the pending
byte is published last. A published request is never rolled back or replayed.
Readback requires the same native object and generation, the game's unique held
slot, no pending request, and completion of the equip action. Separate process
memory operations are not atomic with the game thread.

The bot translates supported gun/grenade/mine quick-slot intents into this native
request and suppresses their D-pad input. The flash controller can also select a
center-slot flash grenade. Busy/refused requests do not fall back to inventory.
Prompt and menu directions are preserved. Healing items retain their existing
quick-slot path because their native lifecycle has not been validated here.
Operator control and modifications-off disable native requests.

Live trial 2026-10-29: owned Spark session
`8b14a71472484560-d5e3ec9d7aa94c9b`, Citron PID 1007275 (birth 1793304348.3),
player generation 36. A single magnum 010B/grid 1 request progressed requested ->
waiting -> equipped (`uWp0b`) in approximately 411 ms. Five bounded writes totaled
17 bytes: target grid, previous/reset/request cells, then the pending byte.
No inventory slot, hand/model object, active pointer or executable code was
assigned. Earlier busy-animation trials refused without writes. These recorded
identities are historical evidence, never authorization for a later write.

Validation: 109 tests passed across RE5 equip, main driver, rampage, mines, and
emergency-flash suites. The live trial verifies native hand attachment; it does
not establish firing damage, target accuracy, an instant native flash blast, or
twenty grenade births in two seconds.

## Repeated center-slot throw refusals, 2026-11-13

RE5 round `4d2c85b3fbfe48b88643928c9fcea29a` repeatedly selected hand grenade
`0x106` in grid 4. Its native request was recorded waiting at
1794585671.503, then `unknown/preparation_changed` at 1794585672.634. Later
throw attempts repeatedly returned `previous_request_unconfirmed`. The throw
machine ignored that terminal receipt and spent its full two-second equip
window holding neutral before each abort. These were center-grid requests, so
the quick-slot D-pad fallback could not resolve them. Spark evidence is in
`analysis/merc-tuning-20261113/re5-4d2c-grenade-equip-windows.json` and the full
`post-dd05a9ef-4d2c85b3fbfe48b88643928c9fcea29a-audit.json`.

The throw policy now releases combat immediately on that explicit permanent
refusal and remembers all refused grenade IDs for the exact round/player/life.
Another weapon request cannot erase this history. Unheld refused grenades are
excluded from subsequent choices; other available kinds remain eligible. A
fresh live observation of the same owner's held grenade allows using it
without replaying native attachment. A new round/player lifetime also begins
fresh admission. Native uncertain-request locks remain unchanged. Deferred
requests that have not reached permanent refusal keep their bounded admission
window. This repair removes repeated futile waits; it does not establish the
cause of the original ambiguous publication or claim a successful throw.
