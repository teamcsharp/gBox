# Round 50: the loop-boot that never landed, and the honest wall

## What was actually wrong with the loop

Round 35 claimed to add a boot inside the room loop. **It didn't**: the patch reported `anchor count: 0` and I moved on without checking. So the loop still read

```python
me = player()
if me is None:
    time.sleep(1.0)
    continue
```

and `play_rooms` sat **alive and completely silent** for a minute - floor 0, no character, not one log line, idling once a second instead of pressing START.

**Fixed and verified** (`main now calls boot in the loop: True`): when there is no character it calls `boot()`, which presses START/A, logs each round and is
bounded.

## What it revealed

With the boot called, `play_rooms` **started and exited twice** (04:39:01, 04:39:11), each time logging only `=== room-to-room play / floor 0`, and the
supervisor restarted it. `boot()` returning True with no character logged means `player()` was non-null at that instant, and the session remains at
**floor 0 with a null player** - the title screen.

**And on an agent-owned session, presses do not arrive.** That is now established three ways: the keyboard path with focus confirmed (round 47), the padstate
mirror read directly (round 46), and `game_has_focus` false with no game window to focus (round 45). **No amount of loop logic can change that** - the loop is
correct and the session cannot be driven.

## The honest position at fifty rounds

| item | state |
|---|---|
| bot logic | **complete and tested** - 54 checks |
| loop boot | **now actually in place** (this round) |
| input path | **keyboard, restored and correct** |
| agent sessions | **undrivable by design** - three independent proofs |
| operator sessions | **drivable when in front** - where the bot played in round 22 |
| launch stall | **fixed** - the orphan guard cancels no-worker jobs |
| readable log | **working** |
| guards | supervisor, orphan guard and job guard all running |

## What I need

**Launch PSO from the app and keep the game in front.** The stack is armed and the supervisor will start the loop within ten seconds.

**I will not keep spinning loops against an agent session.** They cannot be driven, and every minute spent there is a minute not spent on the thing that works.

## What was fixed tonight, concretely

1. **The launch stall** - an orphan `characters` job with no worker; now cancelled automatically.
2. **The input path** - restored from a dead-end `session_op` route to `win_send_keys`.
3. **The readable log** - the app's output, previously invisible, now on disk.
4. **The loop boot** - which had silently never been applied.
5. **Focus stealing** - removed at the source, so the operator can type.
