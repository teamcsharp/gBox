# Agent Under Fire live controls

`auf_live` targets the owned GameCube USA **GW7E69 disc 0 revision 1** executable
(Bond.elf SHA256
`1a9c0d19fb7bab09c2fd6ef56bd8158e88e507f72ba982d0ca292bc8145e716f`).
Its addresses do not apply to the Xbox/PS2 versions or other 007 games. Native
revision, single-player, living on-foot player and cinematic guards are checked
before actions. Vehicle sections and multiplayer remain separate systems.

The catalog aliases `65b7187589166b26` (HyperSpin GCZ) and `a8a1484cf7ac7ce1`
(owned uncompressed GC ISO) were compared by bytes. Both have disc header
`4757374536390001`, the Bond.elf SHA256 above, and main.dol SHA256
`2f082f5b7b3f060746ed28d3ee8970eec2e8613f97136733b2e374173e23d26b`.
Their five executable payloads match, despite different FST directory layouts.
Both aliases use the same exact live guards; a matching game title alone never
authorizes an unreviewed catalog entry.

The adapter implements walk-through-walls, named loaded-weapon insertion, native
level-section completion, unlimited reserve ammunition and P2K primary-fire projectile
replacement. A registered adapter or passing unit test does not publish these as
runtime-verified controls. `reviewed_profile` creates a publication candidate only
for operations backed by separately registered analysis and native runtime
artifacts. The shared [live-controls contract](live-controls.md) supplies Mods
switches, bounded item dropdowns and scene/revision checks after publication.

Item choices are restricted to reviewed weapons packaged in the currently loaded
mission. An unavailable MRL-22 projectile or unequipped P2K keeps rocket-pistol
unavailable. The secondary firing mode and permanent emulator settings are not
changed. Switches read back native state; disabling restores the checked original
mapping/value. Leave noclip in open space before disabling it.

Commands expire, have unique IDs and never retry a failed/uncertain native call.
The game-thread dispatcher checks the player and in-game deadline, clears a
pending call before entry, and returns an acknowledged result. A full verification
receipt must distinguish native command acceptance from the resulting gameplay
effect. Runtime acceptance must come from an isolated test session and private
save data, preserving any operator session and personal memory card.

Level completion follows the authored `TriggerLevelExit` sequence: player
`EndLevel` at `0x800e6400` records statistics, then the fingerprinted
`UI_CompleteSubmap` at `0x8001a314` queues the deferred UI transition. Calling the
statistics routine alone does not leave the section. The imported callback at
`0x803f0154` must match, and pending UI transitions prevent new native commands.
The statistics flag can persist across sections, so one-shot retry protection
uses a checked mission identity/epoch instead of requiring that flag to be zero.

[Native validation](auf-live-validation.json) records the actual wall crossing,
weapon insertion, reserve-ammo retention, moving rocket projectile, restoration,
and first corrected section transition. It also records the inconclusive extra
cross-section probe separately from those demonstrated effects. Automated checks
do not substitute for native gameplay evidence.

## Next checkpoint remains unavailable

The owned on-foot campaign census decoded the BSP entity lump and compiled script
resources for **20 playable NGC campaign sections plus the frontend**. No authored
`ProgressiveStart` or `TriggerCheckpoint` entities were found. Most sections have
one `info_player_start` and one `trigger_levelexit`; `carrier1` has two named
alternative starts, without an established ordered checkpoint graph. Racing/rail
vehicle data outside these NGC packages was not assessed.

`ProgressiveStart::SetSpawnpoint` at `0x800ea700` copies an entity's target name to
the selected game spawnpoint; `Player::ChooseSpawnPoint` at `0x800e6960` uses the
native spawn selector. Neither establishes the next ordered mission checkpoint.
The separately named `TriggerCheckpoint` class has timed challenge state and
failure callbacks. Its name does not prove mission autosave behavior.

Consequently `next_checkpoint` reports unavailable and applies no teleport. An
arbitrary nearby trigger, an alternative starting location, or the level exit
must not be presented as a verified checkpoint warp. The independent finish-level
action does not satisfy that missing capability.
The published candidate records this as a scoped `checkpoints` assessment so Mods
can show the investigated limitation instead of treating an installed tool as a
working warp button.

Static census helpers/results are kept in the private `gbox-data` analysis area;
owned executables, full scripts and personal save data are not shipped in source.
The general discovery objective remains active for other decomposed games, with
unknown and inapplicable operations recorded separately from verified controls.
