# Switch run maps: evidence

The run maps here come from **real live data** with an offline capture.

- **Source:** MercMode's RE6 Switch session `e63110fb49e64756-85de5118a8dd4c93` (Citron on lilspark), 2026-10-27 20:41-20:58 Spark time.
- **Polling:** the bot's own tactical frames (`GET /api/autoplay/tactical/{sid}`, up to 5 a second) and its telemetry stats (once a second) were read through the agent actor, read-only.
- **Replay:** the frames were fed through `gbox.mercs.run_capture.RunCapture`, the same code `engine.play_round` now runs on every tick, on JAYBUILTFINALE. Nothing was sent to the game.

## What the replay cannot show

The live capture in the engine has these too, but the replay does not:
- `bot.doing` / `bot.why`: the tactical frame doesn't carry them, so the replay labels the decision with the telemetry `phase` (`bonus_run` / `match`).
- The engine's own prompt presses.

## The rounds

1. `01-re6-rail-yard-run-map.png`, Rail Yard, completed.
   - Polling began with 188 s left, so the green start is where he stood then, not his spawn.
   - Over 274 s he never got more than 14 m from that point.
   - All 9 capsules were left standing (gold rings).
2. `02-re6-creature-workshop-run-map.png`, Creature Workshop, from the spawn.
   - 406 s, 212 m walked, furthest 40.8 m from the spawn, 35 cells (20% of the stage seen so far).
   - 1 capsule taken, 9 left standing.
   - The round was still running when polling stopped, so it shows as interrupted.

## The run reviewer (PR 2)

These screenshots show the run reviewer rendered in headless Edge by `tests/test_mercs_reviewer_run_maps.cjs`:
- the map comes from the same replayed run maps, through `Reviewer.run_map` (the payload that `/api/mercs/reviewer/round` returns);
- `GBOX_RUN_MAP=<payload>` sets the run map;
- `GBOX_RUN_MAP_AT` sets the scrub position in thousandths of the run;
- `GBOX_RUN_MAP_COLOUR=hp` colours the path by HP.

In each screenshot, the second run in the list is a test fixture. It is there to show the "No run map" badge that rounds played before the capture get.

3. `03-reviewer-creature-workshop.png`: Creature Workshop scrubbed to 4:19 of 6:45, path coloured by time. The traversed part is bright and the rest dim.
4. `04-reviewer-rail-yard-hp.png`: Rail Yard at its end, path coloured by HP (green at full, red low).
