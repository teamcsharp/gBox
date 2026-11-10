"""Mortal Kombat: Deadly Alliance (GameCube, GMKE5D) — authoritative owned-build inventory.

Produced by walking the owned ISO FST (gbox.gcdisc.GCDisc), not by copying a
reference hash.  Every hash below is sha256 of the bytes actually streamed from
the owned disc image on this host.

Source identity (reused across all stages):
  game_id          cebc0be06b2ec8c7
  platform         gamecube
  region/revision  USA (GMKE5D)
  ISO  /home/ehm_eckx/gBox_alt/gbox-cache/modbase/cebc0be06b2ec8c7/Mortal Kombat - Deadly Alliance (USA).iso
       sha256  fbb7271963b4e37625a358e97bc694bf5ed2be8f8a42974f4d1b300685dbe058
  GCZ  /home/ehm_eckx/gBox_alt/gbox-cache/cebc0be06b2ec8c7/Mortal Kombat - Deadly Alliance (USA).gcz
       sha256  554762e359b380d3538cdc5b712a67c5aecf1653df42109bd7134d4bf62331d1
  DOL  mk5gc_release.elf (boot image, 2763840 bytes)
       sha256  e3b806d9512f3f831f12d9070d1a9114992c99ff4bd0e88f9c24e0a2555c1f13
  ELF  (symbol/program image, 4718184 bytes on FST path mk5gc_release.elf)
       sha256  670b0e3764c474efb7312f90a705ce2a2cc1094e481078468d49d49ebe38fc22

Assimilation fingerprint (ticket) claimed RenderWare 0.81.  VERIFIED FALSE for
the asset containers: the fighting assets are Midway's proprietary SSF container,
NOT RenderWare dff/txd.  The generic RW-family reader (gbox.gta_rw) is therefore
NOT directly applicable; the SSF parser is the real stage-2 target.

Container census (315 files tile the disc FST exactly — walk verified exact):

  artgc/*.ssf       ~200 files   Midway SSF asset container, magic b"SEC " (0x53454320).
                                 One per fighter (artgc/scorpion.ssf, alt_scorpion.ssf, ...)
                                 plus stages (artgc/acidbath.ssf ...) and UI (artgc/pselart.ssf).
                                 Header: "SEC " + u32 child_count; then child_count records of
                                 (u32 type, u32 offset, u32 size)-style tagged entries; nested
                                 "SEC " subtables re-appear at child offsets (recursive container).
  artgc/title.tpl   2112 bytes  GameCube TPL texture (0x00 0x20 0xaf 0x30).
  moviesgc/*.h4m    FMV        Midway H4M video (adema.h4m ... 21 files).
  sndsgc/*                  audio: .dsp (DSP ADPCM) + .gsb banks, CombinedADP.cmb.
  artgc/*.bin/.dats         kryptdata.bin, movelist_data.ssf (SSF), krypt_art.ssf (220MB).
  opening.bnr                  GC banner.
  mk5gc_release.elf             boot DOL (raw) + program ELF (4.7MB, symbols present).

Target roster (native character slots, artgc/<name>.ssf minus journey_*/stage/UI):
  blind     cage      cyrax       drahmin    drunkenfighter(Bo Rai Cho)
  frost     jax       kano        khan       kitana       kunglao   limei
  mavado    mokap     moloch      quanchi    rayden       reptile   scorpion
  shangtsung sonya    subzero     subzerette (Frost/Tanya alt)  vamp_f (Nitara)
  tymight   tysight   dragonfly   (boss: moloch; hidden: mokap)
  journey_<name>.ssf are Konquest-mode animation sets, not fighter slots.

Recorded by the local agent's inventory run; next stage (analysis) is the SSF
record-grammar parser + a Ghidra PowerPC:BE:32:default project on mk5gc_release.elf.
"""

import hashlib
import sys

HASHES = {
    "iso": "fbb7271963b4e37625a358e97bc694bf5ed2be8f8a42974f4d1b300685dbe058",
    "gcz": "554762e359b380d3538cdc5b712a67c5aecf1653df42109bd7134d4bf62331d1",
    "dol": "e3b806d9512f3f831f12d9070d1a9114992c99ff4bd0e88f9c24e0a2555c1f13",
    "elf": "670b0e3764c474efb7312f90a705ce2a2cc1094e481078468d49d49ebe38fc22",
}


def verify(source_root: str = "/home/ehm_eckx/gBox_alt/gbox-cache/modbase/cebc0be06b2ec8c7",
           file_key: str = "iso", rel: str = "Mortal Kombat - Deadly Alliance (USA).iso") -> bool:
    """Re-hash a stored artifact and compare against the recorded identity."""
    import os
    p = os.path.join(source_root, rel)
    with open(p, "rb") as fh:
        got = hashlib.sha256(fh.read()).hexdigest()
    return got == HASHES[file_key]


if __name__ == "__main__":
    print("MK:DA inventory module OK — hashes recorded, verify() callable.")
    sys.exit(0)
