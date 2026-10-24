# PS2 SLES_506.50 symbol evidence (request #2045)

- sha256: `cae6ae7587cee1bf17ad88e1b5b257c79adaf0e1813b22c878814b58a9135f8c` (matches the cached boot exe)
- ELF32 MIPS; sections include .strtab, .symtab, .debug, .line
- `.symtab` entries: 11715 (11714 named, 5955 STT_FUNC). The "11,715 symbols" claim is verified (it is the raw entry count).
- `.debug` and `.line` sections exist; no DWARF parse was done, so the "full DWARF" claim is unverified.

## Prior unlock offsets 0x2B363C / 0x2B37BC
- Read as VAs they land in `bhDemoStageParaInit+0x4c` and `bhEvFlagClear+0xc` (code), so they are not flag data.
- Read as file offsets, the load segment maps them to VA 0x3b35bc / 0x3b373c, which is data. Both hold `00 00 00 ff` words. `nm` has no sized symbol there (the nearest function lookup is meaningless in data).
- Unlock flag table: NOT yet mapped.

## Save/flag symbols found (VA)
Save I/O: GameFileSave 0x14f2a0, GameFileSaveWait 0x14f050, MemoryCardFileWrite 0x2daf90, WriteMemoryCard 0x2dbed0, MemoryCardGetSum 0x2db970.
Flags: bhFlagSet 0x25e460, bhFlagCk 0x25e5c0, FileFlagInit 0x27fd90, FileFlagInit01 0x27fdf0, FlagErase 0x2935b0, bhEvFlagClear 0x2b37b0.

Full machine-readable data: `ps2_sles50650_symbol_evidence.json`.

## Next step
Disassemble or decompile GameFileSave, MemoryCardGetSum and bhFlagSet/bhFlagCk with the symbol names. The decompile must run in Ghidra on i9-NUC or lilspark with a PS2 EE (MIPS:LE:64) language id and the exe extracted first. Then find the flag array base and map the unlock bits.
