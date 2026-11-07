// Find code that references the id tables the static scan turned up, and decompile it.
//@category Agent
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

public class TableRefs extends GhidraScript {
    @Override
    protected void run() throws Exception {
        java.util.Set<Function> fns = new java.util.LinkedHashSet<>();
        for (long lo = 0xa04000L; lo < 0xa09000L; lo += 4) {
            Address a = toAddr(lo);
            for (Reference r : getReferencesTo(a)) {
                Function f = getFunctionContaining(r.getFromAddress());
                if (f != null) fns.add(f);
            }
        }
        println("functions referencing the table region: " + fns.size());
        DecompInterface d = new DecompInterface();
        d.openProgram(currentProgram);
        int shown = 0;
        for (Function f : fns) {
            println("==== " + f.getName() + " @ " + f.getEntryPoint());
            if (shown++ < 6) {
                DecompileResults res = d.decompileFunction(f, 60, monitor);
                if (res != null && res.decompileCompleted()) {
                    println(res.getDecompiledFunction().getC());
                }
            }
        }
    }
}
