# DeepSeek PM/engineer — evening log, 2026-11-11 (13:30–17:30 CST)

Continues `DEEPSEEK-HANDOFF-2026-11-10-NIGHT.md` (which ends 14:05) and the operator's
`DEEPSEEK-PM-HANDOFF-2026-11-11.md`. This session ran the gBox MercMode rotation on lilspark while working the
operator's asks; the goal is still active (the operator keeps iterating), so this is a state-of-play, not a close-out.

## The operator's asks this session (verbatim highlights)

- "I want the bot to follow report in Merc mode every time the combo is lost … more proactive with maintaining the combo."
- "Every time the player is hurt or is attacked, I want a report filed for the bot to have an investigation done."
- "If an enemy hurts my character, prioritize using the magnum on that enemy in the future."
- "Randomize the weapon being used between rounds between all of the weapons available in the campaign at random
  emphasizing magnums and shotguns" → then "I'm seeing him still use pistols instead of shotguns and magnums."
- "The bot should be playing the same way in Resident Evil 4 as it does in RE5 and 6 … navigating around the level,
  going for time bonuses … maintaining the combo the entire match … infinite ammo and superior weapon reload and lack
  of recoil."
- "Why does the bot just sit there instead of firing on the enemies?"
- "Make sure the bot is learning and making aim compensation for missed shots … I dont like seeing the bot miss enemies
  so close to him."
- "Make sure the grenade rings are fully comp[lete]."
- (Earlier, still open) the QTE flags + stick throttle; the hand/incendiary/ice/acid grenade kinds; the RE6 remote mines.

## Shipped this session (main, each with tests)

| commit | what |
|---|---|
| `b813c90f` | every combo lost files one follow report (the operator's combo report); `gbox/mercs/combo_reports.py` |
| `9e151053`…`b993d5a9` | every player hurt files one follow report (hp before→after, attackers/wind-ups, doing/why, clock); the damage observer's `player_damage_events` (RE6's own counter), per-round baseline, near-enemy attackers |
| `2e5cb097`…`9983a9a5` | RE6 hand/incendiary ring: the player from `ready()`'s pair; the parameterised spawn/detonate get a 3 s budget |
| `7256b377` | RE6 native call timeout names the mailbox heap state and target (the class-spawn diagnosis) |
| `be7c3098` | RE4 aim: the facing write is smoothed (0.5° deadband, ≤3°/write — the operator's motion sickness) |
| `63b3206f` | RE4 walk: turn hysteresis (no left/right flutter near `TURN_TOL`) |
| `c8517b6f` | RE4 bow: the trigger is held through the draw (the tap was a zero-length press) |
| `bd67ff17` → `4075113c` | RE4 random weapon: primary-only — every round a max-level magnum or shotgun (the pistols upset the stream) |
| `102ae8cd` | RE4: a Ganado inside 3 m gets the body-angle gate after 0.4 s, not the 1.5 s sight stall |
| `46d93947` | aim book: a bias pinned at its cap with no hit probes back to neutral (the close cell sat at −10°, 0 hits) |
| `ccb66ae5` | RE4: no deliberate scatter on a body inside 3 m (the magnum's close misses) |
| `c9efbcb2` | RE5 boot: an alternating select pair forces the direct confirm (the block toggling select_player ↔ select_stage) |
| `dfae0934` | grenade ring: no ring in the first 6 s of a round (the RE5 auto-ring froze two blocks on a loading screen) |
| `9d8b02cd` | RE4 playbook: the mods' live states (weapon class, the bow's motion class/routine, aim counters) in the watch stats |

Deploys verified on the Spark: `b993d5a9` (15:45), `102ae8cd` (16:15, `re4_switch`+`re4_switch_mods` reloaded),
`dfae0934` (16:45, `aim_book`+`grenade_ring`), `ccb66ae5` (17:00, `re4_switch`), `c9efbcb2` (16:30, `mercs_bot`).

## Live evidence

- **Combo reports**: 18+ live requests (one per combo loss, capped 3/round).
- **Hurt reports**: 12 live requests with `hp 750 -> 455`, attackers `uEm4701 at 3 cm`, the bot's own learned "an
  attack that hurt him through his shots"; 12 on the current RE6 block.
- **RE6 doctrine ring**: 6 attempts / 4 deployed on the live block, the one error an honest "player is not alive".
- **RE6 remote mines**: 28–64 bombs, 7–8 rings, 2–5 flag detonations on the live rounds.
- **RE6 kills**: Carla rounds at **153–154 kills** (No Mercy), the crowd-dispatch style the operator wants.
- **RE4 weights**: every round since the primary-only draw read `weapon_class 0x0F/0x05` (magnums) — no pistols;
  Leon rounds 17/23/34 kills with hits ≈ kills.
- **Aim book**: the RE4 cells carry real histories; the close cells were the problem — magnum 0–3 m 386 shots/58 hits
  (15%), the yaw bias pinned at +9°; the handgun cells 14/23, 15/36.
- **RE4 bow**: the trigger-through-draw fix deployed; Krauser's rounds still read 0 hits — under diagnosis (the
  diagnostics `weapon_class`, `motion_rate_class/routine` are live in the watch stats).

## The Hermes queue — the important PM discovery

The queue skips agent-filed `automated` requests unless they are repairs, operator children, actionable
(`gap`/`characters`) or an **explicit dated handoff** (`context.handoff = YYYY-MM-DD`) that is also selected in the
priority list (`gbox/hermes_work_queue.py:368–379`, `_prioritized_handoff`). Every CODE-CHANGE ticket filed this session
was automated without that context, so none was ever dispatched — the queue looked dead while the Hermes workers ran.

Fixed by re-filing all six with the dated handoff and supersedes links, first in the priority:

| now | content | was |
|---|---|---|
| #9933 | RE5 boot / FEATURES + select hangs (#9872) | #9872 |
| #9934 | RE4 movement & aim naturalness (#9789) | #9789 |
| #9935 | QTE flags + stick throttle (#9769) | #9769 |
| #9936 | every grenade-ring kind (#9771) | #9771 |
| #9937 | crowd dispatch / proactive combo (#9720) | #9720 |
| #9938 | combo reports, aim, ordnance (#9744) | #9744 |

A manual `hermes_work_queue.tick()` confirms admission but the queue is at **12/12** capacity (`global_capacity 26`),
held by the operator's 301 durable favorites (DOA5LR #2450, NFL Blitz 2003 #2360, Illbleed, …) with real multi-run
progress notes. The code tickets wait for a slot; the lever (raising `local_settings.max_parallel_jobs`) was **not**
pulled silently — it is a global work-queue setting and the favorites are the operator's own durable work.

## Open / next

1. The live blocks for the last four fixes (RE4 close-scatter clamp + bias probe; RE5 select confirm + ring start
   guard) — the rotation had not reached RE4/RE5 since they deployed.
2. #9936: the RE6 hand ring still fails in the parameterised spawn call (3065 ms, no unit); the mailbox heap-state
   diagnostic (`7256b377`) needs the next service restart to load, then one hand probe reads state 1 vs 2 and picks
   the next experiment (item/register pre-set or the game-throw fallback).
3. #9935: the QTE RAM flags + left-stick analog throttle (the operator's dog-maul acceptance).
4. #9934: the RE4 time-bonus navigation (the mapping/guide hooks) and the never-stand acceptance; the aim book's
   magnum-close hit rate is the live measure.
5. The RE4 bow hits=0 (Krauser) — the diagnostics are deployed; the next Krauser round decides whether the 40x
   motion rate is on.
6. The pre-existing test-collection gaps (`test_re4_menus`, `test_re6_switch` fixtures missing) — unrelated to this
   session's changes, worth a cleanup pass.

## The MercMode rotation (operator 2026-11-11 17:35: "RE4 / 5 / 6 all seamlessly going from game to game")

The rotation's real state lives in the **`autoplay_screensaver_run/<worker>`** store doc (the screensaver's run:
`mercmode` payload, `mercmode_rounds`, `mercmode_quick_deaths`, `mercmode_rotate_requested`), not in the `session` or
`screensaver` docs (both read empty and misled a first diagnosis). The `screensaver.round_boundary` gate is:
`run.get('mercmode')` present, `cfg['enabled']` true, not pinned, `alternatives` (the worker inventory's other titles)
non-empty, and `played >= cfg['rounds_per_title']`.

Live at 17:45: the lilspark block is RE6 (Ada/stage 6, the recovery blueprint), `mercmode_rounds 2` of `5`;
`cfg` normalizes to `enabled: true, titles: [re4, re5, re6], rounds_per_title: 5` with the operator's Switch No Mercy
editions. The 5 rounds per title is the operator's own 2026-11-10 instruction ("i want to see at least 5 matches per
title") - not a bug. The lilspark `setting/lilspark` doc was empty (so the default `enabled: false` applied); it now
carries the enabled rotation and the PC app re-pushed its 5-round cadence.

The earlier "no RE5" was the RE5 *turns* dying in the boot (FEATURES screen, select loop, first-second ring hang - all
fixed and deployed) plus the 5-round block cadence. Watch the block reach `mercmode_rounds 5` and the title switch as
the live proof.

## PM notes

- Verify a deploy by **both** `deployed-main.txt` and the deployed file's content; "reloaded …" names the modules.
- New bot modules (`hit_reports`) do not hot-reload until the worker restarts; `mercs_bot`/`re4_switch` do.
- The live engine telemetry freezes when the bot's thread blocks (the RE5 ring hang was visible as a frozen
  `rings_attempted 1` + a loading screen); the session's `age_s` is the tell.
- The operator's stream preference is explicit and consistent: strong maxed weapons, no pistols, no deliberate scatter
  inside 3 m, no standing, combo and reports always.
