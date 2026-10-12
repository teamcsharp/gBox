# Inbox review — 2026-10-12

Operator request #1381: check every inbox request and make sure it is resolved and implemented. The live inbox held 403 open, in-progress or blocked requests at the start (302 in progress, 94 open, 7 blocked). Every one was read in full and checked against main (commit 7c18343) by eight read-only verifiers, one per group, each producing a per-ticket verdict with file, test, commit or API evidence. Only tickets with concrete evidence were closed; every other ticket received a reply stating exactly what exists and what is missing.

At the end of the pass the inbox held 205 open items: 192 from the starting set plus 13 created during the session (new operator reports and Hermes readiness children). 211 of the 403 were closed.

## Closed with evidence

| Group | Closed | Basis |
| --- | --- | --- |
| Recurring review reminders (37) | 37 | Each reminder's exact 15-minute window was audited across all 31 stored chats (59 operator turns). 23 windows were empty. The other 14 contained the Deku Tree, Shadow Temple, VR Missions, RE5 and pick-whip asks; each note names the gap ticket that tracks the fix. |
| Logged subagent reports (21) | 21 | `<agent-message>` records the prompt hook filed as requests; each points at its real parent. |
| Early chat requests #73–#640 (182) | 115 | UI, hotkey, docking, recording, chat, PSO, OoT, RE4/RE6, GTA, SM64 and character-pipeline asks verified against the clients, tools and docs (for example F2/F3/F4/F5 and Ctrl+I in clients/desktop/main.js, session_swap in gbox/server.py, pso_mods ops, zelda_oot ops, overlay and native swap targets in /api/characters). Meta instructions ("finish the tasks") and statements were closed as not separate requests. |
| In-game chat asks (10) | 6 | PSO drop/meseta/LCK and the Deku Tree asks: the exact tool op exists and was verified earlier; the original sessions no longer exist. |
| App issue reports (60) | 20 | Merged Hermes/Codex work confirmed on main and matching the ask (pause via the live channel, reconnect button, orphaned session_swap cancel, MK4 black 3D, QuickSwap roots, inbox hierarchy, save-state export) plus duplicate captures of the same report. |
| Gap and character records (34) | 12 | GTA III native swap with gameplay video, DOA2 Amy→Ein acceptance, Snake roles, Crazy Taxi collection, session observer fix, taxi extraction. |
| Recent chat (8) | 6 | PR 34 location, worker reconnect, Hermes closing merged tickets, three confirmations fulfilled by PR 34 / PR 36. |

Replies without closure went on the remaining 192, including all 59 "Character replacement readiness" children of #1135 (stage reached and next step per game; seven of them already have a working pipeline that predates the ticket, but the Hermes stage ledger has not checkpointed it), the per-game writer gaps, and the universal "any game" asks.

## Root causes found and fixed (branch `inbox-audit-20261012`, not yet pushed)

- **Ocarina of Time on the operator's ROM.** gbox/oot.py only knew the NTSC 1.2 gSaveContext / gPlayState addresses; the catalog OoT (USA) ROM is NTSC 1.0. Every zelda_oot and zelda op (skip_deku_tree, goto, give, scale, skip_text, items) refused with "no OoT v1.2 save loaded", which is what #1055, #1060, #1075, #1078, #1119 and #1130 actually hit. `oot.layout()` now detects 1.0 / 1.1 / 1.2 from the save's ZELDAZ marker and confirms gPlayState through play->nextEntranceIndex; live edits take their bases from `bases(ad)`, the zelda tool's v1.2-relative tables are remapped through `Mem.remap`, and oot_live / tools / oot_hot_swap resolve `play(ad)` per session. tests/test_oot_layout.py (8 tests) covers detection, edits on the 1.0 and 1.1 layouts, cache revalidation and the remap. The 1.0 and 1.1 bases come from the decomp symbol maps and are confirmed at run time; they have not yet been exercised on the live ROM.
- **Chat agent searched the web for cheats first (#1089, #1103).** The prompt now tries recall, the game's own tool and the emulator cheat database before web_search, and web_search is described as the last resort for codes. The prompt no longer advertises a PSO noclip op that does not exist.
- **Kept mods retried forever (#1130).** A kept mod that fails to re-apply three times stops retrying and says why on its card; turning it on again resets the counter.
- **Context menus clipped by the window (#1052, #1397).** Both clients place every context menu through `fitMenu`, which measures the menu, flips it above the pointer, clamps it to the window and scrolls it when taller than the window; a ResizeObserver re-fits menus whose entries load later. The earlier "verified" #1052 fix existed only as a patch file in a cloud workspace on the Spark and never reached main.

Validation: Python suite 848 passed, 42 skipped (tests/test_doa5a_inventory.py::test_build_inventory_on_synthetic_tree fails identically on main); inline client scripts pass node --check; the node tests that touch the changed code pass.

## Still open, by kind

- Per-game character writers and readiness stages (Hermes continuous queue, four parallel jobs): Parasite Eve II, ClayFighter, Jet Grind Radio live acceptance, MGS VR HUcast identity, Def Jam PS2, DOA++ and the 59 readiness children.
- Capabilities with no implementation yet: PSO run-speed multiplier (#278/#279), RE5 Gold unlocks (#1102/#1104), Vice City and Mario Kart 64 character writers, SA2 progression, PSO enemy writer, NinjaRipper integration, Bevy editor, N64 display offset (#201), texture inspector (#186), decomp.me / IDA / N64Recomp integration.
- Items that need a live session or a screenshot the record lost: #117, #165, #276, #374, #619, #1101.

## Deployment notes

The fixes are committed on `inbox-audit-20261012` and need a push, a PR merge, a Spark `gbox` service restart when no Spark-hosted session is running, and an app relaunch on the operator's PC for the client and worker changes.

## Follow-up: deploy and the second batch (same day)

- PR #150 (the four root-cause fixes) was merged by the operator; the 15 files it changed, plus the session observer fix from PR #132, were copied to the Spark share with a backup under `gbox-data/deploy-backups/20261012-main4f96389` and verified identical. The web client is live immediately. The Spark service refresh is deferred by the idle check while Hermes executions run; the operator restarts it (`sudo -n systemctl restart gbox`) when the check passes, and relaunches the desktop app on the Windows PCs for the worker and client changes.
- Branch `inbox-audit-20261012-b` adds four more requests: online cover art for any game card (#1067, `gbox/cover_art.py`, `POST /api/catalog/{gid}/cover`), a per-PC switch for which computers background testing may use (#1383, `gbox/background_testing.py`, Tasks icon right-click, honoured by `idle_worker` and the MCP test-PC selection), loading a game from a conversation's chip (#152), and "Request about this" on any element in both clients (#1386, #1087). Full suite: 2377 passed, 145 skipped; the two Zelda test expectations that the merged #150 left stale are corrected on this branch.
- Still not possible from the agent session under auto mode: pushing, merging, pausing Hermes dispatch and restarting the Spark service. Each was handed to the operator with the exact command.
