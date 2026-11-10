# Request 4838 — rampage fire — checkpoint (local deepseek run)

## State this run (verified, not assumed)
- i9-NUC (RE5 Mercenaries test host, Windows): `online:false`, admission
  `allowed:false` ("Waiting for five minutes without operator input"),
  ollama unreachable. **Live per-round counter read is NOT runnable.**
- `list_sessions` live sessions: only one — RE4 on lilspark (`worker_name
  lilspark`, citron, `agent_owned`). **No live RE5 Switch session anywhere.**
  lilspark and JAYBUILTFINALE are online, but JAYBUILTFINALE is the operator
  play PC (never test there) and lilspark is running a different game.
- Git: worktree clean, on branch `hermes/request-4838-1794038105876990908`
  head `3bc16533` (the checkpoint commit already recorded on main). No source
  changed this run; nothing to publish.

## Root-cause candidate (documented in code, unproven live)
- `re5_switch.py` crowd/rampage fire path: while `on` (ring enemy in the cone
  OR `_unload`), `_trigger(True, now)` is called every tick at ~2316-2318,
  i.e. `zr` is HELD full-auto (not tapped). Combined with the `fire_rate` mod
  this repeats a held ZR at up to 25 shots/s — the plausible "insane" spray.
- The normal non-rampage path already taps `zr` at a sane cadence
  (`_pull_start`/`_pull_end`, `PULL_SHORT_S`). The crowd path bypasses it.
- Distinguishing the actual fault (swap spam vs fire-rate spray vs 360° whip)
  still requires the live per-round counters (rampage_swaps/shotgun_swaps,
  behind_turns, whips, offscreen_aim_s).

## Next acceptance step (unchanged, still blocked)
One MercMode RE5 round on i9-NUC with rampage on; read per-round counters to
NAME the fault; then bounded fix (front-facing stable aim within the 5 m
circle + swap/fire cadence cap) proven by a focused test and one live round.

## Concrete dependency
i9-NUC must come online / admit a job (operator absent 5+ min right now).
