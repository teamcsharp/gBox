# CP06 `.evt` — partial (the record framing was wrong on main and is fixed; the opcodes are still open)

Session identity: DeepSeek    Branch: ds-pso-cp06-evt-opcodes-20261110    Commits: this branch
Goal: 1 (decrypt / P2b)

## What CP6 item 1 asked

`.evt` opcode semantics: *"`gbox/pso_evt.py` decodes each opcode group to a named op; a test rebuilds one real script
byte-identically from the named ops."*

## What was found instead, first: the record table was mis-framed on `main`

`pso_evt.records()` read `(len(data) - 16) // 20` records and called the remainder "trailing bytes". The header's own
size word says otherwise, and the identity holds in **every** event file:

```
header.a == 16 + 20 * header.c        # 147 of 147 files measured
```

So the file is: 16-byte header, `header.c` records of 20 bytes, then the **script blob** (0…404 bytes). `main`'s reading
fabricated records out of the script in **138 of the 147** files. Decisive evidence that the tail is not records: decoded
as records, its first words are ids `284,428`, `1,477,181,696`, … while the real records carry ids around `0x6f`.

**Fixed** in `gbox/pso_evt.py` (branch): `table_end()` (refuses a header whose count and size disagree),
`script()` (the blob), `build()` (byte-identical inverse), and `records()` now stops at the header's count.

**Verified:** `build(header, records, script) == data` for **143 of 143** archive event files (27,820 script bytes in
total), and the two disc-based tests that encoded the old framing were corrected with the reason written into them.
Tests: `tests/test_pso_evt.py` **11 passed** (including all-files count/rebuild, and the synthetic regressions for the
count and the script).

## The script blob: measured structure (the opcode work, in progress)

- **All scripts are multiples of 4 bytes** (147/147), sizes 8…404, 27,820 bytes total.
- `FF FF` at the end appears in only **76/147** files, so it is a common terminator but not universal - the first
  hypothesis ("ends 0xFFFF") is false as a rule.
- The first byte is dominated by families `0x0C` (684), `0x0A` (1,118), `0x01` (1,067), `0x00` (2,196) per byte
  histogram at 4-byte boundaries.
- The clearest repeated unit is a **6-byte group**: `0c 57 04 00 00 01 | 0c 58 04 00 00 01 | 0c 59 04 00 00 01` in
  `map_forest01_00.evt` - family `0x0C`, a byte that increments (0x57, 0x58, 0x59), and a constant `04 00 00 01` tail.
  That reads like "three objects of a kind, count 4, flag 1", but naming it needs the interpreter (CP7) or a field test
  (CP5), exactly as the guide says.
- A brute-force search for per-family instruction lengths was started and abandoned: `9^20` assignments is not a
  tractable search, and the round's honest result is the container fix above rather than a guessed grammar. The next
  attempt should use the interpreter's dispatch (CP7) to enumerate opcodes, not statistics.

## Still open

- **CP6 item 1 proper:** the opcode names and a byte-identical rebuild *from named ops*. The container rebuild is
  byte-identical today; the opcode layer is not decoded.
- **CP6 item 2:** `n.rel` render geometry (`fmt2` root) - not started.
- **CP6 item 3:** save data - CP9.

## Needs

- CP7 (`0x8028f508` / the `.evt` interpreter) to give the opcode table: the interpreter's dispatch is the ground truth
  for opcode meaning, and the guide pairs the two checkpoints for exactly this.

Tests: 11 passed in `test_pso_evt.py`; CP0 baseline otherwise unchanged.

Next: the `.evt` interpreter's dispatch in the executable (CP7) so the opcode groups can carry names, then the
byte-identical rebuild from named ops.

## Round 68: the event system's debug path, and a runtime field it names (object `+0x84` = event number)

Searching the string table for the event system's own messages finds **`"EVT NO : %d"`** at four addresses, each referenced
by a small function (112-120 bytes) with the same shape:

```c
void FUN_8015bb8c(int param_1) {
    FUN_803d8090(0xff00ff);                                        // set the debug colour
    FUN_803d853c(0x130020, s_EVT_NO____d_80440830, *(u32 *)(param_1 + 0x84));   // draw "EVT NO : %d"
    FUN_803d8090(0xf0f0f0ff);
    FUN_80141cf4(*(f32 *)(r2 - 0x4960), param_1 + 0x38, &DAT_804a7448);         // draw a box at object +0x38
}
```

(`FUN_80188814` and `FUN_8018cbf0` are the same routine for the other areas/languages; `FUN_8018cbf0` is 120 bytes.)

Two measured facts come out of that:

* **the event number lives at object `+0x84`** - the debug overlay prints it for the object at `param_1`, so an object
  that carries an event (a door, a switch, a scripted NPC) is identified by a word at `+0x84`;
* **the object's draw position is at `+0x38`** (the box is drawn there), which matches the placement-to-object copy in
  CP7.2 (`FUN_801057a8` writes the position to `+0x38`).

That is a **runtime** hook, not the interpreter: the overlay draws the number, it does not dispatch it. It is nevertheless the
first piece of the event system's *object* side to be named, and it is the field a CP15 door test would read (the door's
event number) once a live session exists.

**What this does not give:** the opcode dispatch. The interpreter still has to be found either by its file path (the `.evt`
name is built at run time, like the `.rel` names, so there is no string reference to follow) or from a live breakpoint on a
known event number's use.

Tests: none changed; CP0 baseline unchanged.

## Round 75: two dead ends for the interpreter, recorded so they are not repeated

**Dead end 1: the `+0x84` field is not a hook.** The round-68 finding (the debug overlay prints "EVT NO : %d" from
`*(u32 *)(object + 0x84)`) suggested scanning the code for loads of that field. The scan (`lwz rD, 0x84(rA)`:
`(word & 0xFC000000) == 0x80000000 and (word & 0xFFFF) == 0x0084`) finds **506 instructions** across the image - `0x84` is a
common structure offset, so the field cannot be used to locate the event code.

**Dead end 2: the `.evt` name leaves no string to follow.** Like the `.rel` names, an event set's file name is composed at run
time from the area name; the only event-related strings are the debug overlay's `"EVT NO : %d"` and the set loaders'
`o.dat` / `e.dat` / `ad.dat` suffixes (which belong to the placement/enemy sets, not the scripts).

**What is left for the opcodes, and it is live:** break on a known event number's use (the object field `+0x84` of a door
whose event is known, e.g. the city's Warp door), or trace the `.evt` file being opened during a load. Both need a session;
both are recorded in `CP07-*.md` as the reason the interpreter is live-dependent.

Tests: none changed.
