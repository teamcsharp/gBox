# PS3 editions in the rotation: the idle demo, not MercMode

2026-11-06. The operator saw PS3 builds (Resident Evil 5 - Gold Edition on rpcs3) in what looked like the MercMode rotation.
Two earlier versions of this note were wrong: the first blamed `preferred_editions` being unset, the second blamed agent
`@launch` calls. Neither was the cause.

## The actual cause

Jobs `f896f09e` (07:41), `b88b8469` (07:46), `ccf18a2a` (07:51), `8b8e8fa5` (08:04) and `d0f3085d` (09:27) all carry actor
**`autoplay-screensaver`** and `launch.mercmode: null`. They are the **idle demo**:

`screensaver._start` uses MercMode's Switch pick only while MercMode is **on**. When it is off, the same scheduler falls back
to an idle demo picker over the operator's most-played games - and that list includes **RE5 PS3**. So every pause of MercMode
left the Spark idle and the demo filled the gap with the PS3 edition.

- The morning runs (07:41, 07:46, 07:51, 08:04) followed agent pauses.
- The 09:27 run followed a PM test session stopped while MercMode was still off.

MercMode itself never launched a PS3 title: 54 sessions on `eden` against those 5 on `rpcs3`.

## The guard

`mercmode.replaced_editions()` now stops the demo from picking an edition a host's `preferred_editions` replaced. It takes
effect at the next `gbox.service` restart, because `screensaver.py` is control-plane code.

`preferred_editions` still steers only MercMode's own picks, so the lilspark pin is kept as a statement of intent.

## Pausing the rotation without inviting the demo

1. `job_mercmode configure enabled=false`.
2. Stop the rotation's session, and launch the test at once with `node: lilspark`. The demo can start in **any** gap.
3. Test.
4. Restore **in this order: `enabled=true` first, then stop the test session.** Stopping first leaves a gap the demo takes.
5. Confirm `current_run.mercmode` is set and the adapter is `eden`. If a demo got in, `command=switch title=re5` queues the
   return, and the demo ends by itself within 20 minutes.

## Which emulator, and the edition pin

`adapters.switch_linux_kind` reads `switch_linux_emulator` (with `gbox.local-<host>.toml` laid on top) and only then the title
list:

```
effective switch_linux_emulator = auto, citron available = True
RE4 -> citron      RE5 -> eden      RE6 -> eden
```

`SWITCH_CITRON_TITLES` is now RE4-only, and the committed `gbox.toml` also says `auto`, so RE4 no longer depends on the
gitignored per-node file: if that file were lost, RE4 would otherwise fall back to Eden and fail. The old
"Citron NEO aborts at renderer init on the GB10 (VK_ERROR_UNKNOWN)" note predates Citron d3df71e55, which renders RE4 on the
GB10.

## Testing a build

1. A build is a folder `mods/<game_id>/<build>/` **with `.gbox-mod.json`** (`MARKER` in `gbox/switch_mods.py`). A hand-copied
   `romfs/` tree without the marker is ignored - the session comes up with `mod: ""`.
2. `switch_mods` `op: "apply_live"` is the sanctioned path for Switch on Linux: it writes the build and reboots the title in
   the same session. It refuses non-Switch sessions; on yuzu it relaunches as a new session.
3. **Use a test build of your own.** Never write test geometry into the rotation's live build (`cast-inverted`).
4. Reconcile through `switch_mods` and confirm with `op: "audit"`. Deleting an overlay file by hand is what split the
   `cast-inverted` manifest from its disk on 2026-11-06; the tool's `revert` fixed it.
5. Before reading a frame, confirm the session reports your build and `detail.boot_failures` is empty.
6. Look at the frame. Brightness statistics cannot tell you what is on screen.

## Always pass the node

A launch with no `node` can land on another PC: one agent launch produced a yuzu session on **JAYBUILTFINALE**, the
operator's PC. Test sessions belong on lilspark. Two sessions at once is not a slot violation - rpcs3 on lilspark beside yuzu
on JAYBUILTFINALE is fine; the limit is one Switch emulator per PC, because its config and NAND live in one folder.
