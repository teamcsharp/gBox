# MercMode is Switch only, and why PS3 builds appeared

2026-11-06. Operator saw PS3 builds in the MercMode rotation. The rotation was not at fault; the cause is a default plus a
missing pin, and this records both so it cannot recur silently.

## What was actually observed

Sessions by adapter over the last day: **54 Switch (`eden`)**, and **5 PS3 (`rpcs3`)**. Three of the PS3 ones start at
07:41:47, 07:46:27 and 07:52:08 - exactly between two Switch rounds (07:33:30 ended, 07:57:35 running) - and they coincide
with the agent's own boot-test launch attempts. The other two (03:16, 03:41) are from the same kind of probe.

So the rotation itself launched Switch throughout. The PS3 runs were **agent launches**, not rotation rounds.

## Why an agent launch could pick PS3

`gbox/mercmode.py`'s `TITLES['re5']` default is the **PS3** edition:

```
're5': {'name': 'Resident Evil 5', 'map_id': 'BLUS30491', 'platform': 'ps3',
        'game_ids': ('e7ca89bbeb67360d',), ...}
```

The Switch No Mercy edition is selected per host through `preferred_editions`, the same way RE6's Switch backend is. On
lilspark that setting was **absent**, so anything that resolved "RE5" without an explicit Switch edition fell back to the
PS3 default. A launch that names only a title (or that resolves through the library, which is not indexed on the Spark)
lands there.

## The fix, applied

`preferred_editions` is now pinned on the `lilspark` host to the reviewed Switch editions, taken from
`gbox.re_switch.EDITIONS` rather than hand-typed:

```
POST /api/mercmode {"op": "configure", "host": "lilspark", "preferred_editions": {
  "re5": {"platform": "switch", "mode": "no_mercy",     "title_id": "010018100CD46000"},
  "re6": {"platform": "switch", "mode": "no_mercy",     "title_id": "01002A000CD48000"},
  "re4": {"platform": "switch", "mode": "mercenaries",  "title_id": "010099A00BC1E000"}}}
```

Verified stored under `hosts[lilspark].settings.preferred_editions`, and the rotation is back on Switch (`eden`,
`52d15709be0fda1a`, mod `cast-inverted`, running).

## How to launch a test build into MercMode (what the agent had to learn the hard way)

1. A build is a folder `mods/<game_id>/<build>/` **with `.gbox-mod.json`** (`MARKER` in `gbox/switch_mods.py`) whose
   `layeredfs` block names the title id. `gbox.switch_mods` writes it; a hand-copied `romfs/` tree without the marker is
   **ignored** - the session comes up with `mod: ""`.
2. Launch through `POST /api/jobs {"tool": "@launch", "input": {"game": <catalog entry>, "mod": "<build>"}}`. `game_id` at
   the input level is not the same thing and resolved to the wrong edition here.
3. The Switch slot is single-occupancy. `POST /api/jobs {"tool": "session_op", "input": {"session_id": ..., "op":
   "stop_game"}}` frees it; `/reset` does **not** (it restarts the title).
4. A connected stream/PiP viewer holds a `session_watch` lease and refuses a launch with 409 ("Watching ... in a connected
   stream or PiP"); the lease only counts *running* sessions, so stopping the session clears it too.
