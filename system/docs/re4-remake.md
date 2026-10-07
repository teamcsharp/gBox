# Resident Evil 4 (2023 remake, Steam) in gBox

Tool: `re4r` (`gbox/re4r.py`, Windows worker). Bridge: `adapters/reframework/gbox_bridge.lua`. Blender side:
`adapters/reframework/re_blender.py`. Single-player, offline, on the operator's own copy.

## Safety checks (run by the tool every time it changes something)

- Install: Steam app 2050650, `steamapps/common/RESIDENT EVIL 4  BIOHAZARD RE4` (found via `libraryfolders.vdf`).
- Anti-cheat: none ships with the game (no EasyAntiCheat/BattlEye/... files; `re4r op=status` re-scans). If one ever
  appears, every write op refuses.
- DRM: `re4.exe` is protected by Denuvo Anti-Tamper. That is DRM, not anti-cheat. gBox never attaches a debugger to
  the exe and never touches the DRM; the game is always started through Steam (`steam://rungameid/2050650`).
- Steam may show Capcom's EULA before the first launch after an update: the operator accepts it in Steam; gBox never
  does (`op=launch` reports `blocked` / `status` shows `eula_pending`).
- Online features are not touched (no online calls, no stats/leaderboard objects in the profile).

## Why not Ghidra on re4.exe

Denuvo virtualises and encrypts the game code and the protection changes with every build; a static disassembly of
`re4.exe` shows mostly the protector, addresses aren't stable across patches, and attaching a debugger to a
Denuvo-protected process is exactly what gBox must not do. The RE Engine instead ships a complete type database
(every class, field and method, the "TDB") that managed code uses at runtime. REFramework reads it in-process, so gBox
works with names, not addresses:

- `re4r op=dump_types` walks the type graph from seeds (type names found as plain strings in `re4.exe` — a read-only
  file scan — plus fields/methods/parents) and writes `reframework/data/gbox/tdb/types_*.json`;
- `re4r op=types query=<regex>` searches it; Ghidra's role is that dump and any non-protected DLLs (e.g. the Wwise
  `Ak*.dll`s), not the exe.

## Layers

| Layer | What | Revert |
|---|---|---|
| REFramework (`dinput8.dll`) + bridge (`reframework/autorun/gbox_bridge.lua`) | `op=install` (game closed); recorded in `D:/gBox/runtime/re4r/manifest.json` with backups of anything replaced | `op=uninstall` deletes them, REFramework's own runtime files (config/logs, `reframework/`) and every gBox mod file; restores backups |
| Live values | `set`, `freeze`, `infinite_ammo`, `unlimited_items`, `no_recoil`, generic `set path=` / `call` / `lua` | `op=revert_all` (bridge remembers each original once; freezes cleared, hooks switched off) |
| Loose-file mods | `natives/stm/...` files (REFramework loose file loader, `LooseFileLoader_Enabled=true`); built into `D:/gBox/runtime/re4r/mods/<name>/` | `mod_disable name=..` or `revert_all scope=files` deletes exactly gBox's files (the paks are never modified) |

Bridge protocol: gBox writes `reframework/data/gbox/req.json` `{seq, ops:[...]}`; the bridge answers in `resp.json`
on the game thread (UpdateBehavior) and writes `state.json` (heartbeat, freezes, watched values) twice a second.
Type paths: `singleton:<type>` | `type:<type>` | `addr:0x..`, then `field`, `method(args)` or `[i]`.

## Extraction and send-back

- `re4r op=export character=leon|ashley`: `ree-pak-cli` unpacks the character folder from the base pak + patches
  (newest wins) → RE Mesh Editor in headless Blender (4.2–5.0; 5.1 is slow upstream) merges body/face/hair/scalp on
  one armature → glTF with albedo textures (hair colour from the material's BaseColor). `characters op=extract`
  routes RE4 (pc_steam) to it (`characters.DEDICATED` entry `re4r`). In the collection: `re4r_leon`, `re4r_ashley`.
- `re4r op=mod_build`:
  - `artifact=<sha>` / `path=<glb>`: an edited collection model or Blender variant. Parts whose surface is unchanged
    are skipped; same-topology parts get per-vertex offsets carried onto the original mesh (LOD0); new topology
    replaces the part (weights from its vertex groups).
  - `scale=1.6 parts=[1,2,3]`: a transform about the first part's bottom centre (big head), all LODs kept.
  - `texture=natives/stm/...tex png=<image>`: texconv to the original DXGI format with a full mip chain, written to
    the base and `streaming/` paths (RE4 keeps the high mips in the streaming copy).
  - Blend shapes (facial expressions) are not written back by RE Mesh Editor: a rebuilt face keeps its bone animation
    only. Build hair/body edits when expressions matter.
- `mod_enable` copies the files in (manifest-tracked); the game loads them at start.
