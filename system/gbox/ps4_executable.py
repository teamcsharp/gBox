"""Read PS4 ELF64 and decrypted SELF files into an analysis-only ELF.

Container facts follow shadPS4's src/core/loader/elf.{h,cpp}. No keys,
decryption, executable patching or game-specific model conversion are provided.
The original stays untouched; SCE types are normalized only in the Ghidra copy.
"""
import struct
from pathlib import Path


SELF_MAGIC = b"\x4f\x15\x3d\x1d"
PROCESSOR = "x86:LE:64:default"
MAX_IMAGE = 1024 * 1024 * 1024
SCE_TYPES = {0xFE00: 2, 0xFE10: 3, 0xFE18: 3}
PT_SCE_RELRO = 0x61000010
# shadPS4 src/core/module.cpp reads these with TryLoadSegment, tolerating
# absent metadata. Runtime LOAD/RELRO/DYNAMIC/DYNLIBDATA payloads are mandatory.
OPTIONAL_SELF_METADATA = {0x6FFFFF00: "PT_SCE_COMMENT", 0x6FFFFF01: "PT_SCE_LIBVERSION"}


def _span(data: bytes, offset: int, size: int, label: str) -> bytes:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError(f"Truncated PS4 {label}")
    return data[offset:offset + size]


def _headers(data: bytes, start: int = 0) -> tuple[tuple, list[tuple]]:
    header = struct.unpack("<16sHHIQQQIHHHHHH", _span(data, start, 64, "ELF header"))
    ident, kind, machine, version, entry, phoff, shoff, flags, ehsize, phsize, phnum, shsize, shnum, shstr = header
    if ident[:7] != b"\x7fELF\x02\x01\x01" or machine != 62 or version != 1:
        raise ValueError("PS4 analysis requires a 64-bit little-endian x86-64 ELF")
    if kind not in (*SCE_TYPES, 2, 3) or ehsize != 64 or phsize != 56 or not 0 < phnum < 4096:
        raise ValueError("Unsupported PS4 ELF header or program-header table")
    if phoff < 64 or phoff + phnum * phsize > MAX_IMAGE:
        raise ValueError("Invalid PS4 ELF program-header offset")
    _span(data, start + phoff, phnum * phsize, "program-header table")
    programs = [struct.unpack_from("<II6Q", data, start + phoff + i * phsize) for i in range(phnum)]
    for ptype, pflags, offset, va, pa, filesz, memsz, align in programs:
        if offset + filesz > MAX_IMAGE or va + memsz > 1 << 64:
            raise ValueError("PS4 ELF segment exceeds analysis bounds")
        if ptype in (1, PT_SCE_RELRO) and filesz > memsz:
            raise ValueError("PS4 ELF load segment exceeds its memory size")
    if not any(p[0] in (1, PT_SCE_RELRO) and p[6] for p in programs):
        raise ValueError("PS4 ELF has no loadable segments")
    return header, programs


def analysis_image(raw: bytes) -> tuple[bytes, dict]:
    """Validate a native file and return (ELF, provenance notes).

    SELF payloads must be already decrypted, uncompressed and complete. Absent
    unallocated SCE comment/version metadata is omitted with provenance.
    Reconstructed files retain ELF virtual addresses;
    these are link-time addresses, not a claim about a running process's mappings.
    """
    if len(raw) > MAX_IMAGE:
        raise ValueError("PS4 executable exceeds the 1 GiB analysis limit")
    is_self = raw.startswith(SELF_MAGIC)
    start, blocks = 0, []
    if is_self:
        _span(raw, 0, 32, "SELF header")
        if raw[4:10] != b"\x00\x01\x01\x12\x01\x01":
            raise ValueError("Unsupported PS4 SELF header")
        count = struct.unpack_from("<H", raw, 0x18)[0]
        if not 0 < count < 4096:
            raise ValueError("Invalid PS4 SELF segment count")
        start = 32 + count * 32
        _span(raw, 32, count * 32, "SELF segment table")
        blocks = [struct.unpack_from("<4Q", raw, 32 + i * 32) for i in range(count)]
    elif not raw.startswith(b"\x7fELF"):
        raise ValueError("Expected a PS4 ELF or decrypted SELF executable (eboot.bin/.prx/.sprx)")
    header, programs = _headers(raw, start)
    phoff, phsize, phnum = header[5], header[9], header[10]
    notes = ["Analysis addresses are ELF virtual addresses; correlate the loaded module before live memory edits.",
             "SCE dynamic imports/relocations are not resolved by this converter; runtime hooks require separate validation."]
    if is_self:
        head_end = phoff + phnum * phsize
        size = max(head_end, *(p[2] + p[5] for p in programs))
        image = bytearray(size)
        image[:64] = raw[start:start + 64]
        image[phoff:head_end] = raw[start + phoff:start + head_end]
        covered = [(0, 64), (phoff, head_end)]
        seen = set()
        for flags, offset, length, memory_size in blocks:
            if not flags & 0x800:
                continue
            index = flags >> 20 & 0xFFF
            if index >= len(programs) or index in seen:
                raise ValueError("Invalid or duplicate PS4 SELF segment index")
            seen.add(index)
            if flags & 2:
                raise ValueError("Encrypted SELF segment: provide an already decrypted executable dump")
            if flags & 8:
                raise ValueError("Compressed SELF segment: provide an uncompressed executable dump")
            _ptype, _pflags, dest, _va, _pa, wanted, _memsz, _align = programs[index]
            if length < wanted or memory_size < wanted:
                raise ValueError("Truncated PS4 SELF segment payload")
            payload = _span(raw, offset, length, "SELF segment payload")[:wanted]
            for lo, hi in covered:
                a, b = max(lo, dest), min(hi, dest + wanted)
                if a < b and image[a:b] != payload[a - dest:b - dest]:
                    raise ValueError("Conflicting PS4 SELF segment contents")
            image[dest:dest + wanted] = payload
            covered.append((dest, dest + wanted))
        merged = []
        for lo, hi in sorted(covered):
            if merged and lo <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(hi, merged[-1][1]))
            else:
                merged.append((lo, hi))
        omitted = set()
        for index, p in enumerate(programs):
            if p[5] and not any(lo <= p[2] and p[2] + p[5] <= hi for lo, hi in merged):
                if p[0] in OPTIONAL_SELF_METADATA and p[1] == 0 and p[6] == 0:
                    # Do not present zero-filled, nonexistent metadata as source
                    # bytes. A PT_NULL header leaves every runtime segment intact.
                    struct.pack_into("<II6Q", image, phoff + index * phsize, *([0] * 8))
                    omitted.add(index)
                    notes.append(f"Unavailable {OPTIONAL_SELF_METADATA[p[0]]} metadata "
                                 f"(program header {index}, {p[5]} bytes) omitted as PT_NULL "
                                 "in the analysis copy.")
                    continue
                raise ValueError("Incomplete PS4 SELF: a program segment has no decrypted payload")
        if omitted:
            size = max(head_end, *(p[2] + p[5] for i, p in enumerate(programs) if i not in omitted))
            del image[size:]
        # SELF's embedded section table offsets do not identify reconstructed data.
        struct.pack_into("<Q", image, 40, 0)
        struct.pack_into("<HHH", image, 58, 0, 0, 0)
        notes.append("Reconstructed decrypted SELF segments; section headers omitted in the analysis copy.")
    else:
        for p in programs:
            _span(raw, p[2], p[5], "ELF segment payload")
        if header[12]:
            if header[11] != 64:
                raise ValueError("Unsupported PS4 ELF section-header size")
            _span(raw, header[6], header[12] * header[11], "section-header table")
        image = bytearray(raw)
    if header[1] in SCE_TYPES:
        struct.pack_into("<H", image, 16, SCE_TYPES[header[1]])
        notes.append("SCE executable type normalized to standard ELF in the analysis copy.")
    for index, p in enumerate(programs):
        if p[0] == PT_SCE_RELRO:
            struct.pack_into("<I", image, phoff + index * phsize, 1)
            notes.append("SCE RELRO mapped as PT_LOAD for Ghidra analysis.")
    loads = [p for p in programs if p[0] in (1, PT_SCE_RELRO) and p[6]]
    return bytes(image), {"format": "PS4 decrypted SELF -> ELF64" if is_self else "PS4 ELF64",
                          "base": min(p[3] for p in loads), "entry": header[4], "size": len(raw), "notes": notes}


def read_executable(path: Path) -> tuple[bytes, bytes, dict]:
    path = Path(path)
    if path.is_dir():
        path = path / "eboot.bin"
    if path.stat().st_size > MAX_IMAGE:
        raise ValueError("PS4 executable exceeds the 1 GiB analysis limit")
    raw = path.read_bytes()
    image, info = analysis_image(raw)
    return image, raw, info | {"source_file": path.name}
