// gBox: decompile the functions containing the given addresses (hex args after out path).
// Args: <out.txt> <addr> [addr...]
// @category gBox
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import java.io.*;
import java.util.*;

public class DecompAt extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter pw = new PrintWriter(new FileWriter(a[0]));
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        Set<Address> seen = new HashSet<>();
        for (int i = 1; i < a.length; i++) {
            Address ad = toAddr(a[i]);
            Function f = getFunctionContaining(ad);
            if (f == null) { f = createFunction(ad, null); }
            if (f == null) { pw.println("NOFUNC " + a[i]); continue; }
            if (!seen.add(f.getEntryPoint())) continue;
            pw.println("==== " + f.getName() + "@" + f.getEntryPoint() + " body " + f.getBody().getMinAddress() + "-" + f.getBody().getMaxAddress() + " (from " + a[i] + ")");
            for (Function cf : f.getCallingFunctions(monitor)) pw.println("  CALLER " + cf.getName() + "@" + cf.getEntryPoint());
            DecompileResults res = dec.decompileFunction(f, 120, monitor);
            pw.println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : res.getErrorMessage());
        }
        pw.close();
    }
}
