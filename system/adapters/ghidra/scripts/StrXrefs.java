// Find the resource loader: whoever references ".udas" / ".fen" / "imagepack" is on the path a texture id travels.
//@category Agent
import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

public class StrXrefs extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] needles = {".udas", ".fen", "imagepack", "pack", ".awb"};
        DecompInterface d = new DecompInterface();
        d.openProgram(currentProgram);
        java.util.Set<Function> seen = new java.util.LinkedHashSet<>();
        for (Data data : currentProgram.getListing().getDefinedData(true)) {
            Object value = data.getValue();
            if (!(value instanceof String)) { continue; }
            String text = (String) value;
            boolean wanted = false;
            for (String needle : needles) { if (text.contains(needle)) { wanted = true; } }
            if (!wanted || text.length() > 200) { continue; }
            Reference[] refs = getReferencesTo(data.getAddress());
            if (refs.length == 0) { continue; }
            println("STRING " + data.getAddress() + " \"" + text.replace("\n", "\\n") + "\" refs=" + refs.length);
            for (Reference r : refs) {
                Function f = getFunctionContaining(r.getFromAddress());
                println("   from " + r.getFromAddress() + " type=" + r.getReferenceType()
                        + (f == null ? " (no function)" : " in " + f.getName() + " @" + f.getEntryPoint()));
                if (f != null) { seen.add(f); }
            }
        }
        println("distinct functions referencing such strings: " + seen.size());
        int shown = 0;
        for (Function f : seen) {
            if (shown++ >= 4) { break; }
            println("==== decompile " + f.getName() + " @" + f.getEntryPoint());
            DecompileResults res = d.decompileFunction(f, 120, monitor);
            if (res == null) { println("   (no result)"); continue; }
            if (!res.decompileCompleted()) { println("   (failed: " + res.getErrorMessage() + ")"); continue; }
            String c = res.getDecompiledFunction().getC();
            println(c.length() > 6000 ? c.substring(0, 6000) + "\n...truncated" : c);
        }
    }
}
