# RE5 Switch: weapon mastery (2026-11-09)

The operator, 2026-11-09: "Any weapon that I choose to equip the bot with, I need the bot able to masterfully use
that. So if I choose to have the bot use rotten eggs or a bow and arrow, they need to be able to spam fire that." The
same night: "the bot did an absolutely atrocious performance" (Ancient Ruins, the first 28 s: 63 shots, 413 gun raises,
9 hits taken). At 23:10 UTC: "throw eggs 20x the regular speed and fire the bow at 10x regular speed with adjustable
sliders".

All of this is offline work. No game was launched and nothing was written to the live system. The numbers below come
from synthetic snapshots (`system/tests/test_re5_switch_weapon_mastery.py`, a 30 Hz pad simulation). They measure the
bot's inputs, not the game's damage or its real fire rate. Kills per minute cannot be measured offline.

## What was wrong

* **The raise flicker.** `re5_switch_aim.keep_active` repositions when the aim stalls: it puts the gun down and steps
  for 0.65 s. On every tick of that step the crowd fire (`Bot._rampage`) saw `aim_since is None` and raised the gun
  again. keep_active then lowered it again on the same tick. That counted a raise every tick and reset the aim state
  every tick. Reproduced offline (a shotgun, three Majini within 5 m, the dot on none of them): **41 raises in 3 s
  (13.7/s)** before the fix, **3** after. Live telemetry read that night (the running session, 3 rounds) showed
  `raises` 820 and `aim_repositions` 54. That is about 15 raises per step, which matches this cause (inferred, not
  replayed).
  Fix: while a step is under way, the fight leaves the gun down (`Bot._repositioning`, stats `raise_holds`), and
  keep_active lets the step run to its end without a ZL in the act.
* **The bow and the eggs never fired on Switch.** The Switch fight is gated on the laser ray. The longbow has no laser,
  and no laser ray is known for the egg. So the bot raised, waited `LASER_WAIT_S`, re-raised, and so on (read from the
  code; not seen live). In a crowd the shotgun crowd
  fire raised the egg and never pulled the trigger, because no "shotgun" was in hand. On the PS3 path the floor-corridor
  requirement kept the bow silent. It is now only a soft preference in `re5_weapons.bow_fire_policy` and
  `laserless_fire_policy`. Only a known wall (`wall=True`) holds the bow.
* **The operator's weapon was swapped away.** In a crowd the shotgun swap took the chosen weapon away. `_gun_back`
  forced any grenade back to a gun. An empty chosen gun was dropped at once, even with ammo to reload.

## The controllers (`re5_weapons.MASTERY`, `Bot._mastery`)

The hitscan guns keep the Switch laser fight (`Bot._decide`, `_rampage`, `re5_switch_aim.apply`). Each one also gets
its family's tuning. Every other family runs `Bot._mastery`. In its band the stance stays up between shots. Only an aim
more than `UNAIM_ERR` (35 deg) off for `UNAIM_HOLD_S` lowers it to turn the body. The aim is re-made every tick: through
the RAM aim writer when the session has one, else with the right stick. The trigger runs its pattern while aligned.
Out of its band the bot moves: it closes in at a run, or for an explosive it steps out of its own blast while still
facing the targets. The doctrine (never stand, never hold fire among enemies, the combo clock) is kept: `_never_stand`
treats ZL or L held as busy, and target choice still goes through the combo push and threat-first rules.

| family | mode | band (cm) | button pattern | offline: trigger edges/s with a target in band (or ZR held) | first trigger |
|---|---|---|---|---|---|
| handgun | laser | 0-1800 | ZL held; ZR held while the dot or ray is on a body | ZR held 100 % (1 edge) | 0.17 s |
| automatic | laser | 0-2500 | ZL held; ZR held, held through a body-width slide for 0.2 s (`AUTO_HOLD_S`) | ZR held 100 % | 0.17 s |
| shotgun | laser | 0-1000 | ZL held; ZR held; point blank (<= 2.5 m, <= 15 deg yaw, ray not stopped short) counts as contact | ZR held 100 % | 0.17 s |
| rifle | laser | 300-8000 | ZL held; ZR with the dot on him; far targets preferred (cost x0.8, x1.6 under 3 m) | ZR held 100 % | 0.20 s |
| magnum | laser | 0-5000 | ZL held; ZR with the dot on him; big targets (hp_max >= 3000) cost x0.5 | ZR held 100 % | 0.17 s |
| bow | arrow | 0-2500 | ZL held (the draw stance); ZR one tick down, one up while aligned on the chest; heading and pitch re-made between arrows | 14.5 /s | 0.20 s |
| egg | throw | 0-1000 | ZL held (the egg's raise is motion 22 / 24); ZR down / up at the crowd's centre, lofted 2 deg/m | 15.0 /s | 0.17 s |
| thrown (hand, incendiary) | throw | blast 500, up to 1200 | ZL held; ZR down / up at the crowd's centre; never with the impact within 5 m of him or the partner | 14.5 /s | 0.20 s |
| thrown (flash) | throw | 0-1200 | as above, with no self-blast | 15.0 /s | 0.17 s |
| launcher | splash | blast 500, up to 2500 | ZL held; ZR down / up; the laser dot (when shown) is the impact: on a body or within 2 m of the crowd's centre, and outside the blast | 15.0 /s | 0.17 s |
| rocket | splash | blast 700, up to 4000 | as the launcher | 15.0 /s | 0.17 s |
| melee (knives, stun rod) | contact | 0-160 | closes to contact (lup); facing him, L held, ZR down / up | 14.5 /s | 0.00 s |
| flame | stream | 0-400 | ZL + ZR held while he is within 4 m and inside 12 deg | ZR held 100 % | 0.17 s |

Before this change, the same 3 s scenes gave **0 trigger presses** for the bow, the egg, the hand grenade, the grenade
launcher, the stun rod and the flamethrower. The stance came up and waited for a laser ray that never shows. Every
family raised once in its 3 s scene: no flicker. Idle with a target in band: 0.13-0.17 s (the stance coming up,
`READY_S`), 0 for melee. The tap pattern gives a fresh ZR edge every second tick. That is 15 edges/s at 30 Hz, or 13
at the live 26 Hz. A press the game ignores mid-animation is lost, not waited for, so the weapon's own animation sets
the rate. With the per-weapon multiplier, the bot becomes the limit only once the animation repeats faster than about
13-15 times a second.

Distances, windows and lofts are bot tuning values (`re5_weapons.MASTERY`), not decoded game limits. The bow's loft is
0.25 deg/m (6 deg max), the throws' 2 deg/m (25-30 deg max), the launcher's 0.5 deg/m. None of them has been
calibrated against a real impact.

## The operator's weapon (`WM_KEEP_CHOICE`)

The chosen weapon is the native three-minute primary while it is usable, else the `select_weapon` preference
(`Bot._chosen_item`). It stays in hand:

* in a crowd, `_rampage_gun` returns it: a laser family fires through the crowd fire, any other family through its
  own controller. There is no shotgun swap.
* `_gun_back` keeps a chosen grenade, egg or knife in hand. The proximity bomb is never kept; the mine controller owns
  it.
* if it is empty, it stays while ammo is in the inventory, with ZL + B for up to `WM_RELOAD_WAIT_S` (2.5 s). After that
  comes the loaded fallback. With no ammo at all, the fallback is immediate.

With no choice, today's arsenal logic is unchanged: the crowd puts the shotgun up and a grenade in hand goes back to the
gun.

## Stats (live telemetry, per round)

Per family, while its weapon is in hand: `wm_<family>_shots` (trigger edges), `_hits` (target health lost near a pull:
the existing measurement, damage source unverified), `_kills` (the round's kill counter rising), `_hand_s`,
`_range_s` (a target on his level in its band), `_range_shots`, `_shots_per_s` (= range_shots / range_s),
`_trigger_s` (ZR held), `_idle_s` (a target in band, no trigger this tick or the last, no left stick), `_kills_per_min`,
`_spent` (the slot's count falling, without infinite ammo), `_backoffs`, `_raises`, `_ram_writes` and
`_ram_write_failures`. The round line is `wm_summary`. Also: `wm_controller`, `wm_gate`, `raise_holds`, `wm_reload_waits`,
`target_feedback_point_blank`, `target_feedback_auto_holds`, and `weapon_motions_seen` (`{"0x36": {"41": ticks}}`) with
`weapon_motions_seen_text`.

## What to look for live

| family | look at | expect |
|---|---|---|
| bow | `wm_bow_shots_per_s`, `wm_bow_spent` (rounds, without infinite ammo), `wm_bow_idle_s`, `wm_bow_kills_per_min` | 13-15 presses/s in band; arrows actually leaving: `spent` rising, else the press pattern needs the hold variant; idle < 5 % of `range_s` |
| egg | `wm_egg_shots_per_s`, `wm_egg_hits`, `weapon_motions_seen_text` "0x36" | 13-15 presses/s; the throw's motion id to put in `re5_weapons.RATE_MOTIONS[0x36]` |
| thrown | `wm_thrown_backoffs` against `_shots`, `hits_taken` | no self-blast hits; backoffs end in throws |
| launcher / rocket | `wm_launcher_shots`, `mine_blast_hp_loss`-like self-damage in `hits_taken` | shots only from beyond the blast |
| melee | `wm_melee_shots_per_s`, `wm_melee_kills_per_min` | about 13/s swings in contact |
| flame | `wm_flame_trigger_s` / `wm_flame_range_s` | near 1 |
| handgun / magnum / automatic / shotgun / rifle | `wm_<f>_trigger_s` / `_range_s`, `raises` per minute, `raise_holds`, `target_feedback_point_blank`, `target_feedback_auto_holds` | raises no longer above about 1/s; `idle_in_5m_s` falling |

## Per-weapon rates (`re5_switch_mods`: `egg_rate`, `bow_rate`)

These use the same mechanism as `fire_rate`: the player's time scale (+0x1A08) is set to x N while a motion plays and
put back when it ends. They act on the weapon's own motion set (`re5_weapons.RATE_MOTIONS`) while that weapon is in
hand. `egg_rate` runs 1..40 (default 20) and `bow_rate` 1..20 (default 10). `FIRE_MAX` stays the guns' cap only.
Aliases: egg_speed, egg_throw_rate, rotten_egg_rate, throw_rate; bow_speed, bow_fire_rate, longbow_rate, arrow_rate.
`rotten_egg_only`'s rate is the same egg setting.

**The motion sets are empty.** The egg's raise is 22 / 24 (live 2026-10-27, `re5_switch_mods`). Nothing in the code or
docs names the throw's motion or the bow's draw / release motions, so no id was invented. Until the sets are filled the
sliders save their value and scale nothing. To fill them: equip the egg or the bow, let the bot fire, read
`weapon_motions_seen` in the telemetry (every motion byte seen while that weapon is in hand and its trigger is held, by
tick count), then put the throw / release ids in `re5_weapons.RATE_MOTIONS`. While a motion in the set plays the bot
drops the aim stick (`shot_stick_drops`), the same rule as the guns' shot motion.

Controls: `mod.egg_rate` "Rotten egg throw rate ×" and `mod.bow_rate` "Bow fire rate ×" (`gbox/merc_live_controls.py`
MODS, the MCP `game_live_controls` inventory). They are also in the live-mods panel and the PiP sidebar
(`clients/web/viz/re5-modifiers.js` DEFINITIONS, `switchOnly`; `bot-logic-sidebar.js`).

## RAM fields relied on (all already read; no new offsets)

player +0x60 pos, +0x70 rotation (heading), +0x8F8 motion, +0x1EB8 health, +0x3F5C aim pitch; the inventory slots
(+0x30F0: id, rounds, grid, in hand); enemies +0x60 pos, +0x1EB8 health, +0x8F8 motion; the laser unit (line 19:
+0x280 muzzle, +0x60 dot); the camera uCameraQFPS +0x1B0 pitch and the player's heading (`re5_switch_aim.aim_state`,
the aim writer's existing pitch / heading writes, read back); cGameSys kills +0x96C and combo +0x974 / +0x97C; the
stage's nav mesh (`re5_switch_native_nav`, for the corridor preference); player +0x1A08 time scale (the rate mods,
already `fire_rate`'s).

## Reload / restart

Hot reload in place: `gbox/mercs/titles/re5_switch.py`, `re5_weapons.py`, `re5_switch_aim.py`, `re5_switch_mods.py`.
New Bot attributes are read with getattr / setdefault, and no module is imported at tick time that was not already
loaded. The control plane needs a gbox.service restart to show the sliders: `gbox/merc_live_controls.py` (the slider
rows and bounds) and `gbox/mcp_server.py` (the tool description). The web panel files
(`clients/web/viz/re5-modifiers.js`, `bot-logic-sidebar.js`) need a page reload. `gbox/mcp_bot_controls.py` was left
alone: its catalog lists only ops the PS3 tool dispatches (test_mcp_bot_controls). `game_mod` still passes
`egg_rate` / `bow_rate` through to a Switch session, because `mod_input` does not filter ops.
