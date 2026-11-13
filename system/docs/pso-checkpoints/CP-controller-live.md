# You have the controller now, and the bot stands down

## The measured chain, running live

**Your inputs, caught by the relay:**

```
relay watching 'Xbox 360 Controller'
  relayed 6 event(s): ['a', 'up', 'down', 'left', 'right', 'left']
  relayed 5 event(s): ['b', 'up', 'down', 'left', 'right']
  relayed 5 event(s): ['up', 'down', 'left', 'right', 'up']
  operator idle - bot may resume
```

**And the bot giving you the pad:**

```
[22:26:33]   operator is playing - bot standing down
[22:26:42]   operator is playing - bot standing down
```

```
--- pause flag? ---
OPERATOR IS PLAYING - bot standing down
```

## Why it never worked before

Two separate faults, both now measured:

1. **The controller is invisible to XInput.** The Xbox 360 pad enumerates as **HID** — Windows lists it, SDL sees exactly one joystick with 6 axes and 11 buttons, but **XInput slots 1-3 are empty** and
   slot 0 is held by gBox's virtual pad. Dolphin's GCPad is bound to `XInput/0/Gamepad`, so it was **always asking my pad and never yours.**
2. **Nothing was injecting your presses into that pad.** Even once SDL could read you, the presses had to be placed on the virtual pad, because that is the device Dolphin is listening to.

## What is running now

`controller_relay.py`, a daemon that closes the loop:

* reads the pad at **30 Hz** through SDL;
* sends only **changes** (a held stick is not a new event) via `session_op send_input` — the route measured to actually move the character (211 units through a gate, 38.3 after a pause, 44.7 in this
  round's test);
* while you are touching it, writes `D:\gBox\pso-ds\operator-playing.flag`;
* `endless.py` checks that file every loop iteration and **stands down** while it exists;
* after **4 seconds** of no input it clears the flag and the bot resumes.

That is the contract: **the file's presence means you are playing.** The bot waits; it does not compete.

## Also fixed this round

* **Ultimate is actually on now.** The launch config said `difficulty: ultimate` but the game's own global at `0x805D5550` read **0 (Normal)** — it is live memory and does not survive a relaunch. `arm()`
  now writes 3 and verifies, and this run reports `difficulty: already Ultimate`.
* **The relocation settle.** A direct `write_memory` of `x+20` moved the character **exactly 20 units**, which proves the write works; the loop was judging the move only 0.8 s later. It now waits
  **1.2 s** before deciding whether a relocation freed the character.

## One thing in the log that needs a fresh session

```
give 009d00: failed ValueError: Not enough inventory slots
give 003200: failed ValueError: Not enough inventory slots
give 004400: failed ValueError: Not enough inventory slots
```

This session has been alive for hours and its inventory is full from earlier gifting, so the character is unarmed **in this session**. A fresh session resolves it — the arm-once logic already prevents
the accumulation that caused it.

## Try it

The relay is running. **Touch the pad** — the bot will step back within a fraction of a second and your presses go to the game. Stop for four seconds and it takes over again.
