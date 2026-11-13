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

The publisher now distinguishes a stale initial witness before any writer was
called from an attempted write with an uncertain outcome. A zero-write refusal
reports `native_not_submitted` and can capture a new owned witness later. The
attempt is recorded before invoking each writer, so an exception after memory
may have changed remains uncertain. No published request is replayed. Forty-six
equip/throw regressions cover initial witness changes, failed writers and native
consumption of the pending byte. This fixes a definite false-lock path in the
source; the old receipt did not retain enough detail to prove this was the
specific cause of round `4d2c`'s original failure.

## Next-round grenade supply

The fresh cb7 round `fb229d3ded7641e28f0bf669ae3a2220` made no ordinary
throw attempts. Its 295 read-only native samples contained mines, guns, ammo
and heals, but no type-1 WP06/WP07/WP08 grenades. The template composer selected
an existing grenade before an empty or ammo record when preparing mines,
removing the very item the throw policy needed. Native movement mines do not
require equipping or deleting those grenades.

The full-template mine path now preserves existing grenades. It uses an empty
record or ammunition for the mine, retains guns/heals/knives, and adds a hand or
incendiary grenade when no damaging throwable remains. The round's existing
random seed selects that added kind. A free inventory grid is preferred; only
with infinite ammo enabled may the grenade replace an ammo record. A full
protected inventory reports missing grenade supply separately from mine
availability. Existing flash grenades remain available. All changes are to
verified Mercenaries templates for native construction at the next round start;
no live item records or object pointers are synthesized. This supplies a
throwable, not proof of a successful throw or grenade swarm.

The supply, composition, mine and modifier checks passed 80 tests. They cover
all 54 synthetic costume descriptors, exact restoration, protected full
inventories, non-overlapping grids and preservation of existing grenades.
