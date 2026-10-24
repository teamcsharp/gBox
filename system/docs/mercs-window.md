# Mercenaries map and run-review window

Open **Mercenaries live map ↗** or **Mercenaries run reviewer ↗** from the
game's PiP context menu. The detached mini-player has the same entries. Outside
a game, use **Mercenaries run reviewer ↗** in Control, or **File → Mercenaries
run reviewer** (`Ctrl+Shift+M`).

The separate window has **Live map** and **Run reviewer** tabs. Its session
selector uses the server that opened the window. The map uses measured tactical
frames and stage geometry; it waits explicitly when no frame exists. Recorded
runs remain available with no game running. Playback, route teaching and validated
practice selection reuse the existing reviewer. **Always on top** and bounded
window position persist in the local desktop profile's `mercs-window.json`.

When the selected session ends, the viewer follows only its server-recorded
`replaced_by` chain to a currently listed live session with the same game ID.
Only when that session disappears from the live list, it reads the latest 60
history entries through the existing sessions API. It checks at most eight
returned links, rejects cycles or missing/mismatched lineage,
and preserves any manual selection made while a check is pending. It never
substitutes another session merely because it is playing the same game.

Opening, switching tabs or closing the window sends no gameplay input, pauses
no game and changes no emulator parenting. Its keyboard events do not become
gameplay shortcuts. The window stays bound to its original server if the main
shell switches between the local and remote libraries; credentials from another
server are never substituted.

The renderer is a sandboxed local file with a narrow preload and no network
access. Only the main process obtains authentication. Its transport permits
reviewer and map reads, route annotation/teaching, and the existing exact-session
`mercs_team` status/validated-route selection. It refuses arbitrary jobs, mods,
controller input, external navigation, new windows and credential-bearing URLs.

Validation includes IPC sender/frame checks, pinned-authority requests, route-job
scope, popup/navigation refusal, persisted bounds, PiP context routing, and a
managed browser fixture mounting the actual tactical map and reviewer.
