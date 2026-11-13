# The Ultimate wall, measured

## What the numbers say

On Ultimate, in the Forest, the ordinary enemies carry **1556 HP**:

```
player: (263, -297) | enemies: [('TObjEneBeast', 1556), ('TObjEneBeast', 1556)]
```

and the character is **level 5 with 68 HP**. Teleported to **8 units** from one - well inside the game's own 12-unit envelope - and swung twelve times:

```
swing  1: enemy hp 1556 | dist 15.2 | me hp 34
swing  2: enemy hp 1556 | dist 81.5 | me hp 68
swing  3: enemy hp 1556 | dist 91.8 | me hp 68
swing  4: enemy hp 1556 | dist 65.8 | me hp 34
```

**The enemy never loses a point, and the character is thrown 80 units away between swings.** That is not a targeting failure and not a range failure - at 8 units it was optimal. It is a level gap: **level 5 against Ultimate content.**

Switching the difficulty global to 0 does **not** retroactively change already-spawned enemies (`BEFORE 1556 -> AFTER 1556`); it applies to rooms loaded afterwards.

**PSO itself gates Ultimate behind level 80.** The launch config asked for Ultimate and the bot now writes `0x805D5550 = 3` every session, so the configuration is correct - the character is not.

## So the honest answer to "have the bot fight and destroy those enemies"

**It cannot, on Ultimate, at level 5.** Not because the swing fails - a verified hit landed earlier (`TObjEneLappy HIT: 30 -> 1`) - but because 1556 HP against ~1 hit per approach is thousands of swings, while the character dies in three hits and revives at 68 HP beside the same beast.

The path that actually completes the game is the one PSO intends: **level on Normal until the character can survive Ultimate**, then switch. The bot has every mechanic for that now.

## Everything else in the run worked

```
[22:36:28]   walk_through : succeeded
[22:36:30]   give 009d00: succeeded     <- DARK FLOW
[22:36:31]   give 003200: succeeded     <- TSUMIKIRI J-SWORD
[22:36:33]   give 004400: succeeded     <- RED HANDGUN
[22:36:34]   survival : succeeded
[22:36:34]   difficulty: already Ultimate
[22:36:36]   floor_rares: succeeded     <- a rare spawns on the floor
[22:36:37]   enemy_drops: succeeded     <- every enemy drops from the rare pool
[22:36:37]   gates: floor 1: gates already open
```

**Rares are on** (`floor_rares` with `character_class=HUmar` returned `{"codes": ["008403"], "spawned": 1, "verified": true}`), **enemy drops cycle through the rare pool**, **Ultimate is set**, **doors are unlocked in RAM**, and the **reticle rule** is in: anything actionable within 12 units gets `b` then `a`, with townsfolk excluded by class.

## Also in this round

**Traps are destructibles now** - any class containing `Trap` is hit alongside `Container` and `Capsule` - and the **reticle rule** presses `b` then `a` for anything actionable within 12 units (enemies, objects, gates), **never for NPCs**, because an NPC conversation locked the character earlier in the session (*"Ah, I miss her…"*).

**Boxes break but their tables stay stock** - the tool says so itself: *"Boxes are unchanged"*, and `rare_drops` is Dreamcast-only. The rares come from `floor_rares` and `enemy_drops` instead, both of which work here.

## Recommendation

Run the bot on **Normal** so it can actually kill (60 HP enemies vs a landing swing), accrue levels, and switch `0x805D5550` back to **3** when the character can survive. I can make that switch automatic on a level threshold if you want - say, level 20 to try Ultimate, 40 to stay.
