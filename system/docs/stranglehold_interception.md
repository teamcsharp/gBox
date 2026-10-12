# Stranglehold bullet-time interception

This document describes the minimum set of game systems gBox uses to
intercept a Stranglehold precision-aim (bullet-time) shot, suspend its
resolution, and override whether it hits or misses.

## Minimum set of systems

The canonical source is `profiles/stranglehold-ps3-us.json`. The six
systems are:

| Role | Symbol / entry point | Why it matters |
|---|---|---|
| Shot type | `StrangleholdProjectile_Bullet_PrecisionAim` | The only projectile that enters bullet-time. |
| Suspend point | RPCS3 process pause (`RPCS3Adapter.pause`) | Freezes every PPU/SPU thread so the bullet cannot impact. |
| Presentation verdict | `ResolvePrecisionAim` | Decides whether the cinema shows a hit or a miss. |
| Damage verdict | `StrangleholdPawn.ServerResolveDamage` | The precision-aim branch sets lethal damage scale. |
| Slow motion | `WorldInfo.TimeDilation` via `SetTequilaTimeActive` | Slows the world while the shot is suspended. |
| Aim state | `StrangleholdPlayerPawn.IsPrecisionAiming` | Tells the HUD whether the player is currently aiming. |

## Chat / agent interface

The `stranglehold_shot` tool exposes these systems through the gBox chat
agent:

- `op=systems` — list the systems above.
- `op=locate` — find the profile's script functions in RAM for a running
  Stranglehold session.
- `op=arm` — apply the `god` preset (infinite life) so you can test safely.
- `op=fire verdict=hit|miss` — immediately force the next shot to hit or
  miss.
- `op=link` — start a `game_link` with Stranglehold as host and another
  session (e.g. Puyo Puyo Tetris) as guest. Supply `trigger`, `win` and
  `lose` memory watch specs. A guest win forces `god_hit`; a loss forces
  `god_miss`.

## Remaining live gap

The static systems and their bytecode patches are known and stored in the
profile. A full hands-free loop still needs two runtime memory flags:

1. **Bullet-cam / precision-aim start flag** — a stable address that flips
   when the player enters precision aim. The best candidates are
   `WorldInfo.TimeDilation` dropping below 1.0 or
   `IsPrecisionAiming` becoming true. Discovering the exact address requires
   a running session past the title screen with one aimed shot.
2. **Guest result flag** — for the chosen guest game (e.g. Puyo Puyo
   Tetris), a stable address that indicates a won or lost match.

Once those two addresses are pinned, the chat command
`stranglehold_shot op=link session_id=... guest_session_id=...
trigger=... win=... lose=...` runs the end-to-end loop.
