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

### Adding fields (another agent, a script)

Add them to `profiles/gamedata/<map id>-ram.json` in a PR, with `source` and `evidence`. `python -m gbox.ram_map check
<file>` validates a map. The inspector's "add to map" writes the overlay file in gbox-data instead (see Files).
