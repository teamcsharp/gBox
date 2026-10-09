# Inbox review — 2026-10-09

The live inbox contained 861 requests at the last snapshot: 586 done, 244 in progress, 25 open and 6 blocked. New requests arrived during this review, so these counts are a snapshot. Only requests with specific completion evidence were closed.

## Completed in this pass

| Requests | Result |
| --- | --- |
| 89 recurring review reminders | Audited their exact 15-minute windows across 17 stored chats and 38 operator turns. No operator turns occurred in those windows. Audit: `C:/tmp/gbox-review-audit-20261009.json`. |
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
