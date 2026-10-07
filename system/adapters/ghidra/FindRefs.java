// gBox: references to addresses (data tables, strings, functions). Args: <out.json> <hexaddr>[-<hexend>] ...
// For each target (or range): every referencing instruction with its function (name, entry), plus, for code that
// builds the address in registers (PPC lis/addi pairs Ghidra didn't turn into references), a scan of the immediate
// operands. Output: {"targets": [{"addr", "refs": [{"from", "function", "entry", "type"}]}]}
// @category gBox
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.scalar.Scalar;
import java.io.*;
import java.util.*;

public class FindRefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        StringBuilder out = new StringBuilder("{\"targets\": [");
        Listing lst = currentProgram.getListing();
        for (int i = 1; i < args.length; i++) {
            String[] r = args[i].split("-");
            long lo = Long.parseLong(r[0].replace("0x", ""), 16), hi = r.length > 1 ? Long.parseLong(r[1].replace("0x", ""), 16) : lo;
            out.append(i > 1 ? "," : "").append(String.format("{\"addr\": \"%08x\", \"end\": \"%08x\", \"refs\": [", lo, hi));
            Set<String> seen = new HashSet<>();
            boolean first = true;
            for (long a = lo; a <= hi; a += 1) {
                for (Reference ref : getReferencesTo(sp.getAddress(a))) {
                    Address from = ref.getFromAddress();
                    Function f = getFunctionContaining(from);
                    String k = from.toString();
                    if (!seen.add(k)) continue;
                    out.append(first ? "" : ",").append(String.format("{\"from\": \"%s\", \"to\": \"%08x\", \"function\": \"%s\", \"entry\": \"%s\", \"type\": \"%s\"}",
                        from, a, f == null ? "" : f.getName(), f == null ? "" : f.getEntryPoint(), ref.getReferenceType()));
                    first = false;
                }
                if (hi - lo > 0x10000) break;                       // huge ranges: start address only
            }
            // lis rX, hi16 ; addi/ori/lwz ..., lo16 pairs that point into [lo, hi]: scan instructions for the hi half
            long hiHalf = (lo + 0x8000) >> 16, hiHalf2 = lo >> 16;
            InstructionIterator it = lst.getInstructions(true);
            int scanned = 0;
            while (it.hasNext() && !monitor.isCancelled()) {
                Instruction ins = it.next();
                if (!ins.getMnemonicString().equals("lis")) continue;
                Object[] ops = ins.getOpObjects(1);
                if (ops.length == 0 || !(ops[0] instanceof Scalar)) continue;
                long v = ((Scalar) ops[0]).getUnsignedValue() & 0xFFFF;
                if (v != hiHalf && v != hiHalf2) continue;
                // look a few instructions ahead for the low half
                Instruction n = ins.getNext();
                for (int k = 0; k < 6 && n != null; k++, n = n.getNext()) {
                    for (int op = 0; op < n.getNumOperands(); op++) {
                        for (Object o : n.getOpObjects(op)) {
                            if (!(o instanceof Scalar)) continue;
                            long s = ((Scalar) o).getSignedValue();
                            long full = ((v << 16) + s) & 0xFFFFFFFFL;
                            if (full >= lo && full <= hi) {
                                Function f = getFunctionContaining(n.getAddress());
                                String key = n.getAddress().toString();
                                if (seen.add(key)) {
                                    out.append(first ? "" : ",").append(String.format("{\"from\": \"%s\", \"to\": \"%08x\", \"function\": \"%s\", \"entry\": \"%s\", \"type\": \"lis+%s\"}",
                                        n.getAddress(), full, f == null ? "" : f.getName(), f == null ? "" : f.getEntryPoint(), n.getMnemonicString()));
                                    first = false;
                                }
                            }
                        }
                    }
                }
                scanned++;
            }
            out.append("]}");
        }
        out.append("]}");
        try (Writer w = new BufferedWriter(new FileWriter(args[0]))) { w.write(out.toString()); }
        println("gBox FindRefs wrote " + args[0]);
    }
}
