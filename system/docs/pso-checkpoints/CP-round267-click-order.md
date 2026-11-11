# Round 267: clicking the minimap tells the bot where to go

The operator asked for this in the early rounds - *"click on the map in order to tell the bot where it needs to go and click on enemies telling it
what it needs to target"*. The minimap built last round is now the input device for the first half of that.

## How it works

1. **The page inverts its own transform.** Every render records the world-to-screen mapping it used (`/api/transform`), so a click at pixel
   `(px, pz)` maps back to a world coordinate `(x, z)` for the view actually on screen. This matters because the two view types have different
   transforms: the room view scales the whole floor to 900x640, and the radar scales 120 units around the player to 640x640.
2. **The click posts an order.** `POST /api/order?x=..&z=..` writes `goto-order.json` with the point and a timestamp.
3. **The bot obeys it.** Before choosing its own destination, self-play reads that file; if the order is newer than the last one it consumed, it
   plans there with the height-aware planner and walks the legs. The order is consumed by timestamp, so it is followed exactly once.

## Verified end to end

```
GET  /api/transform  -> {"min_x": -43.38, "min_z": 190.59, "scale": 2.417, "width": 640, "height": 640}
POST /api/order?x=120.5&z=-40.0 -> {"recorded": {"x": 120.5, "z": -40.0, "t": 1794438527.67}}
goto-order.json -> {"x": 120.5, "z": -40.0, "t": 1794438527.67}
selfplay2.take_order() -> {'x': 120.5, 'z': -40.0}
selfplay2.take_order() -> None            <- consumed once, not repeated
```

Two defects were found by testing rather than assumed away: the radar view never recorded its transform (so clicks on floors without a room graph
could not be inverted), and the server had no `do_POST`, so the order endpoint answered 501. Both are fixed.

## Why this matters for the goal

The bot's own travel decisions were the weakest part of its play - it walked into walls because the route was planned in two dimensions. Clicking a
target on a map that is shaded by real floor heights gives the operator a direct way to place the bot precisely, and gives the planner a destination
it can be held to. The second half of the operator's request - clicking **enemies** to set the target - is the same mechanism pointed at the entity
table, and the minimap already draws those enemies.
