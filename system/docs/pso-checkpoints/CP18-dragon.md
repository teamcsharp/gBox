# CP18 (P4): the Dragon - status **partial**, fight reached, HP read missing

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Goal: mastery (CP18)
Live: session `75cf966f35164149-4ec5d512e3484b02`, `boss_warp target=dragon`, floor `0x805D5FC0` = 11 (dev warp, allowed by CP18's own instruction)

## What works

- `pso_controls op=bosses` lists Episode I's bosses with floors: `dragon` 11, `de_rol_le` 12, `vol_opt` 13, `dark_falz` 14.
- `pso_controls op=boss_warp {"target": "dragon"}` -> `{"verified": true, "requested": true, "arrived": false, "message":
  "Travelling to Dragon / Sil Dragon; the game is loading the destination."}`, then `adventure_status` ->
  `{"travel": {"state": "arrived", "boss": "Dragon / Sil Dragon", "floor": 11, "age_s": 234, "message": "Boss area loaded"}}`.
- The arena loads and the fight starts: the character's HP fell 40 -> 20 from the Dragon's attacks, and a 40-round
  lock-on/advance/attack loop ran with the working keyboard input path.
- `pso_controls op=survival {"on": true}` -> `{"permanent_scape": true, "verified": true, "note": "Virtual Scape Doll: native
  revival on death"}` keeps the fight from ending while the HP read is built.

## What is missing for the accept

CP18's accept is *the boss's HP reaches 0 from RAM, with both players alive*. Reading the boss HP is the gap:

- `pso_boss_strategy.boss_target(ad)` / `boss_telemetry(ad)` take the **adapter**, and no HTTP operation exposes them
  (`status` returns player stats, `adventure_status` returns travel, `bosses` returns the list).
- No boss HP address appears in the checkpoint docs.

So the next piece is a live read of the boss entity's HP: either an RPC-visible operation over `boss_target`'s own scan, or a
direct replication of that scan (the module already documents which fields it trusts: `_hp_fraction`, `_valid_hp_max`,
`_targetable`, `_pick_main`).

## A correction worth keeping

The character's character-panel read **Total EXP: 0 pt** after hours of driving. The bot was not failing to land hits in a fight -
it was attacking empty ground in Forest 1, where no enemy was present. EXP is the honest scoreboard for "is the bot playing", and it
was zero. Boss EXP is granted on the kill, so the panel is not a mid-fight signal; boss HP from RAM is.
