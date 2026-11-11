# Round 230: CP17's route is certified walkable - 9 clear legs, 999 units, 37 seconds

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
No game running: the operator's app has not started a session yet, so nothing here is a live claim.

## The certificate

`cp17_route_check.py` plans Forest 1 from the operator's own start `(-57,197)` to the exit their play recorded at `(133,-48)`, and then
**checks every leg against the real cell grid** instead of trusting the planner:

```
floor 1 free cells: 5701
plan: 124 cell waypoints -> 10 legs
  leg 1: (-55,195)   -> (-125,205)    70.7 units  clear
  leg 2: (-125,205)  -> (-125,295)    90.0 units  clear
  leg 3: (-125,295)  -> (-85,415)    126.5 units  clear
  leg 4: (-85,415)   -> (-15,405)     70.7 units  clear
  leg 5: (-15,405)   -> (25,305)     107.7 units  clear
  leg 6: (25,305)    -> (245,175)    255.5 units  clear
  leg 7: (245,175)   -> (245,65)     110.0 units  clear
  leg 8: (245,65)    -> (235,15)      51.0 units  clear
  leg 9: (235,15)    -> (135,-45)    116.6 units  clear
total 999 units, 9 legs, 0 blocked legs, final waypoint 3.7 units from the exit, expected 37 s at 27 units/s
CERTIFICATE PASS
```

**Zero blocked legs** is the part that matters: string-pulling can only produce a shortcut if line-of-sight is wrong, so every one of the
nine straight lines was sampled through the free-cell set independently. The final waypoint lands **3.7 units** from the recorded warp.

Written to `D:\gBox\pso-ds\cp17-route-certificate.txt`.

## And the exit is not a collision trigger

Checking all 164 `TRIGGER_FLAG` triangles for proximity to the two recorded warps:

```
exit (133,-48):    nearest trigger 48.7 units away
exit (536,-566):   nearest trigger 70.5 units away
```

So the warp is **not** a trigger region in the collision mesh - it is the `TObjAreaWarpForest` entity that only exists once its room
streams in, exactly as the set-file census concluded. That makes the recorded floor-change event the only static evidence of the exit's
identity, which is why the CP17 accept test has to observe the **floor id changing while walking**.

## What CP17 needs now, precisely

Everything physical is ready: 9 clear legs, 999 units, 37 seconds at the measured 27 u/s, ending 3.7 units from the warp. What is missing
is the **observation**: a run that records the floor id going from 1 to 2 with the character on foot. `learn_live` already records floor
changes; run it during the walk and the acceptance evidence is a timestamped series, not a narration.

## Files

* `cp17_route_check.py` - the leg-by-leg certificate
* `exit_trigger_check.py` - proves the warps are not collision triggers
* `tech_finder.py` (last round) - the pointer-following scan for the technique table, waiting on a loaded character
