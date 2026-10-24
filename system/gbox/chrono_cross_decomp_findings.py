"""Decompile findings for Chrono Cross (USA) Disc 1 boot EXE SLUS_010.41.

Evidence only; no unlock is claimed and profile_for stays research_pending.
Generated from Ghidra 12.1.4 headless decompile of the ELF-wrapped EXE (1240 functions).
"""

FINDINGS = {
 "schema": 1,
 "source_exe_sha256": "9a5453bf09d7f5c71a6451d255471374fb2d7cc5f3dfb1ea51223a5c88cdda47",
 "decomp_jsonl_sha256": "aa5a234fb2e085c7121d466af12a5f43ec50d2c1ae961ddc3426bf11ce103029",
 "functions_decompiled": 1240,
 "table_region_referrers": {
  "file_table_0x80057840": {
   "FUN_80019794": [
    "DATA"
   ],
   "FUN_8002f53c": [
    "READ"
   ]
  },
  "cd_driver_state_0x8006af0c_0x8006af70": {
   "FUN_80039038": [
    "PARAM"
   ],
   "FUN_800395d4": [
    "PARAM"
   ],
   "FUN_8002ceb4": [
    "READ",
    "WRITE"
   ],
   "FUN_8002b400": [
    "WRITE"
   ],
   "FUN_8002b434": [
    "READ",
    "WRITE"
   ],
   "FUN_8002b4c8": [
    "READ",
    "WRITE"
   ],
   "FUN_8003e444": [
    "READ",
    "WRITE"
   ],
   "FUN_8002b34c": [
    "READ",
    "WRITE"
   ],
   "FUN_8002b41c": [
    "READ",
    "WRITE"
   ],
   "FUN_8002b6c0": [
    "READ"
   ],
   "FUN_8002b8c0": [
    "PARAM"
   ],
   "FUN_8002b5c0": [
    "PARAM"
   ],
   "FUN_8002c130": [
    "READ",
    "WRITE"
   ],
   "FUN_8002bc90": [
    "READ",
    "WRITE"
   ],
   "FUN_8002be30": [
    "WRITE"
   ],
   "FUN_8002bfc4": [
    "READ",
    "WRITE"
   ],
   "FUN_8002bc6c": [
    "WRITE"
   ],
   "FUN_8002e660": [
    "WRITE"
   ],
   "FUN_8002ccc0": [
    "READ",
    "WRITE"
   ],
   "FUN_8002cd14": [
    "READ"
   ],
   "FUN_8002f53c": [
    "DATA"
   ],
   "None": [
    "DATA"
   ]
  },
  "cd_driver_state_0x8006b1e8_0x8006b204": {
   "FUN_800301cc": [
    "READ"
   ],
   "FUN_800307cc": [
    "WRITE"
   ],
   "FUN_80030680": [
    "WRITE"
   ],
   "FUN_800308a4": [
    "WRITE"
   ],
   "FUN_80030934": [
    "READ"
   ],
   "FUN_800309d0": [
    "READ"
   ],
   "FUN_8003099c": [
    "READ"
   ],
   "FUN_80030968": [
    "READ"
   ]
  }
 },
 "findings": [
  "All 92 code references into the file-number/LBA table regions come from 32 referrer sites (30 named functions) that are CD-driver/loader state (0x8006af0c..0x8006af70 and 0x8006b1e8..0x8006b204) plus one file-table reader FUN_80019794 -> 0x80057840. No game-logic flag is addressed there.",
  "The boot EXE contains no memory-card routines (no BASLUS/card strings; no A0/B0/C0 card BIOS calls in decompiled code) and no character roster/recruitment strings.",
  "Boot EXE references overlay programs (c:/work/cdrom/prog/title.prg, debug.prg) and cdrom.mde/.fid/.fnd index files: game logic, menus, recruitment and save handling live in overlays loaded via the file-number tables, not in SLUS_010.41.",
  "Therefore lock/progress flags are NOT locatable from the boot EXE alone; next analysis target is the overlay set (resolve file numbers via table 0x8005783c to LBAs on disc1.bin, wrap each PS-X overlay, Ghidra, search save-block writes).",
  "No unlock claimed; profile_for stays research_pending."
 ],
 "next_step": "Extract overlays from disc1.bin using the 0x8005783c table, run run_decomp on each, search for memory-card BIOS calls (B0:0x4B/0x4E..) and the savegame struct; then runtime-verify on idle worker."
}
