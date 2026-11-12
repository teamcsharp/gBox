# RE4 Switch: a boss on screen is neutralized (2026-11-12)

Operator, 2026-11-12 (while watching a Village round):

> "In Resident Evil 4, if a boss character shows up on screen, have the bot pull out a magnum or a shotgun and unload
> on them relentlessly. I am watching the bot let bosses come onto screen. They will knock the bosses down, not get rid
> of all their HP, and then let the boss come right back and finish them off. ... make sure that the bot knows a boss
> has appeared on screen and that they need to be neutralized right now."

and, in the same minute:

> "also if a chainsaw boss approaches the character. Do a 360 grenade launcher 10 round nitrous blast freezing the
> immediate enemies in the vicinity. If a boss is preparing to hit the character with a kill animation, defend them
> with a 360 grenade nitrous blast"

## What the previous run (the evidence for the report)

Session `96df04f47a2f445a-7ef0908f223e4243`, Village / Leon, **three rounds, three deaths**
(`mercs/curriculum/010099A00BC1E000/rounds.sqlite`):

| round | shots | hits | kills | boss_picks | outcome |
|---|---|---|---|---|---|
| 1 | 84 | 41 | 31 | **0** | died |
| 2 | 188 | 141 | 17 | **0** | died |
| 3 | 275 | 181 | 28 | **0** | died |

The aim book in those rows carries a **`0xae7050:6500` cell** - a 6500-health enemy (Dr. Salvador / a Bella Sister)
was being shot at 1.3-2.5 m, with a logged miss "on_body, the line +0.9/+28.6 deg off" - and the round still ended
with `max_hit_dmg 1860`, the whole health bar in one blow. So the boss was engaged, not killed, and the same one came
back. `boss_picks 0` in every round names the first cause exactly.

## Why `boss_picks` was always 0

1. `re4_switch.combat_profile()` passed only `combat.hp_tier(dangerous_hp=HEAVY_HP)` as its tier fallback, so a
   6500-health boss was tiered **dangerous**, never **boss**; and RE4 Switch reads **one RAM class (0xAE7050) for
   every Ganado**, so `enemy_identity` could never name a boss by class either. The scorer's boss band was
   unreachable on this title.
2. The heavy/apex keep rule (`APEX_HP 6000`, `APEX_KEEP_MM 15000`) then **evaded** the boss - `_heavy_keep` is
   evaluated before the target pick - which is the "knocks it down, backs off, it gets back up" behaviour.

## The fix

* **Identity**: `re4_switch.boss_key(enemy, stage)` names a boss from its maximum health and the stage's ESL set list
  (`enemy_identity.re4_unit_key`), with `BOSS_HP_MIN` (3000) as the floor and the chainsaw keys (salvador / bella /
  super_salvador) recognised. `snapshot()` writes `boss` / `key` / `chainsaw` on each enemy row, so every title-level
  rule (and the ring rule) can see it.
* **Tier**: the profile's fallback is `hp_tier(boss_hp=BOSS_HP_MIN, dangerous_hp=HEAVY_HP)` - a 6500 boss is "boss"
  in the shared scorer, so `boss_picks` moves and the boss band outranks the crowd.
* **Target lock** (`Bot._boss_pick`): the nearest boss **on screen** (BOSS_SIGHT_MM 30 m, in front or on him) is
  picked before the range/LOS/crowd/continuity rules, and locked until its health is zero - never released for a
  nearer Ganado. A boss that drops out of the census (a knockdown) keeps the lock `BOSS_LOST_S` and the bot keeps
  firing where it went down; a snapshot row with hp 0 ends it and counts `boss_kills`.
* **No retreat from a boss**: with a boss locked the bot skips `_heavy_keep` (incl. the apex keep), `_low_life`, the
  swarm escape and the melee follow-up, and the fire pattern never hops off it. The landed-blow dodge and the learned
  attack step-out still answer a specific incoming attack, then return to the boss (the lock is unchanged).
* **The gun** (`re4_switch_mods._boss_weapon`): while a boss is on screen, a magnum or a shotgun goes into his hand by
  the same verified in-hand swap as the round's random weapon - `BOSS_GUNS` in order (Handcannon, Killer7, Broken
  Butterfly, Striker, Riot Gun, Shotgun), only an id the build's tables carry, one swap per boss encounter. An
  already-magnum/shotgun hand gets an "already" receipt instead of a write.
* **The defensive Nitrous ring** (`grenade_ring.decide`): a chainsaw boss within `defend_cm` (10 m), any boss within
  `defend_close_cm` (4.5 m), or a boss with a wind-up within `defend_windup_cm` (15 m) earns the 360 10-round ring
  immediately, and its radius grows to reach the boss. The round is the freezing one where the title has it (RE6's
  Nitrogen shell `shell1304`); RE4 and RE5 carry no Nitrogen round, so there the round is the **flash** (their own
  stun). The decision is visible as `kind: nitrous` / `defend: true`; the receipt names what actually fired.
* **Units**: the ring rule speaks centimetres and RE4's snapshot speaks millimetres; `control()` now takes
  `units_per_cm` (the RE4 playbook passes `re4_switch.MM_PER_CM`) and scales the view. Before this RE4's ring counted
  only enemies inside **0.8 m** (800 read as centimetres) and the 90 s ring could not see a room.

## The honest limits

* RE4 has no Nitrogen round; the "nitrous blast" resolves to the flash ring there, which is the game's own stun. The
  title frames it as what it is: `ring_defend_kind` / the receipt's `kind`.
* RE4's mine-thrower ring (`MINE_CANDIDATE = 0x2E5050`, the class table's fourth spawn) is still a **probe**: it is
  called behind `allow_unverified`, its receipt is `probe: true`, and the status refuses it until a live receipt shows
  the placed object arming/exploding.
* The RE4 native harness now attaches on demand (`Controller.ensure_attached`, the RE5/RE6 shape). This is a
  **native-module** change: it needs one `gbox.service` restart to load (`gbox.mercs.titles.re4_switch_native` is in
  `hot_reload.NOT_BOT`); the bot-side logic (boss lock, gun swap, ring decisions) hot-reloads.

## Live acceptance to collect

1. A RE4 round with a 6500 boss: `boss_engagements >= 1`, `boss_target_key` / `boss_target_hp_max` 6500,
   `boss_shots` climbing, `boss_kills >= 1` - and the aim-book cell for that boss at 0 kills-to-death.
2. `mods_boss_weapon_swapped >= 1` with `boss_weapon.verified true` and a magnum/shotgun id in hand when the round's
   random weapon was not one.
3. The defensive ring: `ring_decision` "DEFEND: a chainsaw boss ..." and `ring_defends >= 1` with
   `ring_kind_fired` = shell1304 on RE6, flash on RE4/RE5, and the boss stunned (RE5/RE6) or staggered (RE4).

## Live receipts (after one gbox.service restart, 2026-11-12 16:33 and 16:45 CST)

Both changes are native-module code (`hot_reload.NOT_BOT`), so the service was restarted twice; the second restart
also loaded main's `hot_reload.py` (the share carried an older edit that no deploy would overwrite, which is why
`gbox.re4switch_bot` could not reload in place). The bot-reload route now accepts it ("loads fresh at first use").

**RE4 boss lock** (session `f418bcdd28f748ef-6546ad1414b148e5`, round 1, Village):

    boss_engagements 1, boss_target_key salvador, boss_target_hp_max 6500, boss_chainsaw true,
    boss_on_screen 1, boss_distance_cm 1275.9, boss_locked_s 6.6, boss_picks 0 (the band had not needed to fire yet)

A 6500-health chainsaw boss 12.8 m out is named and locked - the operator's "knows a boss has appeared on screen".

**RE6 ring rule armed and firing on schedule** (session `feb0d0f84514404c-4faa7ec207ab407a`, round 1):

    ring_armed true, ring_prof_map 01002A000CD48000, ring_near 24, rings_attempted 1, ring_kind_fired launcher
    ring_last_reason "periodic: one ring at least every 90 s with a group on him: 2 within 800 cm"
    ring_error "Unavailable: the launcher is not in this inventory yet: the shell ring retries next tick"

The 90-second launcher ring fired and the honest refusal is the loadout (the launcher is not in this round's
inventory) - that is the next fix, not the rule.

**A ring click through the status bar's API reached the game** (same session, op grenade_ring kind flash):

    {"state": "uncertain", "kind": "flash", "requested": 10, "detonated": 1, "radius_cm": 600.0,
     "hp_before": 788, "hp_after": 788, "self_damage": 0,
     "reason": "native explosion transition not confirmed"}

The chain is proven end to end (queue -> worker -> native spawn -> receipt, no self-damage); RE6's flash explosion
confirmation stopped the ring after one grenade, which is the native flakiness the next pass has to close. The
status now advertises all eight kinds (`flash` available on RE6) and a controller that attaches on demand is offered
rather than refused, so the PiP's ring button is no longer greyed out on RE4.
