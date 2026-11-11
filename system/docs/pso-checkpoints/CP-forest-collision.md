# Forest 1 collision is extractable and routable: the disc, the graph, and the coordinate question

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Goal: 2

## The disc

The running Dolphin's own command line names it:

```
D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz
```

`gbox/gcz.GCZ` gives random access to the decompressed image (`read(offset, size)`), so the FST is directly usable. Two parse facts
worth remembering:

- the FST offset is the u32 at `0x424` of the boot header (`0x52400` here), entry count at `fst+8`;
- **entry type 1 is a directory and 0 is a file** (the inverse of the obvious guess): the first parse reported zero `.rel` files and
  every file as a directory until this was flipped.

3,556 entries; the Forest 1 collision is `map_forest01c.rel` (72,096 bytes). `pso_walk.describe` on it:

```
{"floors": 6463, "walls": 2599, "walkable": 5701}
```

and `pso_walk.path` from the live actor position returns a real route (24 waypoints, 231 units for a 174-unit straight line - the
difference is it going around walls).

## The coordinate question, honestly open

Executing that route exposed two things:

1. **The stick->world mapping must be measured, not assumed.** Pressing `left` moved the character `+x`; on this camera the naive
   mapping is wrong. Probing each direction from a standstill and recording the displacement gives a usable table, and a clean probe
   shows the opposites are exact opposites (`up (22.8, -6.9)` vs `down (-22.5, 6.7)`), which is the check that the measurement is
   sound.
2. **A second driver silently invalidates the measurement.** The first calibration produced nonsense (`up` barely moving, `left` and
   `right` both `+x`) because the background walk-and-fight driver was still pressing keys. Any calibration or navigation run must
   own the keyboard alone.
3. With a clean table the walker still oscillates around the route instead of progressing (remaining distance hovered at 70-90 units
   while the character swept +-20 units per hold). The likely cause is the waypoint-advance rule combined with 0.5 s holds that
   overshoot 10-unit cell centres; a smaller hold, a look-ahead point on the route instead of the next cell centre, and a frame check
   between the collision's coordinates and the actor's RAM coordinates are the next things to settle.

So: the disc read, the FST, the graph and the route are **done and verified**; turning a route into a walk that converges is the
remaining piece, and it is a control question rather than a data one.
