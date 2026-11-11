# Round 215: live room crossings with the map-marker navigator, and what the level's trigger data actually is

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Live session `78a8746f5b514450-e9867839b8b74d3d`, Forest 1 (floor 1)

## The explorer crossed rooms live, on its own

`explore2.py` ran against the live game and made a real room transition using the minimap's exit marker:

```
12:51:19 entered room 2 at (-526,-34); visited [2]
12:51:30 room 2 -> 7: exit marker bearing +106 (room bearing +66, error 41 deg)
12:52:17   through=True at (135, -52) (room changed)      <- crossed the doorway
12:52:17 entered room 1 at (135,-52); visited [1, 2]
```

Then, in a room whose minimap showed **no** markers, the fallbacks took over:

```
12:52:28 no exit marker and no door edge; falling back to the room centre
12:53:05 no exit marker and no door edge; nearest live door TObjDoorKey at (277,7)
12:54:07   through=True at (148, -21) (through on the straight approach)
12:54:52   through=True at (258, -53) (through on the straight approach)
12:56:03   through=True at (-185, -17) (through on the straight approach)
```

So the fallback chain **map marker -> room-graph door edge -> nearest live door entity** all work, and the doorway crosser reports
"through" only when the character actually advances.

## The level's 164 trigger triangles are not warps

Clustering every `TRIGGER_FLAG` triangle in `map_forest01c.rel` gives **146 clusters of one or two triangles**, each pair sitting at the
same (x, z) at **two heights: y = 56.4 and y = 135.7**. Paired vertical markers along a route are the **Area Map's guide path** - the red
line and numbered waypoints in the operator's screenshot - not a warp. So the teleporter is not encoded in the collision triggers.

## The teleporter, per the operator

The operator's instruction: the goal is the **red teleporter**, it should be reachable from the byte-level game data, and the **Area Map**
menu screen already draws the whole level (shape, path, numbered waypoints). If the bot can **print that map**, custom levels with custom
doors and enemy spawns become possible.

That means the next build is the **map printer**:
1. open the pause menu and choose **Area Map** (menu navigation now works with the D-pad);
2. capture the map panel and extract its shape, the numbered waypoints and the player marker;
3. store it as a world-space layout (the map has a known origin and scale once matched against the collision bounds), which is the
   top-down level description the operator wants to edit.

## State

Player around (-185,-17), HP 31/48, TP 733/733, floor 1. All bots stopped. The explorer's own log is `explore2.log`, its progress
`explore2-state.json` (visited rooms, flips, exits used).
