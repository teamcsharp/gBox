# PSO session controls

The PSO panel appears in the running game's session sidebar, and in the desktop game's Items menu. Commands are
pinned to that session's worker. The catalog can be browsed for Dreamcast Ver. 2 and GameCube Episode I & II;
live native mutations support US Dreamcast Ver. 2 and **GameCube Plus US, GPOE8P disc 0 revision 2 (3OE2)**.
GameCube uses its own PowerPC routines and revision guards. Other revisions are refused. Episode III is a different
game and does not show this panel.

Item browsing, native actions and the shared equipment default load independently.
A missing preferences endpoint during a backend update does not disable search,
filters, selection or supported live actions. An unknown preference is shown as
indeterminate, with an explanation and Retry loading. Unsupported revisions can browse/select
items and save the shared default, but native actions stay disabled with a visible revision-specific explanation.

## Available implementation

- Search/filter the disc's item database, select up to twenty items and drop those exact items beside the player.
  The count slider controls a random scatter; an explicit selection drops one of each selected item. Spread controls
  the radius in game world units. Clear removes only gBox-created floor items.
- Select one catalog item and use **Add selected to inventory**; Count controls the number of new entries.
  GameCube uses its native item creation/insertion routines and refuses a full inventory before creating objects.
- Scatter random rare weapons compatible with the selected class, optionally limited to the highest base-star tier.
  Each weapon can be spawned at its own maximum grind. Class eligibility does not imply the player meets its ATP,
  MST or ATA requirements. PSO weapons do not have an arbitrary item-level field.
- Equip-any is a shared default across PSO builds and PCs (`GET/POST /api/pso/preferences`, default true). A worker
  boot watcher applies the guarded equip patch and rechecks after reset/state loads. A manual panel change also
  flushes Flycast's JIT through the existing PSO tool. GameCube executes guest `dcbst/sync/icbi/isync` to invalidate
  the already-compiled equip-check block, without a save-state round trip. The boot watcher never loads or saves a state, sends pad
  input, or blocks a launch. If the preference endpoint cannot be read, it does not guess and apply a default.
- Inventory weapon rows offer Stack equip and Unstack using the game's own equip/unequip callbacks. Equipment
  effects stack; the engine continues to draw one weapon, so this does not implement dual-wield animations.
  Native equipment callbacks can enforce the engine's class stat caps when changing equipment.
- ATP/MST/EVP/HP/DFP/ATA/LCK numeric editors use the existing native recompute/read-back path, bounded 0–9999.
  Right-clicking a stat focuses its editor. This is not automatic identification of arbitrary screen text or RAM.

The Dreamcast dispatcher reuses an online network handler and is for **offline sessions**, as documented by
`pso_mods_tool`. The GameCube dispatcher requires offline free-play phase `0x0E`, a matching player vtable,
all native entry fingerprints and an unused scratch region. It preserves the original player update and executes
native actions on the emulated game thread. Online sessions are refused.

## Immediate session commands

On the supported GameCube revision, **Equipment player** selects player 1 or player 2 for
inventory, normal equip, stats, MAG changes and that player's timed equipment randomizer.
The second actor must match the native player table, class, vtable, entity ID and entity table.
Player-two writes additionally require this session's successful two-controller movement probe;
an actor that is only structurally detected is shown as unverified and its controls stay disabled.
Each mutating command pins its actor, and each randomizer keeps separate ownership and reset markers.
Old generated-item IDs are never used to clean up a different recreated actor. Long-lived read-only
readers can follow valid player recreation across area transitions.

Shared code patches, survival, floor-item operations, enemy-drop policies and stack-equipping remain
explicitly player-one/shared controls. Selecting player 2 disables those operations rather than
redirecting them to player 1. Normal **Equip selected item** and inventory-row **Equip** use the
selected actor's native equipment callback and verify the equipped item afterward.

The **Autoplay speed** slider appears only for the dedicated two-player campaign session. Its choices
are 1x, 2x, 4x, 8x and 10x, starting at 1x. The panel separates the requested multiplier from a fresh
native clock measurement: requesting 10x can correctly show a measured 1x. The guarded sampler uses
two native timebase readings with bounded timing uncertainty; hotkey delivery never proves throughput.
`measurement_verified` means that a valid rate was measured, while `achieved_verified` additionally
requires the full measured interval to fall within 5% of the requested rate. At the 1x baseline, or
without a valid sample, the panel reports that no recent measurement is available.

The existing five-second mode refresh carries the cached measurement without another native call.
The panel deducts the entire request round trip from its remaining two-second validity, then labels
an expired value as historical/stale. Pause, reset/restore epoch changes, unknown or changing speed,
unverified player mapping, or a mismatched request suppress current measurement claims. Reconnect
results with unknown transport age cannot revive a measurement. These paths have capability and
caption regression tests; they are not evidence that this session achieved any particular speed.

The eight-second admission deadline remains; an already-started
speed command has a 45-second server response window, a 50-second desktop bridge timeout and a
55-second UI timeout, without automatic retries. A full Windows speed decrease can take over twenty
seconds because each hotkey and modifier must be released between steps. These selected-player paths have guarded-memory and UI regression
tests; player-two live writes remain unavailable until the session probe establishes controller mapping.
Player-two mutations and speed requests retain session receipts and audit records. They are excluded
from the legacy gameplay-action replay journal, whose schema does not preserve their target or multiplier.

GameCube survival, Legendary/Ultimate defaults, timed rare equipment and live MAG
editing/feeding are described in [PSO survival and MAG controls](pso-survival-mag.md).
These additions retain the same exact-revision and offline guards.

Selected enemy loot, reversible collision bypass and explicit boss-area travel are described in
[PSO enemy drops and traversal](pso-enemy-drops-traversal.md). These also apply saved policies to supported custom builds.

Both clients send `pso_controls` through `/api/sessions/{sid}/rpc`, rather than submitting a worker job.
Builds do not sit ahead of a button click. Each request carries a unique command ID and an eight-second admission
deadline. Worker execution is serialized per session; a busy session refuses another mutation instead of queuing it.
Successful and failed receipts are retained in a bounded session cache. Reusing an ID with different input is refused.
Neither the UI nor the worker automatically retries a timed-out native action: its outcome may be unknown.
Expired requests are withdrawn and late receipts discarded. Catalog lookups are cached for five minutes and bounded
to three seconds on a miss. The worker checks the admission deadline after catalog access and before mutation.

The server audits commands and requires `memory_write` for mutations; the worker checks the same permission.
The server also checks the worker's immutable loaded-source hashes. An old worker receives a clear safe-refresh
message rather than a command it cannot execute. The panel reports measured worker milliseconds after acknowledgment.

## GameCube verification

The owned `PsoV3.dol` SHA-256 is
`1f80fb82b41c05b26b6d0545b1ba9c0aa60b52e6589cf32fbb2ffe644692a61a`.
Native entry points and structures were independently checked against that executable and an isolated copy of a
Episode II VR Temple Alpha save state in Dolphin 2609a. The test used its own display, user directory and memory-card paths.
No operator session or original save was modified. No game binary, save or personal asset is included in source.

Observed native checks: real floor objects and their IDs/codes in the floor table; gBox-only clear; inventory insertion;
equip eligibility denied → allowed → denied with a warm JIT; all seven displayed stats set/read back at 900;
weapon effect stack/unstack with the visible weapon slot unchanged. The first inventory-read plus two-item spawn
sequence measured 48 ms in that isolated session. This is a measured example, not a latency guarantee for every PC.
The HP screenshot shows the game's own `27/900` HUD. Actual item pickups, all floor transitions, every catalog item,
other disc revisions and online play are not exhaustively verified.

## Disc metadata and safety

Catalog schema 2 adds base stars, rarity, class usability and maximum grind/stat requirements. It reads fixed,
version-specific PMT record sizes instead of inferring a stride from names. REL relocation targets bound the
arrays, so late weapon classes are included. DC implicit placeholder entries apply to armor/units/mags, not
weapons. The cache filename includes the schema version; the old name-only cache cannot silently satisfy a
class-aware request. On the owned discs this yields 545 Dreamcast and 1,257 GameCube named entries.

Equipment requires all three class-attribute bits (profession, race, sex), rather than any one matching bit. Rare
means at least nine base stars; mags use the native rare-mag index threshold and tools use their rare-item flag.
Name capitalization is not used by the new scatter. The original legacy
`item_set rare=true` helper is unchanged. Automatic class selection requires a bounded DC saved-character pointer,
the save structure signature, and a class index 0–8; otherwise the operator selects a class explicitly.

Concurrent PSO tool calls and boot patches serialize by session. All random-scatter item codes are validated
against that disc's catalog before installing a dispatcher. Spread rejects nonfinite or out-of-range values.

Binary format facts were cross-checked against the independently maintained [newserv ItemParameterTable
implementation](https://github.com/fuzziqersoftware/newserv/blob/9b075e4d125edac2a8740dc90b013e6e41322e1f/src/ItemParameterTable.cc),
its [class flag definitions](https://github.com/fuzziqersoftware/newserv/blob/9b075e4d125edac2a8740dc90b013e6e41322e1f/src/ItemParameterTable.hh),
the [REL footer layout](https://github.com/fuzziqersoftware/newserv/blob/9b075e4d125edac2a8740dc90b013e6e41322e1f/src/CommonFileFormats.hh),
and [saved character layout](https://github.com/fuzziqersoftware/newserv/blob/9b075e4d125edac2a8740dc90b013e6e41322e1f/src/SaveFileFormats.hh).
The Python parser is an independent implementation of those format facts; no upstream source or game data is bundled.

## Reconnect an uninitialized mod panel

The reload icon beside the PSO connection status sends a session-pinned **Reconnect PSO controls** command over the live channel. It remains reachable while the initial version check is stalled. Client reads have a timeout; newer recovery results replace stale initial responses. Recovery diagnostics identify the memory connection, executable/player check, native dispatcher and saved defaults.

On Windows Dolphin, recovery opens a fresh memory handle to the same live process, verifies the PSO header before swapping handles and discards stale RAM mapping caches. It does not reconnect the detached Windows GDB stub. Healthy RetroArch memory connections are reused; Linux Dolphin can reconnect its configured localhost debugger. The complete revision/offline/player guards still apply before native writes.

Recovery checks pending commands before installing an idempotent hook and refreshing saved defaults. It preserves pending commands, never replays an item/stat operation, and refuses unknown hooks. A paused game stays paused, with a request to resume it before reconnecting. Recovery does not close, reset, restart, save or load the game. Unsupported revisions, disconnected workers and workers needing a code update produce explicit diagnostics; re-hooking cannot turn an unverified ROM into a supported revision.

## Default attack accuracy

On the verified GameCube Plus US revision 2, **Default: attacks never miss** starts enabled and is shared across supported PSO builds. It bypasses the local player's native random accuracy miss checks rather than changing ATA or enemy accuracy. Normal range, contact/hitbox checks and invulnerability still apply. The toggle persists the preference and applies it through the acknowledged live channel. Executable fingerprints and instruction-cache publication guard enabling/disabling it. Dreamcast accuracy remains unavailable until its separate native routines are verified.

## Remaining requested native work — not implemented by this panel

1. Additional GameCube revisions and progression patches. The native controls above are verified only for 3OE2;
   they do not imply compatibility with every Episode I & II disc.
2. Start + L / R imported wardrobe. This needs native multi-donor resource banks and a verified reload path, not
   changing a stock costume number or drawing an overlay. Sources requested: Sonic, Mario, DOA2, SC2 and Twin Snakes.
3. Teleporter access to every area, with per-difficulty/episode progression flags and a reversible original snapshot.
4. NPC picking and world placement, retaining entity identity/room checks and collision-aware placement. Existing
   semantic profiles are read-only evidence, not permission to write arbitrary pointers from a screenshot.
5. NPC model bindings for every NPC and shopkeeper, a seeded random Sonic/Mario/DOA2/SC2 cast, and shopkeepers
   specifically mapped to Sonic Adventure 2. Do not silently replace the player slot when an NPC slot is unknown.
   Right-click/Ctrl-click must retain the picked NPC's identity through retarget/build/apply.
6. Arbitrary screen-parameter identification via Ghidra plus a guarded live RAM editor (type, address provenance,
   before/after values, rollback). Ghidra is a static analysis tool; clicking pixels alone cannot establish a RAM address.

No new imported-character ROM is delivered by these live-control changes. The broader PSO feature suite remains
in progress until the wardrobe, teleporter and NPC parts have been implemented and tested in game.
