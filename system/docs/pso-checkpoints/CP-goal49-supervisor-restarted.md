# Round 49: the supervisor had died - restarted, and the stack is fully armed

## What was found

The supervisor was **not running**. Its log stopped at `03:59:28 starting play_rooms.py`, and no `play_rooms` process existed. So a new launch would have had **nothing
to start the loop** - the game would have sat at the title with no bot, exactly the silent failure this whole chain exists to prevent.

**Restarted and verified:**

```
04:37:27 === supervisor starting
04:37:27 background input test: None (game already focused - cannot test)
04:37:27 starting play_rooms.py
```

## What is running now

| process | purpose |
|---|---|
| **supervisor** | polls every 10 s, starts the loop on a session |
| **play_rooms** | boots from the title, then switches → enemies → exit → rooms |
| **orphan_guard** | cancels jobs with no worker, so a launch cannot stall on one |
| **job_guard** | cancels input backlog before it can hang the worker |

**And no focus stealing**, verified from the source:

```
ensure_focus is a pure check: True     (no SetForegroundWindow)
raise_window is a no-op: True          (returns False)
```

## What happens when the operator launches

1. the supervisor sees the session within ten seconds and starts `play_rooms`;
2. `play_rooms` **boots** - START/A until a character exists, logged;
3. it calibrates by walking and measuring, then runs the room logic;
4. **the orphan guard clears any `characters` job that would stall the launch**;
5. **the readable log** records every job and worker message, so a stall names itself.

The bot needs the game **in front** - the keyboard path requires it, and the virtual pad is not created by this app on this machine.

## State

| item | state |
|---|---|
| supervisor | **restarted**, polling |
| play_rooms | running |
| orphan guard | running, caught the stalling job once already |
| job guard | running |
| focus stealing | **impossible in code** |
| bot | complete, 54 checks |
