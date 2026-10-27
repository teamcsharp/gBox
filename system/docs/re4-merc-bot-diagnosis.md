# RE4 Merc Bot Diagnosis — Request #3831

## Summary

The bot (re4_merc_bot.py, 1,776 lines) implements a Mercenaries mode bot for Resident Evil 4
with a layered architecture: memory-backed state, a learned navigation map, a raycast-based
lookahead fan, and a combat decision tree. All prior work is in the isolated task workspace
on branch `hermes/request-3831-1793029425488236437` at baseline `f679ef07`.

## Root Cause: Stuck at Spawn

The stuck log at `~/.gbox/re4_learned/r400-stuck.jsonl` shows **11 identical entries**:

```
at=4.45, pos=[0, 0, 0], goal=[-3900, 300], action=vault, replanned=11
```

All 11 events have the exact same timestamp (`4.45`), the exact same position (`[0, 0, 0]`),
and the exact same goal (`[-3900, 300]`). This is degenerate data — the bot is stuck at the
spawn point (origin) and cannot reach a goal that is 3,900 units away in the negative X
direction. The learned map shows Leon walked 2,074 cells (x: -60 to 63, z: -40 to 77), so the
bot *has* moved from spawn at some point, but the current stuck state is a stale entry.

### Why the Bot Can't Reach the Goal

The goal `[-3900, 300]` is outside the learned map's bounds (x: -60 to 63). The `_path` method
tries to plan a route via the disc's nav map or the learned map, but if neither has a route to
that goal, it returns a straight line that crosses walls. The bot then replans 11 times
(`replanned=11`), gets stuck, and logs the stuck event.

This is a **navigation planning failure**, not a combat failure. The bot is trying to reach a
time bonus or hourglass that is unreachable from its current position without a proper path
planner.

## Combat Architecture

The combat system (`_fight`, `_combat`, `_pick_target`) is well-structured:

1. **Target selection** (`_pick_target`): picks the nearest enemy with line-of-sight, weighted
   by distance and threat level (routine bytes, motion events).
2. **Aim and fire** (`_fight`): aims using the `aim_rot` from memory, fires when the error is
   within tolerance, and manages pitch with a learned stick direction.
3. **Threat detection** (`_threats`): reads routine bytes and motion events from RAM to
   predict attacks, thrown weapons, and quick turns.
4. **Evade** (`_evade`): when an attack is imminent, the bot turns and moves away.
5. **Quick turn** (`_quick_turn`): when a thrown weapon is in the air, the bot turns to
   intercept it.

The `body_band` function determines where shots land on a target based on its HP and routine
state: `BODY_BAND` for standing, `LOW_BODY` for hurt/knocked-down, `SMALL_BODY` for small
animals.

## The `_raycast_fan` Method

Added in request #3299, this method casts a fan of lookahead rays ahead of Leon every tick
using `gbox.re4_collision.raycast`. Each hit marks a wall cell in the learned map so the bot
steers before contact. Stats report `rays_cast` and `ray_hits` per round.

The method is defensive: if `self.st` or `self.learned` is None, it returns early. If the
collision module fails, it silently passes. This is safe but means the raycast fan is only as
good as the disc's wall data.

## What's Missing

1. **Navigation planning to unreachable goals**: The bot needs a fallback when the goal is
   outside the learned map's bounds. Currently it replans repeatedly and gets stuck.
2. **Stuck recovery**: The stuck log shows the bot stuck at spawn. It needs a recovery
   strategy (e.g., back off, try a different direction, or give up on the goal).
3. **Live verification**: The live RE4 session on lilspark (session
   `8b7c0f5675d04c15-f66d53bcf39c4596`) is running but has been timing out on read_memory
   and capture_worker_screen. The session is warm and ready (stage: Castle, room: 1026) but
   the bot isn't actively playing — it's waiting for an operator to start a Mercenaries round.

## Next Steps

1. **Fix the navigation planning** to handle goals outside the learned map's bounds.
2. **Add stuck recovery** for the spawn-stuck case.
3. **Verify the combat system** on the live session once the bot is running.
4. **Publish the diagnosis** as a research artifact.

## Files

- `gbox/re4_merc_bot.py` (1,776 lines, 110,079 bytes)
- `tests/test_re4_merc_bot.py`
- `~/.gbox/re4_learned/r400.json` (2,074 walked cells, 224 blocked cells)
- `~/.gbox/re4_learned/r400-stuck.jsonl` (11 stuck events, all degenerate)

## Verification

- 71 tests passing in `tests/test_re4_merc_bot.py`
- Stuck log shows degenerate data (11 identical entries at spawn)
- Live session on lilspark is running but not actively playing
