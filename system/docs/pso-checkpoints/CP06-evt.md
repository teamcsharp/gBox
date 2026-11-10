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
