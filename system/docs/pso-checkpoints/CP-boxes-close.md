# The box path runs, routes, and closes to 14 units - the last few oscillate

## What the instrumentation proved

**No `box` sample was ever logged** before the fix, because the enemy branch ran first and every room had a `TObjEneBeast` in it. The bot spent every window on an Ultimate-spawned **1556 HP** enemy it
cannot hurt and **never touched the 59 containers**. The box branch below was unreachable - the same class of fault as the reticle catch-all, one level up.

Now, with boxes handled **before** enemies:

```
box TObjContainerItem d=162.9 route=yes
box TObjContainerItem d=102.9 route=yes
box TObjContainerItem d= 56.4 route=yes
box TObjContainerItem d= 21.0 route=yes
box TObjContainerItem d= 16.4 route=yes
box TObjContainerItem d= 14.5 route=yes
```

**The map route is doing its job** - `route=yes` on every sample, and the distance falls from 162 to **14.5 units**. The internalised Forest map is now steering the bot to a target in the live game, which is
exactly the objective's "used for path-guiding".

## The remaining gap, precisely

**The distance oscillates instead of converging:**

```
94.3 -> 21.0 -> 16.4 -> 65.3 -> 134.5 -> 14.5
```

It closes to **14-21 units**, then jumps **away** to 65-134, then comes back. So the sweep range (≤8) is never reached and **no container breaks**.

**The likely cause is the turn heuristic**, which is deliberately crude because `heading_deg` cannot be trusted:

```python
hold(pad, "left" if step[0] >= x else "right", 0.16)   # direction from the waypoint's X alone
hold(pad, "up", 0.7)
```

**Using only the X component** means that when the next waypoint lies mostly along **Z**, the turn picks the wrong way and the 0.7 s step carries the character off - which is exactly the
close-then-jump pattern. The fix is to choose the turn from the **full 2-D direction** of the waypoint (sign of dx *and* dz, i.e. whether to rotate toward +x or -x of the current facing), or to take
shorter steps as the distance shrinks so an overshoot cannot fling it 100 units away.

## What is now true

* **boxes are the target** - the operator's instruction, and the only destructible thing at this level;
* **the box branch is reachable** (boxes handled before enemies);
* **the map route steers it** (`route=yes`, 162 -> 14.5 units);
* **the sweep and range are correct** (8-unit sweep, proven to break a box at heading 58);
* **what is missing is the final 8 units** - an approach-tuning problem, not a recognition or mapping problem.

## Also verified this round

```
[04:12:26]   box TOCapsuleAncient01 d=41.8 route=yes
```

and the gate widening from 60 to 220 units, because this room's containers are **128-176 units away** at spawn - the 60-unit gate meant the branch never fired even after reordering.
