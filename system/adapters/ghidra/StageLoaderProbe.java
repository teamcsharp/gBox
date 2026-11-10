// gBox: MGS2 SLUS_201.44 - locate stage.dat loader and callers (decompiled).
// Args: <out.txt>
// @category gBox
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.util.DefinedDataIterator;
import ghidra.program.model.data.StringDataInstance;
import java.io.*;
import java.util.*;

public class StageLoaderProbe extends GhidraScript {
    @Override
    public void run() throws Exception {
        String out = getScriptArgs()[0];
        PrintWriter pw = new PrintWriter(new FileWriter(out));
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        Set<Address> seen = new HashSet<>();
        Listing L = currentProgram.getListing();
        for (ghidra.program.model.listing.Data d : L.getDefinedData(true)) {
            if (!d.hasStringValue()) continue;
            String s = StringDataInstance.getStringDataInstance(d).getStringValue();
            if (s == null) continue;
            String l = s.toLowerCase();
            if (!(l.contains("stage.dat") || l.contains("stage") && l.length() < 24 && l.contains(".dat"))) continue;
            pw.println("STRING " + d.getAddress() + " " + s);
            for (Reference r : getReferencesTo(d.getAddress())) {
                Function f = getFunctionContaining(r.getFromAddress());
                pw.println("  XREF " + r.getFromAddress() + " fn=" + (f == null ? "none" : f.getName() + "@" + f.getEntryPoint()));
                if (f == null || !seen.add(f.getEntryPoint())) continue;
                DecompileResults res = dec.decompileFunction(f, 90, monitor);
                String c = res.decompileCompleted() ? res.getDecompiledFunction().getC() : res.getErrorMessage();
                pw.println("---- " + f.getName() + "@" + f.getEntryPoint() + " ----");
                pw.println(c.length() > 9000 ? c.substring(0, 9000) : c);
                for (Function cf : f.getCallingFunctions(monitor)) pw.println("  CALLER " + cf.getName() + "@" + cf.getEntryPoint());
            }
        }
        pw.close();
        println("done " + out);
    }
}
