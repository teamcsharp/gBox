# RE5 Switch grenade ring - evidence status

Operator goal (2026-10-31): a button beside the flashbang that fires ~10 grenades in a ring that blooms
out from the player and detonates (flashbangs by default, type selectable), plus the bot using grenades
"like mad" when Majini crowd him.

Title 010018100CD46000, build EBFFDB22 (`EBFFDB223149A725A93CD9B60979F6AA`), Citron on lilspark.

## No live in-game frames yet - do not merge on visuals alone

This change has **no captured in-game frames of the ring**, and per the repo rule ("PRs that change
visuals need in-game screenshots") it must not be treated as visually verified until they exist.

Why no live trial was run:

- The native grenade path only runs on a **Linux Switch NCE host**. The sole such host is **lilspark**
  (JAYBUILTFINALE and i9-NUC are Windows and cannot run the native flash controller).
- At the time of this work lilspark was running the **operator-watched RE5 MercMode broadcast**
  (`program` feed live, pinned to lilspark, a viewer connected). The hard constraints forbid native
  calls on a session the operator may be watching, and there was no idle Linux NCE session to use.
- Therefore the ring was built on the **already live-verified flash path** (spawn `0x118E820`, explode
  `0x118E9D0`, class `main+0x1C5EF58`; PRs ~#1597-#1600) and tested **statically/offline** only.

## What a live capture needs (to finish the evidence)

On an idle lilspark RE5 Mercenaries round (agent-owned, no operator viewer), in a window the operator
approves:

1. `game_intervention {op: "grenade_ring", kind: "flash"}` (or the PiP ring button) during a crowd.
2. `capture_worker_screen` / `job_get_frame` a few frames across the bloom + detonation into this folder,
   named `flash-ring-<ts>-<n>.jpg`, and note which are real frames.
3. Read the receipt's `self_damage` (hp_before - hp_after). A flash should take ~0 HP; record what is
   observed. The ring is clamped to a final radius >= `RING_SELF_CLEAR_CM` (250 cm) regardless.
4. For the bot knob, capture a crowd moment where `stats.bot_grenades` increments and the Majini show the
   stun (`cEm10ActDmgFlash` / Piyori) reaction.

## The one inferred step

Everything except the per-grenade **position relocation** is the verified flash repeated. The ring writes
each spawned flash unit's live transform (`+0x60`) and its home copy (`+0x2680`, 3 floats x/y/z) to a ring
point between init and explode. That the blast then occurs at the written position is the single assumption
not exercised by the shipped flash (which detonates at the player's feet). It is an ordinary RAM write, but
whether it relocates the blast must be confirmed by the capture above.
