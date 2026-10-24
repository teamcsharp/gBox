# Mega Man 64 (USA) unlock research (request #2165)

Status: research in progress, NOT verified. Cheat-DB hypotheses only.

```json
{
 "schema": 1,
 "game_id": "7815f5fed884d651",
 "platform": "n64",
 "title": "Mega Man 64 (USA)",
 "status": "research_in_progress",
 "verified": false,
 "executable": {
  "analysis_elf": "gbox-data/analysis/re/7815f5fed884d651/Mega_Man_64_USA_.zip.elf",
  "sha256": "e0acd9d1bd95371ed488cb5b7c834d1e645877da5bdab68a978e3b8e86916cdc",
  "base_address": "0x80025C00",
  "processor": "MIPS:BE:32:default",
  "analysis_job": "d95499f3fbb74cc0",
  "ghidra_open_job": "9ea238261f024b07"
 },
 "evidence_class": "community_cheat_hypothesis (libretro-database 'Mega Man 64 (USA).cht'); NOT yet confirmed by Ghidra xrefs or runtime",
 "hypotheses": [
  {"name": "all_special_items", "writes": [["0x8120564C", "0xFFFF"], ["0x8120564E", "0xFFFF"]], "category": "items"},
  {"name": "all_special_weapons", "writes": [["0x81205640", "0xFFFF"]], "category": "items"},
  {"name": "all_normal_items", "writes": [["0x81205650", "0xFFFF"], ["0x81205652", "0xFFFF"], ["0x81205654", "0xFFFF"], ["0x81205656", "0xFFFF"]], "category": "items"},
  {"name": "event_based_special_items_cleared", "writes": [["0x800BE41C", "0x00F7"], ["0x800BE41E", "0x00FF"]], "category": "items", "note": "cheat name 'None Event Based Special Items'; semantics unclear"},
  {"name": "enable_hard_and_easy_modes", "writes": [["0x801BC400", "0x0001"], ["0x801BC402", "0x0001"]], "category": "modes"}
 ],
 "inventory": {
  "characters": "unknown", "hidden_characters": "unknown", "modes": "hypothesis: Hard and Easy flags at 0x801BC400/2",
  "levels": "unknown", "stages": "unknown", "costumes": "not_present (unconfirmed)", "items": "hypothesis: bitfields at 0x81205640-0x81205656",
  "extras": "unknown"
 },
 "next_step": "Complete Ghidra open job 9ea238261f024b07, xref 0x801BC400 and 0x80205640-0x80205657 writers/readers, confirm lock checks and save flags, then runtime-test on i9-NUC with isolated save."
}
```
