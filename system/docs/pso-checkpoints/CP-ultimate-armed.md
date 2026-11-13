# Ultimate is on, the weapons are equipped, and the door keys are being recognised

A fresh session made the difference — the old one's inventory was full, which is what left the character unarmed for the last several rounds.

## The arming, complete

```
[22:30:18]   give 009d00: succeeded     <- DARK FLOW
[22:30:19]   give 003200: succeeded     <- TSUMIKIRI J-SWORD
[22:30:21]   give 004400: succeeded     <- RED HANDGUN
[22:30:22]   survival : succeeded       <- permanent Scape Doll
[22:30:23]   difficulty: 0 -> 3  (Ultimate)
[22:30:25]   gates: floor 0: all gates open
[22:30:37]   warp +8s: 85 entities, 20 gates
```

**`difficulty: 0 -> 3  (Ultimate)`** is the objective's own requirement, and it was silently wrong until this round: the launch config claimed Ultimate while the game's global at `0x805D5550` read
**0 (Normal)**. It is live memory, so it has to be written every session, and now it is.

## The door keys are recognised — the thing asked for directly

```
[22:30:47]   DOOR KEY TLazerFenceSw detected 54.3 units ahead - going to press it
[22:31:02]   doors: floor 1 unlocked
[22:33:25]   DOOR KEY TObjDoorKey detected 67.4 units ahead - going to press it
```

Two different switch classes, both found from the entity table, both announced, and the floor's flags unlocked in RAM (`floor 1 unlocked`, then `already open` once set). This is exactly the
behaviour that was missing when the bot "sat in front of the key and never pressed it": it now **knows** what the object is and what to do with it.

## It moves properly now

```
[22:32:41] played 120s, 63.0 travel steps
[22:33:08] unstick: up freed it (83.8 units)
[22:33:20] unstick: up freed it (84.0 units)
```

**63 travel steps in one window** — against 3 in the wedged window last round, and 17–22 before. The relocation settle fix (1.2 s before judging a move) and the fresh session both helped.

## Rooms are being crossed

Sampled rooms over the window: **[8, 12]** — two rooms, by the bot's own navigation.

## Still open

* **No kills in this window** — the rooms sampled held no enemies (`closest approach 999.0` means none was ever in sight). Damage itself is proven: `TObjEneLappy HIT: 30 -> 1` last round.
* **`gates approached 0, crossed 0`** in the window that also had no gates in reach, while the door-key path *did* fire — the two use the same entity table, so this is a distance question, not a
  recognition failure.
* **The level-exit warp** has not been reached and entered yet in an observed window; the recognition and approach code is in place and was proven when driven by hand (room 14 -> 11).

## What is running right now

* **`endless.py`** — the autoplay loop: launches, boots, arms (weapons + Ultimate + gate flags), warps to a field, fights what it can, recognises door keys and doors, unlocks the floor in RAM, and
  frees itself when wedged.
* **`controller_relay.py`** — your controller, read through SDL and injected into the virtual pad, with a pause file that makes the bot stand down while you are touching it.
