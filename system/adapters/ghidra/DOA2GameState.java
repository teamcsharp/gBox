// DOA2GameState.java - Ghidra script to locate DOA2 gameplay state patterns
// Upstream: gBox Ghidra Bridge adapter pattern for DOA2 LE (Dreamcast)
// License: MIT (follows ghidra-bridge)
//
// This script locates key DOA2 LE (JP, Dreamcast) addresses:
// - Select screen fighter confirm handler (0x8c0262e0..0x8c02631e)
// - Commit routine (0x8c02a1ca)
// - Random function (0x8c120cf0)
// - TMU0 counter (0xffd8000c)
// - State table addresses
//
// Used to automate game state analysis for streamlined gameplay (demo skip, fight state detection)

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.SourceType;
import ghidra.util.task.TaskMonitor;

import java.util.*;

/**
 * DOA2GameState: Locate DOA2 LE gameplay state patterns
 * 
 * This script scans a DOA2 LE executable to identify:
 * - State machine addresses (title vs fight vs demo)
 * - Character selection handlers
 * - Random number generator usage
 * - Memory-mapped I/O for state detection
 */
public class DOA2GameState extends GhidraScript {

    private static final long DOA2_BASE = 0x8C010000L;
    private static final String EXECUTABLE_SHA256 = "27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1";
    
    private Map<String, Object> results = new LinkedHashMap<>();
    private List<String> warnings = new ArrayList<>();
    
    @Override
    public void run() throws Exception {
        println("=== DOA2GameState ===");
        println("Scanning for DOA2 gameplay state patterns...");
        
        // Verify executable
        if (!verifyExecutable()) {
            println("WARNING: Executable verification failed - results may be inaccurate");
        }
        
        // Locate key state addresses
        findConfirmHandler();
        findCommitRoutine();
        findRandomFunction();
        findTMUCounter();
        findStateTables();
        findFightStateAddresses();
        findDemoStateAddresses();
        
        // Output results
        println("\n=== Results ===");
        printResults();
        
        // Write results as artifact
        println("\n=== Artifact ===");
        String result = formatResults();
        println(result);
    }
    
    private boolean verifyExecutable() throws Exception {
        var memory = currentProgram.getMemory();
        
        // The DOA2 LE executable is a flat binary loaded at 0x8c010000.  Ghidra's
        // BinaryLoader names the block "ram" (not "ROM"), and the base is only
        // correct when the import used -loader-baseAddr 0x8c010000.
        var block = memory.getBlock(toAddr(DOA2_BASE));
        if (block == null) {
            for (var b : memory.getBlocks()) {
                if (b.isInitialized() && b.getStart().getOffset() <= DOA2_BASE
                        && b.getEnd().getOffset() > DOA2_BASE) {
                    block = b;
                    break;
                }
            }
        }
        if (block == null) {
            warnings.add(String.format(
                "No initialized block covers the DOA2 load address 0x%08X - import with -loader-baseAddr 0x%08X",
                DOA2_BASE, DOA2_BASE));
            return false;
        }
        if (!block.isExecute()) {
            warnings.add(String.format("Block %s is not marked executable", block.getName()));
        }
        
        // Dreamcast startup header: the first word is 0x0009 (SH4 startup marker).
        byte[] hdr = new byte[4];
        try {
            memory.getBytes(toAddr(DOA2_BASE), hdr);
        } catch (Exception e) {
            warnings.add("Could not read the boot header at the load address");
            return false;
        }
        if ((hdr[0] & 0xFF) != 0x09 || (hdr[1] & 0xFF) != 0x00) {
            warnings.add(String.format(
                "Boot header at 0x%08X is %02X%02X, expected 0900 - wrong binary or wrong base address",
                DOA2_BASE, hdr[0] & 0xFF, hdr[1] & 0xFF));
            return false;
        }
        
        return true;
    }
    
    private void findConfirmHandler() throws Exception {
        println("\n--- Finding Confirm Handler ---");
        
        // The confirm handler is at 0x8c0262e0..0x8c02631e
        // Pattern: plays confirm sound, calls commit through literal pool
        
        // We'll search for the sound play pattern and trace from there
        // Sound play: call to 0x8c01235a (36 = confirm sound)
        
        var searchAddr = toAddr(0x8c0262e0L);
        println(String.format("Confirm handler expected at: 0x%08X", 0x8c0262e0L));
        
        // The confirm handler is a code block inside a larger routine, not a function
        // entry point, so resolve it through the containing function and report both.
        var func = getFunctionContaining(searchAddr);
        var instruction = currentProgram.getListing().getInstructionAt(searchAddr);
        if (func != null) {
            results.put("confirm_handler", String.format("0x%08X", searchAddr.getOffset()));
            results.put("confirm_handler_name", func.getName());
            results.put("confirm_handler_function", String.format("0x%08X", func.getEntryPoint().getOffset()));
            results.put("confirm_handler_is_function_entry",
                    String.valueOf(func.getEntryPoint().getOffset() == searchAddr.getOffset()));
            if (instruction != null) {
                String text = instruction.toString();
                if (text.indexOf('"') < 0) {
                    results.put("confirm_handler_instruction", text);
                }
            }
            println(String.format("Found: %s at %s in %s", instruction == null ? "code" : instruction,
                    searchAddr, func.getName()));
        } else {
            warnings.add("Confirm handler address is not mapped in this image");
            results.put("confirm_handler", null);
        }
        
        // Find the commit routine address from the literal pool
        var commitAddr = toAddr(0x8c02a1caL);
        println(String.format("Commit routine expected at: 0x%08X", 0x8c02a1caL));
        
        var commitFunc = getFunctionAt(commitAddr);
        if (commitFunc != null) {
            results.put("commit_routine", String.format("0x%08X", commitFunc.getEntryPoint().getOffset()));
            results.put("commit_routine_name", commitFunc.getName());
            println(String.format("Found: %s at %s", commitFunc.getName(), commitFunc.getEntryPoint()));
        } else {
            warnings.add("Commit routine function not found at expected location");
            results.put("commit_routine", null);
        }
    }
    
    private void findCommitRoutine() throws Exception {
        println("\n--- Finding Commit Routine ---");
        
        // Commit routine at 0x8c02a1ca
        // Copies cursor +1 / +2 into selection tables 0x8c239d50 (slots) and 0x8c239d64 (costumes)
        
        var addr = toAddr(0x8c02a1caL);
        results.put("commit_address", String.format("0x%08X", 0x8c02a1caL));
        
        var func = getFunctionAt(addr);
        if (func != null) {
            var body = func.getBody();
            var iter = currentProgram.getListing().getCodeUnits(body, true);
            
            // Find the selection table writes
            var tables = new ArrayList<Map<String, String>>();
            while (iter.hasNext()) {
                var cu = iter.next();
                if (cu instanceof Instruction) {
                    String disassembly = cu.toString();
                    
                    // Look for writes to selection tables (0x8c239d50, 0x8c239d64)
                    if (disassembly.contains("8c239d50") || disassembly.contains("8c239d64")) {
                        var tableEntry = new LinkedHashMap<String, String>();
                        tableEntry.put("address", cu.getAddress().toString());
                        tableEntry.put("instruction", disassembly);
                        tables.add(tableEntry);
                        
                        if (tables.size() >= 10) break;
                    }
                }
            }
            
            if (!tables.isEmpty()) {
                results.put("commit_tables", tables);
                println(String.format("Found %d selection table writes", tables.size()));
            }
        }
    }
    
    private void findRandomFunction() throws Exception {
        println("\n--- Finding Random Function ---");
        
        // Random function at 0x8c120cf0
        // LCG: seed at 0x8c1e64e0, returns (seed * 0x41c64e6d + 12345) >> 16 & 0x7fff
        
        var addr = toAddr(0x8c120cf0L);
        results.put("random_address", String.format("0x%08X", 0x8c120cf0L));
        
        var func = getFunctionAt(addr);
        if (func != null) {
            results.put("random_name", func.getName());
            println(String.format("Found: %s at %s", func.getName(), func.getEntryPoint()));
            
            // Find the seed address from the function body
            var body = func.getBody();
            var iter = currentProgram.getListing().getCodeUnits(body, true);
            var seedAddresses = new ArrayList<String>();
            
            while (iter.hasNext()) {
                var cu = iter.next();
                if (cu instanceof Instruction) {
                    String disassembly = cu.toString();
                    
                    if (disassembly.contains("8c1e64e0")) {
                        seedAddresses.add(cu.getAddress().toString());
                    }
                }
            }
            
            if (!seedAddresses.isEmpty()) {
                results.put("random_seed_addresses", seedAddresses);
                println(String.format("Found seed references at %d locations", seedAddresses.size()));
            }
        }
    }
    
    private void findTMUCounter() throws Exception {
        println("\n--- Finding TMU Counter ---");
        
        // TMU0 counter at 0xffd8000c (free-running timer used for randomness mixing)
        
        var addr = toAddr(0xFFD8000cL);
        results.put("tmu0_address", String.format("0x%08X", 0xFFD8000cL));
        
        // Search for references to this address
        var references = referencesTo(addr, 100);
        var refList = new ArrayList<Map<String, String>>();
        
        for (var ref : references) {
            var refEntry = new LinkedHashMap<String, String>();
            refEntry.put("from", ref.getFromAddress().toString());
            refEntry.put("type", ref.getReferenceType().toString());
            refList.add(refEntry);
            
            if (refList.size() >= 20) break;
        }
        
        if (!refList.isEmpty()) {
            results.put("tmu0_references", refList);
            println(String.format("Found %d references to TMU0 counter", refList.size()));
        }
    }
    
    private void findStateTables() throws Exception {
        println("\n--- Finding State Tables ---");
        
        // Selection tables at 0x8c239d50 (slots) and 0x8c239d64 (costumes)
        // These are the u16 [side][5] arrays every mode's loader and actor set-up read
        
        var slotAddr = toAddr(0x8c239d50L);
        var costumeAddr = toAddr(0x8c239d64L);
        
        results.put("slot_table_address", String.format("0x%08X", 0x8c239d50L));
        results.put("costume_table_address", String.format("0x%08X", 0x8c239d64L));
        
        // Check if these are valid memory locations
        var memory = currentProgram.getMemory();
        try {
            var slotBlock = memory.getBlock(slotAddr);
            var costumeBlock = memory.getBlock(costumeAddr);
            
            if (slotBlock != null) {
                results.put("slot_table_block", slotBlock.getName());
                println(String.format("Slot table in block: %s", slotBlock.getName()));
            }
            
            if (costumeBlock != null) {
                results.put("costume_table_block", costumeBlock.getName());
                println(String.format("Costume table in block: %s", costumeBlock.getName()));
            }
        } catch (Exception e) {
            warnings.add(String.format("Error checking state tables: %s", e.getMessage()));
        }
        
        // Search for references to these tables
        var slotRefs = referencesTo(slotAddr, 50);
        var slotRefList = new ArrayList<Map<String, String>>();
        
        for (var ref : slotRefs) {
            var refEntry = new LinkedHashMap<String, String>();
            refEntry.put("from", ref.getFromAddress().toString());
            refEntry.put("type", ref.getReferenceType().toString());
            slotRefList.add(refEntry);
            
            if (slotRefList.size() >= 30) break;
        }
        
        if (!slotRefList.isEmpty()) {
            results.put("slot_table_references", slotRefList);
            println(String.format("Found %d references to slot table", slotRefList.size()));
        }
    }
    
    private void findFightStateAddresses() throws Exception {
        println("\n--- Finding Fight State Addresses ---");
        
        // Search for patterns that indicate fight state detection
        // Look for comparison with fight state constants
        
        var searchAddr = toAddr(0x8C0262e0L);
        var func = getFunctionContaining(searchAddr);
        
        if (func != null) {
            var body = func.getBody();
            var iter = currentProgram.getListing().getCodeUnits(body, true);
            var fightStatePatterns = new ArrayList<Map<String, String>>();
            
            var units = new ArrayList<CodeUnit>();
            while (iter.hasNext()) units.add(iter.next());
            for (int ui = 0; ui < units.size(); ui++) {
                var cu = units.get(ui);
                if (cu instanceof Instruction) {
                    String disassembly = cu.toString();
                    
                    // Look for fight state comparisons
                    if (disassembly.toLowerCase().contains("cmp") || 
                        disassembly.toLowerCase().contains("cmplt") ||
                        disassembly.toLowerCase().contains("cmpge")) {
                        
                        var patternEntry = new LinkedHashMap<String, String>();
                        patternEntry.put("address", cu.getAddress().toString());
                        patternEntry.put("instruction", disassembly);
                        
                        // Get next instruction for context
                        if (ui + 1 < units.size()) {
                            var nextCu = units.get(ui + 1);
                            if (nextCu instanceof Instruction) {
                                patternEntry.put("next", nextCu.toString());
                            }
                        }
                        
                        fightStatePatterns.add(patternEntry);
                        
                        if (fightStatePatterns.size() >= 20) break;
                    }
                }
            }
            
            if (!fightStatePatterns.isEmpty()) {
                results.put("fight_state_patterns", fightStatePatterns);
                println(String.format("Found %d fight state comparison patterns", fightStatePatterns.size()));
            }
        }
    }
    
    private void findDemoStateAddresses() throws Exception {
        println("\n--- Finding Demo State Addresses ---");
        
        // Search for demo playback state detection
        // Look for demo-specific memory regions and state transitions
        
        var searchAddr = toAddr(0x8C0262e0L);
        var func = getFunctionContaining(searchAddr);
        
        if (func != null) {
            var body = func.getBody();
            var iter = currentProgram.getListing().getCodeUnits(body, true);
            var demoStatePatterns = new ArrayList<Map<String, String>>();
            
            while (iter.hasNext()) {
                var cu = iter.next();
                if (cu instanceof Instruction) {
                    String disassembly = cu.toString();
                    
                    // Look for demo-related patterns
                    if (disassembly.toLowerCase().contains("demo") ||
                        disassembly.toLowerCase().contains("title") ||
                        disassembly.toLowerCase().contains("intro")) {
                        
                        var patternEntry = new LinkedHashMap<String, String>();
                        patternEntry.put("address", cu.getAddress().toString());
                        patternEntry.put("instruction", disassembly);
                        
                        demoStatePatterns.add(patternEntry);
                        
                        if (demoStatePatterns.size() >= 20) break;
                    }
                }
            }
            
            if (!demoStatePatterns.isEmpty()) {
                results.put("demo_state_patterns", demoStatePatterns);
                println(String.format("Found %d demo state patterns", demoStatePatterns.size()));
            }
        }
    }
    
    private void printResults() {
        for (var entry : results.entrySet()) {
            var value = entry.getValue();
            if (value instanceof String) {
                println(String.format("%s: %s", entry.getKey(), value));
            } else if (value instanceof ArrayList) {
                println(String.format("%s: [%d items]", entry.getKey(), ((ArrayList<?>)value).size()));
            } else if (value instanceof Map) {
                println(String.format("%s: {map with %d keys}", entry.getKey(), ((Map<?, ?>)value).size()));
            } else if (value == null) {
                println(String.format("%s: null", entry.getKey()));
            } else {
                println(String.format("%s: %s", entry.getKey(), value.toString()));
            }
        }
        
        if (!warnings.isEmpty()) {
            println("\n--- Warnings ---");
            for (var warning : warnings) {
                println("WARNING: " + warning);
            }
        }
    }
    
    private String formatResults() {
        var sb = new StringBuilder();
        sb.append("{\n");
        
        boolean first = true;
        for (var entry : results.entrySet()) {
            if (!first) sb.append(",\n");
            first = false;
            
            var key = entry.getKey();
            var value = entry.getValue();
            
            sb.append(String.format("  \"%s\": ", key));
            
            if (value instanceof String) {
                sb.append(String.format("\"%s\"", value));
            } else if (value == null) {
                sb.append("null");
            } else if (value instanceof ArrayList) {
                sb.append(String.format("[%d items]", ((ArrayList<?>)value).size()));
            } else if (value instanceof Map) {
                sb.append(String.format("{%d keys}", ((Map<?, ?>)value).size()));
            } else {
                sb.append(String.format("\"%s\"", value.toString()));
            }
        }
        
        sb.append("\n}");
        
        if (!warnings.isEmpty()) {
            sb.append("\n/* Warnings: ");
            sb.append(String.join("; ", warnings));
            sb.append(" */");
        }
        
        return sb.toString();
    }
    
    private List<ghidra.program.model.symbol.Reference> referencesTo(ghidra.program.model.address.Address addr, int max) throws Exception {
        var results = new ArrayList<ghidra.program.model.symbol.Reference>();
        var rm = currentProgram.getReferenceManager();
        var iter = rm.getReferencesTo(addr);
        
        int count = 0;
        while (iter.hasNext() && count < max) {
            results.add(iter.next());
            count++;
        }
        
        return results;
    }
}
