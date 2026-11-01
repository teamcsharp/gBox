# Merc live weapon controls

The stream weapon picker exposes an infinity button with pending, confirmed On/Off, and error states. Confirmation comes from the active title's native readback. Unknown or stale inventory data does not make a supported weapon unavailable; explicit native unavailability does, with its reason shown. Each request is tied to the selected live session.

A chosen primary weapon is held for 180 seconds. A known-empty or absent selection may temporarily yield to another existing loaded gun. Verified infinite ammo preserves the choice across a transient zero-round snapshot, while RE6 still waits for actual rounds before firing. Automatic recovery does not create ammunition or weapon objects.

RE4, RE5, and RE6 expose guarded infinite-ammo status and setters. They serialize with their native control paths, recheck player identity and operator ownership, and require readback. RE5 reports its native no-spend flags. RE6 reports magazine-maintenance configuration and actual magazine counts. RE4's verified dispatcher and supported grenade types are described in [RE4 live controls](re4-live-controls.md).

RE4 and RE5 can construct supported weapons through their existing guarded native transactions. RE6 shows its full named catalogue, but disables entries whose native weapon objects are absent or whose lifecycle is unsupported. Constructing those RE6 objects is not implemented. The grenade chooser displays each title's supported types; RE4 hand-grenade blasts require verified unlimited health. The number of blasts is title-dependent.

RE5 sniper IDs `05`, `1C`, and `20` use the existing animation-scale mechanism at 30 during verified shot motion. RE6 sniper records `09`, `0A`, `0B`, and `2A` use their native interval divided by 30. Disabling the mod restores native values. These are configured multipliers, not measured claims of thirty times as many emitted bullets.

This update also retains the reviewed RE5 firing and flash corrections: aim acquisition must reach the target before firing, recoil keeps useful aim feedback, and ordinary automatic flash use stays disabled. RE6 time bonuses use melee only, while finite-ammo recovery verifies which equipment request completed and can try another owned loaded weapon.

Native control module changes require a worker process restart. Publishing source does not itself activate these controls or restart a running game. The review package records isolated Python and Node validation; browser visual acceptance remains unverified because the local browser harness did not complete reliably.
