# PSO:GC (GPOE8P, USA) container formats — #9183 research deliverable

Scope: PRS, GSL, AFS, BML — layouts, round-trip capability in this repo,
encryption status, and what is still missing for full acceptance.
Disk catalog: 436e0bb84d5337d1 (GPOE8P USA).

## 1. Where the containers live on the disc (verified structure)

- Top-level disc files: `.prs`, `.bml`, `.gsl` (plus `.tgc` etc.).
- `.gsl` archives embed `.bml` packs (enemy packs, e.g. inside
  `gsl_forest01.gsl` / `gsl_forest02.gsl` per prior-sessions inventory) and
  other files; embedded files are accessed via `pso_gc.gsl_files()`.
- Player banks: `pl?TEX.AFS` (GVR) hold per-player texture banks
  (plA/plB/…/plF), read with `pso_gc.afs()`, parsed GVR headers via
  `pso_gc.gvr_header()`.
- Character data packs: `pl?ANJ.BML` / `PLANJ.BML` (and `pl?NJ.BML`) hold
  per-player geometry/animation entry streams.

## 2. Byte-level layouts (from `system/gbox/pso_gc.py`, `pso_player.py`,
`formats/lz.py`; confirmed by code read this run)

### PRS (Sega PRS compressed stream)
- Used as the per-entry payload encoding inside BML packs, and as standalone
  top-level `.prs` files.
- Header: magic `PRS`, u32 LE raw size, u32 compressed size, stream follows
  (see `formats.lz.prs_decompress`).
- Not encrypted — a classic LZ (copy/literal) compressor.
- Round-trip in repo: `prs_decompress` + `prs_compress`
  (`gbox/formats/lz.py`); `pso_gc.bml_entry()` cross-checks against
  `ninja.prs_decompress` (the swap pipeline treats them as equivalent).

### GSL (archive)
- Entry records at stride `0x30`: name[0x20] (zero-padded), u32 BE
  0x800-sector offset, u32 BE size, 8 spare bytes (see `gsl_entries()`).
- Archive = table + 0x800-aligned body; `gsl_build(data, repl)` rebuilds
  the table + body, preserving entry bytes for unchanged entries (identity
  rebuild is supported via empty `repl`).

### BML (pack)
- Big-endian header; per-entry `>II` (compressed size, raw size) + name,
  PRS-encoded payload (see `pso_player.bml_files`, wrapped by
  `pso_gc.bml_files`).
- `bml_build(bml, repl)` rebuilds header + entries, replacing only named
  entries; unchanged entries keep original PRS bytes.
- Embedded BMLs inside `.gsl` follow the same format (verified by
  `gsl_files()` returning byte strings parsed by `bml_files()`).

### AFS (texture bank)
- Header: first 4 bytes bank tag, u32 LE entry count at offset 4, then
  per-entry pairs (u32 LE offset, u32 LE size) at offset 8, 0x800-aligned
  entry bodies (see `pso_gc.afs`).
- Entries are GVR texture entries: magic `GVR`, u32 flags, u32 fmt, u16 w,
  u16 h, u16 pal_fmt, then data (see `gvr_header()`).
- `pso_gc_swap.afs_build(bank, entries)` rebuilds the bank with the same
  0x800-aligned layout; the verified face-swap pipeline (prior sessions,
  see `1ddb0cca7e4a4f3c` task docs `pso-face-native-validation.json`,
  `pso-native-photo-faces-validation.json`) used GVR encode/decode
  (`gvr_encode`/`gvr_decode`) + `afs_build` for `pl?TEX.AFS` replacement.

## 3. Encryption status

- No per-file encryption evident in any of the four containers: PRS is
  plain compression; GSL/BML/AFS tables are plaintext (BE for GSL/BML
  headers, LE for AFS tables on this disc).
- The `.gcz` wrapper around the disc image is a compression container
  (read path `gbox/gcz.py` exercised this run), not encryption.
- Open item to confirm by measurement: none of the sampled streams showed
  encryption signatures, but a final on-disk pass should record the raw
  bytes' first 16 hex per sampled file as evidence.

## 4. What this repo can already write back

| Container | Read | Rebuild/replace | Entry encode |
|-----------|------|-----------------|--------------|
| PRS       | `formats.lz.prs_decompress`, `ninja.prs_decompress` | — | `formats.lz.prs_compress` |
| GSL       | `gsl_entries`, `gsl_files` | `gsl_build(data, repl)` (identity + replacement) | bytes pass-through |
| BML       | `bml_files`, `bml_entry` | `bml_build(bml, repl)` | PRS payload pass-through or re-encode |
| AFS       | `afs`, `gvr_header` | `pso_gc_swap.afs_build(bank, entries)` | `gvr_encode`/`gvr_decode`, `gsr_encode`/`gsr_decode` |

This is the exact write path the verified face-swap pipeline used, so the
container-level write-back capability is already proven at the GVR/AFS
level; the missing proof is a full-disk measurement pass (below).

## 5. Acceptance gap — on-disk measurements (NEXT STEP, not yet done)

Requirement: 5+ real files per format with sha256 of original vs rebuilt
bytes and round-trip identity, via repo code.

Status this run:
- Measurement probe prepared: `/tmp/probe9183b.py` (per-format sampling,
  sha256 original/rebuilt, identity check, header dumps).
- Blocker found: the GPOE8P disc is NOT in `gbox-cache/gc/` — the 5 discs
  there are 007 AU, NARUTO2, Zelda Collector's, Metroid Prime,
  SC:PT (titles read this run; saved to `evidence/9183-disk.json`).
- Next: locate the owned GPOE8P `.gcz` (check HyperSpin roms dirs and the
  prior task `1ddb0cca7e4a4f3c` profile `profiles/pso-gc-plus-us.json` for
  the rom path), then run the probe and append the measured hashes to
  `evidence/9183-measurements.json`.

No pending remote jobs were started this run; no job IDs outstanding.
