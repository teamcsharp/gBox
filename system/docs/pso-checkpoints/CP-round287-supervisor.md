# Round 287: one supervisor instead of competing loops

## The problem this fixes

Repeatedly during this session two or three play loops were running at once and fighting each other for the keyboard - which is how the bot was seen
"standing still" while another loop walked it somewhere else, and why I had to hunt down stray processes so many times.

## `supervisor.py`

It is now **the only thing that starts a play loop**:

1. **Waits for a live session** - with the game closed it simply logs "no live session" and waits, so nothing spins uselessly.
2. **Tests background input rather than assuming it**: with the game unfocused it sends **one key** and measures whether the character moved.
   * **moves** -> `play_background.py`, which needs no focus and never raises a window;
   * **does not move** -> `play_when_focused.py`, which waits for the operator to give the game the screen.
   The decision is logged with the measurement that produced it: `background input test: True (character moved 4.31 units while unfocused)`.
3. **Runs exactly one child**, and if it exits, restarts it after ten seconds; if the session ends, it stops the child.

So after the relaunch there is one command to run and no way to end up with two loops fighting.

## Live state

```
18:19:25 === supervisor starting
18:19:25 no live session - waiting for the game to be launched
```

The game is closed (all **60** recorded sessions read `ended`, no Dolphin process), so the supervisor is waiting. That is the correct behaviour: it
holds the place and does nothing until there is a game to play.

## What happens when the game is launched

1. the supervisor notices the session within ten seconds;
2. it runs the background-input test - which also **proves whether `BackgroundInput` took effect**, since the config is only read at Dolphin's start;
3. it starts the loop the test chose;
4. it supervises that loop for the rest of the session.

That is the whole hand-off: **launch the game from the app, and the supervisor does the rest.**

## State

| item | state |
|---|---|
| supervisor | running, waiting for a session |
| play loops | none running (the supervisor owns them) |
| game | closed |
| gBox API | up on 18765 and 8765 |
| minimap | up on 8802 |
| topmost fix | in place; the app still re-asserts its own |
| CP17 / CP18 | pass, reproducible evidence |
| CP19 | pending the relaunch |
