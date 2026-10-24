# Complete RE6 PS3 MercMode

Handoff: 2026-10-24. The operator wants RE6 included in the existing random RE4/RE5 MercMode rotation, not merely listed as installed. Continue the existing Hermes request **#3114 / `412028856f044524`**, routed to **`sparkDeux`**, under project `mercenaries-cross-title-united-v1`. Check its current assignment and branch before duplicating work. An open request is not proof that an agent is executing it.

The live request lookup during this handoff still reported **open**. Active execution and a completed implementation were not confirmed.

## Current blocker and available game

RE4 GameCube and RE5 PS3 have native Mercenaries drivers. RE6 does not yet have verified native menu, combat, or terminal-round readers. Its current `mercmode.TITLES['re6']` entry is an unavailable Xbox 360/Xenia placeholder (`0871eee3b68cdea3`, map `BH6`). Adding a PS3 archive does not connect that entry to an RPCS3 driver. Do not mark it playable just to make the selector include it.

- Requested share: `\\10.89.1.125\QuickSwap2\Emulation\PS3`.
- Archive: `Resident Evil 6 (USA, Asia) (En,Fr,De,Es,It,Pt,Pl,Ru).7z`.
- PS3 catalog ID: `6fc93ff62e4eb868`.
- Inspected archive metadata: **BLUS30855, app 01.00**. Confirm the actual loaded revision again after extraction/installation.
- The archive contains a disc-folder layout and needs staging before a native RPCS3 boot. Extraction, Mercenaries readiness, and successful gameplay are not established by catalog registration.
- Production host: `spark` / lilspark, source `/home/ehm_eckx/gBox/system`. Windows source: `C:\_tools\gBox\system`. Keep game files, captures, dumps, saves, decompilation output and test databases outside Git; `.work/` is ignored.

## Required implementation

1. Resolve this exact PS3 catalog item through each host's configured library roots. Prepare its disc folder using the existing RPCS3 archive/launch pipeline. Reuse installed game data, firmware and shader caches. Prove one sequential native launch on lilspark without opening a competing emulator. Record game revision, executable SHA256, emulator version and launch job/session IDs.
2. Build a revision-scoped RE6 observer and menu policy. Read actual screen state, verified solo player, active mode, selected/unlocked characters and stages, timer, health, score/combo where available, and terminal results/death. Confirm cursor selection from native state rather than blind button counts. Implement the title's verified save/unlock path with backups and readback; do not transplant RE5 offsets or assume every RE6 edition uses the same roster.
3. Establish native player/camera/enemy ownership and useful navigation data using the existing RAM/Ghidra workflow. Scope pointers to the current process lifetime and exact binary. Reject stale/invalid actors. Distinguish actual collision geometry from a floor mesh or an inferred blocked approach. Unknown fields stay unknown. Document every decoded field and its live verification.
4. Implement a playable RE6 Mercenaries driver behind the shared engine contracts: time-bonus goals, traversal, enemy targeting, healing and damage avoidance, round logging and normal menu continuation. Keep enemy and self-explosive damage enabled. Modifiers are optional assisted training; tag assisted runs separately from unmodified performance. Player 1 solo training remains the active scope; do not seize a human controller or start co-op testing.
5. Add the **PS3** backend to MercMode readiness/selection and worker preparation, preserving any separate Xenia support. Select only a host-accessible, prepared, verified backend. Publish actual native round-boundary receipts, retain session replacement lineage across RE4/RE5/RE6, and wait for the previous owned emulator to exit before launching the next. Preserve the fixed 16:9 PiP bounds and stream channel across changes. Turning MercMode off must keep the current game/autobot playing Mercenaries.
6. Connect RE6 run recording to the shared Atlas/Notebook/reviewer and existing failed-round analysis outbox. Record measured positions, routes, goals, pickups, weapons, damage and outcomes with native provenance. Preserve missing/uncertain values and use bounded retention. Learning claims require subsequent measured improvement; neither a successful launch nor a modified score proves S rank.

## Acceptance evidence before closing #3114

- Automated meaningful tests cover wrong revision/stale pointers, menus versus actual gameplay, human ownership, death/results, unavailable ROMs, backend selection and duplicate boundary delivery.
- Live receipts show RE6 entering Mercenaries, confirming its selected character/stage, moving/fighting, taking damage normally and completing a real round or death transition. Include distinct tested character/stage selections and unlock readback; state any untested roster/stage combinations.
- A real rotation visits **RE4 → RE5 → RE6 → another ready title**, using one owned emulator at a time. Gameplay and the separate reviewer follow verified session lineage. PiP bounds do not change. Include an actual RE6 run in the reviewer and exercise the right-click modifiers where supported.
- Disable rotation during RE6 gameplay: same native session/process and active autobot remain; subsequent rounds stay in RE6. Re-enable rotation and prove a later native boundary changes title. Human Stop/take-control remains authoritative.
- Observe live video and real emulator audio on the central/Pine path, including the RE6 launch. Report actual frame progression, interruptions, rank and remaining limitations. Do not close the task with mocked gameplay, fabricated rank or a metadata-only playable flag.
- Deliver a reviewed commit/branch, tests, exact live session/round IDs, evidence locations and rollback instructions. Integrate into `main` after checks; deploy at an owned idle boundary, not by killing an in-progress human game.

## Code entry points

- [MercMode readiness and receipts](../gbox/mercmode.py), [scheduler and HTTP API](../gbox/screensaver.py), [preparation tool](../gbox/mercmode_tool.py).
- [Shared Mercenaries engine](../gbox/mercs/engine.py), [title drivers](../gbox/mercs/titles), [RE5 native example](../gbox/mercs/titles/re5_ps3.py), [RE4 native example](../gbox/re4_merc_bot.py).
- [MercMode tests](../tests/test_mercmode.py), [desktop controls](../clients/web/viz/mercmode.js), [MercMode limitations](mercmode.md), [failed-round analysis](mercs-round-reports.md).

The desired long-term result is natural S-rank play and eventual local co-op. Those goals remain separate from this first verified RE6 integration milestone.
