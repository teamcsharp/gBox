"""gbox.formats: the low-level libraries every title reader/writer shares. Start a new title here, not by copying
another title's module (docs/assimilation.md has the per-title history; gbox.assimilate fingerprints a new game).

  lz            PRS (Sega + Eighting), MIO0, Yaz0, LZSS, LZ10, VPK0, RNC/RefPack facades, inflate; encoders for tests
  rnc           RNC ProPack 1/2 (Turok)
  iso9660       ISO9660 directory walk (PS1/PS2/DC/romexport) ; gcfst  GameCube FST + disc header
  disc          one call: disc image / ROM / zip / folder -> file listing with heads + main executable
  texture       PowerVR twiddle, 16-bit pixel words, PS1 TIM, GameCube tiles; facades for PVR/TPL/TXD decoders
  ninja_chunk   Sega Ninja chunk models (decode/encode/fit) by role
  rig           body-role vocabulary, role_of_joint, check_role_map (skinning/retarget role maps)
  oracle        the game's own routine as the oracle (R3000 interpreter harness, inverse/reader checks)
  insn_pattern  find code by masked instruction shape (overlays, per-build patch sites, lis/addi + jal xrefs)
  nitro         Nintendo DS: NitroFS (FNT/FAT), NARC, LZ77 tag + LZ10/LZ11, the seven DS texel formats, GX display lists
  sega_md       Mega Drive art: Nemesis, Kosinski (decode + test encoders), 4bpp VDP tiles, colour words -> RGBA

INDEX below says which title modules use which shared piece (kept honest by tests/test_formats.py).
"""

INDEX = {
    "lz.prs_decompress / prs_compress (Sega PRS)": ["ninja", "pso_player", "pso_enemy", "sa1_inventory", "sa2_chars",
                                                    "sa2_inventory", "psotext", "characters"],
    "lz.prs_msb_decompress (Eighting PRS)": ["cnr2", "con2_inventory"],
    "lz.mio0_decompress (MIO0)": ["sm64_mario", "sm64_inventory", "sf64_inventory"],
    "lz.yaz0_decompress (Yaz0)": ["oot_writer", "mm_inventory", "sms_inventory"],
    "lz.lzss_decompress (Okumura LZSS)": ["mm64_inventory", "ff7_models", "aki_wrestling"],
    "lz.lz10_decompress (LZ10)": ["tetris_ds", "sm64ds_chars (through formats.nitro)"],
    "nitro.NitroROM / narc / decompress / decode_texture / decode_display_list (Nintendo DS)":
        ["sm64ds_chars", "formats.disc (NDS listing)"],
    "lz.vpk0_decode (VPK0)": ["ssb64_inventory", "ssb64_analysis"],
    "rnc.decode_rnc (RNC)": ["turok_inventory", "turok2_inventory", "turok_analysis"],
    "lz.refpack_decompress (RefPack)": ["mayhem_inventory (via gbox.refpack)"],
    "iso9660.walk": ["psxdisc", "gdrom", "defjam_inventory", "raidou2_inventory", "romexport"],
    "gcfst.parse_fst": ["gcdisc (and every GameCube title through it)", "formats.disc (GCZ)"],
    "rarc.parse / rarc.walk (RARC archives)": ["sms_inventory", "tp_inventory"],
    "texture.morton / twiddled_index": ["ninja", "doa2_textures", "mkgold_geo"],
    "texture.tim_parse / tim_build": ["yukes_sd"],
    "rig.role_of_joint": ["re4gc_enemies", "doa2_weighted_retarget", "sm64_swap"],
    "rig.check_role_map": ["pso_player"],
    "oracle.RoutineOracle (R3000)": ["doapp_models / doapp_swap / doapp_motion (same interpreter, gbox.zn_tps_boot)"],
    "insn_pattern": ["assimilate (fingerprinter)", "pattern of mgs_vr_tool.find_clear_handler, nomercy_analysis, "
                     "dmc3_slus, re2psx_exe, nightfire_analysis"],
    "disc.listing": ["assimilate (fingerprinter)"],
    "sega_md.nemesis_decompress / tiles_to_indices / palette_rgba (Mega Drive art)": ["sonic2d_sprites"],
    "sega_md.kosinski_decompress / kosinski_compress (Kosinski; Sonic 1/2/3K level data, no reader uses it yet)": [],
}

# Shared pieces that still live in their original module (imported from there, not duplicated):
ELSEWHERE = {
    "gcz.GCZ (Dolphin GCZ)": "gbox.gcz", "gdrom.GDRom / CDIRom (GD-ROM, DiscJuggler)": "gbox.gdrom",
    "psxdisc.PSXDisc / RawBin (CHD v4, sector EDC/ECC rewrite)": "gbox.psxdisc",
    "refpack (EA RefPack)": "gbox.refpack", "ue_pak / ue_asset / ue_mesh (Unreal 4)": "gbox.ue_*",
    "ue3 (Unreal 3 packages)": "gbox.ue3", "gta_rw (RenderWare IMG/DFF, write_skinned_glb)": "gbox.gta_rw",
    "sm64_swap.load_rig / retarget (generic donor retarget)": "gbox.sm64_swap",
    "re4gc_enemies.retarget / decimate (rigid retarget, budgets)": "gbox.re4gc_enemies",
    "melee_models.write_gltf": "gbox.melee_models", "naomilib (NaomiLib model scan)": "gbox.naomilib",
    "zn_tps_boot.R3000 + psx_gte.GTE (MIPS interpreter + GTE)": "gbox.zn_tps_boot / gbox.psx_gte",
}
