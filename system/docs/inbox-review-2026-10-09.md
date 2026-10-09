# Inbox review — 2026-10-09

The live inbox contained 861 requests at the last snapshot: 618 done, 216 in progress, 21 open and 6 blocked. New requests arrived during this review, so these counts are a snapshot. Only requests with specific completion evidence were closed.

## Completed in this pass

| Requests | Result |
| --- | --- |
| 121 recurring review reminders | Audited their exact 15-minute windows across 17 stored chats and 38 operator turns. In 120 windows no operator turn occurred. One contained “Are you able to hear me?”, answered correctly with “I can hear you.” Audits: `C:/tmp/gbox-review-audit-20261009.json` and `C:/tmp/gbox-review-audit-late-20261009.json`. |
| 809 | Console checklist persists visibility, filters game results, and applies to All, search, favorites, letter paging and console tiles. Eleven Edge checks passed. |
| 807 | Flow icon placed at the far right of the desktop conversation toolbar; Edge layout checked at 1500, 1000 and 800 px. |
| 811, 812, 814 | Running-session thumbnails keep the same image element through routine polling. The next frame is preloaded before replacement; a failed frame request does not erase the displayed frame. Browser check confirmed stable image identity while notifications changed. |
| 815 | Titlebar Mini icon is hidden without a running game and updated by session polling. Edge layout confirmed it hidden at 1280 and 800 px. |

## Material progress still open

| Request | Progress and remaining condition |
| --- | --- |
| 764 | Added 18 QuickSwap2 ROM roots; live scan indexed 195 games. ZIP/7z disc extraction supports cue/gdi track sets, platform hints and safe local caching. A real NES 7z launched on Spark, produced a live gameplay frame, and was stopped cleanly. Switch titles still need a configured emulator, and full-library playability has not been verified. One loose PS2 cue points to a missing source track; its archive copy has the track and can be repaired during extraction. |
| 712 | Fixed worker death on registration timeout, indexed queued-job lookup, removed unnecessary registration scans, and fixed thumbnail temp-file collisions. These target observed failure traces; the wider GPU/performance request needs more measurement. |
| 839, 841 | Task panel no longer scrolls horizontally at 1280 or 800 px, allows expansion of process commands and job progress/errors, and waits long enough for the measured 25.66-second Tasks response. Universal foreground/background task and console-log coverage is not complete. |

## Verification

- Python suite: 149 passed, 6 skipped. One pre-existing test teardown warning concerns a background worker attempting to post after its test client closed.
- Desktop JavaScript syntax checked. Browser checks covered the console checklist, Flow position, Mini visibility, Tasks layout and stable session-strip thumbnails.
- QuickSwap catalog scan succeeded with receipt `4b66da81894147c7`; NES archive launch job `032a7d29483744b1` produced a live frame (`C:/tmp/gbox-quickswap-nes-frame.jpg`). The test session was ended.
- Updated web and desktop source files were synchronized by SHA-256 to the Spark share. The desktop app picks up its changes on its next launch.

The remaining inbox includes game-specific failures, cross-game model editing and larger integrations. No blanket completion status was applied to them.

## Follow-up: stuck queue and Tasks panel

- The footer's `characters queued` item was bound to an ended game session. An audit found 43 queued jobs, all 31-87 hours old and tied to ended/missing sessions or absent workers. Their IDs and prior states were saved in `C:/tmp/gbox-stale-queued-jobs-20261009.json`; all 43 were canceled. The live user-job queue was empty afterward.
- The server now fails queued work attached to ended sessions, and work assigned to workers that have been unavailable for more than an hour. The footer also has a cancel-and-close control so a task can be dismissed directly.
- Request 839 was completed: the Tasks panel loads without waiting for slow process counters, expands worker-job progress and stored logs, and shows desktop command output and cancellation. The live `/api/tasks` response returned in 1.2 seconds after deployment. Request 841 remains in progress because a Windows worker still times out while gathering its process inventory; the source now avoids reading every unrelated Windows process, but that worker has not yet loaded the updated file.
- The Python suite passed with 151 tests and 6 skips before the final queue and Windows inventory changes; focused tests for those changes passed 5/5. JavaScript syntax checks and mocked Edge interactions passed. Updated desktop files require an app relaunch to appear in the running window.
- Closed three more recurring reminders (#862-864) after checking all 17 stored chats for operator turns in each exact 15-minute window; none occurred. Closed #558 after verifying the deployed right-click issue report UI and endpoint, and #600 after verifying the desktop Alt+Enter, Escape and right-click fullscreen exit paths.

## Follow-up: Hermes and recent model reports

- Closed 28 recurring review reminders (#865-892). For each reminder, its own 15-minute window contained no operator chat turn among 17 stored chats and 38 operator turns. Each live inbox record has the specific audit note.
- Registered gBox's MCP server in Hermes on the DGX Spark and verified the MCP handshake and 206 discovered server tools. Hermes selects 12 tools for everyday use, including `start_job` and `get_job` for nonblocking access to any gBox registry job. A gBox MCP round trip submitted an `echo_artifact` job and observed it succeed. A Hermes one-shot model invocation did not return within 60 seconds, so model-directed use remains unverified.
- Added a Hermes gBox workflow skill and deployed it to the Spark. Favoriting a game now schedules one native character roster collection job if a reader exists, without launching a game; repeated favorites reuse the job. A later favorite action retries a failed job. Of 28 existing favorites, 19 have no native reader, five were previously collected, and four new jobs were submitted. GTA Liberty City Stories and Metal Arms completed, PSO Ver.2 reported partial. No Mercy was interrupted by a service restart; its retry job `fd67939a9b57488e` was queued after deployment. This does not satisfy the request to extract characters from every ROM.
- For #848, extracted the US VR Missions disc's 72,593,408-byte `MGS/STAGE.DIR`, used MetalMintSolid to list/extract `init.stg`, and identified PSX DAR entries containing KMD models. Decoded one 13,608-byte KMD into a 65,264-byte GLB. The player-model identity, HUcast retarget, stage/disc rebuild and emulator verification remain undone; no writer was routed.
- #847 remains open: ReAgent/Ghidra Bridge/Ariane integration and GTA live editing were not implemented. Ariane's documented editor targets GTA III, Vice City and San Andreas, with hot reload for supported San Andreas changes; this does not itself provide Liberty City Stories model replacement.
