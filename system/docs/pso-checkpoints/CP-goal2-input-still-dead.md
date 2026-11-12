# Goal round 2: the loop is correct, the keyboard device is configured, and input still does not arrive

## What now works

The room loop runs without errors and does the right thing:

```
19:29:59 === room-to-room play
19:30:03   switch TObjDoorKey state 224 at 12 units
19:30:37     step+press x1: at 12.3 units, state 224
19:30:44     step+press x2: at 12.3 units, state 224
19:30:51     step+press x3: at 12.3 units, state 224
```

It finds the switch, walks to it, and does the step-then-press loop - and **focus is held** (`focused: True` on every check, restored with SW_RESTORE before
each cycle). Two regressions were fixed on the way: a patch that had deleted the switch helpers (`NameError: press_switches` on every cycle) and a
duplicated `def main`.

## What is still broken, with the evidence

**The character does not move, on any delivery path, with focus held:**

| path | result |
|---|---|
| `G.send` -> gBox window pid (the one that forwards) | accepted, **0.0 units** |
| `session_op send_input` | job **succeeded**, **0.0 units** |
| synthesised click on the game view first | **0.0 units** |
| after `resume` (the emulator had been PAUSED) | **0.0 units** |

**The emulator's own input configuration is correct**, which rules out the obvious explanation:

```
GCKeyNew.ini:  [GCKeyboard1]  Device = DInput/0/Keyboard Mouse,  A/B/C ... all bound
Dolphin.ini:   SIDevice0 = 6   (the keyboard device on controller port 1)
Process 34168: 80 threads, 988 MB, Responding, 2 s CPU per 3 s wall
```

**And the operator's controller works**, which proves the game itself responds to input - the emulator is not frozen, the session is not stuck, and the game
is in the field with 91 entities. It is specifically the **keyboard path into the game** that has stopped.

## The remaining difference from every working moment tonight

Every period when the bot moved - 12.96 units, 29 units, 208 units of travel, the Dragon fight - was on a **freshly launched** session. The current one
has been through: the emulator being paused and resumed, the app being minimised and restored, two extra sessions launched and stopped, a co-op launch
that rewrote the Dolphin pad/keyboard configuration files at 18:55 (the same minute this session's emulator started), and several PiP mode changes.

**The one action that resets all of that is a relaunch from the app**, and the configs that make it work afterwards are already in place
(`BackgroundInput = True` in both profiles, keyboard bound on port 1).

## State

| item | state |
|---|---|
| room loop | **running, correct behaviour**, switches first |
| focus holding | **working** (`focused: True`) |
| keyboard device | configured and bound |
| input into the game | **0.0 units on every path** |
| controller input | works (operator confirmed) |
| needed | **relaunch the game from the app** |
