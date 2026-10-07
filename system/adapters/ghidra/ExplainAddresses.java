// gBox: explain runtime addresses statically. Args: <out.json> <hexaddr> [<hexaddr> ...]
// For each address: containing function (name, entry, body range), decompiled C, and callers.
// @category gBox
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class ExplainAddresses extends GhidraScript {
    private String q(String s) {
        StringBuilder b = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            if (c == '"' || c == '\\') b.append('\\').append(c);
            else if (c == '\n') b.append("\\n");
            else if (c < 0x20 || c == 0x7f) b.append(String.format("\\u%04x", (int) c));   // every control char
            else b.append(c);
        }
        return b.append('"').toString();
    }
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        // runtime register values (e.g. r13:805da600 r2:805dfd00 from the live debugger) make SDA-relative code decompile
        // (':' not '=': Windows analyzeHeadless.bat splits arguments on '=')
        for (int i = 1; i < args.length; i++) {
            if (!args[i].contains(":")) continue;
            String[] kv = args[i].split(":");
            ghidra.program.model.lang.Register reg = currentProgram.getRegister(kv[0]);
            if (reg == null) continue;
            int tx = currentProgram.startTransaction("gbox context");
            for (ghidra.program.model.mem.MemoryBlock blk : currentProgram.getMemory().getBlocks()) {
                if (!blk.isInitialized()) continue;                 // one range per loaded block (same address space)
                currentProgram.getProgramContext().setValue(reg, blk.getStart(), blk.getEnd(),
                    new java.math.BigInteger(kv[1].replace("0x", ""), 16));
            }
            currentProgram.endTransaction(tx, true);
        }
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        StringBuilder out = new StringBuilder("{\"program\":" + q(currentProgram.getName()) + ",\"language\":" + q(currentProgram.getLanguageID().toString()) + ",\"addresses\":[");
        boolean first = true;
        for (int i = 1; i < args.length; i++) {
            if (args[i].contains(":")) continue;
            Address a = toAddr(Long.parseLong(args[i].replace("0x", ""), 16));
            Function f = getFunctionContaining(a);
            if (f == null) {                                   // not discovered by auto-analysis: create one at the nearest prologue
                Address s = a;
                for (int k = 0; k < 4096 && f == null; k += 4) {
                    Instruction ins = getInstructionAt(s);
                    if (ins != null && ins.getMnemonicString().equals("stwu")) { f = createFunction(s, null); break; }
                    s = s.subtract(4);
                }
            }
            if (!first) out.append(",");
            first = false;
            out.append("{\"address\":" + q(a.toString()));
            if (f != null) {
                out.append(",\"function\":" + q(f.getName()) + ",\"entry\":" + q(f.getEntryPoint().toString()));
                out.append(",\"body\":[" + q(f.getBody().getMinAddress().toString()) + "," + q(f.getBody().getMaxAddress().toString()) + "]");
                StringBuilder callers = new StringBuilder();
                for (Reference r : getReferencesTo(f.getEntryPoint())) {
                    Function c = getFunctionContaining(r.getFromAddress());
                    if (callers.length() > 0) callers.append(",");
                    callers.append(q(r.getFromAddress() + (c != null ? " in " + c.getName() : "")));
                }
                out.append(",\"callers\":[" + callers + "]");
                Instruction ins = getInstructionAt(a);
                out.append(",\"instruction\":" + q(ins != null ? ins.toString() : "?"));
                DecompileResults res = dec.decompileFunction(f, 300, monitor);
                String c = res.decompileCompleted() ? res.getDecompiledFunction().getC() : ("decompile failed: " + res.getErrorMessage());
                out.append(",\"decompiled\":" + q(c.length() > 6000 ? c.substring(0, 6000) : c));
            }
            out.append("}");
        }
        out.append("]}");
        try (Writer w = new FileWriter(args[0])) { w.write(out.toString()); }
        println("gBox ExplainAddresses wrote " + args[0]);
    }
}
