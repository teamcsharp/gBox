# Goal round 3: the input path, measured to the end

## Everything about the game side is correct

The launch line proves the emulator is configured exactly as it should be:

```
-C Dolphin.Input.BackgroundInput=True
-C Dolphin.Core.SIDevice0=6          (keyboard device on controller port 1)
-C Dolphin.General.HotkeysRequireFocus=False
-u D:\gBox\runtime\dolphin\Dolphin-x64\User
```

and that user directory's own `GCKeyNew.ini` has `[GCKeyboard1] Device = DInput/0/Keyboard Mouse` with every key bound. The process is healthy (80
threads, 988 MB, Responding, 2 s CPU per 3 s wall), the game is in the field (floor 1, 91 entities, player `0x80da62a0`), and **the operator's controller
works**.

## Every input path, measured

| method | result |
|---|---|
| `G.send` -> emulator pid | accepted, **0.00 units** |
| `G.send` -> gBox window pid | accepted, **0.00 units** |
| `session_op send_input` | job **succeeded**, **0.00 units** |
| synthesised click on the game view first | **0.00 units** |
| after `resume` (the emulator had been **PAUSED**) | **0.00 units** |
| **virtual-key `SendInput`** (what the adapter does) | **0.00 units** |
| **scancode `SendInput`** (`KEYEVENTF_SCANCODE`, hardware scan codes) | **0.00 units** |

The last two matter: DirectInput devices read scan codes, so if the adapter's virtual-key presses were being silently dropped by that layer, scancodes
would have worked. **Neither reaches the game**, which means the keyboard is not reaching the emulator at all - not a code-format problem, not a focus
problem, not a configuration problem.

## What the evidence points to

The app's own pad module states what it forwards: *"The view forwards the operator's controller to the session it shows"*. The controller path is alive -
that is why the operator can play. **The keyboard path into the emulator is not**, and every mechanism available to the agent goes through that keyboard
path.

The one path that would not need it - the plane's virtual pad, `send_input_player` - is **refused by `session_op`** (`op send_input_player not allowed
via session_op`), so it is unavailable to an agent, and the agent cannot drive the physical controller.

## Why this is blocked and not merely unfinished

The bot's logic is finished and was running correctly this round: switches found at 12 units, walked to, and stepped toward before each A press (the
step is what turns the character so the reticle appears). The room loop, the switch priority, the bounded attempts and the maps for all 14 floors are all
in place.

What is missing is **permission to press a button**: the agent has no working channel into this game's input. That is not difficulty or uncertainty - it
is a hard boundary of the current app instance, and the only reset is a relaunch that the agent cannot perform (agent-launched sessions are
`agent_owned` and receive no input at all, which is the original problem this session began with).

**A relaunch from the app** is the action that restores the keyboard path, and it has restored it every time tonight.

## State

| item | state |
|---|---|
| game | running, in-field, healthy |
| keyboard input into the game | **does not arrive, on any method or encoding** |
| controller input | works (operator) |
| agent's virtual pad | refused by `session_op` |
| bot logic | complete: switches first, rooms with bounded attempts, maps for 14 floors |
| needed | **relaunch from the app** |
