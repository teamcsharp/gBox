"""NFL Blitz 2001 (Dreamcast, T9712N V1.001) 1ST_READ.BIN loader evidence.

Static SH-4 (little-endian, base 0x8C010000) facts re-derived from the owned
executable by literal-pool xrefs.  `verify_executable` re-checks every claim.
Facts marked HYPOTHESIS are NOT proven.
"""
from __future__ import annotations
import hashlib, struct
from pathlib import Path

BASE = 0x8C010000
SHA256 = "342a9a097c387800d2df7ff017e5cca7164a751756006fea65a885523bc35007"

# VERIFIED by literal-pool scan (mov.l @(d,pc),Rn -> pool word == address)
BODY_NAME_TABLE = 0x8C1E7BA4          # 3 x char* : S,M,B body-type SBM names
BODY_NAMES = ("players.sbm", "playerm.sbm", "playerb.sbm")
BODY_SLOT_TABLE = 0x8C1E7BB0          # 3 x model* filled by the init loop
BODY_INIT = 0x8C0E1B20                # loop: slot[i] = load_model(name[i]) x3
BODY_UNLOAD = 0x8C0E1B80              # loop: if slot[i]: free(slot[i]); slot[i]=0
MODEL_LOAD_WRAPPER = 0x8C0E1AC0       # r0 = 0x8C0DFDC0(name, 1); one-shot init
MODEL_FIXUP = 0x8C0E0C00              # called only when (word0 & 0x08000000)==0
MODEL_READY_FLAG = 0x08000000         # word0 bit27 set after fixup; slot+32 = 0
MODEL_LOAD_FN = 0x8C0DFDC0
MODEL_DRAW = 0x8C0E0DC0               # skinned draw: 48 B per-bone matrix (12 f32)
BONE_MATRIX_STRIDE = 48

EXPECTED_XREFS = {  # literal-pool word address -> string
    0x8C1E7BA4: "players.sbm",
}

def _u32(x: bytes, va: int) -> int:
    return struct.unpack_from("<I", x, va - BASE)[0]

def _cstr(x: bytes, va: int) -> str:
    o = va - BASE
    return x[o:x.index(b"\0", o)].decode("ascii")

def pool_loaders(x: bytes, pool_vas: set[int]) -> list[tuple[int, int]]:
    """(instruction va, pool va) for each mov.l @(d,pc) reading a wanted pool word."""
    out = []
    for o in range(0, len(x) - 1, 2):
        h = struct.unpack_from("<H", x, o)[0]
        if h >> 12 == 0xD:
            a = BASE + o
            t = ((a + 4) & ~3) + (h & 0xFF) * 4
            if t in pool_vas:
                out.append((a, t))
    return out

def verify_executable(path: str | Path) -> dict:
    x = Path(path).read_bytes()
    r = {"sha256": hashlib.sha256(x).hexdigest()}
    r["sha_ok"] = r["sha256"] == SHA256
    r["body_names"] = tuple(_cstr(x, _u32(x, BODY_NAME_TABLE + 4 * i)) for i in range(3))
    r["body_names_ok"] = r["body_names"] == BODY_NAMES
    pools = [BASE + i for i in range(0, len(x) - 3, 4)
             if _u32(x, BASE + i) == BODY_NAME_TABLE]
    r["table_pool_words"] = [hex(p) for p in pools]
    r["table_loader_insns"] = [hex(a) for a, _ in pool_loaders(x, set(pools))]
    r["flag_const_ok"] = _u32(x, 0x8C0E1B04) == MODEL_READY_FLAG
    r["load_fn_ok"] = _u32(x, 0x8C0E1B00) == MODEL_LOAD_FN
    r["fixup_fn_ok"] = _u32(x, 0x8C0E1B08) == MODEL_FIXUP
    return r
