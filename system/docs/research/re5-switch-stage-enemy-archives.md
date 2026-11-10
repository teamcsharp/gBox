# RE5 Switch Mercenaries stage -> enemy archive mapping

Research for request #9074. Scope: map the eight Mercenaries stage display names to their
stage archives and per-stage enemy archives, using the local Switch RomFS
(010018100CD46000, nativeNXx64/ImgNX/Archive, 1368 .arc files) plus one verified live census.

## Method
1. Listed stage archives matching s4xx.arc in nativeNXx64/ImgNX/Archive: exactly eight
   (s400-s407.arc, plus eight s4xxSub.arc).
2. Parsed each s4xx.arc entry table with the repo's gbox.mt_arc parser (parse(bytes) -> Arc.entries,
   Entry.name/data).
3. For each archive counted: total entries, `stage\s4xx\soft\merce` script entries, and
   `pawn/em/emNN` enemy-pawn entries (the pattern campaign stages use, e.g. s100.arc embeds 14
   pawn entries for em10 and em97).
4. Searched RomFS archives for the Mercenaries-only display-name string "Public Assembly"
   (ASCII) to try to anchor a display-name -> s### mapping.
5. Cross-checked against the live Public Assembly enemy census verified 2026-11-08 on i9-NUC.

## Findings
- Exactly 8 s4xx stage archives exist, consistent with 8 Mercenaries stages:
  | stage archive | entries | soft/merce scripts | pawn/em enemy entries |
  |---|---|---|---|
  | s400.arc | 590 | 0 | 0 |
  | s401.arc | 356 | 0 | 0 |
  | s402.arc | 458 | 0 | 0 |
  | s403.arc | 450 | 0 | 0 |
  | s404.arc | 322 | 0 | 0 |
  | s405.arc | 663 | 0 | 0 |
  | s406.arc | 646 | 0 | 0 |
  | s407.arc | 506 | 0 | 0 |
  (per-stage entry counts from this run's parse; entry names use backslash separators,
  e.g. stage\s400\scr\scr01\..., effect\efl\stage\s400\auto\...)
- Campaign comparison: s100.arc embeds enemy pawn data inline (14 pawn/em entries: em10, em97).
  The Mercenaries s4xx archives do NOT embed enemy pawn data or soft/merce scripts in their
  entry tables. Enemy model data for Mercenaries stages is therefore not resolvable from the
  s4xx stage archives alone.
- Live census (Public Assembly, verified 2026-11-08, i9-NUC): uEm10 (majority), uEm11, uEm20,
  uEm21, uEm62. This is runtime-verified evidence of one stage's enemy set, but does not by
  itself identify the s### archive.

## Undetermined
- Display-name -> s### mapping for all eight stages: not determined. The RomFS string search for
  "Public Assembly" found no archive entry containing that display string (see JSON evidence);
  a Mercenaries stage-name resource would settle it.
- Per-stage enemy archives for the seven stages without a live census: not determined.
  What would settle it: (a) the display-name -> s### mapping, then (b) inspection of the
  stage\s4xx\soft\merce EmSet script bytes for enemy-set IDs (scripts live outside these
  entry tables if present at all), or (c) a live census per stage on an agent session.
- Previous local run's scan reported 3 entries named em32* inside s404.arc (asset paths, not an
  enemy pawn table). This run's per-archive count of pawn/em entries is 0 for all eight s4xx
  archives, so no per-stage enemy pawn table exists in the Mercenaries stage archives.

## Artifacts
- Machine-readable: system/docs/research/re5-switch-stage-enemy-archives.json
- Live census source: request #9074 checkpoint 2026-11-08 (uEm10, uEm11, uEm20, uEm21, uEm62).
