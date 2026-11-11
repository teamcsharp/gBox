# Round 258: input delivery fixed, attacks verified, self-play making progress

Session `25cacd834981410c-b3ca7fc2a1864b4c` — operator-owned, floor 1.

## The real fault was input delivery, and it was measurable

A held "up" moved the character **0.0 units**. The diagnostic explained it:

```
session pid: 45920        <- the emulator
target window: 7935766    <- the gBox app shell
window title: "gBox"      owner pid: 60304
raised: True   win_input_in_front: True
send up held 1.0 s: True   ->  moved 0.0 units
```

With the game **docked**, the emulator has **no top-level window**: `EnumWindows` only walks top-level windows, so it found the shell that hosts
the game, raised it, and every key went to the shell. `game_input.app_window()` now also walks **child windows** by pid
(`EnumChildWindows` over each top-level) and prefers the emulator's real render window. After that change the same test moved the character
**2.95 units** - input was reaching the game.

## Attacks work; the problem was range

The engaged Lappy sat at **HP 30** through every form: quick tap, held press, and "step toward then press". Movement worked, so it was not input.

After unequipping the extra copies (the rotation had left one weapon equipped) and swinging at **5 units**, the enemy went **30 -> 0**. So:

* melee needs roughly **<= 5 units** - self-play was attacking from 8-13;
* the fight loop's approach tolerance is now **4 units** instead of 8.

## Self-play is progressing

```
16:10:45 === self-play on floor 1, 11 rooms in the graph, visited [0, 1, 5]
16:10:45 entered room 4 at (292,25)
16:10:56 enemy TObjEneLappy at 6 units - engaging
```

Four rooms visited (0, 1, 5, 4), every entry and fight written to `selfplay.jsonl`. The give-up rule also fired correctly once:

```
16:08:36   target survived - skipping it for 45 s
```

Its one flaw: the skip is keyed by **class + position**, and the enemy moved, so a moved enemy is re-engaged. Keying by class is the fix (the
patch for it failed to apply through the shell this round; it is a one-line change for the next).

## What this changes for CP17

The warp scan found nothing while the character sat in one room. Now that self-play is actually **moving between rooms**, `warp_watch` has a real
chance of catching the area warp when its room streams in - which is the mechanism that replaces the disproved (133,-48) theory.
