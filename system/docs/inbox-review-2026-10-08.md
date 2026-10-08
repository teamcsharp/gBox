# Inbox verification — 2026-10-08

This review covers the live gBox inbox and the Windows/Spark deployments. A successful build alone is not a gameplay verification. The older `in_progress` entries remain pending unless there is specific completion evidence; this report does not declare the entire backlog finished.

The final reviewed snapshot has 241 pending entries: 230 in progress, five open and six blocked. This pass closed 23 implementation, asset, packaging and publishing requests, plus 71 empty recurring review reminders.

## Completed requests

| Requests | Result and evidence |
| --- | --- |
| 462 | Rouge extracted from the original SA2 Dreamcast assets: 1,280 triangles, 62 joints, textures and bind matrices validated; preview inspected. |
| 469, 114 | Standalone Decant package built. ZIP CRC and identity audit passed; extracted wizard self-test and Edge hardware/ROM-folder workflow passed. |
| 504, 503, 501, 498, 496 | Aya, Shadow, Cloud with cone hat, Tifa and Zelda replace both adult and child Link. All ten finished-ROM readbacks validated and rendered; Aya additionally verified in the running game. |
| 455 | Cloud in Mario 64 verified from a fresh launch, outside the castle, moving and jumping. |
| 448, 437, 450 | HUcast, original GameCube Leon and Cloud verified in GTA LCS gameplay. Every build covers 17 outfits and preserves the game's 24-bone skeleton. Intro cutscene actors retain their original models. |
| 480, 478 | Real Blender 4.0 import, export and two `.blend` saves updated one running Mario 64 session at head scales 1.25 and 1.5. All skeleton, memory, texture, model budget, culling and animated-frame checks passed. Headless verification explicitly drained the callbacks registered by the real save handler. |
| 252, 263, 239 | Nintendo 64 controller glyph verified in the live web play view: actual session button down lights B; release clears it. The console-family renderer and input hooks are present. Native desktop character overlays are a separate request. |
| 624 | Normal reset preserves the current LiveLink character. Browser verification then hard-reset the same test game to the original ROM, with character and mod preferences cleared. |
| 585 | Cloud replaces The Rock in a live SmackDown 2 match. Finished-disc readback has 437 triangles; head/body/leg files fit their original slots. This does not resolve the separate Toni fitting report, request 603. |
| 621 | Installed an Xbox SDL3 profile into the actual SDL3-only Windows RetroArch runtime. Runtime log confirms selection; mapping regressions pass. Physical stick direction in gameplay has not been confirmed by the operator. |
| 623 | Recent, name, console and file-size sorting checked against the live character collection. File size now uses model-file bytes rather than triangle count. Variants remain grouped under their base. |
| 628, 546 | Tested source changes committed and pushed to `origin/main` as `8c7ba12`. The working tree was clean and local/remote heads matched after publishing. |
| 71 recurring review reminders | All 15 stored conversations (37 user turns) checked against each reminder's original requested time window. Every window contains zero user requests, so no failures or fixes were required. Local audit: `C:/tmp/gbox-review-reminder-audit.json`. These closures do not close any feature or game request. |

## Fixes included

- Driver-specific SDL3 Xbox axis mappings prevent the inappropriate XInput fallback.
- Exact character slugs take precedence over ambiguous aliases, including original Leon versus the remake.
- OoT role inference avoids assigning Zelda's central dress chain as a leg or arm.
- Thumbnail capture rejects JSON bodies as images and permits recapture of missing or tiny corrupt artifacts.
- Inbox mutation responses tolerate lone Unicode surrogates in imported prompts.
- LiveLink identifies whole model segments and tracks the current live model independently of the boot ROM.
- Reset keeps a character changed in memory through LiveLink.
- GTA atlas generation honors opaque material alpha; triangle strips preserve face winding and join parity.
- Blender simplification welds seam-split vertices before collapse. A separate closed 320-triangle fixture simplified to 100 triangles with zero boundary or nonmanifold edges.
- Character file-size sorting reports actual model-file bytes.

## Remaining work

- Crazy Taxi player replacement (608), ClayFighter sprite writers (588, 487), Parasite Eve II replacement (559) and Crazy Taxi yellow-taxi extraction (459) still lack their required game-specific writer or extractor.
- The six original PSO edit requests (286, 281, 279, 278, 266, 253) refer to sessions that no longer exist. Their player states cannot be edited or verified from a different new game. Request 281's captured value is Money/meseta 300, requested 900; request 286 targets LCK/luck 1000.
- Native Windows character overlay verification (486) reached the actual desktop app: a fresh Windows Cloud/Mario 64 session docks, Rouge loads, overlay controls appear, and the tracker reports 21-23 fps. Correct placement over the moving player remains unverified. Toni's SmackDown fitting issue (603) also remains pending.
- The broader historic inbox includes UI reports, game-specific investigations, universal capability requests and imported agent reports. These require their own evidence before closure. A recent `chat_review.py --hours 0.25 --full` returned zero new requests and zero flagged requests. Recurring reviews may create new inbox reminders after this snapshot.

## Validation and local artifacts

- Python suite: 72 passed; existing dependency deprecation warnings remain.
- `node tests/gamepads.cjs`: passed.
- Real Blender simplification and two successive Save LiveLink updates: passed.
- Real Edge checks: live input glyph, normal/hard reset and all four character sort modes passed.
- Standalone ZIP: `C:/tmp/gBox-decant-20261008.zip`; refreshed package has 95 character recipes and 80 built-mod recipes, without game ROMs or character model payloads.
- Detailed local evidence: `C:/tmp/gbox-blender-live-results.json`, `C:/tmp/gbox-reset-validation.json`, `C:/tmp/gbox-decant-manifest.json`, and screenshots named `C:/tmp/gbox-*.png`. OoT readbacks are in `C:/tmp/gbox-oot-readback/validation.json`.
- The full pending inbox snapshot is retained locally in `C:/tmp/gbox-inbox-remaining.json`; it is not published as project source.

Source fixes are synchronized to the live Spark mirror. Verification sessions are stopped after use. Existing user edits to the desktop conversation controls and PS2 launch routing are retained.
