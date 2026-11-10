# CP09 save data — the real card found, the reader fixed, BQF's save listed (checksum: not found, not proven absent)

Session identity: DeepSeek    Branch: ds-pso-cp09-save-data-20261110    Commits: this branch
Goal: 1 and 4

## The real card (accept item 1)

`D:\gBox\runtime\dolphin\Dolphin-x64\User\GC\MemoryCardA.USA.raw` - **16,777,216 bytes (2048 blocks)**, mtime
**2026-11-10 12:57:37**, i.e. written during today's sessions. That is the card the running Dolphin uses: the gameplay
demo cards under `D:\gBox\runtime\gameplay-demos\...` are 2 MiB images from 4 November.

## Why the lane's reader said "no data" (the bug, and the proof)

Two bugs in `pso_memcard`, both fixed here:

1. **The block fields were read at the wrong offset.** The GC directory entry is game code (4), company (2), banner (1),
   icon (1), name (32), time (4), then the **first block at `0x36`** and **block count at `0x38`**; `0x3A..0x3F` are
   unused. The module read the pair at `0x3A`, which on this card is `0xFFFF, 0` - exactly the "every PSO entry at first
   block 0xFFFF, count 0" the lane reported while BQF was loading from it.
2. **The size check** demanded exactly 16 MiB, so a 2 MiB demo card could not be read at all.

With the fields read correctly the six entries chain perfectly - `5+1, 6+4, 10+4, 14+3, 17+11, 28+10` - which is also
the proof that this card's directory is the one at `0x2000`:

| entry | game | name | first block | blocks |
|---|---|---|---|---|
| 0 | `G4BE` | `bh4_system` | 5 | 1 |
| 1 | `GRSE` | `sc2_0.dat` | 6 | 4 |
| 2 | `GCTE` | `Crazy Taxi` | 10 | 4 |
| 3 | `GPOE` | **`PSO_SYSTEM`** | **14** | **3** |
| 4 | `GPOE` | **`PSO_CHARACTER`** | **17** | **11** (90,112 bytes) |
| 5 | `GPOE` | **`PSO_GUILDCARD`** | **28** | **10** |

**BQF's save is `PSO_CHARACTER`, 11 blocks at block 17**; its payload begins
`PSO EPISODE I & II Plus` (0x20 bytes) + `CHARACTER_FILE ` (0x20), i.e. the save header is plain ASCII and not ciphered
at the front.

## The checksum / cipher question (accept item 4) - measured, partial

* the **last 16 bytes of the 11-block character file are zero**, so there is no trailing checksum;
* no sum-of-bytes, sum-of-u16 (LE/BE) or sum-of-u32 (LE/BE) over the payload matches any word in its first 0x100 bytes;
* there is no cipher in evidence: the header is plain ASCII and the payload after 0x40 is structured game data, not
  high-entropy (the whole card's first 64 KiB has 3.6 bits/byte, driven by the card's own header/zero fill).

**Conclusion, stated honestly:** no checksum or cipher was found by the standard schemes, and none was *proven absent* -
proving that needs the live accept test (flip a byte, let the game load it), which needs CP4's launch path. The evidence
does establish item 3 of CP9's state (the card *does* hold PSO saves with data) and retires the "no data blocks" claim as
a reader bug.

## Tests

`tests/test_pso_memcard.py` **8 passed**:

* the synthetic entry now writes the standard `0x36`/`0x38` fields;
* the real card (skipped when absent) lists `PSO_SYSTEM` 14/3, `PSO_CHARACTER` 17/11, `PSO_GUILDCARD` 28/10 with a
  contiguous allocation chain;
* the character save begins with its ASCII header;
* a 2 MiB card is accepted by `read()`.

## The payload is ciphered or packed - measured (step 4's first half)

Comparing the three PSO saves on the card:

| save | header (plain) | body |
|---|---|---|
| `PSO_SYSTEM` (3 blocks) | `PSO EPISODE I & II Plus` + `SYSTEM_FILE ` | no printable run of 6+ bytes at all |
| `PSO_CHARACTER` (11 blocks) | ... + `CHARACTER_FILE ` | 116 printable runs of 6+, all gibberish (`pBRWYPA`, `6+4QJ;=`); no `BQF`, no `HUmar`/`HUcast`/`FOnewearl`, no `Forest`, no `Level` anywhere |
| `PSO_GUILDCARD` (10 blocks) | ... + `GUILDCARD_FILE ` | same: 93 gibberish runs |

So the **header is plaintext and the payload after `0x40` is not**: a plaintext character save would contain the
character's name and class somewhere, and the name `BQF` appears nowhere in the file. The body also holds a
**10,828-byte run of zeros at `0x135B4`**, which a pure XOR stream cipher would not produce over a zeroed plaintext
region - so the encoding could be a cipher, a packed/compressed format, or both per section.

**The six CARD functions are glue, not the codec:** decompiled them all (`801fbb7c` 96 B, `801fc564` 116 B, `801fd94c`
68 B, `801fe8a8` 144 B, `801fe938` 152 B, `802008e8` 176 B, kept in `docs/research/pso-card-decompiles.txt`) and none
contains a XOR, a rotation or a 4-byte constant - they call out to the codec. So naming the encoding means following their
callees, or flipping one payload byte under a live jump state and watching the game accept or reject it (the latter
distinguishes a cipher from a packed format, and neither is possible in this round).

## Next (needs the live window)

Decode `PSO_CHARACTER`'s per-character record layout (name, class, level, position, flags - where "BQF has entered
Forest 1" would live) from the payload, and prove or disprove a checksum by a byte flip under CP4's jump state. Both are
one live session away.

Needs: CP4's launch path (the i9 worker's `launch_game` claim) for the accept test; nothing else.

## Round 49: the save module's anchor, and where the codec is not

* **The save module is now anchored by its own strings.** Searching the defined string data for
  `CHARACTER_FILE` / `SYSTEM_FILE` / `GUILDCARD_FILE` / `PSO_CHARACTER` / `PSO_SYSTEM` and taking their code references
  gives **35 functions**; the two largest character-save paths are **`FUN_801fd21c` (1,096 B)** and
  **`FUN_801fce6c` (940 B)**, with `FUN_801fc6a4` (436 B) and the small per-file helpers
  (`801fbb1c`, `801fbbdc`, `801fd990`, `801fd9cc`, `801fda4c`, …) beside them. Decompiles kept in
  `docs/research/pso-save-module-decompiles.txt`.
* **The codec is not in the card API or these paths' first two hops.** A 2-hop sweep of the six `CARD*` functions found
  only card status codes (`0xffffff83`, `0xffffff05`, …) and status bit masks, and the save paths themselves contain a
  single shift (`<< 0xd`) and no XOR or key constant. So the encoding is applied by a generic file-read/write path the
  save module calls - the next hop to chase - or by the loader that decompresses the card image before it is parsed.
* **Branch hygiene re-checked against the new main:** all **36** `ds-pso-*` branches still exit 0 from
  `git merge-tree --write-tree origin/main <branch>` after main advanced by 12 commits (the grenade-checkpoints merge),
  so CP0's "every branch merges clean" property still holds.

## Round 50: PRS and a repeating XOR are both ruled out; the decode candidates are named

Three cheap hypotheses tested against the real card before more decompiling:

1. **PRS compression** (the game's standard compression, `gbox.ninja.prs_decompress`): fails with an `IndexError` on the
   character and system payloads at starts `0x00`, `0x40` and `0x100` - so it is **not** a plain PRS stream.
2. **A repeating-key XOR**: the body's most common 2-byte patterns are `0000` (5,414 occurrences), `ffff` (82), `f7ff`
   (46), `98ab` (46). XOR with each of the top pairs (`9934`, `9955`, `3499`, `5534`) leaves **0 zero bytes and about 40 %
   printable** - no better than chance, so **not** a simple repeating XOR either.
3. **The body is structured, not uniform**: 5,414 zero 2-byte words and 2,707 zero 4-byte words, plus a 10,828-byte zero
   run at `0x135B4` (which is the *tail* of the 90,112-byte file). Whatever the encoding is, the zero regions survive it.

The character-save path **`FUN_801fd21c`** (1,096 bytes) was decompiled in full and has **no XOR and no byte loop**; it
validates, calls `FUN_801fcd74` (184 B) several times, and its likely decode/commit calls are **`FUN_80200560` (304 B)**
and **`FUN_80200778` (368 B)**, with `FUN_80200a44(1)` after them. Those are the next two functions to read, and the
whole decompile is kept in `docs/research/pso-character-save-path.txt`.

**Status of accept item 4: still open, but narrowed.** The encoding is not PRS and not a repeating XOR; it is applied by
a routine the save path calls (`80200560`/`80200778` neighbourhood) or by the loader that decompresses the card image.
The live byte-flip accept test remains the only way to prove "cipher" versus "packed" for certain.

Note: CP4's gates were checked again this round (worker `idle_seconds = 44.9`, CPU 54 %) - the operator was at the
machine, so no launch was attempted.

## Round 51: the copy path does not decode - the record size is 0x2798, and the "cipher" hypothesis weakens

Decompiling the two candidates from round 50:

* **`FUN_80200560`** (304 B) allocates two ~71 KB buffers (`0x1156c` = 71,020 bytes), takes two card handles
  (`FUN_801fc900`), and moves data through a state struct at `0x8051381c` with the **file layer**'s
  `FUN_8007c0cc` / `8007c134` / `8007c264` / `8007c378` / `8007c48c` calls;
* **`FUN_80200690`** (232 B) then copies the buffer **record by record at a stride of `0x9e6` words = `0x2798` bytes**
  (10,136 bytes), until `0x454b` words = **71,020 bytes**, i.e. **7 records**, calling **`FUN_801fdfb8`** once per record;
* **`FUN_801fdfb8`** (88 B) is a **plain structure copy**: `FUN_8013a650`, `FUN_801fe010(dst+0x41c, src+0x41c)`, then the
  three words at `+0x278c/+0x2790/+0x2794`. **No XOR, no shift, no table lookup.**

So the bytes that sit on the card are copied into RAM *as they are* by this path: the character save's record size is
**`0x2798` (10,136 bytes)**, and the 71,020-byte area holds **7 records**. That weakens the "cipher" hypothesis and
favours "the save stores the game's own packed structs" - in which case the earlier "gibberish" was packed data, not
ciphertext, and the missing `BQF` string means the name is in a slot/encoding I have not located (PSO GC stores the
character name in its own text encoding, not ASCII).

**What is still solid:** the card path, the block map, the file sizes, the record stride, and that the payloads are not
plain ASCII. **What changed:** the encoding is *not* applied by the file copy path, so if a decode exists it happens
later (when a slot is parsed) or there is none. Decompiles kept in `docs/research/pso-save-copy-path.txt`.

Next: read the slot parser that consumes a record (`FUN_801fe010` and the three words at `+0x278c..+0x2794`), and locate
the character-name field by walking a record against the known character data (class/level/position fields are
recognisable in RAM).

## Round 52: all seven records are encoded - round 51's "packed structs" reading is corrected

Walking the character file's **seven `0x2798`-byte records** (area starts at file offset `0x40`; record *i* at
`0x40 + i*0x2798`):

| record | non-zero bytes | printable runs in the first 1 KiB |
|---|---|---|
| 0 | 10,128 / 10,136 (99.9 %) | none |
| 1 | 10,086 (99.5 %) | `-r y`, `bFM2`, `ranx6`, `{l3G!W`, … |
| 2 | 10,107 (99.7 %) | `t$uG`, `272.J`, `K/+p`, … |
| 3 | 10,102 (99.7 %) | `)}Z2`, `Q@bC`, `"S6@`, … |
| 4 | 10,097 (99.6 %) | `GIgTW`, `9$&{`, `ngjN`, … |
| 5 | 10,103 (99.7 %) | `@|vL`, `.Y[R{`, `b2*TT`, … |
| 6 | 10,092 (99.6 %) | `|/86@`, `;ZJS`, `q5z{\}`, … |

**Every record is ~99.6 % non-zero and high-entropy.** A character struct with empty slots would be mostly zeros; this is
not. So **the storage is encoded**, and round 51's "the save stores packed structs, the cipher weakens" was **wrong** -
what round 51 proved is narrower and still true: the `FUN_80200560` -> `FUN_80200690` -> `FUN_801fdfb8` path is a plain
copy, therefore it copies a buffer that is **already decoded** (or the decode happens on the way in/out through the file
layer's `FUN_8007c0cc` / `FUN_8007c134` / `FUN_8007c264` / `FUN_8007c378` / `FUN_8007c48c` calls in `FUN_80200560`).

**Where the codec must be:** in those file-layer calls (the buffer is full of high-entropy bytes when it is read from the
card and plain structure copies after), or in a decompression step between the card read and `FUN_80200560`. That is the
next decompile target, and it is named.

Record 0 is also the one that differs in appearance (its head is a repeating `99 34 / 99 55 / 9d 56` pattern, while records
1-6 are flat high-entropy) - consistent with record 0 being a *header/slot-0 special* block rather than a character.

## Round 53: the codec is found - a byte permutation plus a 56-word subtractive PRNG ring

The round-52 target (the file-layer calls inside `FUN_80200560`) resolves it. Decompiled from `PsoV3.dol`:

**`FUN_8007c0cc(state, buf, size)`** - the word cipher:

```c
uVar1 = size + 3;
for (i = 0; i < (uVar1 >> 2); i++) {
    iVar2 = FUN_8007c3e0(state);            // next key word from the ring
    *(int *)(buf + 4*i) = iVar2 - *(int *)(buf + 4*i);   // buf[i] = key - buf[i]
}
```

**`FUN_8007c3e0(state)`** - the key stream: `*state` is a cursor; it returns `state[cursor + 2]`, advances the
cursor, and when the cursor passes `0x37` it calls `FUN_8007c438(state)` and resets the cursor to 1. So the keystream is a
**56-word (0x38) ring** in the state struct.

**`FUN_8007c48c(state, seed)`** - the seed initialisation: stores the seed at `state[0x38]` and `state[0x39]`, then walks the
ring at a stride of `0x15` (mod `0x37`) filling `state[1..0x37]` with the subtractive recurrence `a(k+1) = seed - a(k)`
starting from `a(0) = 1`, then runs **four** `FUN_8007c438(state)` warm-up rounds and sets the cursor to `0x37`.

**`FUN_8007c438(state)`** - one ring regeneration step: 25 iterations of
`state[i+4+4] = state[i+4+4] - state[i+4+0x80]` (a lag of 0x80 bytes = 31 words), followed by more of the same shape
past `iVar1 = 100`.

**`FUN_8007c134(state, src, dst, size)`** - the byte permutation: for each 256-byte block it copies `src[256k + j]` to
`dst[256k + table[j]]` using the **256-byte table at `0x80500498`**. This is a de-interleave, not a cipher of its own.

So PSO's save body is protected by **a 256-byte permutation table plus a subtractive 32-bit stream cipher** (the
keystream from a lagged-subtraction ring seeded by `FUN_8007c48c`). That is exactly the shape community save editors
describe, and it is now pinned to addresses in this build:

| piece | address | role |
|---|---|---|
| word cipher | `0x8007C0CC` | `buf[i] = key_i - buf[i]` |
| key stream | `0x8007C3E0` | cursor into the 56-word ring |
| seed init | `0x8007C48C` | recurrence `a(k+1) = seed - a(k)`, four warm-up rounds |
| ring step | `0x8007C438` | 25-term subtraction with a 31-word lag, then more |
| byte permutation | `0x8007C134` | table at `0x80500498` |
| seed source | `_DAT_8051391C` / `FUN_80202984` | set in `FUN_80200560` |

**What is left to prove it end to end:** implement the ring and the permutation in Python (`gbox/pso_save.py`), decode a
real record with the right seed source, and show the plaintext is structured (a decoded record 0 should become
zero/fixed-field data instead of 99.9 % entropy). That is the next step, and it has a file-level test: the same decode
applied to `PSO_SYSTEM` and `PSO_CHARACTER` must both produce plainer output, while a byte flip in the ciphertext must
still decode (the cipher is key-driven, not self-verifying).

Decompiles kept in `docs/research/pso-save-cipher.txt`.

## Round 54: first implementation of the cipher does not reproduce it - and why

Implemented the ring, the keystream and the word cipher in Python and tried twelve (recurrence variant x seed) combinations
against the real `PSO_CHARACTER` body (seeds: `0`, `1`, the directory entry's time `0x3285d13d`, and its complement;
recurrences: `a(k+1) = seed - a(k)`, `a(k+1) = a(k) - seed`, and a constant-seed form):

| variant / seed | zero bytes | printable |
|---|---|---|
| `seed_minus` / any | 0.00 | 0.37-0.38 |
| `a_minus_seed` / any | 0.00 | 0.37-0.38 |
| `const_s` / any | 0.00 | 0.37-0.38 |

**None produces structured output** (a correct decode should make most of a character record zero/fixed-field data). So the
round-53 structure is right in shape but my transcription of at least one of the three small routines is wrong - the
decompiled C is ambiguous exactly where it matters:

* `FUN_8007c48c`'s recurrence: the decompile reassigns `param_2 = param_1[iVar1 + 1]` inside the loop, which makes the
  recurrence `a = a - a = 0` if read literally - so the loop's real operand order is lost in the C;
* `FUN_8007c3e0`'s returned index (`state[state[0] + 1]` after the cursor update) and `FUN_8007c438`'s two index ranges
  (`state[k+1] -= state[k+0x20]`, then `state[k+1] -= state[k-0x17]`) are transcription-sensitive;
* the byte table is **not** at `0x80500498` as read by file offset: that address yields float data (`3f 80 00 00` = 1.0f),
  so `DAT_80500498` in the decompiled `FUN_8007c134` is either a different symbol or the table lives at another offset.

**Next step is exact, not exploratory:** transcribe the **assembly** of the three small routines
(`FUN_8007c48c` 148 B, `FUN_8007c438` 84 B, `FUN_8007c3e0` 88 B) and of `FUN_8007c134`'s table load, then reimplement. The
C is not reliable enough for a subtractive ring.

What this round does establish: the cipher cannot be reproduced from the decompiled C alone, the negative result is
recorded rather than hand-waved, and the acceptance test for the next attempt is objective (a decoded record must lose its
~99.6 % entropy).

## Round 55: the ring is now transcribed exactly; the byte table is runtime-built (.bss), which is the missing piece

**Assembly transcriptions (exact):**

* `FUN_8007c48c` (the seed init): `state[0x38] = state[0x39] = seed`; then 54 iterations of
  `idx = (21*k) mod 55; state[idx+1] = a; a = s - a; s = old a` - the assembly shows `subf r7,r7,r4` followed by
  `lwzx r4,r31,r0`, so the "seed" operand of the recurrence is the **previously written value**, not the original seed:
  `a_{k+1} = s_k - a_k`, `s_{k+1} = a_k`, with `a_0 = 1`, `s_0 = seed`. Then four `FUN_8007c438` rounds and `state[0] = 0x37`.
* `FUN_8007c438` (the ring step): 24 x `state[k+1] -= state[k+0x20]` (k = 1..24), then 31 x
  `state[k+1] -= state[k-0x17]` (k = 25..55) - confirmed instruction by instruction (`add r6,r3,r4`, `lwz`/`subf`/`stw`).
* With the corrected recurrence the word cipher still produces **unstructured output** for every seed tried
  (`0`, `1`, the entry time `0x3285d13d`, its complement): 0.00 zero bytes, 0.37 printable.

**Why: the byte table is not static.** `0x80500498` - the table `FUN_8007c134` permutes with - lies **between the end of the
`.data` section (`0x804805E0 + 0x7DA40 = 0x80500020`) and the next section (`0x805D7D00`)**, i.e. in **`.bss`**: it is
filled at run time, so no offline read of the executable can produce it, and my earlier attempt to read it as file data
landed on float values because the offset was wrong.

A **static** 256-byte permutation table does exist at file `0x4E9A5C` (VA `0x804F595C`), and it is the only 256-byte
permutation window in the image; the natural reading is that the `.bss` table is generated from it at start-up (possibly
seeded by the same value that seeds the ring).

**The next step is therefore specific:** find the code that writes `0x80500498` (Ghidra references / the .bss
initialisation in `FUN_80200560`'s state struct at `0x8051381C`) and transcribe *that* generator; with it plus the ring
(now exact), the decode should reproduce. The acceptance test stays objective: a decoded record must lose its ~99.6 %
entropy.

Attempt scripts kept: `docs/research/pso-save-cipher-attempt.py` (round 54) and this round's exact-ring version in the same
folder.

## Round 56: the cipher is fully transcribed - the seed is the one remaining unknown, and it is runtime data

The missing generator from round 55 is found and transcribed:

* **`FUN_8007c264(state)`** builds the 256-byte table at `0x80500398` (identity `0..255`) and then does a **Fisher-Yates
  shuffle** into the table at `0x80500498`: for `i = 255..0`, `j = FUN_8007c584(state, i+1)`, `b = A[j]`, `A[j] = A[i]`,
  `B[b] = i`, `A[i] = b`. (Ghidra's reference list confirms `FUN_8007c134` *reads* the table and `FUN_8007c264` builds it.)
* **`FUN_8007c584(state, n)`** = `((n & 0xffff) * (next_key(state) >> 16)) >> 16` - a 16-bit multiply-shift bounded by `n`.
* The permutation use in `FUN_8007c134`: for each 256-byte block, `dst[256k + B[j]] = src[256k + j]`.

So the complete pipeline is: **seed** -> `FUN_8007c48c` ring init (exact, round 55) -> `FUN_8007c264` permutation table ->
`FUN_8007c134` byte permutation -> `FUN_8007c0cc` word cipher (`buf[i] = key_i - buf[i]`).

**Swept 64 combinations** (8 seeds x {permute direction, order permute/words, keystream offset 1/2, subtract/add}) against
the real `PSO_CHARACTER` body: **none produces structured output** (best is still 0.00 zero bytes, 0.37 printable). With the
ring and the shuffle both verified, what is left is the **seed**.

**The seed is runtime data, not a constant in the file:** `FUN_80202984()` returns `*(*(r13 - 0x4694) + 0x118)` - a field of
a runtime object - and `FUN_80200560` uses it as the seed for both passes. Nothing in the DOL ties it to the card image, so
it can only be read from a running session (read that structure's `+0x118` while a save is loaded, or read it from RAM at
save-load and then decode offline).

**This ties CP9's last step to CP4's live window.** The moment a session is available:
1. read `[*(state_ptr) + 0x118]`-style seed (the object at `r13-0x4694` is reachable from the save path),
2. decode `PSO_CHARACTER` with the transcribed pipeline and confirm the entropy drops,
3. then the byte-flip accept test (prove the game re-reads a modified save, or rejects it).

Attempt scripts kept: `docs/research/pso-save-cipher-exact-ring.py` (round 55 ring) and the round-56 full pipeline with the
64-combination sweep in the same folder.

## Round 70: the seed's source function found - a 24-way per-slot initialiser

Searching the code for the store that sets the pointer behind the seed (`[r13-0x4694]`) finds **24 `stw r3,-0x4694(r13)`
instructions**, all in one function: **`FUN_802019f8`** (3,748 bytes, Ghidra's `getFunctionContaining(0x80201aec)`), i.e.

```
0x80201aec, 0x80201b3c, 0x80201be4, 0x80201c6c, 0x80201cd4, 0x80201d7c, 0x80201dc4,
0x80201e6c, 0x80201f14, 0x80201f7c, ... (24 total)
```

Its head explains the seed:

```c
*(u32 *)(unaff_r13 - 0x468c) = 0;
*(u32 *)(unaff_r13 - 0x4658) = 0;
FUN_801fcc18(0x805137d8);
FUN_80202c3c(0x805137f8);
uVar1 = FUN_8037aacc();                                  // a 4-byte value (RTC/tick-like)
FUN_8039dc9c(unaff_r13 - 18000, uVar1, 4);               // -> [r13-0x4650]
FUN_801e2bd4(0x80513904);
FUN_801e2b24(0x80513904, &local_18);
switch (local_18 % 0x18) {                               // 24 branches
default: ... uVar1 = FUN_801fc900(); ...                 // per-branch setup
```

So the picture is:

* **`FUN_802019f8` is the save-slot initialiser**: it zeroes two state words, initialises two structures
  (`0x805137d8`, `0x805137f8`), samples a 4-byte value from `FUN_8037aacc()` into `[r13-0x4650]`, reads a selector from
  `0x80513904` and **switches on `local_18 % 24`**, and each branch stores its descriptor pointer at `[r13-0x4694]`;
* **the descriptor is runtime state** (each branch builds its pointer through the card/file setup, e.g. `FUN_801fc900`),
  which is why the seed at `+0x118` could not be found in the file: it is a field of the **currently selected save slot's
  descriptor**, chosen by `local_18 % 24` at load time;
* **24 slots/contexts** is a new structural number for the save system (PSO's four characters x areas/file kinds, or the
  card's file contexts).

**What this changes for CP9's last step:** the live read becomes a two-step, both now named: read `[0x80585F6C]` (the
descriptor) and then its `+0x118` - or, equivalently, read `local_18 % 24` from `0x80513904`'s structure and the
corresponding descriptor. The offline side of CP9 is now as far as it can go without a session.

Decompile kept in `docs/research/pso-save-slot-initialiser.txt`.

## Round 94: the cipher is code now, not a research dump - and it round-trips

The round-70 note ended with "the offline side of CP9 is now as far as it can go without a session". That was true of the
*save data*, but not of the *cipher*: everything known lived in `docs/research/pso-save-cipher-full.py`, which is not
reviewable, testable code. This round promoted it to **`gbox/pso_save_cipher.py`**:

| function | the assembly fact it encodes |
|---|---|
| `ring_step(state)` | 24 x `state[k+1] -= state[k+0x20]` (k 1..24), then 31 x `state[k+1] -= state[k-0x17]` (k 25..55) |
| `seed_ring(seed)` | `state[0x38]=state[0x39]=seed`, 0x36 x `idx=(0x15 i)%0x37`, then four ring rounds, cursor 0x37 |
| `next_key(state)` | cursor++ / wrap through `ring_step` / `state[cursor+1]` |
| `rand(state, n)` | `((n & 0xffff) * (key >> 16)) >> 16` |
| `build_perm(state)` | Fisher-Yates over 0..255, returning the inverse table `B` |
| `permute` / `unpermute` | `dst[256k + B[j]] = src[256k + j]` and its inverse |
| `word_cipher(data, state)` | `buf[i] = key_i - buf[i]`, which is its own inverse |
| `decode` / `encode` | permute then word cipher, and the exact inverse order |

`tests/test_pso_save_cipher.py` **11 passed**: the ring's determinism and cursor, the keystream's reproducibility and seed
dependence, the permutation invariant (`sorted(perm) == 0..255`), `permute`/`unpermute` inversion including a trailing partial
block, the word cipher's involution, `encode -> decode` round trips for **five seeds** (0, 1, 0x12345678, 0xDEADBEEF,
0xFFFFFFFF), and a wrong seed not round-tripping.

**One correction to an assumption of mine:** `state[0x38]`/`[0x39]` hold the seed only *before* the four warm-up rounds - they
sit inside the 55-word window, so `ring_step` changes them (the first version of my test asserted otherwise and failed). The
test now asserts that the seed reaches the ring, which is the property that matters.

**What this buys the live step:** CP9's remaining step is "read the seed, decode `PSO_CHARACTER`, byte-flip accept test". The
seed read yields an integer, and `pso_save_cipher.decode(body, seed)` is now a reviewed, tested call - the live work is a
single read plus that call, not a script archaeology exercise.
