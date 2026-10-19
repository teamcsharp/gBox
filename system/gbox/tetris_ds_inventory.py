"""Inventory evidence for Tetris DS (USA) — request #2459, game 25da54968d78f816.

Authoritative owned-build manifest for the stage=inventory milestone.
All values below were produced by streaming the owned .nds bytes in this
workstream (probe: scratch tetris_ds_inventory_probe.py, manifest
tetris_ds_inventory_manifest.json sha256 d549d018d0d377bb381c1448dbcfb32cab3d90f7b2f78ea178b70d239813e587)
and are re-asserted by tests/test_tetris_ds.py::TestOwnedBuildInventory.

Platform correction: the gBox catalog labels this title "psp"; the files say
Nintendo DS (gamecode ATRE, ARM9/ARM7 tables, NitroFS FNT/FAT, 3 embedded
SRL sub-roms). The catalog label is wrong and was confirmed against the ROM.
"""

TETRIS_DS_INVENTORY = {
    "game_id": "25da54968d78f816",
    "request_id": "a7bd7730a812464c",
    "stage": "inventory",
    "source": {
        "packaged": "/mnt/gbox/hyperspin/Arcade/collections/Nintendo DS/roms/"
                    "Tetris DS (USA).7z (3859093 B)",
        "extracted": "0366 - Tetris DS (U)(WRG).nds",
        "bytes": 16777216,
        "sha256": "4e443f9b03363900dda6fa308229a3b14631b0fedd14f1c2e4cc1d5b3224db68",
        "hash_method": "streamed in 1 MiB chunks",
    },
    "platform": {
        "catalog_label": "psp",
        "actual": "nintendo_ds_nitro",
        "evidence": "header game_code=ATRE, ARM9@0x4000 size 0x770b8, "
                    "ARM7@0x16cc00 size 0x28684, NitroFS FNT/FAT, "
                    "3 SRL sub-roms (NINTENDO/NTRJ magic)",
    },
    "header": {
        "game_title": "TETRIS DS",
        "game_code": "ATRE",
        "maker": "01",
        "revision_byte_0x1C": 0,
        "unit_code": 0x00,
        "ds_only": True,
        "byte_order": "little-endian",
        "offset_base": "absolute cartridge offset",
        "arm9_offset": "0x4000",
        "arm9_size": "0x770b8",
        "arm9_sha256": "395348597da9fdda6db2956f9e9f0fd1575f27f70e0c3e7afb2b90adb3edb4e4",
        "arm7_offset": "0x16cc00",
        "arm7_size": "0x28684",
        "fnt_offset": "0x1c5c",
        "fnt_size": 1667584,
        "fat_offset": "0x195400",
        "fat_size": 4328,
    },
    "nitrofs": {
        "file_count": 528,
        "extension_counts": {
            "chr": 70, "objs": 70, "clz": 22, "plz": 33, "slz": 52,
            "cz": 78, "ntfp": 77, "blz": 57, "tds": 4, "srl": 3,
            "lz": 11, "bdz": 42, "char": 1, "plt": 1, "bin": 1,
            "fnt": 2, "pak": 2, "dat": 1, "sdat": 1,
        },
        "sprite_families_counted": 70,
        "note": "counts are enumerated from the FAT/FNT walk, not filename guesses",
    },
    "target_asset": {
        "family": "op_characters",
        "members": [
            {"path": "op_characters.chr", "role": "raw 8x8 8bpp tile bank",
             "decompressed_size": 26481, "container": "LZ10 (type 0x10)",
             "magic": None, "constraint": "size % 64 == 0 (8x8 8bpp tiles)"},
            {"path": "op_characters.objs", "role": "per-sprite (tile_index, attr) pair list",
             "container": "LZ10 (type 0x10)",
             "constraint": "3 u32 header words + u16 pairs to EOF"},
        ],
        "paired_palette": "op_characters.plz (256 x u16 BGR555, no header)",
        "selection": "ranked by decompressed .chr size across all 70 counted families",
        "loader_evidence": "ARM9 carries literal '<stem>.chr'/'.objs' format strings "
                           "(46 hits, e.g. tt_bar.chr, wf_time.chr); "
                           "op_characters loads by table, not literal — confirmed in analysis stage",
    },
}
