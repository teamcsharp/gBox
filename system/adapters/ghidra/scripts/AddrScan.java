// Which instructions name an address in a window? Finds the code that indexes a string/blob table via ADRP+ADD.
//@category Agent
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;

public class AddrScan extends GhidraScript {
    @Override
    protected void run() throws Exception {
        long lo = 0x6d0700L, hi = 0x6d0b00L;   // around the ".udas" literal at 0x6d08ca
        int shown = 0;
        for (Instruction ins : currentProgram.getListing().getInstructions(true)) {
            long budget = 0;
            for (int op = 0; op < ins.getNumOperands(); op++) {
                for (Reference r : ins.getOperandReferences(op)) {
                    Address to = r.getToAddress();
                    if (to == null) { continue; }
                    long value = to.getOffset();
                    if (value >= lo && value <= hi) {
                        Function f = getFunctionContaining(ins.getAddress());
                        println("INSN " + ins.getAddress() + "  " + ins.toString() + "   -> " + to
                                + (f == null ? "" : "   in " + f.getName() + " @" + f.getEntryPoint()));
                        if (shown++ > 20) { return; }
                        budget++;
                    }
                }
            }
            if (budget > 0) { }
        }
        println("instructions shown: " + shown);
    }
}
