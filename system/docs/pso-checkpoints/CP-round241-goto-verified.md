# Round 241: the map-control chain is verified end to end (without a game)

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
PSO not running (eleventh round); the machine's only session is another lane's Resident Evil 4 VR.

## The operator's map-control request was already built - and is now proven wired

They asked: *"click on the map in order to tell the bot where it needs to go and click on enemies telling it what it needs to target."*

Both halves existed:

* the viewer page has `click` on the map and **shift+click** on an enemy, POSTing to `/api/goto`;
* `map_bot.py` reads `goto.json`, walks to the point, and when an enemy is within 35 units approaches and attacks while stepping.

What had never been shown is that the handoff carries the right payload. It does:

```
waypoint order  -> (200, {"ok": true})   goto.json {"x": -125, "z": 205, "t": 1794429248.75}
enemy order     -> (200, {"ok": true})   goto.json {"enemy": "TObjEneBeast", "x": 502, "z": 3, "t": 1794429249.17}
has enemy field: True    timestamp fresh: True
```

So a shift+click really does arrive at the bot as an enemy target with a fresh timestamp, and a plain click arrives as a waypoint. The only
untested link is the bot's movement itself, which needs a running game.

## Also this round

The full CP3 second-model batch is running: **10 of 82** labels written so far at ~25 s each (`ATTRIBUTE_MANAGER`, `ProcessEvent`, ...), on
track for the ~35-minute unattended run.

## State of the operator's outstanding requests

| request | state |
|---|---|
| randomized equipment every 2 min | implemented and running (`equip_roulette --loop`) |
| five copies in all five slots | implemented (`five_slots.py`, verified against inventory) |
| mag with random stats each swap | implemented and applied live earlier (level 200 roll) |
| click-to-move / click-to-kill from the map | **verified wired this round** |
| all spells | blocked on a live session: the technique table is located (+0x2E7) and the write channel proven |
| Ultimate difficulty | `apply_master.py ultimate`, needs a session |
| bot plays the game | needs a session: the certified 37-second Forest 1 walk is ready |

## Files

* `verify_goto.py` - posts both order kinds and checks the file the bot consumes
