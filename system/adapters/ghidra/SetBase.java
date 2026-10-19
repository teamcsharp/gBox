// gBox: N64 raw-import fixup - set image base 0x80000000 and entry 0x80000400.
// Usage: analyzeHeadless <proj> kigold -import rom.z64 -processor MIPS:BE:32:default \
//        -scriptPath <worktree>/system/adapters/ghidra -preScript SetBase.java \
//        -postScript DecompileAll.java out.c entry:0x80000400 \
//        -postScript ExportAnalysis.java out.json
// @category gBox
import ghidra.app.script.GhidraScript;
import ghidra.program.model.mem.MemoryBlock;

public class SetBase extends GhidraScript {
    @Override
    public void run() throws Exception {
        long base = 0x80000000L;
        MemoryBlock blk = currentProgram.getMemory().getBlock(currentProgram.getMinAddress());
        if (blk == null) {
            println("SetBase: no memory block; abort");
            return;
        }
        if (blk.getStart().getOffset() != base) {
            currentProgram.setImageBase(toAddr(base), true);
            blk = currentProgram.getMemory().getBlock(currentProgram.getMinAddress());
            println("SetBase: relocated image base to " + blk.getStart());
        } else {
            println("SetBase: image base already " + blk.getStart());
        }
        currentProgram.getSymbolTable().addExternalEntryPoint(toAddr(0x80000400L));
        println("SetBase: external entry 0x80000400");
    }
}
