"""Carry what Ghidra work named in one title over to the next one: a cross-title library of masked function bodies.

Every title gBox cracks leaves named functions behind (dossier findings, Ghidra symbols, ELF symbols). Sibling titles
(region builds, sequels, games on the same SDK/middleware: Katana/Ninja on Dreamcast, Dolphin SDK on GameCube, PsyQ on
PS1, libultra on N64) contain many of the same function bodies at different addresses. This module stores each named
function as a *masked* body hash, so the next executable gets those names in seconds instead of re-deriving them:

  learn(store, source, exe, base, processor, functions, names)   add named functions of a studied executable
  elf_functions(exe)                                             named function symbols of a debug/prototype ELF
  transfer(store, game, exe, base, processor, functions=None)    find library bodies in a new executable and record
                                                                 them in its dossier as hypotheses that cite the source

Masking (what may differ between two copies of the same function and is ignored):
  SH-4 (16-bit insns)  bra/bsr displacements. Data addresses come from the literal pool, which is outside the body.
  PowerPC              b/bl targets; lis/addis immediates; the low half of an address (addi/ori/load/store whose base
                       register was set by a lis in the previous 16 insns); r2/r13 small-data offsets.
  MIPS                 j/jal targets; lui immediates; low halves through a lui register (previous 16 insns); $gp offsets.
Everything else (opcodes, registers, struct offsets, stack frame, intra-function branches) must match exactly, and a
body must be at least MIN_BYTES long with a few distinct instructions, so a hit is a precise match, not a similarity.
A body that two different names share in the library is ambiguous and never transferred. A body found at more than one
address of the target is reported, not recorded. Transfers never overwrite documented or validated findings.
"""
from __future__ import annotations

import hashlib
import re
import struct
import time

LIB_KIND = "re_signatures"
LIB_VERSION = 1
MIN_BYTES = 32                     # 16 SH-4 / 8 PowerPC or MIPS instructions
MIN_DISTINCT = 4                   # distinct masked instructions in a body
PREFIX = 6                         # instructions in the scan index key
SUFFIX = 4                         # last instructions checked before a candidate body is hashed
HI_WINDOW = 16                     # instructions a lis/lui register stays "an address high half"

_AUTO = re.compile(r"^(FUN|thunk_FUN|LAB|SUB|sub|func|fcn|DAT|PTR|switchD|caseD|entry)_?[0-9a-fA-F]*$|^_?FUN_[0-9a-fA-F]+")

_PPC_LOW = {14, 24, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55}
_MIPS_LOW = {8, 9, 13, 30, 31, 32, 33, 34, 35, 36, 37, 38, 40, 41, 42, 43, 46, 49, 53, 55, 57, 61, 63}


def arch_of(processor: str) -> tuple[str, str, int]:
    """Ghidra processor id (or a short name) -> (library arch id, struct endian, instruction size)."""
    p = (processor or "").lower()
    be = ":be:" in p or p.endswith(("-be", "be"))
    if p.startswith(("superh", "sh4", "sh-4", "sh")):
        return "sh4", ">" if be else "<", 2
    if p.startswith(("powerpc", "ppc")):
        le = ":le:" in p or p.endswith("-le")
        return ("ppc-le" if le else "ppc-be"), "<" if le else ">", 4
    if p.startswith("mips"):
        return ("mips-be" if be else "mips-le"), ">" if be else "<", 4
    raise ValueError(f"no signature masking rules for processor {processor!r} (supported: SuperH4, PowerPC, MIPS)")


def is_auto_name(name: str) -> bool:
    return not name or bool(_AUTO.match(name.strip()))


def _family(arch: str) -> str:
    return arch.split("-")[0]


def coarse_mask(arch: str, w: int) -> int:
    """Context-free mask: clears every field `precise_masks` might clear, so equal precise bodies have equal keys."""
    fam = _family(arch)
    if fam == "sh4":
        return 0xF000 if (w >> 12) in (0xA, 0xB) else 0xFFFF
    op = w >> 26
    if fam == "ppc":
        if op == 18:
            return 0xFC000003
        return 0xFFFF0000 if op == 15 or op in _PPC_LOW else 0xFFFFFFFF
    if op in (2, 3):
        return 0xFC000000
    return 0xFFFF0000 if op == 15 or op in _MIPS_LOW else 0xFFFFFFFF


def precise_masks(arch: str, words: list[int]) -> list[int]:
    """Function-local masks: tracks lis/lui destinations from the body's own first instruction."""
    fam = _family(arch)
    if fam == "sh4":
        return [coarse_mask(arch, w) for w in words]
    hi: dict[int, int] = {}
    out = []
    for i, w in enumerate(words):
        op, m = w >> 26, 0xFFFFFFFF
        if fam == "ppc":
            rd, ra = (w >> 21) & 31, (w >> 16) & 31
            if op == 18:
                m = 0xFC000003
            elif op == 15:
                if ra in (0, 2, 13):
                    m = 0xFFFF0000
                hi[rd] = i
            elif op in _PPC_LOW:
                base = rd if op == 24 else ra               # ori rA,rS,UI: the source is the rS field
                if base in (2, 13) or i - hi.get(base, -99) <= HI_WINDOW:
                    m = 0xFFFF0000
        else:
            rs, rt = (w >> 21) & 31, (w >> 16) & 31
            if op in (2, 3):
                m = 0xFC000000
            elif op == 15:
                m = 0xFFFF0000
                hi[rt] = i
            elif op in _MIPS_LOW and (rs == 28 or i - hi.get(rs, -99) <= HI_WINDOW):
                m = 0xFFFF0000
        out.append(m)
    return out


def body_hash(arch: str, words: list[int]) -> str | None:
    """sha1 of (masked word, mask) pairs; None for bodies too short or too uniform to be a precise match."""
    unit = 2 if _family(arch) == "sh4" else 4
    if len(words) * unit < MIN_BYTES:
        return None
    masks = precise_masks(arch, words)
    masked = [w & m for w, m in zip(words, masks)]
    if len(set(masked)) < MIN_DISTINCT:
        return None
    h = hashlib.sha1()
    for v, m in zip(masked, masks):
        h.update(struct.pack(">II", v, m))
    return h.hexdigest()


def segments(exe: bytes, base: int = 0) -> list[tuple[int, bytes]]:
    """(vaddr, bytes) of the executable: PT_LOAD segments of a 32-bit ELF, else one raw image at `base`."""
    if exe[:4] == b"\x7fELF" and exe[4] == 1:
        e = "<" if exe[5] == 1 else ">"
        phoff, = struct.unpack_from(e + "I", exe, 28)
        phentsize, phnum = struct.unpack_from(e + "HH", exe, 42)
        out = []
        for k in range(phnum):
            p_type, off, vaddr, _pa, filesz = struct.unpack_from(e + "IIIII", exe, phoff + k * phentsize)
            if p_type == 1 and filesz:
                out.append((vaddr, exe[off:off + filesz]))
        if out:
            return out
    return [(base, exe)]


def elf_functions(exe: bytes) -> list[dict]:
    """Named STT_FUNC symbols with sizes from a 32-bit ELF's .symtab: debug/prototype builds seed the library directly."""
    if exe[:4] != b"\x7fELF" or exe[4] != 1:
        return []
    e = "<" if exe[5] == 1 else ">"
    shoff, = struct.unpack_from(e + "I", exe, 32)
    shentsize, shnum = struct.unpack_from(e + "HH", exe, 46)
    if not shoff or not shnum:
        return []
    sh = [struct.unpack_from(e + "IIIIIIIIII", exe, shoff + k * shentsize) for k in range(shnum)]
    out = []
    for _name, typ, _fl, _a, off, size, link, _i, _al, ent in sh:
        if typ != 2 or not ent or link >= shnum:            # SHT_SYMTAB
            continue
        stroff = sh[link][4]
        for j in range(size // ent):
            st_name, value, st_size, info, _o, _shndx = struct.unpack_from(e + "IIIBBH", exe, off + j * ent)
            if info & 0xF != 2 or not st_size:               # STT_FUNC with a size
                continue
            end = exe.find(b"\0", stroff + st_name)
            out.append({"address": value & ~1, "size": st_size,
                        "name": exe[stroff + st_name:end].decode("latin-1")})
    return out


class Image:
    def __init__(self, exe: bytes, base: int, processor: str):
        self.arch, self.e, self.unit = arch_of(processor)
        self.segs = []
        for va, data in segments(exe, base):
            n = len(data) // self.unit
            fmt = f"{self.e}{n}{'H' if self.unit == 2 else 'I'}"
            self.segs.append((va, list(struct.unpack_from(fmt, data, 0))))

    def words(self, address: int, size: int) -> list[int] | None:
        for va, ws in self.segs:
            if va <= address and address + size <= va + len(ws) * self.unit and (address - va) % self.unit == 0:
                i = (address - va) // self.unit
                return ws[i:i + max(1, size // self.unit)]
        return None


def _int(a) -> int:
    if isinstance(a, int):
        return a
    s = str(a).strip().lower()
    s = s.split(":")[-1]                                   # Ghidra "ram:8c010000"
    return int(s, 16) if s.startswith("0x") or re.search("[a-f]", s) or len(s) >= 8 else int(s)


def library(store, arch: str) -> dict:
    return store.get(LIB_KIND, arch) or {"arch": arch, "version": LIB_VERSION, "sigs": {}, "sources": {}}


def learn(store, source: str, exe: bytes, base: int, processor: str, functions: list[dict],
          names: dict | None = None) -> dict:
    """Add the named functions of one executable to the library. `functions`: [{address, size, name?}] (Ghidra
    list_functions with sizes); `names`: {address: name} from the dossier, which wins over Ghidra's name."""
    t0, img = time.time(), Image(exe, base, processor)
    names = {_int(k): v for k, v in (names or {}).items()}
    lib = library(store, img.arch)
    stats = {"added": 0, "confirmed": 0, "ambiguous": 0, "unnamed": 0, "too_short": 0, "outside_image": 0}
    for f in functions:
        try:
            addr, size = _int(f.get("address") or f.get("entry")), int(f.get("size") or 0)
        except (TypeError, ValueError):
            continue
        name = (names.get(addr) or f.get("name") or "").strip()
        if is_auto_name(name):
            stats["unnamed"] += 1
            continue
        ws = img.words(addr, size)
        if ws is None:
            stats["outside_image"] += 1
            continue
        h = body_hash(img.arch, ws)
        if not h:
            stats["too_short"] += 1
            continue
        src = {"source": source, "address": f"0x{addr:08X}"}
        cur = lib["sigs"].get(h)
        if cur is None:
            mw = [w & coarse_mask(img.arch, w) for w in ws]
            lib["sigs"][h] = {"name": name, "names": [name], "words": len(ws), "prefix": mw[:PREFIX],
                              "suffix": mw[-SUFFIX:], "sources": [src]}
            stats["added"] += 1
            continue
        if name not in cur["names"]:
            cur["names"].append(name)
            cur["ambiguous"] = True
            stats["ambiguous"] += 1
        elif src not in cur["sources"]:
            stats["confirmed"] += 1
        if src not in cur["sources"]:
            cur["sources"] = (cur["sources"] + [src])[-12:]
    lib["sources"][source] = {"functions": len(functions), "added": stats["added"], "ts": time.time()}
    store.put(LIB_KIND, img.arch, lib)
    return stats | {"arch": img.arch, "library": len(lib["sigs"]), "seconds": round(time.time() - t0, 3)}


def match(lib: dict, exe: bytes, base: int, processor: str, functions: list[dict] | None = None) -> dict:
    """Library bodies in the executable: {address: sig} plus unique/duplicate bookkeeping. With `functions`
    (Ghidra entries + sizes) only those bodies are hashed; without, every aligned offset is scanned."""
    img = Image(exe, base, processor)
    sigs = {h: s for h, s in lib.get("sigs", {}).items() if not s.get("ambiguous")}
    found: dict[str, list[int]] = {}
    if functions:
        for f in functions:
            try:
                addr, size = _int(f.get("address") or f.get("entry")), int(f.get("size") or 0)
            except (TypeError, ValueError):
                continue
            ws = img.words(addr, size)
            h = body_hash(img.arch, ws) if ws else None
            if h and h in sigs:
                found.setdefault(h, []).append(addr)
    else:
        index: dict[tuple, list[str]] = {}
        for h, s in sigs.items():
            index.setdefault(tuple(s["prefix"]), []).append(h)
        for va, ws in img.segs:
            key = [w & coarse_mask(img.arch, w) for w in ws]
            for i in range(len(ws) - PREFIX + 1):
                cands = index.get(tuple(key[i:i + PREFIX]))
                if not cands:
                    continue
                for h in cands:
                    n, suf = sigs[h]["words"], sigs[h].get("suffix")
                    if i + n > len(ws) or (suf and key[i + n - len(suf):i + n] != suf):
                        continue                               # cheap end check before hashing the body
                    if body_hash(img.arch, ws[i:i + n]) == h:
                        found.setdefault(h, []).append(va + i * img.unit)
    hits, dup = {}, []
    for h, addrs in found.items():
        if len(addrs) > 1:
            dup.append({"name": sigs[h]["name"], "addresses": [f"0x{a:08X}" for a in addrs[:8]]})
            continue
        a = addrs[0]
        if a not in hits or sigs[h]["words"] > hits[a]["words"]:        # longest body wins at one entry
            hits[a] = sigs[h] | {"hash": h}
    return {"arch": img.arch, "hits": hits, "duplicates": dup,
            "skipped_ambiguous": sum(1 for s in lib.get("sigs", {}).values() if s.get("ambiguous"))}


def transfer(store, game: dict, exe: bytes, base: int, processor: str, functions: list[dict] | None = None,
             record: bool = True, exclude_source: str = "") -> dict:
    """Find library functions in this title's executable and record them in its dossier (hypothesis, citing the
    source titles). Addresses already documented/validated count as confirmations and are left untouched."""
    from . import re_lab
    t0 = time.time()
    arch = arch_of(processor)[0]
    lib = library(store, arch)
    if exclude_source:
        lib = lib | {"sigs": {h: s | {"sources": [x for x in s["sources"] if x["source"] != exclude_source]}
                              for h, s in lib["sigs"].items()}}
        lib["sigs"] = {h: s for h, s in lib["sigs"].items() if s["sources"]}
    m = match(lib, exe, base, processor, functions)
    d = re_lab.dossier(store, game)
    known = {f.get("address"): f for f in d.get("findings", []) if f.get("kind") == "function"}
    out = {"recorded": [], "confirmed": [], "conflicts": []}
    for a in sorted(m["hits"]):
        s, addr = m["hits"][a], f"0x{a:08X}"
        old = known.get(addr)
        srcs = ", ".join(sorted({x["source"] for x in s["sources"]}))
        if old and old.get("status") in ("documented", "validated"):
            (out["confirmed"] if old.get("name") == s["name"] else out["conflicts"]).append(
                {"address": addr, "name": s["name"], "known": old.get("name")})
            continue
        row = {"address": addr, "name": s["name"], "bytes": s["words"] * (2 if arch == "sh4" else 4), "from": srcs}
        out["recorded"].append(row)
        if record:
            re_lab.record(store, game, "function", addr, s["name"],
                          f"signature transfer: masked body ({row['bytes']} bytes) identical to {s['name']} in {srcs}; "
                          "verify the callers before relying on it", "hypothesis", actor="re_transfer")
    total = len(functions) if functions else None
    named = len(out["recorded"]) + len(out["confirmed"])
    return out | {"arch": arch, "library": len(lib["sigs"]), "duplicates": m["duplicates"],
                  "skipped_ambiguous": m["skipped_ambiguous"], "named": named,
                  "coverage": round(named / total, 4) if total else None, "seconds": round(time.time() - t0, 3)}
