# Sonic Gems Collection (USA, GameCube) — inventory, request #2362

Source: `/mnt/gbox/quickswap2/Emulation/_emulation/GC ISO/Sonic Gems Collection (USA).nkit.iso`
(staged copy in gbox-cache), 1,355,980,800 B, **sha256 38853c1ec80c5ef1cdea4c533dc6a9ad5ddbc3ebcb405450fff0979248ea6322**
(streamed). Disc id G2XE, maker 8P, title SONIC GEMS COLLECTION. NKit v01 image; its GCM FST
(big-endian, FST @0x218600, 134 entries) is valid with in-image offsets (all 118 files in range,
magics match types). **The disc is GCM, not ISO9660** — the previous run's ISO9660 walk was wrong.

- 5 sub-games: Sonic CD (soniccd.dol + CVM), Sonic R (sonicr.dol + sonicrgc.dat), Sonic the Fighters
  (stf.dol + bin.cvm + adxj.cvm), Mega Drive/GG ROM `.cpt` set (mdrom_us, ggrom), museum.
- 13 plain CRI AFS (manual_e/*.afs x11, museum/museum.afs, museum_p.afs): **all members are GVM
  textures** (no models). Fingerprint said 14 AFS; one more is nested inside soniccd.cvm.
- 3 CVM (CVMH, ISO9660 base +0x1800): soniccdu.cvm 579 files, stf/bin.cvm 203, stf/adxj.cvm 24 ADX.
- Fingerprint "CRI AFS x14 / CVM x5" not matched on disc top-level (3 CVM top-level; counts differ).
- Native target: stf/bin.cvm → `OBJ_SNC1.CMP` (Sonic fighter data, 361,822 B, abs offset 151304480,
  sha256 9595c68d18fd80f0d16cdb879061e2e01e4cd96cddd88bec8821a9606c2eddc6). Container "CRICMP" v2.10,
  little-endian header: data @0x20, field 0xCD2D4 (likely uncompressed size 840,404). Roster siblings:
  OBJ_{SNC,AMY,BIN,ESP,FNG,KCS,KMA,MTS,TEI}{1,2}.CMP (+R/V variants). Not yet decoded: CRICMP codec
  is the next step (analysis stage). `.gcz` copy payload hash still unverified.

Reproduce: `python3 gbox/sonic_gems_inventory.py --disc <iso> --out docs/evidence/sonic_gems_manifest.json`.
