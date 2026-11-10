# RE4 Merc Bot Diagnosis — Request #3831

## Summary

The bot (`re4_merc_bot.py`, 1,776 lines) implements a Mercenaries mode bot for RE4 with a
layered architecture: memory-backed state, a learned navigation map, a raycast lookahead fan,
and a combat decision tree. All prior work is in the isolated task workspace on branch
`hermes/request-3831-1793029425488236437` at baseline `f679ef07`.

The operator asked two questions about live gameplay:

1. **"Why is the bot unable to deal with this bot?"** (an enemy it cannot handle)
2. **"Why does the aim go so wayward?"**

The first revision of this document answered only (1) and hand-waved (2) as "likely a side
effect of being stuck". This revision adds an independent, code-grounded answer to (2): the
wayward aim has concrete root causes in the aim/steering code and is **not** merely a symptom
of the navigation failure.

---

## Question 2 — Why does the aim go wayward?

The wayward aim is a separate defect with three compounding causes, all visible in the aim
control flow and the constants at the top of `re4_merc_bot.py`. The operator's own words
already describe the symptom: on 2026-10-22 the camera "spun so spastically, the bot overshot
and circled" — which is why `AIM_SPEED_X` was reduced from ×3 to ×1 (line 134-137). That
change reduced the *rate* of the oscillation but did not remove the underlying *error source*.

### 2.1 The `err` estimate uses `aim_rot`, but `aim_off` is stale between aims

`_fight` computes the heading error as (line 685):

```python
err = wrap(heading(tx - px, tz - pz) - p.get("aim_rot", p["rot"]))
```

`aim_rot` is produced by `snapshot` as `aim_rot, aim_off, pitch = aim_of(m, pl, rot, r)`
(line 316-318), and `aim_of` (line 290-300) reads the horizontal aim offset **only while
actively aiming**:

```python
off = 0.0
if len(r) > 1 and r[0] == 0 and r[1] == AIM_R1:   # AIM_R1 == 6
    off = struct.unpack(">f", m.rd(pl + AIM_YAW_OFF, 4))[0]
    if not math.isfinite(off) or abs(off) > 0.5:
        off = 0.0
n = struct.unpack(">f", m.rd(AIM_PITCH, 4))[0]
return wrap(rot + off), off, pitch
```

The Hand Cannon's real aim cone is only **+0.063 / −0.050 rad** (`AIM_YAW_OFF` comment,
line 111-114) — about 3.6°/2.9°. But `aim_of` accepts any offset up to `abs(off) > 0.5`
(~29°) before treating it as "unknown" and flooring it to `0.0`.

Consequence: between aims (`r[1] != AIM_R1`) `off` is forced to `0.0`, so `aim_rot == rot`
(the body facing). But the moment R is pressed the game restores the gun's yaw offset from
its own aim state, which the bot then reads as `aim_rot = rot + off` where `off` can be up to
±0.5 rad. The bot's `err` estimate is therefore **stale or mismatched against where the gun
actually points** by up to ~0.44 rad (25°), against a fire tolerance of only
`FIRE_TOL = 0.035` rad (2°, line 103). The bot keeps steering to close an error that the gun
cannot physically reach, overshoots, and the aim "wanders" around the cone edge.

### 2.2 `AIM_KEEP_ERR` (0.8 rad) is far wider than the aim cone

While already aiming, `_fight` keeps the gun up and aim-turns when the error is within
`AIM_KEEP_ERR = 0.8` rad (~46°, line 139):

```python
aiming = self.r_since is not None
if abs(err) > (AIM_KEEP_ERR if aiming else TURN_TOL):   # line 715
```

The aim-turn moves the *offset* inside the Hand Cannon's ±0.063 rad cone first, and only then
turns Leon's body. So a new target up to 46° off the gun's point keeps the gun raised and
aim-turns, but the aim-turn's authority is the weapon cone — the moment `err` exceeds ~0.063
the offset saturates and the game autorotates the body instead, which fights the bot's own
turn stick (`left`/`right`). That fight between the bot's stick and the game's autorotation is
exactly the "spastic" oscillation: the bot pushes a turn, the game counter-rotates, the bot
recomputes a new `err`, pushes the other way.

The `_turn` controller (line 669-680) only damps this down below `AIM_FINE = 0.12` rad
(line 675-678), but nothing stops the bot from entering the wide-keep-err regime in the first
place.

### 2.3 Pitch is a global kept between aims, and it is applied blindly

The aim pitch is a single global `AIM_PITCH = 0x80218738` (line 104-108) that the game keeps
**between aims** ("a global ... kept between aims. Read only."). `_aim_body` (which decides the
pitch for a body target) only checks whether the pose is up and never issues a corrective
pitch; `_aim_height` (for thrown weapons) reads the current pitch and pushes a stick to walk it
toward the target.

So the sequence that produces wayward vertical aim is: Leon aims up at a roof/no-high-ground
Ganado (`HIGH_GROUND`, line 705), the global pitch climbs; he drops R to reposition; the next
Ganado is at chest height, but the global pitch is still up. `_aim_body`'s `level` test fails
against the stale pitch, the bot holds a fire while `_turn` re-aims, and every press of the
pitch stick (`PITCH_RATE`, line 156, learned) overshoots because it is walking a large residual
error through a 7-frame ramp ("the routine ramps the stick over 7 frames: ~2.4 a second held").

The shared conclusion: all three causes trace to the bot steering on **estimates of aim
orientation (`aim_rot`, global pitch) that are stale whenever the gun is not currently raised
and actively aiming**, plus a keep-err threshold far wider than the weapon's actual cone.

---

## Question 1 — Why is the bot unable to deal with this bot?

(Retained from the first revision.)

The stuck log at `~/.gbox/re4_learned/r400-stuck.jsonl` shows **11 identical entries**:

```
at=4.45, pos=[0, 0, 0], goal=[-3900, 300], action=vault, replanned=11
```

All 11 events have the exact same timestamp (`4.45`), position (`[0, 0, 0]`), and goal
(`[-3900, 300]`). This is degenerate data — the bot is stuck at the spawn point (origin) trying
to reach a goal 3,900 units away in the negative X direction, outside the learned map's bounds
(x: -60 to 63). The learned map shows Leon walked 2,074 cells (x: -60 to 63, z: -40 to 77), so
the bot *has* moved from spawn at some point, but the current stuck state is a stale entry.

The goal `[-3900, 300]` is outside the learned map's bounds. `_path` tries to plan via the
disc's nav map or the learned map; when neither has a route it returns a straight line that
crosses walls. The bot then replans 11 times, gets stuck, and logs it.

This is a **navigation planning failure**, not a combat failure. The bot is trying to reach a
time bonus / hourglass that is unreachable without a proper path planner.

---

## What's Missing

1. **Aim desaturation / dead-zone** — the aim cone error in §2.1–2.2 (the core of "wayward aim").
2. **Pitch re-zeroing** — reset or re-read the global pitch when R is lowered / a new target is
   acquired (§2.3), instead of trusting the kept-between-aims global.
3. **Navigation planning to unreachable goals** — fallback when the goal is outside learned map
   bounds (replans repeatedly, gets stuck).
4. **Stuck recovery** — back off / re-route / abandon the goal.
5. **Live verification** — the live session (lilspark, `8b7c0f5675d04c15-f66d53bcf39c4596`)
   is warm but the bot was not actively playing at the time of the first pass.

## Next Steps

1. Bound the accepted aim offset to the weapon cone (±0.063/−0.050) rather than ±0.5 (§2.1),
   and lower `AIM_KEEP_ERR` to within the cone so aim-turn never fights the body autorotation (§2.2).
2. Re-read/re-zero pitch on target acquisition, not just on pose-up (§2.3).
3. Fix navigation planning for out-of-bounds goals; add stuck recovery.
4. Verify on the live session once the bot is running.

## Files

- `gbox/re4_merc_bot.py` (1,776 lines, 110,079 bytes) — aim flow at lines 103-160, 290-300,
  313-318, 669-680 (`_turn`), 682-729 (`_fight`), 974-1015 (`_aim_body`/`_aim_height`).
- `tests/test_re4_merc_bot.py`
- `~/.gbox/re4_learned/r400.json` (2,074 walked cells, 224 blocked cells)
- `~/.gbox/re4_learned/r400-stuck.jsonl` (11 stuck events, all degenerate)

## Verification

- Aim cone constants verified against source: `AIM_YAW_OFF` cone +0.063/−0.050 (line 113) vs
  accepted ±0.5 (line 296) and `FIRE_TOL = 0.035` (line 103).
- `AIM_KEEP_ERR = 0.8` (line 139) vs `AIM_FINE = 0.12` (line 138) and `AIM_SPEED_X` history
  (line 134-137, operator note 2026-10-22).
- Global pitch `AIM_PITCH = 0x80218738` read-only, kept between aims (line 104-108).
- `pytest tests/test_re4_merc_bot.py` — see the test run in this revision's commit.
