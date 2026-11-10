# DeepSeek task: the grenade ring on every Mercenaries title (2026-11-10)

> **Hard rule (2026-11-10 ~12:50): hands off lilspark.** Never `ssh` into the Spark (10.89.1.246), never run
> `sudo` / `systemctl` / `kill` there, never launch or stop a game on it. Something did that twice today, and each
> `systemctl restart gbox.service` killed the live MercMode games. Work on the i9 against its own gBox
> (`10.89.1.43:8765`). Send `x-gbox-actor: agent` on every API call. Anything that needs lilspark is a request in
> your lane log; the RE session does it. See DEEPSEEK-HANDOFF-2026-11-10.md section 0.


Written for the DeepSeek session. The operator, 2026-11-10, about the PiP's grenade button, whose menu shows
"Flash (unavailable) / Hand (unavailable) / Incendiary (unavailable)": "i need the grenade deployment feature completed
across all titles in full ... and all these titles." The RE session's own agent for this was stopped part-way, so the
task is yours. This is separate from your PSO lane (DEEPSEEK-PSO-TASK-GUIDE-2026-11-09.md); keep both moving.

## What "the grenade ring" is

The `grenade_ring` intervention: ten grenades spawned in a ring around the player that bloom outward and detonate. It
is a spectacle mod that clears a crowd. The operator wants the bot to fire it by itself when surrounded or facing a
heavy, and wants it available from the PiP button on every title.

## What exists today (check each line on main before relying on it)

**Switch only** (operator 2026-11-10: "we should only be focusing on switch versions. The ps3 and gamecube versions no
longer matter. I only want the switch version of RE4/5/6"). Do no work on RE5 PS3, RE6 PS3, RE4 GameCube or RE4 Wii;
read their code only as a reference.

| Title | Ring | Where |
|---|---|---|
| RE5 Switch (010018100CD46000) | flash only, verified live; hand and incendiary are refused "until verified" | `gbox/mercs/titles/re5_switch_native.py` (`Controller.grenade_ring`, `grenade_ring_now`) |
| RE4 Switch (010099A00BC1E000) | none (the GameCube edition's `gbox/mercs/titles/re4_gc_native.py` `grenade_ring` is a reference only) | |
| RE6 Switch (01002A000CD48000) | none (another lane may land it: look for `grenade_ring` in `re6_switch*` on main first) | |

The plumbing is already there and is the same for every title:
- The request: `POST /api/sessions/{sid}/interventions` with `{"op": "grenade_ring", "request_id": <new UUID>,
  "args": {"kind": "flash" | "hand" | "incendiary"}}`. `gbox/mcp_server.py` (the `game_intervention` tool) and
  `gbox/merc_live_controls.py` already accept the op and the three kinds.
- The status: `GET /api/sessions/{sid}/interventions`, which the PiP reads to grey out kinds. The backend is
  `gbox/mercs/interventions.py`; the PiP's menu is `system/clients/web/viz/stream-interventions.js`.
- Known bug: on RE6 Switch (1.0.2) the status answers `available: false, "no living player in an active Mercenaries
  round"` while a round plays, which greys out every intervention there (flash_now and magnum_quick4 as well).

## The packages, in order

1. **An honest status.** Per title and per kind: available, or unavailable with the reason (not built for this
   title / kind not verified / no player found). Fix the RE6 player/round detection for 1.0.2. Accept on: the PiP
   shows exactly what works on each title.
2. **RE5 Switch: hand and incendiary.** Follow how flash was done and proven in `re5_switch_native.py`. Accept on: a
   live ring of each kind, with frames before and after and the kill/score delta.
3. **RE4 Switch: the ring**, modelled on `re4_gc_native.py` and `re5_switch_native.py`, for flash / hand /
   incendiary (RE4 item ids: 0x0E flash, 0x01 hand, 0x02 incendiary; see `gbox/mercs/titles/re4_weapons.py`). The
   decrypted executable and the RAM maps are described in `docs/research/re4-weapons-ram.md` and
   `docs/research/re4-parity.md`. Accept on: a live ring of each kind in a MercMode RE4 round.
4. **RE6 Switch: owned by the RE session's lane** (branch `re6-bomb-mind`: the RE6 ring, the bomb hook and the RE6
   barrage below). Do not work on RE6 grenades; keep main's RE6 ring as it is until that branch merges.
5. **The bot deploys it by itself:**
   - when to fire: when surrounded (several enemies within a few metres), when facing a boss / dangerous class (a
     shared `gbox/mercs/enemy_identity.py` with tiers is being built), or when a crowd is not thinning;
   - never within the learned blast reach of himself;
   - at most every N seconds (tunable);
   - stats `rings_deployed`, `ring_kills`.
   The shared combat core `gbox/mercs/core/combat.py` is on main (UNIVERSAL_CORE in each title): put the "when to
   ring" rule there once and give each title a one-line hook.
6. **The scatter barrage on RE4 and RE5 Switch** (operator 2026-11-10: "i want the bot able to spray a scatter shot of
   grenades from his postion at threats at will. I want the bot able to randomly spray a rapid barrage of random
   grenades from the grenade launcher without equipping it on his character. I want it sprayed like a scatterhsot
   whenever the going gets tough"). Built on each title's ring spawn:
   - N rounds spawned at his position (chest height), fired outward in a cone toward the threats, with a random
     spread and a random kind per round. Use the grenade launcher's own rounds where identified (RE5: explosive /
     acid / nitrogen / flame / flash / electric), else the hand / incendiary / flash grenades. Kinds are held to what
     is verified live.
   - Rapid: about 0.1-0.2 s apart. Nothing equipped, no inventory or item screen: his gun stays in hand.
   - Never inside his learned blast reach.
   - At will: an intervention op `grenade_scatter` beside `grenade_ring` (`gbox/mercs/interventions.py`,
     `merc_live_controls.py`, the PiP menu).
   - By himself "whenever the going gets tough": surrounded, hurt with threats close, a boss or dangerous class in
     reach, or a pack not thinning, through the same core rule as the ring, with a cooldown knob.
   - Stats `scatters_fired`, `scatter_rounds`, `scatter_kills`. Accept on: a live barrage on each title, with frames
     and the kill delta.

## How to work

- The Switch titles run on lilspark (the Spark, `10.89.1.246:8765`) in MercMode. Find the live session with
  `GET /api/mercmode` (host lilspark, `current_run`), and read and write its memory through the gBox API's memory jobs
  for that session.
- Only in MercMode's own sessions: check `agent_owned` and that the launch actor is not `operator` before any write.
  Never stop, relaunch or reconfigure a session; never change MercMode settings or the queue.
- Token in `system/gbox-data/api_token`, never printed; header `x-gbox-actor: agent`.
- Work in a git worktree on a branch, and push the branch, not main (operator 2026-11-10: the grenade ring works in
  a branch). The RE session reviews and merges it. Write tests on synthetic memory for every new function. The
  RE4/RE5/RE6 test files must show no new failures (RE5 Switch has 11 known failures on main, RE6 3). Also fix the 4
  failing tests in `system/tests/test_pso_steering_evidence.py` that the PSO lane pushed to main.
- Hot reload: the title modules (`re4_switch`, `re5_switch`, `re6_switch`, their `*_native` / `*_mods`) reload in
  place when deployed to the Spark (`~/bin/gbox_autodeploy.sh` runs every 15 minutes). The interventions backend and
  the server need a gbox.service restart; ask the RE session (via this doc's lane log) to do it at a gap.
- Evidence: session ids, frames (`GET /api/sessions/{sid}/frame.jpg`), the kill/score counters before and after.

## What to send back

Append each step to `docs/ds-grenade-ring-lane-2026-11-10.md` on main: what works per title and kind, the commits,
the evidence, and what is still missing and why.
