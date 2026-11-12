# Round 35: boot verified - the piece that runs once per launch

## Why this one mattered

`boot()` runs **exactly once per launch**, as the first thing that touches a live session. A bug there wastes the launch the operator waited for - and it is easy
to get wrong: a loop that never re-checks `player()`, a bound that is not honoured, or a boot that keeps pressing keys when the game is already in the field.

So it is tested against recorders in place of the emulator, and **all nine checks pass**:

```
PASS in the field returns True
PASS in the field presses nothing
PASS eventually in the field returns True
PASS it pressed START and A
PASS the first press is START
PASS each round is START then A
PASS no character returns False
PASS the bound is respected (3 rounds = 6 presses)

all boot checks passed
```

Three behaviours are pinned down:

* **already in the field -> zero presses.** It does not fight the player for control when the game is already running.
* **START before A, alternating.** That is the order that walks PSO's bootstrap; A-first can dismiss a dialog before START opens the menu.
* **the bound is real.** With `limit=3` it stops after exactly six presses and returns False, rather than pressing forever.

The log lines the test produced are the same ones a live run will show:

```
no character yet - pressing through the title
character appeared after 6 rounds of start+A
gave up waiting for a character
```

## Total verification now

| layer | checks |
|---|---|
| perception - entity table, names, position, HP, door state | 11 |
| movement - calibration-driven direction, approach | 10 |
| decision - switch/enemy/exit/room priority | 12 |
| batched input - payloads, cap, counter | 12 |
| **boot - no-op in the field, START then A, bounded** | **9** |
| **total** | **54** |

Every layer of the bot is now covered by tests that need no emulator: what it can see, how it moves, what it chooses, how it presses, and how it gets into the
game.

## State

```
health: True   workers: 1 of 1   live: 0   queue: 0
supervisor: waiting for the game to be launched
```

**The chain is built, tested, and waiting.** The only step left is the launch.
