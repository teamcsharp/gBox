# RAM maps and the RAM inspector

Operator 2026-10-20: "we need to somehow hook an analysis system into the game that provides like some sort of RAM
inspector that lets us see in real time what's happening in the game and to identify the hex codes associated with QTE
events and door opening events and map navigation ... Vision analysis to me should be the last level that we have to
fall back to, with the primary levels being you being able to see the very code of the game itself as it's being
executed in the RAM."

A **RAM map** names what a game keeps in RAM: "the Mercenaries clock is the u32 at 0x80279308, frames at 30 fps",
"Leon's position is 3 floats at +0x94 of the player em that 0x802B3044 points to". Bots read named fields from it
instead of hard-coded offsets (`ram_map.load(game).read(reader)`), the inspector panel shows them live and logs the
changes of state fields as events, and its search finds new addresses (Cheat Engine style, plus label correlation) and
adds them to the map. Vision (gbox/screen_prompt.py) is only a labeler for those searches, never the source of truth.

## Files

| file | what |
|---|---|
| `profiles/gamedata/<map id>-ram.json` | the map, in the repo. Map id = the disc id for discs that carry one (GameCube / Wii: `G4BE08`), else the catalog game id (16 hex digits). |
| `gbox-data/ram_maps/<map id>-ram.json` (control plane) | fields added from the inspector ("add to map"). Loaded over the repo map. Never written into the share's code tree (the deploy would keep it as a share edit); copy them into the repo file in a PR to keep them for good. |

## Format (`gbox-ram-map/1`)

```json
{
  "format": "gbox-ram-map/1",
  "id": "G4BE08",
  "title": "Resident Evil 4 (GameCube, NTSC-U)",
  "platform": "gamecube",
  "endian": "big",
  "pointer_size": 4,
  "pointer_range": ["0x80000000", "0x81800000"],
  "match": {"disc_id": "G4BE08", "game_ids": ["78ab9efa2e310db4", "e42c9b780c07c437"],
            "memory": {"address": "0x80000000", "equals": "G4BE08"}},
  "regions": [{"name": "MEM1", "base": "0x80000000", "size": "0x1800000"}],
  "groups": {"merc": "The Mercenaries: clock and combo"},
  "fields": {
    "merc.timer": {"address": "0x80279308", "type": "u32", "scale": 0.033333333, "units": "s",
                   "description": "Mercenaries clock (frames at 30 fps)", "source": "manual",
                   "evidence": "gbox/re_games.py MERC_TIMER; live 2026-10-20"},
    "player.pos": {"pointer": {"base": "0x802B3044", "offsets": ["0x94"]}, "type": "f32", "count": 3,
                   "units": "world units", "description": "Leon's position x, y (up), z", "source": "manual"},
    "prompt.action": {"pointer": {"base": "0x802B3044", "offsets": ["0x1234"]}, "type": "u8",
                      "enum": {"0": "none", "3": "TAKE", "5": "JUMP OVER"}, "source": "scan",
                      "evidence": "search 2026-10-20: 14 on / 15 off samples, labeler screen_prompt"},
    "enemies": {"pointer": {"base": "0x8027DF20", "offsets": ["0x0"]}, "type": "struct", "stride": "0xDE0",
                "count": "@emmgr.count", "first": 1,
                "live": {"all": [{"field": "flags", "mask": "0x601", "ne": 0}, {"field": "esl", "ne": 255}]},
                "fields": {"flags": {"offset": "0x0", "type": "u32", "format": "hex"},
                           "pos": {"offset": "0x94", "type": "f32", "count": 3},
                           "hp": {"offset": "0x320", "type": "s16"},
                           "esl": {"offset": "0x398", "type": "u8"}}}
  }
}
```

(`prompt.action` above only illustrates a field found by search; it is not a real address.)

Numbers (addresses, offsets, masks, strides, enum and flag keys, condition values) are JSON numbers or strings,
`"0x..."` hex or decimal.

### Map keys

| key | |
|---|---|
| `format` | `"gbox-ram-map/1"` |
| `id` | the map id (the file name's prefix) |
| `title`, `platform` | the game; the platform as the catalog names it (`gamecube`, `wii`, `n64`, `psx`, `ps2`, `dreamcast`, ...) |
| `endian` | `"big"` / `"little"`: the default for every field. Default: the platform's (big: GameCube, Wii, N64, PS3, Xbox 360, Saturn, Genesis, ...). |
| `pointer_size` | bytes per pointer in chains and `ptr` fields (default 4) |
| `pointer_range` | `[lo, hi)`: a pointer read in a chain outside it is null and the field reads as `null` (GameCube: MEM1 `0x80000000`-`0x81800000`). Default: the platform's main RAM. |
| `match` | how a session finds its map: `disc_id`, the catalog `game_ids`, and `memory` (bytes that must be at an address: an ASCII string, or `{"hex": "..."}`) |
| `regions` | what the search snapshots by default (default: the platform's main RAM, `gbox.tools.MAIN_RAM`) |
| `groups` | optional: group -> description, in display order |
| `fields` | name -> field |

### Fields

Names are lowercase and dotted, `group.name` (`player.pos`, `merc.timer`, `door.state`): the part before the first dot
is the group unless `group` says otherwise. A struct's sub-fields have plain names (`hp`, `pos`).

| key | |
|---|---|
| `address` | a static address, or |
| `pointer` | a pointer chain, Cheat Engine style: `{"base": B, "offsets": [o1, ..., on]}` (or the list `[B, o1, ..., on]`): start at B, then for each offset read the pointer there and add the offset. `{"base": "0x802B3044", "offsets": ["0x94"]}` = (u32 at 0x802B3044) + 0x94. A pointer outside `pointer_range` (null, garbage) stops the chain: the value is `null`. |
| `offset` | inside a struct only: bytes from the start of the element |
| `type` | `u8` `u16` `u32` `u64` `s8` `s16` `s32` `s64` `f32` `f64`, `bool` (one byte, non-zero), `ptr` (unsigned, `pointer_size` bytes, shown hex), `bytes` / `str` (with `length`; `str` is ASCII up to the first NUL), `struct` (with `fields`) |
| `length` | bytes, for `bytes` / `str` |
| `endian` | overrides the map's |
| `count`, `stride`, `first`, `max` | an array: `count` elements, `stride` bytes apart (either a number, or `"@field.name"`: another field's value, read first), starting at element `first` (default 0), never more than `max` (default 256) elements. The stride defaults to the type's size, so `"type": "f32", "count": 3` is a vector. |
| `fields` | `"type": "struct"`: its sub-fields, each at an `offset` (every field key but `address` / `pointer`) |
| `live` | struct arrays: which elements are reported (a condition, below); the others are left out |
| `mask`, `shift` | value = (raw & mask) >> shift (bit fields; one bit of a flag byte) |
| `scale`, `bias`, `units` | number = value x scale + bias, shown with its units (`"s"`, `"rad"`, `"world units"`) |
| `enum` | value -> label: `{"3": "TAKE", "5": "JUMP OVER"}` (keys are the value after mask / shift, before scale). A value missing from the table shows as the number. |
| `flags` | bit -> label: `{"0x100": "A", "0x200": "B"}`. The value shows as the labels of its set bits. |
| `format` | display hint: `hex`, `dec`, `deg` (radians shown in degrees), `bin` |
| `valid` | `[min, max]`: a value outside it is marked suspect (a wrong pointer or a moved structure shows at once) |
| `watch` | `true`: every change of the field is logged as an event; `false`: never. Default: fields with an `enum` or `flags` table. |
| `group`, `description` | where it shows, and what it is |
| `source` | `ghidra` (static analysis: Ghidra, REA, capstone), `scan` (found with the inspector's search) or `manual` (cheat codes, documentation, hand-checked reads) |
| `evidence` | how it was verified: the routine that reads it, the search (samples, labeler), the live check and its date |
| `added`, `by` | when (ISO date) and who (agent or operator) |

### Conditions (`live`)

`{"field": "<sub-field>", "mask": M, "<op>": V}` with op one of `eq` `ne` `lt` `le` `gt` `ge` `in` (a list), combined
with `{"all": [...]}`, `{"any": [...]}` and `{"not": {...}}`. RE4's EmMgr: a slot is live when `(flags & 0x601) != 0`
and its ESL index is not 0xFF.

### Events

The inspector evaluates the map while someone watches (the panel, a search labeler, a bot) and logs each change of a
watched field (enum / flags by default) as `{seq, t, field, old, new, old_label, new_label}`; struct elements as
`enemies[5].hp`. A frame of the game at that moment is kept with the newest events when the control plane has one in
memory (no encoding, no request to the worker).

A struct element's sub-field is watched when it has an enum / flags table (or `"watch": true`); `"watch": true` on
the struct itself also logs elements appearing and disappearing (`enemies[5]: None -> live`).

### Adding fields (another agent, a script)

Add them to `profiles/gamedata/<map id>-ram.json` in a PR, with `source` and `evidence`. `python -m gbox.ram_map check
<file>` validates a map; `python -m gbox.ram_map read G4BE08 --pid <Dolphin pid>` reads it once from a Dolphin on the
same Linux host (read-only, its shared RAM view). The inspector's "add to map" writes the overlay file in gbox-data
instead (see Files).

## Python API (playbooks, scripts)

```python
from gbox import ram_map, ram_reader
m = ram_map.load("G4BE08")                  # a map id, a disc id, a catalog game id, a session / game dict, or a path
v = m.read(ram_reader.for_adapter(ad))      # in the worker: Dolphin's shared RAM on Linux, else the adapter's reads
v["merc.timer"]                             # 87.3 (after scale: seconds)
v["player.pos"]                             # [x, y, z]; None when the player pointer is null (v.errors says why)
v.label("pad.held")                         # "R, A"
v["enemies"]                                # [{"index": 3, "address": ..., "pos": [...], "hp": 1000, ...}] live slots only
m.read(reader, names=["merc.timer"])        # only these fields (and the fields their counts / strides need)
```

Any reader works: a function `read(addr, n) -> bytes`, or an object with `read`, `rd` (the RE4 bot's `ShmMem` /
`AdMem`) or `read_memory` (an adapter). With `read_many([(addr, n)])` (every `gbox.ram_reader.Reader`) one call per
pointer level reads the whole map: RE4's 21 fields with the 80-slot enemy table are three batched reads, about 1.5 ms
through Dolphin's shared RAM on the Spark (live 2026-10-20: median 1.52 ms, p95 6.9 ms; at the title 0.39 ms).
`ram_map.changes(previous, current)` lists the watched fields that changed. `ram_map.detect(read, platform)` finds a
map from the game's own memory (the disc id at 0x80000000 on GameCube / Wii).

## The inspector (gbox/ram_inspector.py)

One per running session, made on first use, on the control plane:

* **Reader** (`gbox/ram_reader.py`), quickest first, every one read-only and within a budget (bytes and reads per
  second by how it reads; a read that cannot get its budget in time raises `Throttled` and the panel shows the last
  values):
  * the session's adapter when its worker runs in the control plane's process (the Spark's `serve --worker`):
    Dolphin's shared MEM1 / MEM2 views through `/proc/<pid>/mem` (`ram_dump.ShmRam`, opened read-only, no halt; a
    24 MiB MEM1 snapshot takes ~80 ms), else the adapter's reads (Windows Dolphin's process memory: no halt;
    RetroArch's network commands; a GDB stub: a batch per CPU halt, 64 KiB pieces with play between them);
  * a Dolphin on the same Linux host whose worker is another process: its shared views by the session's pid;
  * a session on another PC: its worker over the session channel, rpc op `read_ranges` (up to 512 ranges / 2 MiB per
    request, base64; one CPU halt per batch on a GDB stub). A worker older than this answers "not allowed": the
    reader then asks `read_memory` per range.
* **Map**: the session's catalog game id, else the disc id read from RAM (GameCube / Wii), else `match.memory`.
* **Live values**: the map read at most 10 times a second however many viewers poll; while someone watches (the
  panel's polls, a labeler) a thread keeps reading (10 Hz shared memory / process memory, 4 Hz adapter commands and
  the session channel, 2 Hz a GDB stub) and logs events. The last 500 events and the frames of the last 40 are kept.
* **Hex**: up to 4 KiB at an address or at the end of a pointer chain.
* **Search** (`gbox/ram_search.py`): a region (default: the map's first region, else the platform's main RAM) at
  u8 / u16 / u32 / s8 / s16 / s32 / f32. Each sample: the region (or, once 20,000 or fewer candidates are left, only
  the ranges around them), an optional Cheat Engine filter (changed / unchanged / increased / decreased / equals /
  not_equals / range) and an optional label. Labeled samples keep the addresses whose "on" values and "off" values
  never overlap, with the values each label saw: on {3 ×6, 5 ×3} off {0 ×14} reads "3 and 5 while the prompt shows".
  `tolerance` (mislabels ok) lets a candidate keep up to that many samples on the wrong side: labels from the
  picture are a little late at the edges. Memory: whole labeled samples while more than a million candidates are
  left (one on / off pair usually leaves a few hundred thousand), then per candidate its last value and up to 8
  values per label (more is a counter or a timer, not a state); 320 MiB at most per search, two searches at once.
* **Labelers**: the screen-prompt watcher (`gbox/screen_prompt.py`) on the stream's newest frame (on while the game
  draws a button prompt, optionally only A or B), or a RAM-map field's condition (`{"mask": "0x100", "ne": 0}`: A
  held). A labeler reads the RAM once its label held for two checks and 0.25 s, and the sample counts only if the label
  still holds 0.3 s later (the frame lags the RAM: a read at either edge of a short prompt would carry the wrong label;
  `discarded` counts those). While the search keeps whole samples it samples at label changes only; after that, every
  second while a label holds. A labeler stops after 30 minutes.
* **Promote**: name, type, description, group, enum (prefilled from the candidate's values) into the overlay, with the
  search as evidence (`source: scan`), audited.

Nothing in the inspector writes game memory, sends input, pauses or touches save states.

### API

| route | |
|---|---|
| `GET /api/ram/maps` | the maps: id, title, platform, fields, promoted fields, catalog game ids |
| `GET /api/ram/maps/{map_id}` | one map merged with its overlay (`describe()`) |
| `POST /api/ram/maps/{map_id}/fields` `{name, field}` | add / replace a field in the overlay (checked: the merged map must load) |
| `DELETE /api/ram/maps/{map_id}/fields/{name}` | remove a promoted field (repo fields change in a PR) |
| `GET /api/sessions/{sid}/ram` | the inspector: map, reader and its budget, watcher, search |
| `GET /api/sessions/{sid}/ram/live?since=N` | rows (name, group, value, display, label, address, error, suspect; struct rows), events after seq N, reader, reads / bytes |
| `GET /api/sessions/{sid}/ram/events?since=N&limit=` | the event log |
| `GET /api/sessions/{sid}/ram/frames/{fid}.jpg` | the frame kept with an event |
| `GET /api/sessions/{sid}/ram/hex?address=&length=&pointer=base,off,...` | bytes now (hex), the chain it followed |
| `POST /api/sessions/{sid}/ram/search` `{type, base?, size?, tolerance?}` | start (the first snapshot is taken) |
| `GET /api/sessions/{sid}/ram/search?limit=` | status and candidates (address, value, per-label values, mislabeled) |
| `POST /api/sessions/{sid}/ram/search/sample` `{label?: on/off, op?, value?, lo?, hi?}` | one sample |
| `POST /api/sessions/{sid}/ram/search/auto` `{source: screen_prompt/field/off, button?, field?, cond?, hz?, tolerance?}` | a labeler |
| `DELETE /api/sessions/{sid}/ram/search` | end it (frees its memory) |
| `POST /api/sessions/{sid}/ram/promote` `{name, address or pointer, type, description, group, enum, flags, units, scale}` | add a found field to the session's game map |

Errors: 404 no such session, 409 the session ended (or two searches already run), 422 a bad request (the message
names it), 429 the read budget is spent, 502 the read failed.

### The panel (clients/web/viz/ram-inspector.js)

The chip button in a running session's header (after the pick whip) opens a floating panel over the session view,
draggable by its title, placed first under the header and left of the watch panel; it reopens with the session's
header when it was open there. Tabs: **Live** (by group; a changed value flashes; an address opens Hex), **Events**
(newest first, with the frame of the moment), **Hex** (address, length, pointer chain, live; click a byte to follow
the word there as a pointer) and **Search** (start with type / region / mislabels ok; Event on / Event off / Sample;
a filter; an auto-labeler; candidates with their values per label and "Add to map"). Screenshots:
`docs/evidence/ram-inspector/` (the panel drawn by the web shell headless, answering what the inspector read
read-only from the live RE4 agent session on the Spark: the map's values, events and bytes, and the field-labeled
search below; the game picture is that session's own frame).

## Live check, 2026-10-20 (Spark)

Read-only (shared RAM through `/proc/<pid>/mem` opened O_RDONLY, frames through `GET .../frame.jpg`), with this
branch's modules in a scratch copy, against RE4 GameCube agent sessions on lilspark while the Mercenaries bot played:

* every field of G4BE08 read as the bot reads it: room 0x0400, Leon (hp 1860, then 0 when he died), position, facing,
  aim pitch, the clock counting down, EmMgr 80 slots of 0xDE0 with 16 live Ganados (positions, health 1000 / 1400 /
  1800), the unlock bits; null player pointers at the title and the menus reported as such;
* events: the pad's A / B presses as the bot pressed them, each with the stream's frame;
* search: 24 MiB MEM1 snapshot 77 ms, a filter step 70-140 ms dense, 28 ms sparse; at the Select Player menu
  122,000 bytes change on their own (the frame buffer, audio, animation);
* the screen-prompt labeled search did not find the prompt byte in two runs (4 and 5.5 minutes): the bot answers a
  prompt within about half a second, so the labeler got 2 "on" samples in the first run (before the confirmation
  window and the tolerance existed) and none in the second, which ended with Leon dead. A slower driver (the
  operator, or a bot that waits on a prompt) gives it the samples it needs;
* the same search labeled by a RAM-map field (`prompt.kind != 0`, #724's address; tolerance 1) ran 4 minutes while
  the bot played and left 23 of 25,165,824 bytes after 8 on / 37 off samples, among them the prompt's own state
  found independently of #724's static analysis: 0x80279320 (prompt.kind) on {11 ×5, 1 ×3} off {0 ×37} (11 = SHAKE
  OFF, 1 = A), 0x80278B26 (prompt.valid) on {1} off {0}, 0x80213E6B (the low byte of prompt.label_shown) on {1, 3}
  off {0}, 0x80278B24 (prompt.count, 1 mislabel), plus unmapped ones to look at: 0x8097D5A0 / 0x8097D810 /
  0x8097D6D8 (255 off, 45 or 13 on), 0x80241D6C-73, 0x8027F5E3;
* `pad.held` (0x80287E9E in the first map) is the previous frame's buttons: polled every 2 ms, each change showed at
  0x80287EA2 one game frame (29-43 ms) earlier (65 of 65 in 20 s). The map now has `pad.held` at 0x80287EA2 and
  `pad.held_prev` at 0x80287E9E; the whole 45-field map read from that session;
* seen on the way: after Leon died the game sat on "You Are Dead · Continue Yes / No" for minutes while RAM still
  read as a running round (room 0x0400, player present, clock frozen at 302.1 s, hp 0): `player.hp == 0` tells that
  screen apart where `in_mercenaries` does not.
