// Search the loaded image for a literal byte string and report what references it - no reliance on defined data.
//@category Agent
import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Reference;

public class MemSearch extends GhidraScript {
    private static final String[] NEEDLES = {".fen", "imagepack", ".udas", ".acb"};

    private Address find(byte[] hay, byte[] needle) {
        outer:
        for (int i = 0; i + needle.length <= hay.length; i++) {
            for (int j = 0; j < needle.length; j++) { if (hay[i + j] != needle[j]) { continue outer; } }
            return null;
        }
        return null;
    }

    @Override
    protected void run() throws Exception {
        Memory memory = currentProgram.getMemory();
        DecompInterface d = new DecompInterface();
        d.openProgram(currentProgram);
        int found = 0;
        for (String needle : NEEDLES) {
            byte[] target = needle.getBytes("US-ASCII");
            for (MemoryBlock block : memory.getBlocks()) {
                if (!block.isInitialized()) { continue; }
                byte[] hay = new byte[(int) block.getSize()];
                try { block.getBytes(block.getStart(), hay); } catch (Exception e) { continue; }
                outer:
                for (int i = 0; i + target.length <= hay.length; i++) {
                    for (int j = 0; j < target.length; j++) { if (hay[i + j] != target[j]) { continue outer; } }
                    Address at = block.getStart().add(i);
                    Reference[] refs = getReferencesTo(at);
                    StringBuilder where = new StringBuilder();
                    for (Reference r : refs) {
                        Function f = getFunctionContaining(r.getFromAddress());
                        where.append(" ").append(r.getFromAddress())
                             .append(f == null ? "(?)" : "(" + f.getName() + ")");
                    }
                    println("FOUND " + needle + " at " + at + " refs=" + refs.length + where);
                    if (refs.length > 0 && found++ < 3) {
                        Function f = getFunctionContaining(refs[0].getFromAddress());
                        if (f != null) {
                            DecompileResults res = d.decompileFunction(f, 120, monitor);
                            println("==== " + f.getName() + " @" + f.getEntryPoint());
                            if (res != null && res.decompileCompleted()) {
                                String c = res.getDecompiledFunction().getC();
                                println(c.length() > 5000 ? c.substring(0, 5000) + "\n...truncated" : c);
                            } else {
                                println("   (decompile failed: " + (res == null ? "null" : res.getErrorMessage()) + ")");
                            }
                        }
                    }
                    break outer;
                }
            }
        }
        println("done, " + found + " decompiled");
    }
}
