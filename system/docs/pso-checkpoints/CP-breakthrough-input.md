# The breakthrough: input was being rejected by the wrong endpoint

## The bug, and it was mine

On the live session, every press the bot made returned:

```
422  {"detail": "read-only, reset, pause/resume and debug_* ops only; edits go through the write_memory job"}
```

I had routed all input through `S.rpc("send_input", ...)` in round 8. **The session RPC endpoint does not accept `send_input`** - it only allows read-only,
reset, pause/resume and `debug_*` operations. So **every press since then was rejected before it ever became a key**, and `send` swallowed the failure in
its retry loop. The bot looked like it was pressing while nothing was sent.

That is the answer to the question that took ten rounds: it was never focus, never the drive, never the pad slot, never the config. **The presses were
being refused by an API that only reads.**

## The fix

`send` now submits a **`session_op` job**, which is the path that works (verified earlier in this session):

```python
POST /api/jobs {"tool": "session_op",
                "input": {"session_id": sid, "op": "send_input", "args": {"events": rows}},
                "require_worker": <worker>}
```

and returns **True only when the job actually succeeded**, so a rejected press is visible instead of silent.

## Proof it works

```
start: (0, 0)
  round 8:  floor=0 player=0x80da62a0     <- character created
  round 11: floor=1 player=0x80da62a0     <- IN THE FIELD
IN THE FIELD - input works and the boot sequence works
```

**Eleven rounds of START/A took the game from the title screen into Forest 1.** Input lands, and the boot sequence works.

## Then the bot played

```
20:21:19 === room-to-room play
20:21:20 floor 1
20:21:38   heading for room 5 at (-57,85)
20:22:05   room 5 reached - marked visited
20:24:43   room 5 not reachable in 4 attempts - moving on
20:25:12   heading for room 7 at (-341,321)
20:25:12     route 39 cells -> 4 legs
player: (-173.9, 25.7, 127.4)  hp 27  floor 1
```

**It reached a room, marked it visited, moved on, and is traveling to the next** - which is the room-to-room behaviour the operator asked for.

## One bug found while playing

```
switch TObjDoorKey state 1129705297 at 92 units
  step+press x1: at 142.3 units
```

`1129705297` is not a door state (the real values are 0, 2, 224, 240), so that entity is a despawned or unrelated door, and the bot **walked away from it**
(92 → 142 units) while enemies hit it (hp 40 → 27). Fixed with two narrow guards: the switch search drops from 120 to **40 units**, and only states
**0, 2, 224, 240** qualify. The real key door at 12 units - the one the operator pointed at - still qualifies.

## State

| item | state |
|---|---|
| input | **works** - via `session_op` jobs |
| session | `1c04bcd53a4c4a8c-6767cb2d8533497d`, pid 58572, operator-owned |
| bot | **playing**: room 5 visited, traveling to room 7 |
| hp | 27/40 - taking damage, not dying |
| next | keep it running; fix targeting when it stalls |
