# RE2 GameCube state engineering

This is exact-build static evidence and a read-only snapshot reader. It does not
enable unlock-on-load, edit saves, write live inventory, or mark either parent
request complete. The requested all-unlocked startup and sidebar inventory/equip
controls remain the acceptance target.

## Identity and evidence

Catalog game `c6adbfa00c20aaf9`, disc `GHAE08`:

| Owned member | Bytes | SHA-256 |
| --- | ---: | --- |
| main.dol | 800672 | `71401bd622ab5a09e40d5cd6feb07f3725d7a24356fb0cf133e3991c941e2a05` |
| leon.rel | 2330660 | `84bc991038949d0452a5ac7999f67e761323f8ba30bca333163cb2ba345808e8` |
| claire.rel | 2330228 | `58de2056e8b625575617cb2220829a7d4998bf642f99aec67e6be42c6954e437` |

`gbox.re2gc_state.Build` requires these source hashes before interpreting state.
The owned GCZ is directly readable through `GCDisc`; another port's addresses,
an extracted PSX/N64 executable, or RE2 Remake cannot substitute for this build.

On Spark, source evidence is in
`~/gbox-pr-audit-20261017/re-export-evidence/`. The reusable Ghidra project is
`~/gbox-pr-audit-20261017/re2gc-unlock-analysis/re2gc.gpr`. The `*-v2.elf`
programs import with PowerPC:BE:32:default and completed analysis successfully.
`state-functions.c`, `progress-functions.c`, `claire-state-functions.c`,
`flag-encoding.c`, and the `*-refs*.json` files contain the local owned-code
decompilation/xref evidence. Proprietary source bytes and recovered C are not
committed to the repository.

The analysis image maps the REL at **synthetic** base `0x80400000`. Its BSS is
also synthetic. Never copy its BSS addresses into an emulator profile.
Main startup at `0x80005444` establishes r2=`0x803ac6e0` and r13=`0x803abd00`.

## Dynamic allocation matters

Main function `0x80046d98` opens `leon.rel` or `claire.rel`, allocates its image,
stores the image pointer at `0x8015fcfc`, separately allocates BSS, and calls
OSLink at `0x8005df64`. OSLink converts header `+0x10` into the absolute section
table pointer and fills the zero-offset BSS section with the separate allocation.
Both modules have 16 section records and BSS size `0xd7f90`.

The reader obtains the module and BSS pointers from those captured structures.
It verifies module identity, section sizes/locations, allocation bounds, absence
of overlap with main state, and every executable DOL/REL byte. REL code is
independently relocated at the captured image and BSS addresses for comparison.
It also requires membership in OSLink's live module list at `0x800030c8`/`cc`,
so a cached pointer left behind after OSUnlink cannot validate freed old state.

The only accepted code differences are the exact audio NOP sites documented in
[Dolphin GHAE08.ini at 38d619b](https://github.com/dolphin-emu/dolphin/blob/38d619b07691231f54e6f037fcf30a3b64fdd5a5/Data/Sys/GameSettings/GHAE08.ini):
main `0x800339e4`, Leon **REL offset** `0x1903fc`, and Claire REL offset `0x190294`.
The latter two were rederived from the owned audio routines and their branch
targets (`memset` at `0x80003100`). Dolphin's absolute REL patch addresses are
not file offsets. Tests check the original branch targets and reject a nearby
unrelated code change.

## Native inventory and equipment layout

| Location | Proven use |
| --- | --- |
| `0x801688dc`, u8 | Active ordinary inventory capacity; initialized to 8, expanded to 10 |
| `0x80168c6c`, 11 records × 4 bytes | 10 ordinary records plus reserved lighter/lockpick record |
| `0x80168c98`, 64 records × 4 bytes | Item-box records |
| Record +0 / +1 / +2 / +3 | Item ID / quantity / size marker / untouched unknown byte |
| REL BSS +`0x13534`, u8 | Current equipped inventory slot; `0x80` means unequipped |
| REL BSS +`0x13536`, u8 | Current equipped item ID |
| `0x801688ec` / `0x801688ed`, u8 | Saved item ID / saved slot restored on load |
| `0x80163f36`, u16 BE | Loaded weapon word; inventory-close code preserves upper `0xf000` |
| `0x80168c5c`, 8 bytes | Persistent save-state clear flags; full eligibility mapping pending |

At synthetic base `0x80400000`, Leon initialization is `0x80472a98` and Claire
initialization is `0x80472830`. Both copy 11 three-byte default records into
four-byte native slots, clear 64 item-box records, and set capacity 8. The fourth
byte is not initialized by these loops and must be preserved by a future writer.

Two-slot weapons use markers 1 and 2 for the adjacent inventory halves; counts
are synchronized by the reload path. Item-box representation can use marker 3.
The 19 weapon IDs are below `0x14`; other items have separate native Use logic.
Do not infer that every item can use a weapon equip path or that all 19 weapon
assets exist for every character.

Leon `0x80477058` / Claire `0x80476da0` toggle selected weapon slot/item state.
That alone does not load the weapon. Inventory close (Leon `0x804741e8`, Claire
`0x80473fc0`) updates the loaded weapon word and calls native reload functions.
Directly poking just the selected slot/item would leave the model/animation state
inconsistent. The future sidebar backend must reproduce the native transition
and prove weapon/character PLW availability and animation compatibility.

The snapshot reader returns current and saved equipment separately and marks
equipment coherence explicitly. A snapshot of a transition may be incoherent;
it is never silently converted into a plausible inventory.

## Unlock findings and remaining proof

REL BSS +`0x1e724` is an **ending result/notification word**, not a persistent
all-unlocks field. Leon `0x80499764` initializes it to `0x2000`, copies a `0x598`
byte save-state block into ending work memory, then calls `0x8049d128` to compute
results. New-game routine `0x8049db74` consumes some result bits to add unlocked
weapons to the item box. Setting every bit here is not an unlock implementation.

The native bit setter/checker at Leon `0x80465b4c` / `0x80465b94` operates on
big-endian 32-bit words using `0x80000000 >> (index & 31)`, not `1 << index`.
The ending routine checks/sets clear-flag indices `0x13`, `0x14`, and `0x15` in
the save-state copy. Their masks in the first word are `0x1000`, `0x0800`, and
`0x0400`. Menu eligibility, persistence/checksum handling, and complete names of
the categories gated by those bits remain to be traced. Do not label them as a
verified HUNK/Tofu/Extreme Battle profile from ending conditions alone.

Next acceptance work:

1. Trace save serialization/checksums and title/menu eligibility for all scenarios,
   HUNK, Tofu, Extreme Battle levels and characters, costumes, weapons, items,
   and extras. Record absent categories explicitly rather than guessing.
2. Create an isolated monotonic unlock save overlay; preserve the operator's
   saves/settings. Prove clean boot, menu selection/play, second launch and rollback.
3. Capture native-byte-order MEM1 snapshots from an idle authorized test worker
   in stable gameplay/inventory states, independently compare both scenario
   readers against the native UI, and retain the capture identity.
4. Implement guarded native inventory/equip transitions and complete per-character
   weapon resources; then wire the sidebar. No live write route is registered here.
5. Validate the final Sonic/Mario cast build with the same unlock and inventory
   workflow. Static/synthetic checks cannot close requests #2037 or #2339.

## Reproduction

```sh
python -m gbox.re2gc_state --dol main.dol --rel leon.rel --analysis-elf NEW_leon.elf
JAVA_HOME=/usr/lib/jvm/java-21-openjdk-arm64 \
  /home/ehm_eckx/reverse/ghidra_12.1.4_PUBLIC/support/analyzeHeadless \
  NEW_PROJECT_DIR re2gc -import NEW_leon.elf -processor PowerPC:BE:32:default
python -m gbox.re2gc_state --dol main.dol --rel leon.rel \
  --snapshot ISOLATED_CAPTURE.mem1 --out NEW_state.json
GBOX_RE2GC_EVIDENCE=/path/to/exact/owned/files python -m pytest -q tests/test_re2gc_state.py
```

Both CLI output modes create new files exclusively. The ELF is an analysis
artifact: paired-single operations are reduced to support integer data-flow
analysis and it must not be launched. Its BSS layout splits the overlapping DOL
BSS envelope around initialized sections and uses file offset zero for zero-fill
segments; the older generic conversion produced importer failures for this title.
REL image/BSS addresses must be 32-byte-aligned 32-bit addresses wholly within
MEM1, without overlaps with each other or main state. ELF file offsets preserve
each segment's virtual-address alignment. Invalid placements are rejected before
relocation. CLI inputs use bounded reads of the largest exact supported size
plus one sentinel byte, including snapshots; no preceding file stat is trusted
to prevent growth during the read.

Tests use the owned sources plus **synthetic** RAM fixtures with two different
BSS allocations. They verify relocation, source-code attestation, inventory
decoding, corruption rejection, audio exceptions and exclusive output. These are
not live gameplay or unlock acceptance tests.
