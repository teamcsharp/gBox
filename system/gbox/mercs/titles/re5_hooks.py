"""BLUS30491 01.01 Mercenaries access recovered with Ghidra, 2026-10-23.

PPU hash pins the boot patch to the exact executable. At 0x005FFEA8 the Play Game
UI normally loads its availability word into r0 (800b0020), then stores it at
uIdStartUp01+0x180. Its observed offline mask is 0xb3; 0xf3 adds only entry 6,
The Mercenaries. The normal game routines still enter the mode and construct the
selected character. No campaign or Mercenaries score record is manufactured.
The original title's Start entry separately checks save+0xA4 bit 4. Its branch
at 0x006139C8 skips setting UI+0x184 bit 0; replacing only that branch with nop
enables Start without writing the campaign-completion flag.

RPCS3's patch parser and enable schema: Utilities/bin_patch.cpp in RPCS3/rpcs3.
"""
import json
import shutil
import struct
from pathlib import Path

HASH = "PPU-a9b0ce57ebd318bd02879751067ceca83b508dd1"
NAME = "gBox Mercenaries menu access"
SITE, ORIGINAL, PATCHED = 0x005FFEA8, 0x800B0020, 0x380000F3
START_SITE, START_ORIGINAL, NOP = 0x006139C8, 0x419E000C, 0x60000000


def install(home):
    import yaml
    home = Path(home)
    patch_path = home / "patches" / "BLUS30491_patch.yml"
    config_path = home / "patch_config.yml"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch = yaml.safe_load(patch_path.read_text(encoding="utf-8")) if patch_path.exists() else {"Version": "1.2"}
    if str(patch.get("Version")) != "1.2":
        raise ValueError("RPCS3 patch format differs; existing patches kept")
    for path in (patch_path, config_path):
        backup = path.with_suffix(path.suffix + ".gbox-mercs-backup")
        if path.exists() and not backup.exists(): shutil.copy2(path, backup)
    patch.setdefault(HASH, {})[NAME] = {
        "Games": {"All": {"All": ["All"]}}, "Author": "gBox",
        "Patch Version": "1.0", "Notes": "Exact-build offline Mercenaries menu access; earned scores unchanged.",
        "Patch": [["be32", f"0x{SITE:08x}", f"0x{PATCHED:08x}"],
                  ["be32", f"0x{START_SITE:08x}", f"0x{NOP:08x}"]]}
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    cfg = cfg or {}
    cfg.setdefault(HASH, {}).setdefault(NAME, {}).setdefault("All", {}).setdefault("All", {})["All"] = {"Enabled": True}
    for path, data in ((patch_path, patch), (config_path, cfg)):
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        temp.replace(path)
    return {"patch": str(patch_path), "hash": HASH, "effective_next_boot": True}


def unlock(g):
    """OR only recovered availability fields in the currently loaded save profile.

    Ghidra: 0x143090 reads original character bits at +0x108; 0x612F3C reads
    original stages at +0x10C and Reunion stages at +0x3F70. Profile stride
    is 0x7EB8; uIdStartUp's module TOC identifies its own sSave pointer.
    """
    toc = g.u32(0x01714C1C)
    slot = g.u32(toc - 0x7FEC)
    save = g.u32(slot)
    if not 0x30000000 <= save < 0x40000000:
        return {"verified": False, "reason": "Save manager not loaded"}
    index = g.u32(save + 0x24)
    if index > 3:
        return {"verified": False, "reason": "Save profile is outside the verified range"}
    base = save + index * 0x7EB8
    changes = []
    ok = True
    for offset, mask in ((0x108, 0x3FF), (0x10C, 0xFF), (0x3F70, 0xFF)):
        address = base + offset
        before = g.u32(address)
        if before & mask != mask:
            g.orig.setdefault("mercs_unlock_originals", {}).setdefault(address, before)
            ok &= g.wr(address, struct.pack(">I", before | mask))
            changes.append(hex(address))
    return {"verified": ok, "characters": 10, "stages_per_mode": 8, "changed": changes,
            "scope": "availability bits; score records untouched"}
