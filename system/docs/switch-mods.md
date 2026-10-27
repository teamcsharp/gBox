# Switch mods: LayeredFS overlays on the active build

Operator, 2026-10-26: "make sure on the switch version I can do character replacement and in game swapping without
rebuilding the rom since builds are beginning to get to be 20gb a build so i need it able to modify the active and
current build and not make duplicate builds taking up all the memory."

Code: `gbox/switch_mods.py` (the `switch_mods` tool), `gbox/adapters.py` (`SwitchLinuxAdapter`, `YuzuAdapter`),
`gbox/tools.py` (`_launch_game`, `file_mod`, `session_op reset`), `gbox/server.py` (`session_swap`),
`gbox/characters.py` (Switch routing), `gbox/filemods.py` (guards). Tests: `tests/test_switch_mods.py`.

## Why builds were 20 GB

A build for a single-image game is a copy of the image with the changes applied (`filemods.build_image`, used by
`file_mod op=build` and most writers). For a Switch game that image is the whole NSP: RE5 is 20.0 GB, RE6 18.8 GB. Every
PC that plays the build downloads it (`filemods.stage`), and a rebuild under the same name is staged beside the copy a
running game holds open (`<build>~<key>`), so each change could leave another full copy on each machine. And the
changes themselves were byte patches inside encrypted NCAs, which no game file carries.

Now `build_image` refuses `.nsp` / `.xci` / `.nsz` / `.xcz`, `file_mod op=build` on a Switch game writes an overlay, and
the launch boots the base NSP with the overlay enabled. The base NSP stays the only full copy.

## The emulator mechanism (read in Eden's sources, 2026-10-26)

Eden v0.2.1 (the AppImage gBox runs; tag commit `58c1e20e`) and master (`26a03d24`) agree; yuzu (Windows) has the
same code, which Eden inherited.

| What | Where in Eden | Fact |
|---|---|---|
| Load folder | `src/core/file_sys/bis_factory.cpp` `GetModificationLoadRoot` | `<data>/load/<title id as %016X>/`; update title ids (low 12 bits `0x800`) get none, so mods key on the base id |
| Layering | `src/core/file_sys/patch_manager.cpp` `ApplyLayeredFS`, `PatchExeFS` | every subfolder is a mod; one whose name is in `disabled_addons[title_id]` is skipped; enabled mods' `romfs/` (`romfslite/`, `romfs_ext/`) and `exefs/` are layered over the game's own, mods sorted by name, the first layer holding a file wins (`vfs_layered.cpp` `GetFileRelative`), the game's RomFS last; `CreateRomFS` packs the result once per boot. No layers: the RomFS is not repacked (so gBox never leaves an empty `romfs/` behind) |
| SD card mods | same | `sdmc/atmosphere/contents/<TID>` joins unless the name `SDMC` is disabled; gBox never adds that name |
| Per-game toggles | `src/frontend_common/config.cpp` `Read/SaveDisabledAddOnValues`; `src/yuzu/configuration/configure_per_game_addons.cpp` | the global `qt-config.ini`, section `[DisabledAddOns]`, QSettings-style arrays (below); the Add-Ons tab edits the same map (names = mod folder names) and deletes `<cache>/game_list/<TID>.pv.txt` when it changes |
| When it is read | `src/yuzu/main_window.cpp` `BootGame` | settings are read when Eden starts and saved back from memory at every boot (`config->SaveAllValues`): gBox writes `[DisabledAddOns]` while that Eden is down, right before starting it |
| Links | `src/common/fs/fs.cpp` `IterateDirEntries` | follows symlinks (`directory_entry::status`), so a linked folder is a mod |

```
[DisabledAddOns]
; RE5: title id 010018100CD46000, written in decimal
1\title_id\default=false
1\title_id=72084051251716096
1\disabled\1\d\default=false
1\disabled\1\d=re5_wesker_build
1\disabled\size=1
size=1
```

An update applies before the mods (`PatchRomFS`: the update's RomFS, then `ApplyLayeredFS`), so an RE6 overlay
replaces files of the v131072 game that gBox loads from the game's folder.

Every value has its `\default=false` twin. A missing twin reads as the default in Eden (title 0, name `""`), so the
entry would be silently ignored. Values with Eden's special characters (`~` among them) are written quoted, as
`AdjustOutputString` does. Entries that are not mod folders (`Update`, `Update@<version>`, `Update (NAND)`, `SDMC`,
`cheat_*`) and other titles' entries stay as the operator set them.

## What a Switch build is now

```
<cache>/mods/<game_id>/<build>/          the mod collection, as for every other build (Builds view, sync, delete)
    .gbox-mod.json                       "layeredfs": {title_id, base, load}, files, file_changes, history
    romfs/...                            only the changed RomFS files
    exefs/...                            optional ExeFS replacements / IPS patches
    .gbox-backup/<edit>/...              the files each edit replaced
    .gbox-pending/<edit>/...             edits waiting for the title to restart on THIS node (never in the manifest)
<eden data>/load/<TID>/<build>           a symlink to the build (a junction on Windows; a copy when no link works)
```

Builds are KB to MB. They sync through the collection like any build (`/api/modfiles`); `.gbox-pending/` is
node-local (`filemods.LOCAL_ONLY`), so an edit waiting for a restart never makes other PCs re-stage the build.

## Selecting a build

Starting a build (`@launch mod=<build>`, Mods page, Builds) sets `adapter.overlay_build`; before the emulator starts,
`switch_mods.prepare_launch`:

1. lands the build's pending edits (`apply_pending`),
2. links every overlay build of the game for that title into `load/<TID>/` (a staged `<build>~<key>` copy only while
   it is the one started; links whose build is gone are removed; foreign folders are never touched),
3. writes `[DisabledAddOns]`: the started build enabled, the title's other gBox builds disabled. A mod folder gBox did
   not make keeps the state the operator gave it (enabled or disabled) and is listed as `foreign`,
4. records the selection (`<runtime>/switch-overlays.json`) and reports it in the session detail (`overlay`).

Starting the original game disables every gBox build of the title; the operator's own mod folders stay as they are. Old full-copy builds still boot their own image until
they are converted. `switch_mods op=select build=<b>` (or `""`) sets the selection without starting the game; it
takes effect at the next start.

## Modifying the active build in place

The active build is the one the session shows (its `mod`), else the one this node last started the title with, else a
new `<title>_mods` overlay. Nothing else is ever copied.

```
switch_mods op=write game_id=<id> [build=<b>] changes={
    "arc/pl/pl00.arc": {"artifact": "<sha256>"},        # a bare path is a RomFS path
    "romfs/arc/pl/pl01.arc": {"from": "/path/file"},    # or {"bytes"} / {"b64"} from Python / JSON
    "arc/pl/pl02.arc": {"romfs": "arc/pl/pl05.arc"},     # the game's own file at another path (needs an extracted
                                                         # RomFS: Eden's Dump RomFS, or romfs_dir=)
    "arc/em/em10.arc": {"patch": [{"offset": "0x10", "hex": "ff"}]},
    "arc/old.arc": {"remove": true}}                     # the game's own file shows again
```

`file_mod op=build name=<b> changes=...` on a Switch game does the same (it merges into the build; it never rebuilds
from scratch). Each edit moves the files it replaces to `.gbox-backup/<edit>/` and records them in the marker's
`history`; `op=revert [edit=<id>] [paths=[...]]` puts them back (an undo is an edit too, so it can be undone).
`op=new_build new_name=<n>` copies only the overlay folder of the active build (or makes an empty one).

While a session on this node runs that build, the edit waits in `.gbox-pending/` and lands when the title restarts:
the running Eden never has a file changed under it. Its layered RomFS keeps offsets from boot, and Windows would
refuse to replace an open file anyway.

Edits of a build that lives in the central collection run on the collection node (the Spark: `require_os=linux`).
A PC refuses them, because its next launch would stage the collection's copy and lose the edit.

## In-game swapping

Eden layers mods only when a title boots and has no save states, so changing what the game sees means booting the
title again. gBox does that as one action and keeps the session:

- `switch_mods op=apply_live session_id=<sid> [build=<b>] [changes=...]` writes the edit (if any), then
  `SwitchLinuxAdapter.restart_title`: Eden's process tree stops (SIGTERM, SIGKILL after 6 s), the selection and pending
  edits are written while it is down, and Eden starts the same NSP on the same Xvfb display. The session id, display
  and stream stay. A stand-in process object keeps the session pump from reporting the session ended in the gap, and
  the pump re-docks the new pid. The control plane moves the session's `mod` to the build and `detail.pid` to the new
  Eden (`switch_mods` on_accept). The game's own saves (NAND) are kept.
- The UI's swap (`POST /api/sessions/{sid}/swap`, "Switch to this build") on an Eden session runs that same in-place
  restart; on a Yuzu session it relaunches the build without a moment (a new session, the old copy closed first).
- Reset on an Eden session (`session_op reset`) restarts the title in place with the current build. It answers once
  the new Eden runs, and the game boots in the stream.
- Eden and Yuzu never relaunch beside a running copy (`server.RELAUNCH_BESIDE_UNSAFE`): there is one emulator folder
  per PC (its config holds the selection, its NAND holds the saves).
- A debug session (GDB stub) relaunches instead: the stub attaches only at boot.

## Character replacement

`characters op=use`, `op=live_use` and `op=cast_swap` on a Switch title go to `switch_mods.character_use`. The title's
writer (`switch_mods.register_writer(title_id, fn)`, `fn(ctx, game, inp, meta) -> {"changes": {...}, "kind", "slots"}`)
produces RomFS files. They go into the active build in place, and a running session restarts the title with it
through the swap above. No Switch model writer exists yet for RE5 / RE6: these ops file the usual repair request
(`char_coverage.no_writer`) and return where the files would go (`switch_overlay`). Explicit file swaps work now through
`switch_mods op=write` / `apply_live`.

## Disk audit

`switch_mods op=audit` is read-only. It covers every full Switch copy on the node it runs on: container copies and
extracted `romfs/` trees in the mod collection, staged copies, launch-cache / export / extract copies. Run it on the
Spark and on each PC.

```
{"node", "cache", "items": [
   {"id": "mods/<gid>/<build>", "kind": "container_copy" | "romfs_tree" | "staged_copy" | "cache_copy" | "export" | ...,
    "path", "game_id", "build", "bytes", "own_bytes" (what deleting frees), "files", "title_id", "recorded_changes",
    "convertible": "empty_overlay" | "overlay" | "quarantine" | false, "reason" | "plan" | "keep": [{path, size}]}],
 "overlays": [{"game_id", "build", "files", "bytes", "pending"}],
 "quarantined": [{"id", "path", "bytes", "own_bytes"}],
 "totals": {"items", "bytes", "convertible", "frees", "quarantined_bytes", "overlay_bytes"}}
```

- A container copy with no recorded change becomes an empty overlay (it was the original game). One with byte patches
  is not convertible: those patches live in encrypted NCAs. `force_empty=true` makes it an empty overlay and drops them.
- An extracted RomFS tree keeps the files its marker recorded as changed, else those that differ from an extracted
  base RomFS of the title (`romfs_dir=`, or Eden's dump in `<data>/dump/<TID>/romfs`). Otherwise it is not convertible.
- A staged copy is moved aside; the build itself carries its content.

`op=convert` is a dry run by default. With `dry_run=false` the overlay takes the build's name, so its card, display
name and favorite stay, and the full copy is renamed to `<game>/.switch-full-copy.<build>.<stamp>/` with its marker
renamed, so no gallery, heartbeat or launch sees it. Nothing is deleted. `op=purge` lists those copies;
`op=purge confirm=true` deletes them and nothing else.

## Windows (Yuzu)

The Windows adapter selects overlays in the portable install's `user/load/` and `user/config/qt-config.ini` only when
that folder is local to the PC. A Yuzu on a network share is shared by every PC, and a link there would point at one
PC's cache. On a shared install a build launch is refused with the reason, and the original game launches with its
config untouched.

## Needs a live check

Eden v0.2.1 boots RE5 and RE6 to gameplay on the Spark (2026-10-26, single-core per title, RE6's update from the
game's folder: docs/research/switch-emulator-spark.md). The overlay path itself has not run against a real emulator
yet; only the tests above have.

1. Eden on the Spark boots RE5 with an overlay build enabled, and `eden_log.txt` shows
   `RomFS: LayeredFS patches applied successfully`. With the original selected that line is absent.
   **Checked live 2026-10-26 on Citron NEO** (now the canonical Switch emulator; the same LayeredFS code as Eden), in a
   private Citron home on the Spark (its own Xvfb, never a gBox session). This module's own calls made the overlay:
   `write_files` built `sheva_textures` (one file, `romfs/nativeNXx64/ImgNX/Archive/uPl00ChrisNormal.arc`, 43,488,626
   bytes, edit applied) in a scratch cache. `prepare_launch` linked it into `load/010018100CD46000/sheva_textures`
   (mode link, enabled, nothing disabled, config unchanged), and the archive was reachable through the link.
   The archive is Chris's own with two texture blobs from Sheva's (her arm skin in his shirt slot, her face in his face
   slot; byte-identical TEX headers, every entry inflating to its size). Citron booted with it and the bot's menu walk
   took it to a round in 29 s. **Chris's shirt shows Sheva's skin texture** in the intro and the round
   (docs/evidence/switch-citron/re5-switch-layeredfs-before-after.jpg, real frames: vanilla from the same day beside the
   overlay run; re5-switch-layeredfs-frames.jpg). The log line itself is not in `citron_log.txt`: Citron's default
   `log_filter` is `*:Warning`, which drops Info messages like the LayeredFS one. A run with `log_filter="*:Info"`
   should record it; that run has not been made yet.
2. The symlinked build folder is listed in Eden's per-game Add-Ons tab, with the right box checked after a gBox start.
3. `restart_title` on the Spark: the same session keeps streaming, the pump re-docks the new pid, audio follows
   (broadcast taps by `detail.pid`), and RE5 boots with the edited file.
4. The portable Yuzu on the i9-NUC: a junction in `user/load/<TID>/` is seen as a mod, and the yuzu build there writes
   the same `[DisabledAddOns]` layout (old QSettings yuzu reads it too: same keys).
5. The audit on the Spark and on each PC: whether any 20 GB Switch copies exist today.
