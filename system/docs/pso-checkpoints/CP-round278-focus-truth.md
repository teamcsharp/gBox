# Round 278: the bot does fight - and the one thing that stops it is Windows focus

## What was measured, not assumed

The operator reported the character standing in the room letting an enemy hit it. The investigation produced four separate facts:

1. **The character was defenceless because the game was unfocused.** `focused: False` and `allowed: False` while a Shark stood 16 units away. Keys
   only reach a window that has focus - that is the protection asked for, working exactly as designed, with the side effect that a character being
   attacked stands still when the operator is looking elsewhere.
2. **Movement works when focused.** `run_to` moved the character **12.96 units** toward the enemy.
3. **Damage lands.** A swing sequence took the Shark from **85 to 69 HP** - the combat itself is sound.
4. **The problem is staying in reach.** Distances across successive attempts went **18 -> 12 -> 23 -> 12 -> 14**: the character **overshoots a
   moving target**, so only one attempt in five landed a hit.

So "the bot doesn't fight" is really two narrower facts: it cannot act while unfocused, and when it can act it overshoots.

## Fixes built this round

**`play_focus.py`** - an explicit play mode: while playing it **takes focus back** whenever the game is unfocused, logs that it did so, and never
takes focus if the operator has touched the pad within thirty seconds. Their control always wins; the behaviour is visible instead of mysterious. A
`PAUSED` file stops it instantly.

**`melee_loop.py`** - the answer to overshooting: instead of long strides, a **0.12 s step** toward the enemy (which also turns the character, since
PSO faces the direction of travel) followed by a swing, repeated every cycle. Short steps cannot overshoot, and continuous swings are the stun-lock
the operator described.

**`one_strike.py`** - the diagnostic that separates approach from attack: it closes, **prints the distance it actually achieved**, and only then
swings. It is what proved the attack is fine (85 -> 69) and the approach is not.

**Dolphin's `BackgroundInput = True`** was written into `Dolphin.ini`. Dolphin reads that at startup, so it takes effect on the next launch - and if
it works as intended it removes the entire focus problem, allowing input to reach the game while another window is in front.

## The honest constraint

While the operator is reading this chat, the game is not focused, and the bot is frozen - every attempt to act in that state returns "not allowed".
The play mode grabs focus back, logs it, and gets a few seconds of fighting before the next focus change. That is a Windows input rule, not
something the bot can route around, and the two requirements - "let me use the PC" and "keep playing" - are in direct conflict unless Background
Input solves it.

**The practical setup that works right now:** click the PSO window and leave it alone. The play mode will fight, and the melee loop will keep the
character inside reach instead of running past. Reading the chat is what pauses it.

## State

| item | state |
|---|---|
| combat verified | **yes** - Shark 85 -> 69 HP |
| movement verified | **yes** - 12.96 units per `run_to` |
| overshoot | addressed by short-step melee loop |
| focus problem | mitigated by play mode; possibly solved on next launch by BackgroundInput |
| Cave 1 map | 22 rooms, 16 navigable |
| character | HP 31/62, floor 3 (Cave 1) |
