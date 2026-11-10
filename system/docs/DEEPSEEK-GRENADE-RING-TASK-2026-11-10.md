# DeepSeek task: the grenade ring on every Mercenaries title (2026-11-10)

Written for the DeepSeek session. The operator, 2026-11-10, about the PiP's grenade button, whose menu shows
"Flash (unavailable) / Hand (unavailable) / Incendiary (unavailable)": "i need the grenade deployment feature completed
across all titles in full ... and all these titles." The RE session's own agent for this was stopped part-way, so the
task is yours. This is separate from your PSO lane (DEEPSEEK-PSO-TASK-GUIDE-2026-11-09.md); keep both moving.

## What "the grenade ring" is

The `grenade_ring` intervention: ten grenades spawned in a ring around the player that bloom outward and detonate. It
is a spectacle mod that clears a crowd. The operator wants the bot to fire it by itself when surrounded or facing a
heavy, and wants it available from the PiP button on every title.

## What exists today (check each line on main before relying on it)

| Title | Ring | Where |
|---|---|---|
| RE5 Switch (010018100CD46000) | flash only, verified live; hand and incendiary are refused "until verified" | `gbox/mercs/titles/re5_switch_native.py` (`Controller.grenade_ring`, `grenade_ring_now`) |
| RE4 GameCube | yes | `gbox/mercs/titles/re4_gc_native.py` (`grenade_ring`) |
| RE4 Switch (010099A00BC1E000) | none | |
| RE6 Switch (01002A000CD48000) | none (another lane may land it: look for `grenade_ring` in `re6_switch*` on main first) | |
| RE5 PS3, RE6 PS3, RE4 Wii | unknown: report what exists | |

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
4. **RE6 Switch: the ring**, if no other lane has landed it by the time you get here.
5. **The bot deploys it by itself:**
   - when to fire: when surrounded (several enemies within a few metres), when facing a boss / dangerous class (a
     shared `gbox/mercs/enemy_identity.py` with tiers is being built), or when a crowd is not thinning;
   - never within the learned blast reach of himself;
   - at most every N seconds (tunable);
   - stats `rings_deployed`, `ring_kills`.
   A shared combat core (`gbox/mercs/core/combat.py`, branch `mercs-universal-core`) is being built for RE4/RE5/RE6.
   If it is on main, put the "when to ring" rule there once and give each title a one-line hook.

## How to work

- The Switch titles run on lilspark (the Spark, `10.89.1.246:8765`) in MercMode. Find the live session with
  `GET /api/mercmode` (host lilspark, `current_run`), and read and write its memory through the gBox API's memory jobs
  for that session.
- Only in MercMode's own sessions: check `agent_owned` and that the launch actor is not `operator` before any write.
  Never stop, relaunch or reconfigure a session; never change MercMode settings or the queue.
- Token in `system/gbox-data/api_token`, never printed; header `x-gbox-actor: agent`.
- Work in a git worktree on a branch. Write tests on synthetic memory for every new function. Merge to main only when
  the RE4/RE5/RE6 test files have no new failures (RE5 Switch has 11 known failures on main, RE6 3); push.
- Hot reload: the title modules (`re4_switch`, `re5_switch`, `re6_switch`, their `*_native` / `*_mods`) reload in
  place when deployed to the Spark (`~/bin/gbox_autodeploy.sh` runs every 15 minutes). The interventions backend and
  the server need a gbox.service restart; ask the RE session (via this doc's lane log) to do it at a gap.
- Evidence: session ids, frames (`GET /api/sessions/{sid}/frame.jpg`), the kill/score counters before and after.

## What to send back

Append each step to `docs/ds-grenade-ring-lane-2026-11-10.md` on main: what works per title and kind, the commits,
the evidence, and what is still missing and why.
