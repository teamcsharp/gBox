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
