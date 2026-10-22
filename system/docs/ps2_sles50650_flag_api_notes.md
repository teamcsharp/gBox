# SLES_506.50 (RE Survivor 2 CV, PS2 EU) — flag API static notes (request #2045)

Exe sha256 cae6ae7587cee1bf17ad88e1b5b257c79adaf0e1813b22c878814b58a9135f8c.
ELF section `main`: vaddr 0x100000 <-> file offset 0x80 (vaddr = off - 0x80 + 0x100000).
Disassembled with capstone MIPS64-LE (R5900 extras like `ext`/`addu.qb` in output are mis-decodes of MMI/R5900 ops; treat as hypotheses).

## Findings (hand-disassembled, unverified against runtime)
- `sys` is a global pointer at vaddr 0x3a8140 (nm symbol `sys`); code loads it via `lui at,0x3b; lw r,-0x7ec0(at)`.
- `bhFlagSet` (0x25e460) / `bhFlagCk` (0x25e5c0): args (group a0&0xff < 12, bit a1 & 0x3ff, mode/value a2).
  Bit storage is 32-bit words, word = (bit>>5), bit within word counted from MSB (`sllv` then sign test), i.e. mask 0x80000000>>(bit&31).
  Group base = `*sys + off`; jump tables at 0x3e9d90 (Set) and 0x3e9dc0 (Ck):
  g0,g10 -> shared tail (base from reg, not resolved),
  g1 +0x14b8, g2 +0x1638, g3 +0x15b8, g4 +0x1490, g5 +0x1488, g6 +0x1498, g7 +0x1538, g8 +0x?, g9 +0x1578, g11 +0x1484.
  (g8 table entry 0x25e4fc/0x25e65c not decoded; g0/g10 tail only.)
- `GameFileSave` (0x14f2a0) serialises the struct at `sys+0x1478`; `sys+0x14ac/0x14ad/0x14ae` are bytes used as mode/slot indices (also read by `GetBonusWeapon` 0x134e20).
- Prior offsets 0x2B363C/0x2B37BC are file offsets (vaddr 0x3b35bc/0x3b373c) and not flag data: not accepted as unlock evidence.
- Constant-argument scan of bhFlagSet/Ck callers (addiu-zero immediates within 10 insns of the jal) only resolved group 8 bits 1-3 in `MapCnvStatus2Flag`; other callers pass computed args, so a decompiler is needed.
- Candidate named functions for unlock logic: `GetBonusWeapon`, `CallDGEnding`, `DispRoachEnding`, `CheckRankingDisp`, `bhFlagSet`, `bhFlagCk`, `FileFlagInit`, `FileFlagInit01`.

## Status
Unlock flag table NOT mapped; no category asserted unlocked/not_present. Next: Ghidra (language MIPS:LE:64:default) on i9-NUC/lilspark: decompile GetBonusWeapon, GameFileSave, CheckRankingDisp and xref `sys+0x1478..0x1638` writers; then emit RE2SV profile.
