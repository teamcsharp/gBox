"""NSO images as ELF, so ordinary binary tools can read a Switch executable.

`hactool -t nso --uncompressed` writes the sections out *with the 0x100-byte NSO header still in front*. That single fact
is easy to miss and it matters: every address in the output is off by 0x100 from its real virtual address. Measured on
RE4 Switch's `main`: the `".udas"` literal sits at file offset `0x6d08ca`, and the instruction that reaches it adds
`0x7ca` to the page base `0x6d0000` - i.e. the real address is **`0x6d07ca`**. Assuming file offset == vaddr made the
literal look unreferenced for two rounds.

This module builds an ELF64/AArch64 image from that output, mapping each section at the virtual address the NSO header
declares. A converter rather than a loader hack: REA and other tools open ELF, and Ghidra's raw import can then be
replaced by a correct image.
"""
import struct

ELF_HEADER = 64
PHDR = 56
PT_LOAD = 1
SHT = 0x04000000 | 0x0  # unused; kept for clarity in callers reading the constants
MACHINE_AARCH64 = 183
ET_EXEC = 2

# the NSO0 header, as measured from a real file
NSO_MAGIC = b"NSO0"
FIELDS = {"flags": 0x0C,
          "text_file": 0x10, "text_memory": 0x14, "text_size": 0x18, "module_name": 0x1C,
          "rodata_file": 0x20, "rodata_memory": 0x24, "rodata_size": 0x28,
          # the data group is NOT laid out like text and rodata: 0x2C is a flag, 0x30 is the compressed size, and the
          # memory offset/size/bss sit at 0x34/0x38/0x3C (measured: reading them one word early gives .rwdata a "size"
          # of 0xae2000, which is its own memory offset - the mistake this comment records)
          "data_file": 0x30, "data_memory": 0x34, "data_size": 0x38, "bss_size": 0x3C}


class NsoError(RuntimeError):
    """Not an NSO image, or a section lies outside the file."""


def header(image: bytes) -> dict:
    """The NSO header fields, or NsoError. A `hactool --uncompressed` file has this header at offset 0 too."""
    if len(image) < 0x100 or image[:4] != NSO_MAGIC:
        raise NsoError("not an NSO0 image")
    return {name: struct.unpack_from("<I", image, offset)[0] for name, offset in FIELDS.items()}


def sections(image: bytes, *, payload_offset: int = 0x100) -> list[dict]:
    """The three loadable sections with the slice of `image` that holds each, plus .bss as memory-only.

    `payload_offset` is where the section bytes begin. It is 0x100 for `hactool --uncompressed` output (the header is
    kept) and 0 for an image already stripped of the header.
    """
    head = header(image)
    rows = []
    for name in ("text", "rodata", "data"):
        vaddr = head[f"{name}_memory"]
        size = head[f"{name}_size"]
        start = payload_offset + vaddr
        if start > len(image):
            raise NsoError(f"the {name} section starts past the end of the file")
        rows.append({"name": {".text": ".text", "text": ".text", "rodata": ".rodata", "data": ".rwdata"}[name],
                     "vaddr": vaddr, "size": size, "offset": start,
                     "data": image[start:start + size],
                     "short": max(0, size - max(0, len(image) - start))})
    if head.get("bss_size"):
        rows.append({"name": ".bss", "vaddr": head["data_memory"] + head["data_size"],
                     "size": head["bss_size"], "offset": None, "data": b"", "short": 0})
    return rows


def to_elf(image: bytes, *, payload_offset: int = 0x100, entry: int = 0) -> bytes:
    """An ELF64/AArch64 executable whose PT_LOAD segments carry the NSO's sections at their declared addresses."""
    rows = sections(image, payload_offset=payload_offset)
    loadable = [row for row in rows if row["offset"] is not None]
    if not loadable:
        raise NsoError("no loadable sections")
    file_base = 0x1000                                  # one page of ELF header + phdrs, then the segments
    cursor = file_base
    placed = []
    for row in loadable:
        pad = (-cursor) % 0x1000
        cursor += pad
        placed.append({**row, "file_offset": cursor, "pad": pad})
        cursor += len(row["data"])
    total = cursor

    out = bytearray(total)
    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\0" * 8
    struct.pack_into("<16sHHIQQQIHHHHHH", out, 0, ident, ET_EXEC, MACHINE_AARCH64, 1, entry,
                     64, 0, 0, ELF_HEADER, PHDR, len(placed), 64, 0, 0)
    for index, row in enumerate(placed):
        struct.pack_into("<IIQQQQQQ", out, ELF_HEADER + index * PHDR, PT_LOAD, 5, row["file_offset"],
                         row["vaddr"], row["vaddr"], len(row["data"]), len(row["data"]), 0x1000)
        out[row["file_offset"]:row["file_offset"] + len(row["data"])] = row["data"]
    return bytes(out)


def section_table(elf: bytes) -> list[dict]:
    """Read back the PT_LOAD segments - the check that the image says what it was meant to say."""
    if len(elf) < ELF_HEADER or elf[:4] != b"\x7fELF":
        raise NsoError("not an ELF image")
    e_phoff = struct.unpack_from("<Q", elf, 0x20)[0]
    e_phnum = struct.unpack_from("<H", elf, 0x38)[0]
    rows = []
    for index in range(e_phnum):
        p_type, p_flags, p_offset, p_vaddr, _paddr, p_filesz, p_memsz, _align = \
            struct.unpack_from("<IIQQQQQQ", elf, e_phoff + index * PHDR)
        if p_type == PT_LOAD:
            rows.append({"vaddr": p_vaddr, "filesz": p_filesz, "memsz": p_memsz, "offset": p_offset})
    return rows
