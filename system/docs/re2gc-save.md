# RE2 GameCube save integrity and award records

`gbox.re2gc_save` inspects explicit copied one-block GCI files for the owned US
GameCube revision GHAE08. It requires the exact DOL and one exact scenario REL
through `re2gc_state.Build`. It creates, patches, imports and activates no saves.
A matching checksum and recognized load route do not prove playable state.

```sh
python -m gbox.re2gc_save --dol /evidence/re2gc-main.dol \
  --rel /evidence/leon.rel /copied-saves/example.gci
```

The CLI reads each fixed supported size plus one sentinel byte and emits JSON
to stdout. It scans no card directories and attaches to no running emulator.
Hermes/Spark engineering prompts expose this command and its limitations via
`native_engineering.prompt`. Tests use synthetic save envelopes; these are not
claimed to be native gameplay saves.

## Source and integrity evidence

- Game `c6adbfa00c20aaf9`, disc `GHAE08`.
- DOL SHA-256 `71401bd622ab5a09e40d5cd6feb07f3725d7a24356fb0cf133e3991c941e2a05`.
- Leon REL SHA-256 `84bc991038949d0452a5ac7999f67e761323f8ba30bca333163cb2ba345808e8`.
- Claire REL SHA-256 `58de2056e8b625575617cb2220829a7d4998bf642f99aec67e6be42c6954e437`.

REL offsets below are **file-relative**. Analysis used the corrected synthetic
ELF at base `0x80400000`, separate BSS, and read-only Ghidra 12.1.4. These are not
runtime addresses or a memory-write profile.

| Evidence | Leon REL offset | Claire REL offset |
| --- | --- | --- |
| Card state machine | `0x9fe68` | `0x9fbb0` |
| Directory preview/checksum | `0x9f7b0` | `0x9f4f8` |
| Card block-size check | `0x17ba80` | `0x17b858` |
| Checksum routine, 80 bytes | `0x17ded0` | `0x17dca8` |
| Ending award evaluation | `0x9d128` | `0x9ce70` |

Both card state machines copy exactly `0x798` bytes from file+`0x1600` to
RAM `0x801686d4` after checksum success; the write path copies the same extent
back. Both reject a native card block size other than `0x2000`. The checksum
sums unsigned bytes over the first `0x1ffc` bytes and occupies the final four
bytes in big-endian order. It covers icons, payload and padding, excluding the
separate GCI directory header. No game-specific encryption or other checksum
occurs in these traced paths. This does not validate the raw card filesystem or
prove state consistency or authenticity.

Both checksum routines have SHA-256
`f217caf774e2a594e5f1b2ef7336130e943cdf41e4e0cda6bface7f56399610d`.
`adapters/ghidra/RE2GCSaveChecksum.java` independently executes their owned PPC
instructions in Ghidra, verifies return value/stack restoration and bounds each
vector to 100000 instructions. Reproduce against an existing read-only analysis
project:

```sh
JAVA_HOME=/usr/lib/jvm/java-21-openjdk-arm64 analyzeHeadless /analysis re2gc \
  -process re2gc-leon-analysis-v2.elf -noanalysis -readOnly \
  -scriptPath system/adapters/ghidra -postScript RE2GCSaveChecksum.java \
  /evidence/leon-checksum.json 8057ded0 \
  f217caf774e2a594e5f1b2ef7336130e943cdf41e4e0cda6bface7f56399610d
```

For Claire use her analysis program and entry `8057dca8`. Twelve vectors per
scenario cover lengths 0, 1, 255 and 8188 with zeros, 255s and a deterministic
pattern. The maximum-length all-255 vector returns 2087940; the pattern returns
1043854. This is offline instruction execution, not Dolphin gameplay. Receipts
are under `re-export-evidence/re2gc-save-proof/`. Original owned files remain
unchanged; no proprietary binary/decompiled source is committed.

## Layout and interpretation

[Dolphin's directory definition](https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/Core/HW/GCMemcard/GCMemcard.h)
and [GCI reader](https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/Core/HW/GCMemcard/GCMemcardUtils.cpp)
confirm a 64-byte directory entry followed by the declared 8192-byte blocks.
The inspector requires game/maker bytes `GHAE08`, one block, and the native
filename families `RESIDENTEVIL2 -00`..`-14` or `RESIDENTEVIL2A-00`..`-14`.
Leon REL+`0x9fcac` constructs these names. Padding after the NUL is ignored.

Offsets below exclude the 64-byte GCI header:

| Field | Card-file offset | Owned-code meaning |
| --- | --- | --- |
| Native payload | `0x1600`, length `0x798` | Copy to/from RAM `0x801686d4` |
| Working save | `0x1800`, length `0x598` | RAM `0x801688d4` |
| Saved character | `0x180a`, byte | Native load routing |
| Saved system flags | `0x1814`, big-endian u32 | Bit `0x4000` routes to Extreme Battle |
| Clear bank | `0x1b88`, two big-endian u32s | MSB-first progression records |
| Progression counter | `0x1cde`, byte | Next-scenario carry/increment |
| Checksum | `0x1ffc`, big-endian u32 | Byte sum of preceding 8188 bytes |

The loader tests character `0x0c` (HUNK) or `0x0d` (Tofu) first, then system flag
`0x4000` (Extreme Battle), otherwise ordinary loading. The inspector preserves
that priority even for contradictory synthetic fields. It reports a dispatch
route, without claiming coherent room, scenario, resources or inventory.

## Award records are insufficient

Native flag index `0x13` uses mask `0x1000`, index `0x14` uses `0x800`, and index
`0x15` uses `0x400` in the first clear word. Ending evaluation records them and
sets transient result bits `0x100`, `0x200` and `0x10000` respectively. Leon's
ending dispatcher REL+`0x9a1fc` then prepares **separate playable saves**:

- HUNK: mode bit 8, character `0x0c`, then the native save UI.
- Tofu: mode bits 9, character `0x0d`, then the native save UI.
- Extreme Battle: system flag `0x4000`, title mode `0x1000000`, then save UI.

Preparation at REL+`0x9db74` loads `common/datu/init_tbl.dat`, initializes room,
position, health and inventory, and constructs that mode's state. The loader
selects modes from the saved state, not the three award records. Already-set
award records suppress newly-earned result bits. Blindly setting them can
suppress a reward-save prompt without creating its playable save. Therefore
`award_records` must never be labeled `unlocked`. No writer is exposed here.

## Remaining acceptance

No actual GHAE08 GCI has been accepted in native gameplay by this work. Before
unlock-on-load or a writer is enabled, derive/verify complete mode preparation,
then use the reviewed i9-only private-card test session to create and load each
mode, verify native inventory/equipment, save/reload on a second launch, and
verify restoration of copied cards. Preserve original saves and use no shared
or cloud card context. Extreme Battle characters/levels, all items/weapons and
other unlocks need separate evidence. Parent request 2037 remains open; completed
read-only inventory child 2323 is prior evidence.
