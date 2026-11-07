// Does the decompiler produce ANY C on this build? Try the smallest functions and report lengths and errors.
//@category Agent
import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;

public class DecompProbe extends GhidraScript {
    @Override
    protected void run() throws Exception {
        DecompInterface d = new DecompInterface();
        d.openProgram(currentProgram);
        int tried = 0;
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            long size = f.getBody().getNumAddresses();
            if (size < 16 || size > 400) { continue; }
            DecompileResults res = d.decompileFunction(f, 60, monitor);
            String c = (res != null && res.decompileCompleted()) ? res.getDecompiledFunction().getC() : "";
            println("fn " + f.getName() + " @" + f.getEntryPoint() + " size=" + size
                    + " completed=" + (res != null && res.decompileCompleted())
                    + " c_len=" + c.length()
                    + " err=" + (res == null ? "null" : res.getErrorMessage()));
            if (c.length() > 0) { println(c.substring(0, Math.min(600, c.length()))); }
            if (++tried >= 4) { break; }
        }
        println("tried " + tried);
    }
}
