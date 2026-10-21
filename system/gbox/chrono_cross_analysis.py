"""Static-analysis facts for Chrono Cross (USA) (Disc 1) (game_id 357b4ff44f7a2a68).

Every constant and function here was produced by running Ghidra 12.1.4 headless
(MIPS:LE:32:default) against the owned boot executable and by parsing the owned
Disc 1 image. The evidence is committed under artifacts/ and pinned by
tests/test_chrono_cross_psx_analysis.py.

SCOPE: this module records analysis evidence only. It implements NO unlock writer.
The lock checks, save/progress flags and menu-eligibility paths are not yet proven,
so gbox.game_unlocks.profile_for must keep this game at research_pending and no
pre_launch hook may write memory or saves for it.
"""
import hashlib
import re
import struct

GAME_ID = "357b4ff44f7a2a68"
EXE_NAME = "SLUS_010.41"
EXE_SHA256 = "9a5453bf09d7f5c71a6451d255471374fb2d7cc5f3dfb1ea51223a5c88cdda47"
EXE_SIZE = 606208
DISC_SHA256 = "01a0716ed46b6bce7717be1f9220f9bf323cee52404c9cd7fd4ef747d41a98da"

# --- PS-X EXE header (offsets are fixed by the format) ---
#   +0x10 pc0   +0x14 gp0   +0x18 t_addr +0x1C t_size
#   +0x20 d_addr +0x24 d_size +0x28 b_addr +0x2C b_size +0x30 s_addr +0x34 s_size
EXE_PC0 = 0x80010008      # entry point
EXE_GP0 = 0x00000000      # header gp0 is 0 on this build
EXE_TADDR = 0x80010000    # text load address
EXE_TSIZE = 0x00093800    # text length (604160 bytes)
EXE_SADDR = 0x801FFFF0    # stack top
EXE_HEADER_SIZE = 0x800

# $gp recovered from the crt0: lui r28 at 0x80010088, addiu r28,r28,0xce1c.
EXE_GP = 0x8006CE1C

# --- Ghidra 12.1.4 headless run on the ELF wrapper of that executable ---
GHIDRA_LANGUAGE = "MIPS:LE:32:default"
GHIDRA_IMAGE_BASE = 0x80010000
GHIDRA_FUNCTIONS = 1240
GHIDRA_STRINGS = 214
GHIDRA_ELF_SHA256 = "4e3463bfdfb623f9ed0b8749c976bc7abd49205304f5807f87cd8e6525012347"

# --- inventory found on the owned disc ---
CHARACTER_PROFILE_COUNT = 51


def parse_psx_exe_header(data: bytes) -> dict:
    """Parse a PS-X EXE header into its real fields.

    The field names follow the format (pc0/gp0/t_addr/t_size/d_*/b_*/s_*), not the
    offsets: an earlier revision of this project read pc0 as taddr, which put the
    text load address and the entry point 8 bytes apart from the truth.
    """
    if len(data) < EXE_HEADER_SIZE or data[:8] != b"PS-X EXE":
        raise ValueError("not a PS-X EXE")
    (pc0, gp0, t_addr, t_size, d_addr, d_size,
     b_addr, b_size, s_addr, s_size) = struct.unpack_from("<10I", data, 0x10)
    if t_size > len(data) - EXE_HEADER_SIZE:
        raise ValueError("t_size exceeds file")
    return {"magic": data[:2].decode("latin-1"), "pc0": pc0, "gp0": gp0, "taddr": t_addr, "tsize": t_size,
            "daddr": d_addr, "dsize": d_size, "baddr": b_addr, "bsize": b_size,
            "saddr": s_addr, "ssize": s_size, "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def verify_exe(data: bytes) -> dict:
    """Check the owned boot executable and report its real header fields."""
    p = parse_psx_exe_header(data)
    p["matches_owned"] = (p["sha256"] == EXE_SHA256 and p["size"] == EXE_SIZE
                          and p["pc0"] == EXE_PC0 and p["taddr"] == EXE_TADDR
                          and p["tsize"] == EXE_TSIZE and p["saddr"] == EXE_SADDR)
    p["gp"] = EXE_GP
    return p


def character_profiles(disc: bytes) -> list[dict]:
    """Read the character profile blocks out of a Disc 1 image.

    Each block is the game's own text: name, age, origin, height, weight, build,
    handedness. This is an inventory of what the disc contains; it says nothing
    about which entries are locked, and it must not be used as one.
    """
    out = []
    for m in re.finditer(b"Origin:", disc):
        o = m.start()
        head = disc[max(0, o - 500):o]
        am = head.rfind(b"Age:")
        if am < 0:
            continue
        runs = [r.group().decode("latin-1") for r in re.finditer(rb"[ -~]{3,}", head[:am])]
        name = runs[-1].strip() if runs else ""
        if not name or ":" in name:
            continue
        seg = disc[o:o + 260]
        ageseg = head[am:am + 260]

        def g(pat, s=seg):
            mm = re.search(pat, s)
            return mm.group(1).decode("latin-1").strip() if mm else ""

        def ga(pat, s=ageseg):
            mm = re.search(pat, s)
            return mm.group(1).decode("latin-1").strip() if mm else ""
        out.append({"disc_offset": o, "name": name, "age": ga(rb"Age:\s*([^\x00\r\n]{1,20})"),
                    "origin": g(rb"Origin:\s*([^\x00\r\n]{1,30})"),
                    "height": g(rb"Height:\s*([^\x00\r\n]{1,16})"),
                    "weight": g(rb"Weight:\s*([^\x00\r\n]{1,16})"),
                    "build": g(rb"Build:\s*([^\x00\r\n]{1,24})"),
                    "handed": g(rb"([A-Za-z][ -~]{2,24}handed)")})
    return out
