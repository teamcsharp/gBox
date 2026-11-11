# Round 224: random weapon + frame + shield + mag every 2 minutes, with a freshly built mag each cycle

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Live session `78a8746f5b514450-e9867839b8b74d3d`

## What the operator asked for

A random weapon, frame, shield and mag on a two-minute timer, and a mag whose **stats and level vary** each time - sometimes magic, sometimes
strength, sometimes defence.

## What the plane can and cannot do

Reading `system/gbox/pso_live.py` and `pso_modes.py` settled it:

* `pso_controls op=randomized` accepts `categories` of **weapon, armor, shield, mag** (`PREFIXES` in `pso_modes.py`), picks rare items from the
  owned disc's catalog, gives/equips each one and cleans the previous one up. Interval must be 5-300 s.
* it **does not touch mag stats** - `pso_modes.roll` only *records* `def/pow/dex/mind/iq/synchro/color/form` after the swap.
* `pso_controls op=mag_set` **does** set them: each stat <= 200, the four totalling <= 200, `synchro` <= 120, `color` 0-18.

So the design is both halves: the plane swaps the four categories, and `equip_roulette.py` re-builds the mag's stats after every swap.

## The mag builds

Six archetypes, each a different distribution of the 200-point budget, verified to stay inside `mag_set`'s caps:

```
power      def   8 pow 132 dex  56 mind   4   sum 200
mind       def   9 pow   5 dex  32 mind 154   sum 200
dexterity  def  18 pow  33 dex 149 mind   0   sum 200
defence    def 130 pow  30 dex  28 mind  12   sum 200
balanced   def  35 pow  63 dex  61 mind  41   sum 200
hybrid     def   8 pow  15 dex  86 mind  91   sum 200
```

`iq`, `synchro` and `color` are randomised too, so the mag differs every cycle in form as well as focus.

## Applied live, verified

```
randomizer on: interval 120s, categories ['weapon','armor','shield','mag'], cycles 1, Equipment randomized
mag 15728645 (4 stage), build balanced: def 35 pow 48 dex 36 mind 81 (sum 200)
  applied: set -> def 35.0 pow 48.0 dex 36.0 mind 81.0 level 200
```

The mag's level followed the stats to **200**, and the plane acknowledged the change.

## Running

`equip_roulette.py --loop` (PID 55832) is live: it keeps the four-category randomizer armed at 120 s and re-rolls the mag's build every
120 s, always looking up the *current* mag first, so it follows the plane's swap rather than fighting it. Log: `D:\gBox\pso-ds\roulette.log`.

## Files

* `equip_roulette.py` - `--once` (apply one roll now), `--loop` (every 2 minutes), `enable_swaps()` for the four categories
* `check_builds.py` - proves every archetype stays inside the `mag_set` caps
