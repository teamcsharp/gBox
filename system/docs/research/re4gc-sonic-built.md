# Sonic in RE4 GameCube: the mod is built, the launch is blocked

The RE5 Switch engine will not take a foreign mesh (four builds: a restructured part table is never drawn; a
topology-preserving write draws garbage). RE4 GameCube is different: gBox already writes rigged glTFs into the game's own
format, and a Sonic rigged to the game's bone numbering already existed.

## Built this round, verified by the tool's own report

```
source     ~/agent-work/re4chars/sonic_on_leon.glb   286,996 bytes, 119 joints named b000, b001, ... (already rigged)
disc       Resident Evil 4 (USA) (Disc 1).iso        1,459,978,240 bytes (copied locally: the share is read-only)
swap_packs em/pl00.drs  759 verts, 1369 tris, 4 textures added, 2,089,760 bytes vs 2,221,088 on disc
           em/pl08.drs  759 verts, 1369 tris, 4 textures,       2,060,096 vs 2,223,616
           em/pl09.drs  759 verts, 1369 tris, 4 textures,       2,072,640 vs 2,248,224
           em/pl10.drs  759 verts, 1369 tris, 4 textures,       2,060,032 vs 2,208,352
mod        ~/gBox/system/gbox-data/cache/mods/78ab9efa2e310db4/re4gcs1358/
           image re4-d1.iso + em/pl00.drs, em/pl08.drs, em/pl09.drs, em/pl10.drs
```

Every pack fits inside its disc original, so nothing was decimated to make room: this is Sonic's 1,369-triangle mesh with its
own four textures replacing the player body, on the game's own skeleton.

## Why it is not on screen yet

The launch was refused three times with

```
Watching Resident Evil 5 in a connected stream or PiP. Close that view before loading another game on this PC.
```

That guard counts **running** watched sessions, so it should clear when the round ends - and it did once (the PC was idle for
60 s and the launch got as far as rejecting the mod for being in the wrong cache path). After the rebuild it would not clear:
`session_op stop_game` returned success but the RE5 session stayed running, so the lease never lapsed.

## To launch it

```
POST /api/games/78ab9efa2e310db4/launch?node=lilspark&mod=re4gcs1358
```

when no watched session is running. RE4 GC boots to its main menu; Mercenaries is under the usual menu path, and the mod
replaces the player body in all four player packs (pl00, pl08, pl09, pl10), so any of those characters shows Sonic.

Two operational notes worth keeping: `build_mod` needs a staging dir on the **same filesystem** as the image (its hard link is
cross-device otherwise), and its `cache` argument is the parent - passing `.../cache/mods` produces `mods/mods/...` and a launch
that says the mod was never built.
## Second attempt: the packs are placed, the launch still refuses the mod

Placed the four swapped packs inside the mod folder (`em/pl00.drs`, `pl08`, `pl09`, `pl10`), refreshed the gallery, and the
launch still says:

```
no built mod 're4gcs1358' for this game: it is neither on this PC nor in the central collection
```

while `POST /api/mods/built/refresh` reports `{"ok": true, "indexing": true}` and the gallery still does not list it. The mod
folder holds the marker (`.gbox-mod.json`, keys `built file_changes files game_id image kind name`), the image and the packs -
so this is a **registry/marker-shape** problem, not a missing build. Other writers' markers carry `title`, `writer` and
`platform`; `char_swap.build_mod` -> `filemods.build_image` produced one without them.

Next step, and it is not another guess: compare this marker against a file mod the **app itself** built for a GameCube title
(the app's own build path is what the gallery indexes), and either call that path or match its marker exactly. Everything
downstream of that - the launch, the boot, the Mercenaries menu, the frame - is ordinary work; the only unknown left is the
registration shape.