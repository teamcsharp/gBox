# Bloody Roar II (USA) unlock research evidence (request #2063)

Status: static identity milestone only; no unlock routine, no runtime proof.

```json
{
 "request": "9177f0cf10bb4bcc",
 "number": 2063,
 "game_id": "27223b425ab0eea6",
 "platform": "psx",
 "title": "Bloody Roar II (USA)",
 "source_chd": "Sony PlayStation/roms/Bloody Roar II (USA).chd",
 "chd_sha256": "843db353f51a9ec9cdc2c3e3eb340da5d694082fe26ab28f720ddb9775e6f64b",
 "chd_data_sha1": "990115eb22e748d2b9fdab103c76377195501bbb",
 "extraction": "chdman 0.264 extractcd -> br2.bin (scratch)",
 "bin_sha256": "fbad8aef53b160abfcebddced9f9d69dcf39df00d8853b4c11f231b37220fc57",
 "bin_size": 552729408,
 "disc_id": "SCUS_94424",
 "boot_exe": "SCUS_944.24",
 "exe_size": 659456,
 "exe_sha256": "0685d1262c1467d20f5eb38545abfc6fa2c1b5dec1d2964416a00e420138cdd5",
 "exe_header": {
  "t_addr": "0x8011e800",
  "t_size": 657408,
  "entry": "0x80126174"
 },
 "iso_file_count": 292,
 "character_dirs_3letter": [
  "ALI",
  "BAK",
  "BUS",
  "GAD",
  "JEN",
  "LON",
  "MAR",
  "RON",
  "ULI",
  "YUG",
  "ASC"
 ],
 "stage_dirs": [
  "ST0",
  "ST1",
  "ST2",
  "ST3",
  "ST4",
  "ST5",
  "ST6",
  "ST7",
  "ST8",
  "ST9",
  "STA",
  "STB",
  "STC",
  "STU",
  "STY"
 ],
 "exe_mode_strings": [
  "STORY",
  "ARCADE",
  "VERSUS",
  "SURVIVAL",
  "OPTIONS",
  "MEMORY CARD",
  "SPECIAL STAGE",
  "FINAL STAGE",
  "AFTERIMAGE MODE",
  "MODEL TYPE",
  "BEAST",
  "SURVIVAL RANKING",
  "ARCADE RANKING",
  "ARCADE VS RANKING"
 ],
 "categories": {
  "characters": "unknown",
  "hidden_characters": "unknown",
  "modes": "unknown",
  "levels": "unknown",
  "stages": "unknown",
  "costumes": "unknown",
  "items": "unknown",
  "extras": "unknown"
 },
 "note": "Static identity only. Directory names are not verified as roster; no lock flag/save routine traced yet. No unlock profile registered.",
 "next": "Load SCUS_944.24 (PS-X EXE, load 0x8011e800) into x64 Ghidra with MIPS:LE:32:default; xref 'CHARACTER SELECT'/'SURVIVAL'/memory-card strings to find unlock bitfield, then implement guarded save-overlay unlock."
}
```
