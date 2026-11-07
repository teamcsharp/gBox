// Decompile specific functions by entry address, for following the resource loader by hand.
//@category Agent
import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;

public class Decomp extends GhidraScript {
    @Override
    protected void run() throws Exception {
        long[] targets = {0x004f5e50L, 0x004f7b40L, 0x004f4c00L};
        DecompInterface d = new DecompInterface();
        d.openProgram(currentProgram);
        for (long target : targets) {
            Address at = toAddr(target);
            Function f = getFunctionAt(at);
            if (f == null) { println("no function at " + at); continue; }
            println("==== " + f.getName() + " @" + f.getEntryPoint());
            DecompileResults res = d.decompileFunction(f, 180, monitor);
            if (res == null || !res.decompileCompleted()) {
                println("   (failed: " + (res == null ? "null" : res.getErrorMessage()) + ")");
                continue;
            }
            String c = res.getDecompiledFunction().getC();
            println(c.length() > 9000 ? c.substring(0, 9000) + "\n...truncated" : c);
        }
    }
}
