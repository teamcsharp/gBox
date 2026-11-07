// What code touches the id tables? Disassembly around each reference, no decompiler needed.
//@category Agent
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.symbol.Reference;

public class TableDisasm extends GhidraScript {
    @Override
    protected void run() throws Exception {
        Listing listing = currentProgram.getListing();
        int shown = 0;
        for (long lo = 0xa04000L; lo < 0xa09000L; lo += 8) {
            for (Reference r : getReferencesTo(toAddr(lo))) {
                if (shown++ >= 12) { return; }
                Address from = r.getFromAddress();
                println("---- reference from " + from + " -> " + toAddr(lo) + " (" + r.getReferenceType() + ")");
                Instruction ins = listing.getInstructionContaining(from);
                if (ins == null) { println("    (no instruction)"); continue; }
                Address start = ins.getAddress();
                for (int i = 0; i < 4 && start != null; i++) { start = start.subtract(4); }
                Address cursor = start;
                for (int i = 0; i < 14 && cursor != null; i++) {
                    Instruction here = listing.getInstructionAt(cursor);
                    if (here != null) {
                        println((here.getAddress().equals(ins.getAddress()) ? "  >> " : "     ") + here.getAddress()
                                + "  " + here.toString());
                        cursor = here.getAddress().add(4);
                    } else {
                        cursor = cursor.add(4);
                    }
                }
            }
        }
        println("references examined: " + shown);
    }
}
