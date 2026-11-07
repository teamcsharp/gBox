"""Where does the module actually read offset 0x3C2? Scan the code for LDRH/LDRSH with that immediate.

`RE4_REASON` says the health lives at `unit+0x3c2`. Instead of trusting that, find the instructions that use it: among
the hits, the one whose base register comes from a global pointer is the health read, and the offsets beside it are the
structure's neighbours.
"""
import os
import struct

ELF = os.path.expanduser("~/gBox_alt/gbox-cache/exefs/010099A00BC1E000/main.elf")
image = open(ELF, "rb").read()

# ELF program headers -> the .text segment (vaddr 0, size 0x655850)
e_phoff = struct.unpack_from("<Q", image, 0x20)[0]
e_phnum = struct.unpack_from("<H", image, 0x38)[0]
segments = []
for index in range(e_phnum):
    p_type, _flags, p_offset, p_vaddr, _paddr, p_filesz, _memsz, _align = \
        struct.unpack_from("<IIQQQQQQ", image, e_phoff + index * 56)
    if p_type == 1:
        segments.append((p_vaddr, p_offset, p_filesz))
text_vaddr, text_off, text_size = segments[0]
print("text: vaddr %#x file %#x size %#x" % (text_vaddr, text_off, text_size))


def immediate(word: int) -> int:
    return (word >> 10) & 0xFFF


def kind(word: int) -> str | None:
    top = word & 0xFFC00000
    return {0x79400000: "LDRH", 0x79800000: "LDRSH", 0x79000000: "STRH"}.get(top)


for wanted in (0x3C2, 0x320, 0x322):
    hits = []
    for offset in range(0, text_size - 4, 4):
        word = struct.unpack_from("<I", image, text_off + offset)[0]
        what = kind(word)
        # a halfword load scales its imm12 by 2 (a 64-bit LDR scales by 8: measured 0x158 at imm12 0x2b)
        if what and immediate(word) == wanted >> 1:
            hits.append((text_vaddr + offset, what, (word >> 5) & 0x1F, word & 0x1F))
    print("offset %#x: %d instruction(s)" % (wanted, len(hits)))
    for address, what, rn, rt in hits[:8]:
        print("   %#x %-6s [x%d], #%#x -> w%d" % (address, what, rn, wanted, rt))
