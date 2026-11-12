# The last five launched games, as squares at the top of the right-click menu

## What was added

A strip above the Streams heading: **the last five games you launched**, each a **64×64 square**, in a horizontally scrollable row,
**click to launch again**.

* the five come from **your own sessions** (`agent_owned === false`), newest first, de-duplicated, Merc titles excluded;
* clicking one posts `@launch` with that catalog entry - the same tool the Play button uses - and the status line says `Starting <game>…`;
* it is populated when the panel mounts, and logs `pip recent: drew N` so a failure is visible in `app-console.log`;
* if you have fewer than five, it shows what you have; with none, the strip hides itself rather than showing an empty row.

## About the cover art - the honest answer

**There is no cover art on this machine.** The catalog advertises it:

```json
"media": { "boxart": ["collections/Nintendo GameCube/boxart/Phantasy Star Online Episode I & II Plus (USA)"] }
```

but:

* **no `collections` directory exists** - checked `D:\collections`, `C:\collections`, `C:\_tools\gBox\collections`, `D:\gBox\cache\collections`;
* `D:\gBox\cache\<game_id>` holds the **game archive** (a 300 MB `.7z` for Mercenaries), not art;
* the only images in the cache are **Smash character previews**;
* the app has **no boxart route** - `boxart` appears nowhere in its JS, and `/api/art?path=` and `/api/media/boxart?path=` both 404.

So each square shows a **generated cover**: the title's initials on a colour derived from the game id, with the full title as a tooltip. That is deliberate - it
looks like a tile, it is unambiguous which game is which, and **the same slot will show real art the moment `media.boxart` resolves**.

**I did not fake a thumbnail URL**, because a broken image frame would be worse than an honest tile.

## Verified

```
node check:  OK
strip container:  True
five tiles:       True
clickable:        True
runs on mount:    True
```

## Try it

**Ctrl+Shift+R**, right-click in the PiP - the squares should appear above "Streams". Click one to launch it.
