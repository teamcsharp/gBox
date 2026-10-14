# PSO session controls

The PSO panel appears in the running game's session sidebar, and in the desktop game's Items menu. Commands are
pinned to that session's worker. The catalog can be browsed for Dreamcast Ver. 2 and GameCube Episode I & II;
live native mutations currently require the US Dreamcast Ver. 2 executable fingerprint. GameCube never receives
Dreamcast addresses. Episode III is a different game and does not show this panel.

Item browsing, native actions and the shared equipment default load independently.
A missing preferences endpoint during a backend update does not disable search,
filters, selection or supported live actions. An unknown preference is shown as
indeterminate, with an explanation and Retry loading. GameCube can browse/select
items and save the shared default, but live drops and stat/equipment writes stay
disabled with a visible revision-specific explanation. Saving that default never
applies Dreamcast memory patches to the current GameCube game.

## Available implementation

- Search/filter the disc's item database, select up to twenty items and drop those exact items beside the player.
  The count slider controls a random scatter; an explicit selection drops one of each selected item. Spread controls
  the radius in game world units. Clear removes only gBox-created floor items.
- Scatter random rare weapons compatible with the selected class, optionally limited to the highest base-star tier.
  Each weapon can be spawned at its own maximum grind. Class eligibility does not imply the player meets its ATP,
  MST or ATA requirements. PSO weapons do not have an arbitrary item-level field.
- Equip-any is a shared default across PSO builds and PCs (`GET/POST /api/pso/preferences`, default true). A worker
  boot watcher applies the guarded equip patch and rechecks after reset/state loads. A manual panel change also
  flushes Flycast's JIT through the existing PSO tool. The boot watcher never loads or saves a state, sends pad
  input, or blocks a launch. If the preference endpoint cannot be read, it does not guess and apply a default.
- Inventory weapon rows offer Stack equip and Unstack using the game's own equip/unequip callbacks. Equipment
  effects stack; the engine continues to draw one weapon, so this does not implement dual-wield animations.
- ATP/MST/EVP/HP/DFP/ATA/LCK numeric editors use the existing native recompute/read-back path, bounded 0–9999.
  Right-clicking a stat focuses its editor. This is not automatic identification of arbitrary screen text or RAM.

The native dispatcher reuses an online network handler and is for **offline sessions**, as documented by
`pso_mods_tool`. Online play has not been verified. Never apply this dispatcher to an active online session.

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

## Remaining requested native work — not implemented by this panel

1. GameCube revision-specific live ground creation, unrestricted/multiple equip, progression and stat patches.
   The owned Plus disc is GPOE8P revision 2; the executable to analyze is `PsoV3.dol`, not the AppSwitcher main DOL.
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

No new imported-character ROM has been built or gameplay-verified by these UI/catalog changes. The requested
PSO feature suite remains in progress until those native parts have been implemented and tested in game.
