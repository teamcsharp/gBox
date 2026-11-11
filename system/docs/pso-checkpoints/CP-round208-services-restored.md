# Round 208: back in play, all services restored, and the remaining navigation gap

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Live session `78a8746f5b514450-e9867839b8b74d3d`, pid 58572, **Forest 1**, `supported: true`

## State at the end of the round

```
player  (-115, 70)   hp 40     tp 29 / 999     floor 1
equipped items: 7  ->  5x Saber (000100) + Frame + Mag
crit true   always_hit true   equip_any true
map viewer live on http://127.0.0.1:8801/   (state answers in ~5 s: floor, hp, player, 14 doors, enemies)
demo recorder writing demos/demo-<stamp>/   operator lock running
```

## What this round fixed

1. **The freeze was a wedged emulator**, proved by measurement: zero bytes of the player struct changed over 2 s, and a savestate load
   sat at "Decompressing State..." for 80+ s while `pause`/`resume` reported PLAYING.
2. **The live mod channel is the desktop service on port 18765**, not the worker on 8765 (which returns 504 "Session did not
   acknowledge" for every session action). `session.py` now targets 18765 and every mod works again.
3. **Worker rebind procedure**: stop emulators and workers, delete `D:\gBox\runtime\gbox-running.json` (it held three stale owned-launch
   records), start `python -m gbox --config ... serve --worker`, then `launch_game` with **`debug: true`** and the full catalog entry.
4. **Menus: the D-pad steps exactly one row, the analog stick jumps 2-3.** `menu_select.py` reads the highlighted row's orange bar from
   the screenshot and taps the D-pad toward the target - the boot now goes title -> START -> OFFLINE GAME -> SINGLE MODE -> BQF ->
   Confirm -> EPISODE 1 -> area -> A through the dialogue until `capabilities` reports `supported: true`.
5. **The build on the fresh character**: TP max 999 via `stat mst 999` (measured 29/999), crit + always_hit + equip_any, and **five
   copies of the same Saber equipped simultaneously** (four extra copies given, each `multi_equip`'d: "Weapon effects stacked").
6. **All live tools restored and hardened**: the map viewer used to die mid-request on a short memory read; every read is now guarded and
   `/api/state` always answers.

## The remaining gap

The map bot receives click orders and its `send` now moves the character (verified: `(-82,137) -> (-120,192)` on a 1.2 s hold), but its
**steering drifts away from the clicked point**: ordered to `(-40,240)`, the character walked from `(-134,61)` to `(-126,21)`, increasing
the distance from 202 to 235 units. The route lookup itself returns a sane 9-waypoint path, so the fault is in translating waypoints into
held directions (the same class of problem that produced the "orbiting" walkers earlier).

Also still open: technique table (so "all spells" and rapid-fire casting), and HP writes (the job channel reports `SessionGone`; only
`stat mst` style ops write memory today).

## Next

1. steering: replace `pso_kbwalk.walk_path` in the map bot with the per-stride empirical controller that measures each key's displacement
   immediately (it is the only walker that consistently closed distance), keeping the route for waypoint order;
2. then a click order should complete, which is the operator's "click the map to tell the bot where to go".
