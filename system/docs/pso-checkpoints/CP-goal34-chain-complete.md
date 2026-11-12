# Round 34: two gaps in the chain that would have made the bot idle

Neither of these would have crashed anything - they would have made the bot **sit still next to a running game**, which is worse, because the log would say a
loop was running.

## Gap 1: the supervisor was pointed at a loop that cannot act

```python
script = "play_background.py" if works else "play_pad.py"
```

`play_pad.py` drives the **virtual pad**. The pad is not available to the bot: `_setup_vpad` binds the **app's own** pad (which the bot cannot press), and
`send_input` falls back to the keyboard anyway. So whenever the background-input test failed - as it always has - the supervisor would start a loop that
cannot move the character.

**Fixed**: the fallback is `play_rooms.py`, the loop that actually played in round 22 - it drives movement through `pso_input` → `game_input.send` → a
`session_op` job, which uses whatever path the plane has working.

## Gap 2: `play_rooms` had no boot step

`play_pad.py` begins with `boot()`. `play_rooms.py` did not - it started its room loop and waited for `player()`, which is **null at the title screen**. On a
fresh launch it would log nothing while the game waited at the title, which is the same silent idle the boot step exists to prevent, in the other loop.

**Fixed**: the same boot - START and A in alternation through `pso_input.hold`, bounded at 120 rounds, logged so a stall names where it stopped - and it runs
before the room loop.

## The chain is now complete

| stage | mechanism | verified |
|---|---|---|
| operator launches PSO | their app, operator-owned session | they have done it before |
| supervisor notices | polls every 10 s | waiting now |
| chooses the loop | `play_background` if the keyboard works, else `play_rooms` | **fixed this round** |
| gets past the title | `boot()` - START/A until a character exists | **added to play_rooms this round** |
| plays | switches (step-then-press) → enemies → exit → next room | built and unit-verified |
| proves progress | `AREA CLEARED: floor N -> M` | built |
| survives a slow worker | one job per action, cap 4, job guard | built and tested |

**45 checks passing** across perception, movement, decision and batched input; two more invariants now fixed in the orchestration.

## Verified right now

```
health: True
workers online: 1 of 1
live sessions: 0
queue: 0
supervisor: 21:26:04 === supervisor starting / waiting for the game to be launched
```

**Nothing is blocking but the launch itself.**
