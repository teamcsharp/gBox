# Goal round 1: the emulator runs, the game is live, and input no longer reaches it

## What is verified working

```
session 4b43bd602a584d8f-d6acee9c57ab48ff   state running   agent_owned False
floor 1   player pointer 0x80da62a0   position (-94.5, 34.1, 226.2)   hp 40/40
entities 91
process 34168 "gBox Dolphin": 80 threads, 988 MB, Responding True, 2 s CPU per 3 s wall
```

So the game is **in the field**, the emulator is **running at speed**, and the session is **operator-owned** - the configuration that has worked before (the
Dragon fight, nine floor changes, hundreds of units walked all happened on a session like this).

## What is broken

**A held direction moves the character 0.0 units**, every time, through every delivery path:

| path | result |
|---|---|
| `G.send` -> `win_send_keys(emulator pid)` | accepted, no movement |
| `G.send` -> `win_send_keys(gBox window pid)` | accepted, no movement |
| `session_op send_input` with the app window active | succeeds, no movement |
| a synthesised click on the game view first | no movement |
| `resume` (the emulator reported **PAUSED**, now `PLAYING`) | no movement |

**The pause was real** - `resume` answered `{"state": "PLAYING"}` - and fixing it changed nothing, so the game was not merely paused.

**The frame reports `gameplay_verified: False`** with `covered: 0` and luma 70.75, i.e. something is being rendered and nothing is covering it, but the
plane does not consider it gameplay.

## The one delivery path that has never failed

Every success in this session happened on a session the operator launched, with the game **visibly rendering in the PiP**, and via input the app
forwarded. All of that is nominally true now and input still does not arrive - so the forwarding itself has stopped in this app instance, most likely
because it has been running since 18:18 through several app-level mode changes (minimised, restored, PiP toggles, F3 takeovers, two extra sessions
launched and stopped).

**The reliable fix is the one that has worked every time: relaunch the game from the gBox app.** That rebuilds the forwarding path with a known state.

## What the bot needs once input flows

The loop is ready and was already running room-to-room before this:

* switches are hunted up to 120 units and **stepped toward before every A press** (which turns the character so the reticle appears), logged every iteration;
* `walk_through` is **off**, so the bot cannot clip through a door without opening it;
* rooms have bounded attempts, so it moves on instead of circling one destination;
* the room graph and height tables cover floor 1 (11 rooms) and the rest of Episode I.

Nothing about the game logic is blocked - only the keyboard.

## State

| item | state |
|---|---|
| emulator | running, 80 threads, unpaused |
| input | **does not reach the game** on any path |
| frame | rendering, `gameplay_verified: False` |
| bot logic | ready: switches first, then enemies, then rooms |
| needed | **relaunch the game from the app** |
