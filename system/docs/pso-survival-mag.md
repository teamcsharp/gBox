# PSO survival, Legendary, Randomized and MAG controls

These controls appear in the PSO session sidebar and shared desktop item panel. Native
actions support **GameCube Plus US, GPOE8P disc 0 revision 2 (3OE2), offline free play**.
Other revisions and Dreamcast do not receive these new addresses. Existing Dreamcast
item/stat controls remain available.

- **Permanent Scape Doll** is a virtual auto-revival default for supported builds. The
  local player's guest update calls native resurrection and restores maximum HP/TP on
  death. No physical Doll or inventory slot is required. **Revive now** performs the
  same recovery manually; it does nothing to an already living character.
- **Legendary: start in Ultimate** is an optional shared default. It makes the offline
  difficulty selector offer Ultimate immediately and return Ultimate for the next game.
  Return to difficulty selection or relaunch to start a new Ultimate area. It never
  changes the difficulty of an already loaded field, character level, or saved quest flags.
  Disabling restores the original selector instructions. Only the offline selector's
  three call sites are changed; the shared menu getter is retained for all other menus.
- **Randomized** changes selected weapon, armor, shield and/or MAG slots every **5–300
  seconds**, initially 15 seconds. Choose the character class, select categories and
  turn it on. Moving the interval slider updates a running mode. The owned-disc rare
  catalog and class metadata supply candidates. Native equipment eligibility still
  applies; enable the existing equip-any default to use weapons beyond normal stats.
  A refused equip stops the mode with an explanation rather than reporting success.
- **Equipped MAG** reads the actual equipped item ID. DEF/POW/DEX/MIND, IQ, synchro,
  color and evolution form edits apply after a 350 ms adjustment pause over the immediate
  session channel. Native callbacks recompute level/equipment effects and reload the
  form. Total stat level is limited to 200, IQ to 200 and synchro to 120. Existing Photon
  Blasts/flags and item identity are retained. A changed MAG identity requires a refresh.
  **Feed MAG** applies the game's food table and natural evolution rules. Panel feeding
  supplies virtual food, bypasses the normal feed cooldown and consumes no inventory food.

## Session and storage behavior

Scape Doll and Legendary preferences persist on Spark alongside equip-any. Partial
preference updates preserve the other defaults. The boot watcher applies them to new
supported sessions and rechecks after state loads. Loading new worker code requires a
safe worker refresh and a new game launch. Known version-1/version-2 dispatchers in
older save states migrate to a separate code address, preserving the item-ID counter
and leaving the old compiled code intact. A pending command, unknown hook, modified
vtable or occupied unowned scratch buffer is refused before writing.

Randomized runs on the selected emulator worker even when the panel closes. It needs
one free inventory slot and retains at most one generated item per selected category
between cycles (one temporary extra slot while replacing it). It never removes original
items. Stop restores original equipment only for slots still controlled by this mode,
then removes its tracked generated gear. Manual equipment changes are respected.
Native errors stop cycling without automatic retry; Stop can clean up acknowledged
generated items. A changing marker in save-state RAM detects rewinds/resets and stops
the mode without trusting item IDs from a different branch. Original/restored items
are left intact. The mode does not automatically resume after a worker restart.

The game owns normal character saving. Gear and MAG edits can be saved by the game;
gBox does not create, load or overwrite an operator save slot to apply these controls.
Unexpected process termination may leave generated gear in a saved inventory.

All mutations use the existing serialized PSO RPC channel, revision fingerprints and
`memory_write` permission. Timed work yields to another session command, waits while
the debugger/emulator is paused, and ends with the session. A timed-out native batch
has unknown outcome and is not automatically retried.

## Verification

Tests use a separate Dolphin process/display, copied Forest state and isolated memory
cards. The native checks cover repeated resurrection; MAG stat edits, explicit form
changes, feeding through a level-10 natural evolution; inventory-bounded randomized
gear and original equipment restoration; and reversible Ultimate selector behavior
without modifying the shared menu getter. The timer is exercised at five seconds;
the UI checks live interval changes from 15 to 20 seconds and coalesced MAG edits.
This does not establish compatibility with other discs, online play, every rare item,
every MAG cell/Photon Blast combination, or a complete new Ultimate playthrough.
An additional real save/load check restored a version-1 dispatcher, migrated it while
retaining the old code and item counter, and verified native full HP/TP revival.

The owned executable digest and earlier native controls are documented in
[PSO controls](pso-controls.md). MAG item encoding facts were cross-checked against
the primary [ItemData format reference](https://github.com/fuzziqersoftware/newserv/blob/9b075e4d125edac2a8740dc90b013e6e41322e1f/src/ItemData.hh).
Native addresses, routines and control flow were independently checked in the owned DOL.

[Native validation receipts](pso-survival-mag-validation.json) and
[the labelled browser UI fixture](images/pso-survival-mag-ui.png) accompany this change.
