# Round 279: a play loop with one clean contract - the game on screen means the bot plays

## The rule, inverted

The previous play mode fought for focus. This one waits for it:

* the game must hold focus for **1.5 seconds** (so a passing click is not enough) before the bot acts;
* focus leaving pauses it **immediately**, with nothing sent;
* it **never** calls `raise_window` - no focus is ever taken;
* pad activity suppresses it for **thirty seconds**, so the operator's own control always wins;
* the `PAUSED` file stops it outright.

One contract: **the game on screen means the bot plays; anything else means it waits.** No focus war, no stolen keystrokes.

## What it does while playing

1. **Locks one enemy** and keeps it until it dies or is given up on after 45 s.
2. **Closes with short steps** (0.12 s), which also turn the character, since PSO faces the direction of travel - the fix for overshooting a moving target.
3. **Swings continuously** at melee range, or **casts a technique** beyond 30 units, which is what actually reaches that far.
4. **When nothing is alive**, it walks to the nearest room centre on the current floor's map, or wanders on floors with no map.

## Door-aware pathing, and what it changed

`nav_fast.cells` now includes the room mesh's **doorway cells**, because a closed door reads as wall in the static collision while at runtime it opens
and the character walks through. Reachability improved wherever doors were the obstacle:

| floor | before | after |
|---|---|---|
| 1 Forest 1 | 5696 / 5701 | 5698 / 5701 |
| 3 Cave 1 | 13031 / 15576 | 13031 / 15779 (more cells known) |
| 5 Cave 3 | 9934 / 10028 | **10022 / 10116 PASS** |
| 7 Mines 2 | 10270 / 10270 | **10470 / 10470 PASS** |
| 9 Ruins 2 | 8812 / 9799 | 9364 / 10228 |
| 10 Ruins 3 | 15131 / 15824 | 15259 / 15873 |

## State

| item | state |
|---|---|
| play loop | running, waiting for focus - never steals it |
| contract | game focused = playing; unfocused = waiting |
| door-aware pathing | active on all floors |
| Cave 1 | 22 rooms, 16 navigable |
| character | HP 31/62, floor 3, no enemies within 90 units |
| remaining goal item | CP19, one continuous unattended episode |
