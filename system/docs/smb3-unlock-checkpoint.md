# SMB3 unlock-on-load - milestone checkpoint (request #2256)

- Date: 2026-10-21. Request 7f1ef02a7e6f4b26 (#2256), parent 600ead0e94d14d28.
- game_id=213e4208929ec3e9, platform=nes. Status: in_progress - not runtime-verified.
- This run made no side effects: no ROM, save, SRAM, settings or session was written,
  patched or deleted, no game was launched, the operator PC (JAYBUILTFINALE) was not touched.

## 1. Resolved owned executable (authoritative)

Source: this request's own task cache
`/home/ehm_eckx/gBox_alt/gbox-cache/213e4208929ec3e9/source.zip` -> member
`Super Mario Bros. 3 (USA).nes`

- size 393232 B
- sha256 `6ea0777ca520ba7ad7b0ea0f6452140d59aa0b1dffe5045cb1e8020dde10c267`
- md5 `bb5c4b6d4d78c101f94bdb360af502f3`
- iNES header `4e45531a 10 10 40 00 00 00 00 00 00 00 00 00 00 00 00`
  - PRG 16 x 16 KiB = 256 KiB (32 x 8 KiB banks), CHR 16 x 8 KiB = 128 KiB
  - flags6 0x40 -> battery bit set, vertical mirroring; flags7 0x00 -> mapper 4 (MMC3)
  - byte 8 (PRG-RAM size) = 0x00 -> no PRG-RAM declared; byte 9 = 0x00 -> iNES, not NES2

Consequence: the file carries a battery flag but declares zero PRG-RAM, so an emulator
will not allocate or persist the MMC3 SRAM save. A save-file edit cannot survive a
reload; the unlock must be written at load time (the "unlock on load" scope) into RAM,
idempotently, with rollback.

## 2. Owned build vs stock SMB3 (read-only diff)

Compared the owned PRG against the shared library's
`Super Mario Bros. 3 (USA) (Rev 1).zip` (md5 `e883e0d43448d9fdd8ce626f75fe4e5d`):

| bank | CPU window | differing bytes |
|---|---|---|
| 25 | $2000 | 951 |
| 31 | $E000 | 519 |
| 22 | $C000 | 36 |
| 30 | $C000 | 24 |
| 24 | $0000 | 17 |
| all others | - | 1-9 |

- The owned build is a modified SMB3 whose patch concentrates in banks 25 and 31 - the
  usual location for a trainer/cheat or unlock patch - not a plain ROM.
- The prior cached note calling the owned file "Rev 0 / PRG0" does not match this byte
  pattern against Rev 1. Revision identity must be keyed on the sha256 above, never on
  a human label.
- The other library files ("Mario Family 10-in-1.zip", "Super Mario Bros (JU) (PRG 0).zip")
  are different games and sizes; they are not a baseline.

## 3. Reusable analysis artifacts

- `gbox-cache/213e4208929ec3e9/disasm/smb3.asm` - the nesasm SMB3 US PRG1 disassembly.
  It documents `MMC3_SRAM_EN = $A001` (bit 7 enables $6000-$7FFF), $6000-$67FF tile-grid
  memory and the $6800+ Vs-mode block. It is a stock disassembly, so offsets inside the
  owned patch banks must be confirmed against the owned binary in REA/Ghidra before any
  write is attempted.
- Existing registration point (untouched this run): `gbox/game_unlocks.py` ->
  `profile_for()` / `pre_launch()`, and `docs/unlock-on-load.md`.

## 4. Blockers

- REA 6's bundled Ghidra rejects this host (Linux ARM, per the 2026-10-16 handoff), so
  the REA/Ghidra session must be opened on an x64 worker (i9-NUC) and pinned with
  `require_worker` to the worker that returns the session. Do not hand Linux `/home`
  paths to the Windows Ghidra worker (prior 3500 s hang).
- No REA/Ghidra open of the owned binary and no live acceptance run happened in this
  run: the budget went to resolving the executable, the revision diff and the RAM/save
  implications. The prior handoff stands otherwise (Spark standalone ghidra_bridge is
  installed; exact-revision implementation and runtime acceptance still outstanding).

## 5. Exact next step for the next local run

1. `job_rea_open_binary` / `job_rea_binary_session` on the owned file
   (sha256 `6ea0777c...`, pin the x64 worker), then `job_rea_xrefs` /
   `job_rea_read_function_instructions` on the bank-25 / bank-31 patch to identify the
   lock check and the progress/save RAM writer, and `job_rea_search_strings` for
   character/mode names to build the category inventory (characters, hidden_characters,
   modes, levels, stages, costumes, items, extras) with per-entry evidence
   (unlocked / not_present / unknown).
2. Implement the revision-guarded profile in `gbox/game_unlocks.py` (guard = sha256 +
   md5 + iNES header bytes + PRG-RAM size): an idempotent monotonic RAM write plan
   applied by `pre_launch`, plus a session-start hook only if the game must first load
   its native save; keep original bytes for rollback, use an isolated save overlay, and
   report pending/unsupported/failed honestly.
3. Runtime acceptance on i9-NUC or the Spark while idle at 2% audio, isolated save copy:
   fresh boot, actually select and play each inventoried character and mode, then a
   second launch and a rollback test.
4. `publish_task_changes` with the implementation, focused tests and the evidence bundle.

## 6. Evidence table

| artifact | hash |
|---|---|
| owned executable | sha256 `6ea0777ca520ba7ad7b0ea0f6452140d59aa0b1dffe5045cb1e8020dde10c267` |
| stock Rev 1 baseline (read-only reference) | md5 `e883e0d43448d9fdd8ce626f75fe4e5d` |
