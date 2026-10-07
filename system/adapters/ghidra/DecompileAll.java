// gBox: decompile every function of a program to one C file (for grepping offline).
// Args: <out.c> [gp:<hex>] [reg:<name>:<hex>] [entry:<hex>] [jalscan]
//   reg:<name>:<hex>  set any register program-wide, e.g. GameCube/Wii SDA bases reg:r13:804babe0 reg:r2:804c2420
//   gp:<hex>     set the MIPS $gp register value program-wide (PS1 games: from the crt0 `lui/addiu gp`)
//   entry:<hex>  disassemble + create a function there (raw-binary imports have no entry point)
//   jalscan      MIPS raw images: create a function at every in-image `jal` target, then re-analyze
// Typical PS-X EXE use (no PSX loader installed): strip the 0x800-byte header, import as raw
//   -processor MIPS:LE:32:default -loader BinaryLoader -loader-baseAddr <t_addr>
// @category gBox
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import java.io.*;
import java.math.BigInteger;

public class DecompileAll extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        boolean jalscan = false;
        for (int i = 1; i < args.length; i++) {
            String a = args[i];
            if (a.startsWith("gp:")) {
                ghidra.program.model.lang.Register reg = currentProgram.getRegister("gp");
                for (MemoryBlock blk : currentProgram.getMemory().getBlocks())
                    currentProgram.getProgramContext().setValue(reg, blk.getStart(), blk.getEnd(),
                        new BigInteger(a.substring(3).replace("0x", ""), 16));
            } else if (a.startsWith("reg:")) {
                String[] kv = a.substring(4).split(":");
                ghidra.program.model.lang.Register reg = currentProgram.getRegister(kv[0]);
                for (MemoryBlock blk : currentProgram.getMemory().getBlocks())
                    currentProgram.getProgramContext().setValue(reg, blk.getStart(), blk.getEnd(),
                        new BigInteger(kv[1].replace("0x", ""), 16));
            } else if (a.startsWith("entry:")) {
                Address e = toAddr(Long.parseLong(a.substring(6).replace("0x", ""), 16));
                disassemble(e);
                createFunction(e, null);
            } else if (a.equals("jalscan")) {
                jalscan = true;
            }
        }
        if (jalscan) {
            Memory mem = currentProgram.getMemory();
            int made = 0;
            for (MemoryBlock blk : mem.getBlocks()) {
                if (!blk.isInitialized()) continue;
                long lo = blk.getStart().getOffset(), hi = blk.getEnd().getOffset();
                for (Address p = blk.getStart(); p.getOffset() + 4 <= hi; p = p.add(4)) {
                    int w = mem.getInt(p);
                    if ((w >>> 26) != 3) continue;                         // jal
                    long t = ((p.getOffset() + 4) & 0xF0000000L) | ((long) (w & 0x03FFFFFF) << 2);
                    if (t < lo || t > hi) continue;
                    Address ta = toAddr(t);
                    if (getFunctionAt(ta) != null) continue;
                    if (getInstructionAt(ta) == null && !disassemble(ta)) continue;
                    if (createFunction(ta, null) != null) made++;
                }
            }
            println("gBox DecompileAll: jalscan created " + made + " functions");
            analyzeChanges(currentProgram);
        }
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        int n = 0;
        try (Writer w = new BufferedWriter(new FileWriter(args[0]))) {
            for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
                if (monitor.isCancelled()) break;
                DecompileResults res = dec.decompileFunction(f, 120, monitor);
                w.write("// ==== FUNC " + f.getEntryPoint() + " " + f.getName() + "\n");
                w.write(res.decompileCompleted() ? res.getDecompiledFunction().getC() : ("// decompile failed: " + res.getErrorMessage() + "\n"));
                n++;
            }
        }
        println("gBox DecompileAll wrote " + n + " functions to " + args[0]);
    }
}
