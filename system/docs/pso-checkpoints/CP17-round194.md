# Round 194: the arrival-pad freeze and a verified walk_through; the character then sat on a slope

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Live: session `e731ee594dde4a89-cae9dad929a34d17`, Forest 1, floor 1

## The pad freeze, measured

A warp lands the character on an arrival pad, and **the pad blocks movement until B is pressed**. This is the mechanism behind most of
the "frozen character" episodes in rounds 189-193:

```
Pioneer 2:  before (349.9, -36.4)   B x2 + down -> (347.2, -20.7)   left -> (318.6, -9.3)
Forest 1:   before (532.7, 483.3)   B x2 + down -> (561.4, 471.9)   left -> (570.1, 501.5)
```

Every walk driver must press **B twice after a warp** before trusting a movement probe. My external keys were fine all along; the
character was standing on a pad.

## walk_through verified on

```
op=walk_through {"on": true} -> {"on": true, "verified": true, "message": "Walk through collision barriers enabled."}
adventure_status             -> {"walk_through": true}
```

Round 192's attempt had never applied (its reply was swallowed and `adventure_status` read false). It is on now.

## What the walk then hit

Two empirical walkers were tried. The four-key calibrated walker **orbited**: alignment readings of 0.85-1.00 while the distance sat
in a 510-580 band, because the calibration rotates with the character. The empirical walker (measure each key's displacement
immediately before choosing it) also orbited, with every key moving the character a clean **16 units** while the distance stayed at
~500.

The screenshot explains it: the character is on a **steep hillside** (minimap shows a small enclosed pocket). All four directions move
it within that slope pocket; nothing points downhill out of it. So the failure is terrain, not calibration and not input - a
direction the probe keys cannot see with 0.4 s holds on a slope.

## Next

1. walk **downhill** deliberately: probe with longer holds (1.5-2 s) and prefer the key whose displacement **increases height** loss or
   leaves the pocket, rather than the one pointing at the goal;
2. or start the run from a spawn that is not on a slope (a different `floor_warp` arrival or a save state);
3. then the key door and `0x805D5FC0`.

The state left behind: Forest 1, floor 1, HP 10/40, walk_through on, randomizer at 30+ cycles, character on a slope at
`(485.6, 17.4, 368.1)`.
