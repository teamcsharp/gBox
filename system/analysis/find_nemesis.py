# Locate the Nemesis decompressor and related data references in a Genesis ROM.
# @category Analysis
# @keybinding
# @menupath
# @toolbar

from ghidra.program.model.lang import OperandType
from ghidra.program.model.symbol import SymbolType

def report(msg):
    print("[NEMESIS] " + msg)

# 1. Identify the Nemesis decompressor by a distinctive instruction sequence.
#    The M68k code from Sega Retro starts like:
#      lea     (Nem_PCD_WriteRowToVDP).l,a3
#      lea     (VDP_data_port).l,a4
#      bra.s   Nem_Decomp_Main
#    We look for the pair of LEA (xxx).l,A3 followed by LEA (xxx).l,A4 and a short branch.
nemesis_entry = None
for block in currentProgram.getMemory().getBlocks():
    if not block.isExecute():
        continue
    start = block.getStart()
    end = block.getEnd()
    addr = start
    while addr < end:
        inst = getInstructionAt(addr)
        if inst is None:
            addr = addr.add(1)
            continue
        # Look for lea (xxx).l,a3
        if (inst.getMnemonicString().lower().startswith("lea")
                and inst.getDefaultOperandRepresentation(1) == "A3"
                and inst.getDefaultOperandRepresentation(0).startswith("0x")):
            next_inst = inst.getNext()
            if (next_inst is not None
                    and next_inst.getMnemonicString().lower().startswith("lea")
                    and next_inst.getDefaultOperandRepresentation(1) == "A4"):
                report("candidate Nemesis entry at " + addr.toString())
                nemesis_entry = addr
                break
        addr = inst.getNext().getAddress() if inst.getNext() else addr.add(inst.getLength())
    if nemesis_entry:
        break

if nemesis_entry:
    report("Nemesis decompressor entry: " + nemesis_entry.toString())
else:
    report("Nemesis decompressor not found by signature")

# 2. Find functions that reference the decompressor.
if nemesis_entry:
    refs = getReferencesTo(nemesis_entry)
    report("references to decompressor entry: " + str(len(refs)))
    for r in refs[:20]:
        src = r.getSourceAddress()
        fn = getFunctionContaining(src)
        if fn:
            report("  call from " + fn.getName() + " @ " + src.toString())
        else:
            report("  call from " + src.toString())

# 3. Search for potential Nemesis stream headers: word tile count with high-bit
#    indicating XOR mode.  We only report word-aligned offsets in ROM where the
#    count is in a plausible range (4..1024 tiles).
rom = currentProgram.getMemory()
base = rom.getMinAddress()
for block in rom.getBlocks():
    if block.isExecute():
        continue
    addr = block.getStart()
    end = block.getEnd()
    while addr < end.subtract(1):
        word = getShort(addr)
        if word <= 0:
            addr = addr.add(2)
            continue
        tile_count = word & 0x7FFF
        if 4 <= tile_count <= 1024:
            # Also require next byte (initial palette index) not 0xFF and
            # within a non-executable region.
            first_table = getByte(addr.add(2))
            if 0 <= first_table <= 0x0F or (0x10 <= first_table <= 0x7F):
                report("possible Nemesis header at " + addr.toString()
                       + " tiles=" + hex(tile_count)
                       + " xor=" + str(bool(word & 0x8000)))
                # Only emit the first few to keep output bounded.
                if addr.subtract(block.getStart()) > 0x20000:
                    break
        addr = addr.add(2)

report("analysis complete")
