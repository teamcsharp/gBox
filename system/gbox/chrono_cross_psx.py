"""Source inventory for Chrono Cross (USA) Disc 1 (PSX), owned CHD.

Owned source: hyperspin CHD
``collections/Sony Playstation/roms/Chrono Cross (USA) (Disc 1).chd``
(game 357b4ff44f7a2a68). The catalog CHD is zlib CHD v4 which
``gbox.psxdisc.CHD`` cannot read, so extract with chdman first
(``chdman extractcd -i <chd> -o disc.cue -ob disc.bin``) and open the
resulting raw MODE2/2352 image with ``gbox.psxdisc.RawBin``.

Disc 1 layout (verified from the owned image, request #2074): the ISO9660
root holds exactly two files — ``SYSTEM.CNF`` (``BOOT=cdrom:\\SLUS_010.41;1``,
``STACK=801fe000``) and the PS-X EXE ``SLUS_010.41`` (606208 bytes,
sha256 9a5453bf09d7f5c71a6451d255471374fb2d7cc5f3dfb1ea51223a5c88cdda47,
load address 0x80700008). The bulk of the disc is not ISO9660: the game
data lives as raw 2048-byte sectors behind the two tracked files and is
reached through the executable's own file-number/LBA tables (same pattern
as :mod:`gbox.re2psx_exe` on RE2 SLUS_007.56, whose forward-LBA copy
constraint applies here too).

No unlock profile is claimed by this module: the character-recruitment
routine, the save/progress flag locations and the hidden New Game+ roster
have not been located in ``SLUS_010.41`` yet, so ``game_unlocks.profile_for``
must keep reporting research_pending for this game_id and no launch hook may
write memory or saves on its behalf.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys

GAME_ID = "357b4ff44f7a2a68"
TITLE = "Chrono Cross (USA) (Disc 1, PSX)"
PLATFORM = "playstation"

# Owned Disc 1 CHD (hyperspin) — sha256 of the CHD container itself.
CHD_SHA256 = "38fde0417b095f45ce4a84bb9cafb0863c7d0198684c7b7b58cae665968d9299"

# PS-X EXE SLUS_010.41 as extracted from the owned CHD (chdman extractcd).
EXE_NAME = "SLUS_010.41"
EXE_SHA256 = "9a5453bf09d7f5c71a6451d255471374fb2d7cc5f3dfb1ea51223a5c88cdda47"
EXE_SIZE = 606208
# PS-X EXE header fields, verified from the owned SLUS_010.41 image:
#   pc0 +0x10, gp0 +0x14, t_addr +0x18, t_size +0x1C,
#   d_addr/d_size +0x20/+0x24, b_addr/b_size +0x28/+0x2C, s_addr/s_size +0x30/+0x34
EXE_PC0 = 0x80010008     # header pc0 (entry point)
EXE_GP0 = 0x00000000     # header gp0 (0; $gp comes from the crt0)
EXE_TADDR = 0x80010000   # header t_addr: text load address
EXE_TSIZE = 0x00093800   # header t_size: 604160 bytes of text
EXE_SADDR = 0x801FFFF0   # header s_addr: stack top
EXE_GADDR = 0x8006CE1C   # $gp from the crt0 (lui r28 0x80010088 + addiu 0xce1c)



def parse_psx_exe(data: bytes) -> dict:
    """Parse the PS-X EXE header into its real fields (pc0/gp0/t_addr/t_size/...)."""
    if len(data) < 0x800 or data[:8] != b"PS-X EXE":
        raise ValueError("not a PS-X EXE")
    (pc0, gp0, t_addr, t_size, d_addr, d_size,
     b_addr, b_size, s_addr, s_size) = struct.unpack_from("<10I", data, 0x10)
    if t_size > len(data) - 0x800:
        raise ValueError("t_size exceeds file")
    return {"magic": data[:2].decode("latin-1"), "pc0": pc0, "gp0": gp0,
            "taddr": t_addr, "tsize": t_size, "daddr": d_addr, "dsize": d_size,
            "baddr": b_addr, "bsize": b_size, "saddr": s_addr, "ssize": s_size,
            "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

def verify_exe(data: bytes) -> dict:
    """Pinned-hash check for the owned Disc 1 boot EXE (guards every probe)."""
    parsed = parse_psx_exe(data)
    return {
        "game_id": GAME_ID,
        "name": EXE_NAME,
        "sha256": parsed["sha256"],
        "matches_owned": (parsed["sha256"] == EXE_SHA256 and parsed["pc0"] == EXE_PC0
                              and parsed["taddr"] == EXE_TADDR and parsed["tsize"] == EXE_TSIZE
                              and parsed["saddr"] == EXE_SADDR),
        "gp": EXE_GADDR,
        **parsed,
    }


def inventory(bin_path: str) -> dict:
    """Walk the extracted Disc 1 image and build the pinned source manifest."""
    from gbox.psxdisc import RawBin

    rb = RawBin(bin_path, writable=False)
    try:
        cnf = rb.read("SYSTEM.CNF").decode("latin-1")
        boot = [ln.split("=", 1)[1].strip().replace("\\", "/").split("/")[-1].split(";")[0]
                for ln in cnf.splitlines() if ln.upper().startswith("BOOT")]
        boot = boot[0] if boot else None
        files = {"count": len(rb.files), "boot": boot,
                 "entries": [{"name": k, "lba": v[0], "size": v[1]}
                             for k, v in sorted(rb.files.items())]}
        exe = rb.read(EXE_NAME) if EXE_NAME in rb.files else None
    finally:
        rb.close()
    out: dict[str, object] = {"game_id": GAME_ID, "title": TITLE, "platform": PLATFORM,
                              "bin": bin_path, "iso9660": files,
                              "chd_sha256": CHD_SHA256}
    out["exe"] = verify_exe(exe) if exe is not None else None
    return out


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 1:
        print("usage: python -m gbox.chrono_cross_psx DISC.BIN [--out manifest.json]",
              file=sys.stderr)
        return 2
    out_path = None
    if "--out" in args:
        i = args.index("--out")
        out_path = args[i + 1]
        del args[i:i + 2]
    man = inventory(args[0])
    text = json.dumps(man, indent=1, default=str)
    if out_path:
        with open(out_path, "w") as f:
            f.write(text)
        print(f"manifest -> {out_path}")
    exe = man["exe"] or {}
    print(f"files {man['iso9660']['count']} boot {man['iso9660']['boot']} "
          f"exe sha {exe.get('sha256', 'missing')} matches_owned {exe.get('matches_owned')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
