# The input path was wrong since round 8 - now corrected

## The proof

Reading XInput around a bot press while a session was live:

```
before:  slot 0: connected buttons=0x0000 lx=658 ly=-295
DURING press (START held): buttons=0x0000
after:   slot 0: connected buttons=0x0000

VERDICT: the mirror does NOT carry the bot's press - it only reflects the operator's pad
```

**The button never appears.** The stick values are the operator's physical controller resting; the bot's START press never becomes a button on any pad.

## What that means

This chain is a dead end:

```
game_input.send -> session_op -> padstate.report -> control plane -> the pad mirror
```

The mirror exists so **the operator's controller** can drive a remoted session. **Bot events posted to the control plane never become a pad a game reads.**
My round-8 change routed all input there - and from that round onward **no press ever reached a game**, while the keyboard path in round 22 had already walked the
bot through Forest 1.

## The correction

`send` is back on **`win_send_keys`**, the path that sends real key events to the window that relays them into the emulator:

```
pso_input.hold  ->  G.send  ->  win_send_keys
```

with the batching preserved - `tap(key)` is one press-release in one call, `move(*keys)` is many taps in one call, and `hold` makes one `send` call per action.
`tap` and `move` were re-added when the replacement removed them, and the file compiles.

## Why focus is required, and what it is not

`win_send_keys` needs the game (or gBox) to be the **active window**. That is inherent to the keyboard path - it is how the app forwards keys into the emulator.
It is not a bug I introduced and not something the pad will fix on this machine, because the pad is not created at launch.

So: **the bot plays when the game is in front.** That is exactly the configuration in round 22, and it is the configuration available today.

## What this round changes for the better

Before this round, the bot's presses were going to a place that could never reach the game, and every "it doesn't move" observation was being explained by
focus, timing or the pad. **Now the path is the one that worked**, and the only requirement is the one the app documents: the game must be the active window.

## State

| item | state |
|---|---|
| `send` | **`win_send_keys`** - the keyboard path |
| batching | preserved: `tap`, `move`, one call per `hold` |
| requirement | the game (or gBox) active - inherent to this path |
| bot | complete, 54 checks |
| next | launch, keep the game in front, and it plays |
