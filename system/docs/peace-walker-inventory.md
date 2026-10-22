# Metal Gear Solid: Peace Walker – owned-build inventory (request #2500)

Source: `Metal Gear Solid - Peace Walker (USA).cso`, SHA-256 `26430f5ad29d989e005e75bc9b34b03e4830b4b25666978891029f58085b3a28`
Container: CISO v1, block 2048, align 0, uncompressed 1,532,938,240 bytes. ISO9660 offset base 0 (LBA*2048).
Reader: `gbox/psp_ciso_inventory.py` (streaming; 243 files, 1,532,694,394 bytes).

PARAM.SFO: DISC_ID **ULES01372** (European region code, catalog label says USA – verify), CATEGORY UG, DISC_VERSION 1.01, PSP_SYSTEM_VER 6.20, TITLE "METAL GEAR SOLID PEACE WALKER".

Extensions: prx 129, cmf 40, pmf 35, pdt 26, bin 5, png 3, dat 2, sfo/old/key 1.
Magics: ELF 97 (prx), CMF 40, PSMF 35, ~SCE 34, PNG 3.

Character-asset candidates (unproven, no reader yet):
- `/PSP_GAME/USRDIR/SLOT.DAT` 505,368,576 B, head `9527c84b01000100`, with `SLOT.KEY` (24,636 B, sha256 54a9b59b…6535)
- `/PSP_GAME/USRDIR/STAGEDAT.PDT` 89,036,800 B, head `fa459600e9886861`
- `*.PDT` (26 files; VOICE*/BGM are audio), `BRIEFING.DAT`
Boot: `SYSDIR/EBOOT.BIN` is 4,146 B (stub), `EBOOT.OLD` 5,069,136 B ELF (sha256 bc020306…db8f), `BOOT.BIN` 5,069,136 B zero-headed (sha256 e27d0223…1a99).
