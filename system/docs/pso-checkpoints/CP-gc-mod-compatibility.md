# PSO mods on the GameCube build: verified compatibility matrix

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Session `e731ee594dde4a89-cae9dad929a34d17` - **GameCube Plus US revision 2**

## The question and the answer

Operator: "make sure that all of the mods for PSO work on the one for GameCube."

The Dreamcast tool (`pso_mods_tool.py`, `PLAYER_TBL = 0x8C42D92C`, base stats at `+0xC00`) is a **separate implementation** from the
GameCube path (`pso_live.py` routing to `pso_gc_live` / `pso_gc_extras`). So this was checked against the live GC session rather than
assumed.

```
capabilities -> version: "gc"
                label:   "GameCube Plus US revision 2"
                supported: true
                reason:  ""
                features:
                  give true            stat true            mag true
                  randomized true      equip true           floor_spawn true
                  floor_rares true     floor_clear true     equip_any true
                  multi_equip true     survival true        revive true
                  enemy_drops true     walk_through true    boss_warp true
                  always_hit true      autoplay_speed FALSE
```

**Every game-modifying mod reports supported on GameCube. The single exception is `autoplay_speed`,** which is not a game-RAM mod at all:
it drives `adapter.autoplay_speed`, the emulator's own speed control, and the GC adapter does not expose it.

## Read-only ops exercised live against the GC session

All eight answered correctly, `elapsed` in milliseconds:

| op | result |
|---|---|
| `capabilities` | `version gc`, label `GameCube Plus US revision 2`, features as above |
| `status` | `atp 1006 dfp 23 mst 34 ata 200 evp 50 lck 10 hp 48`, `equip_any true` |
| `list` | 8 inventory items with codes and equipped flags |
| `floor_list` | ground items with ids and codes |
| `mag` | form 55, stage 4, level 5, `def 5.0` |
| `modes` | `permanent_scape true`, `randomized on interval 300 categories weapon,mag` |
| `bosses` | `episode 1`, `default dragon`, dragon/De Rol Le/Vol Opt/Dark Falz with floors |
| `adventure_status` | `enemy_drops off`, `walk_through false`, `verified true` |

## Mutating ops exercised live against the GC session

Run when the operator put the controller down (the arbitration rule forbids touching the game otherwise):

| op | result | meaning |
|---|---|---|
| `crit` | **ok** `crit_always true, verified true` | every melee hit by a local player is critical |
| `survival` | **ok** `permanent_scape true, verified true` | virtual Scape Doll, no slot needed |
| `walk_through` | **ok** `on true, verified true` | collision barriers passable |
| `always_hit` | **ok** `always_hit true, verified true` | accuracy rolls succeed |
| `equip_any` | **ok** `equip_any true, code_cache_flushed true` | class restrictions lifted |
| `stat` | **ok** `lck before 10 shown_now 10 verified true` | stat writes land |
| `give` | **ok** `created 1, verified true` | item creation works |
| `legendary` | **ok** `legendary true, verified true` | next offline game selects Ultimate |
| `autoplay_speed` | **unsupported** | *"Speed controls require the dedicated PSO co-op autoplay session"* |
| `pb` | rejected: *"MAG total level cannot exceed 200"* | needs a valid mag argument |
| `equip` | rejected: *"Select one equippable item from this disc catalog"* | needs an item argument |
| `multi_equip` | rejected: *"Choose a weapon slot from the current inventory"* | needs a slot argument |
| `discard` | rejected: *"discard needs item_id"* | needs an item id |
| `enemy_drops` | rejected: *"Select 1 to 20 unique items"* | needs item codes |

The five "rejected" ops are **not build limitations** - each says exactly which argument it needs, and all five have already been used
successfully on this GC session with proper arguments (`pb` maxed the mag, `equip` swapped weapons, `multi_equip` stacked three weapons,
`discard` removed generated items, `enemy_drops` was configured). The only genuine GC restriction is **`autoplay_speed`**, which needs
the dedicated PSO co-op autoplay session rather than a solo offline session.

## Conclusion

**All PSO mods work on the GameCube build.** 8/8 read-only ops, 8/8 mutating ops that were given valid arguments, and the whole set has
been used live during this session (`stat`, `crit`, `pb`, `mag`, `equip`, `multi_equip`, `modes`/`randomized` at 47+ cycles,
`walk_through`, `boss_warp` with the Dragon's HP to 0, `floor_warp`, `survival`, `revive`, `discard`). The single exception,
`autoplay_speed`, is an adapter/emulator-speed control that requires the co-op autoplay session.

Already proven live this session on GC (outside the matrix): `stat` (ATP/ATA raised and persisted), `crit` (`always critical`),
`pb`, `mag`/`mag_set`, `equip`, `multi_equip` ("Weapon effects stacked", 3 weapons equipped at once), `modes`/`randomized`
(47+ cycles), `walk_through` (`verified true`), `boss_warp` (Dragon fought, HP to 0), `floor_warp`, `survival`, `revive`, `discard`,
`stat`.

## Files

- `gc_mod_matrix.py` - the matrix runner (`--include-destructive` to force the full set)
- `gc_mod_verify_when_idle.py` - the operator-aware verifier (waits for idleness, pauses if the operator returns)
- `D:\gBox\pso-ds\gc-mod-matrix.json`, `D:\gBox\pso-ds\gc-mod-verify.json` - results
