# CP17 round 190: navigation converges, the enemies are what stops the walk

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Live: session `e731ee594dde4a89-cae9dad929a34d17`, Forest 1 (floor 1), character BQF Lv 1

## What worked

- `floor_warp {"target": "1"}` -> Forest 1, `survival {"on": true}` on.
- **The collision navigator converges over long distances**: `pso_walk.path(map_forest01c.rel)` + `pso_kbwalk.walk_path` took the
  character from **708 units to 163 units** from the key door, round by round
  (`708 -> 643 -> 576 -> 513 -> ... -> 163`), where the probe-only walker had wandered the wrong way entirely.
- The plane's randomizer ran the whole time: **`cycles: 8`**, message `Equipment randomized`, categories `[weapon, mag]`,
  interval 300 - and the inventory did not grow (the generated item is replaced in its slot).

## What stopped it

Forest 1 at **Lv 1** is a hostile place: a Booma stays on the character and every hit interrupts the stride, so the same navigator
that converged once then wandered (distances rose from 446 to 633 while the character was being knocked around). Measured HP over a
few minutes: **10/40 and 20/40 alternating** - `survival`'s native revival returns the character at partial HP, not full, so the
character neither dies nor recovers while the Booma keeps hitting.

`pso_controls floor_clear` does not help: it answers `{"removed": 0, "verified": true, "scope": "only gBox-spawned items"}` - it
clears gBox-spawned **items**, not enemies.

## What this means for the accept

CP17's remaining obstacle is not the door and not the navigation - both are solved. It is **surviving the walk at Lv 1**. The
cheapest fixes, in order:

1. **level up first** (the enemy that blocks the walk is worth EXP: an earlier character reached Lv 3 / 365 EXP by killing Boomas);
2. fight the blocker before walking (the chase loop needs to actually close - the Booma keeps its distance at 60-100 units);
3. or use `walk_through` (collision bypass) so terrain cannot pin the character while an enemy interrupts.

The accepting run still needs: reach a `TObjDoorKey`, press A once, walk through, and see `0x805D5FC0` change **with no
`floor_warp`** after the start.

## Revival is a partial heal (measured)

`survival` brings the character back at **10/40 or 20/40**, never full. It keeps a Lv 1 character alive indefinitely in Forest 1 but
does not replace a real heal (hospital or mate).
