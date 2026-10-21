// FindGameplayState.java - Ghidra script to identify common gameplay state patterns
// Upstream: gBox Ghidra Bridge adapter pattern
// License: MIT (follows ghidra-bridge)
//
// Usage: Run against a loaded game binary to discover:
//   - Boot jump / title skip states
//   - Fight state transitions
//   - Demo playback states
//   - Game state machine addresses
//
// This script is meant to be run via ghidra_bridge op=run_script
// from gBox workflow to automate game state analysis.

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.block.BasicBlockModel;
import ghidra.program.model.block.CodeBlock;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.address.AddressSetView;
import ghidra.program.model.mem.MemoryAccessException;
import ghidra.util.task.TaskMonitor;

import java.util.*;

/**
 * FindGameplayState: Automated game state pattern discovery
 * 
 * This script scans a loaded binary for common gameplay state patterns:
 * - State machine dispatch tables
 * - Conditional branch patterns (fight vs title vs demo)
 * - Memory-mapped I/O regions that control display state
 * - Timer/counter patterns used for state transitions
 */
public class FindGameplayState extends GhidraScript {

    @Override
    public void run() throws Exception {
        println("=== FindGameplayState ===");
        println("Scanning for gameplay state patterns...");
        
        // Detect game ID from memory
        String gameId = detectGameId();
        println(String.format("Detected game ID: %s", gameId));
        
        Map<String, Object> allResults = new LinkedHashMap<>();
        
        // 1. Find potential state machine addresses
        Map<String, Object> stateMachines = findStateMachinePatterns();
        allResults.put("stateMachines", stateMachines);
        
        // 2. Identify fight/demo/boot state transitions
        Map<String, Object> stateTransitions = findStateTransitions();
        allResults.put("stateTransitions", stateTransitions);
        
        // 3. Find common gameplay memory regions
        Map<String, Object> gameplayRegions = findGameplayRegions();
        allResults.put("gameplayRegions", gameplayRegions);
        
        // 4. Game-specific patterns based on detected ID
        Map<String, Object> gameSpecific = new LinkedHashMap<>();
        if (gameId.equals("DOA2")) {
            gameSpecific.put("doa2", findDOA2Patterns());
        } else if (gameId.equals("G4BE08") || gameId.equals("RE4")) {
            gameSpecific.put("re4_mercenaries", findRE4MercPatterns());
        } else {
            gameSpecific.put("unknown", Collections.singletonMap("message", "No game-specific patterns defined"));
        }
        allResults.put("gameSpecific", gameSpecific);
        
        // Output results
        println("\n=== Results ===");
        println(String.format("Found %d switch patterns", listSize(stateMachines.get("switchPatterns"))));
        println(String.format("Found %d state table references", listSize(stateMachines.get("stateTables"))));
        println(String.format("Found %d state variable accesses", listSize(stateMachines.get("stateVariables"))));
        println(String.format("Found %d conditional branch transitions", listSize(stateTransitions.get("transitions"))));
        println(String.format("Found %d gameplay memory regions", listSize(gameplayRegions.get("regions"))));
        println(String.format("Found %d game-specific pattern groups", gameSpecific.size()));
        
        // Write results to artifact (expected by gBox bridge)
        String result = String.format(
            "{\"stateMachines\": %d, \"stateTransitions\": %d, \"gameplayRegions\": %d, \"gameSpecific\": %d}",
            stateMachines.size(), stateTransitions.size(), gameplayRegions.size(), gameSpecific.size()
        );
        println("\n=== Artifact ===");
        println(result);
        
        // Also print full JSON for detailed results
        println("\n=== Full Results JSON ===");
        String fullJson = formatJson(allResults);
        println(fullJson);
    }
    
    /**
     * Detect the game ID from the loaded binary
     * Returns "DOA2" for Dead or Alive 2, "G4BE08" for RE4 Mercenaries, or "UNKNOWN"
     */
    private String detectGameId() throws Exception {
        var memory = currentProgram.getMemory();
        
        // Dreamcast flat binary: Ghidra's BinaryLoader leaves the image base at 0 and
        // adds no ELF header, so neither the ELF magic nor the image base can name
        // this build.  Identify it from the load address and the SH4 startup marker.
        if (isDreamcastFlatBinary()) return "DOA2";
        
        // RE4 GameCube/Wii image: game ID string lives at the base of the main code area
        try {
            var bytes = new byte[6];
            memory.getBytes(toAddr(0x80000000L), bytes);
            if ("G4BE08".equals(new String(bytes, "US-ASCII"))) {
                return "G4BE08";
            }
        } catch (Exception e) {
            // 0x80000000 not mapped -> not a GameCube/Wii image
        }
        
        // Dreamcast ELF: the program image base is the strongest DOA2 signal
        try {
            long imageBase = currentProgram.getImageBase().getOffset();
            byte[] magic = new byte[4];
            memory.getBytes(currentProgram.getImageBase(), magic);
            boolean elf = magic[0] == 0x7f && magic[1] == 'E' && magic[2] == 'L' && magic[3] == 'F';
            if (elf) {
                if (imageBase >= 0x8C000000L && imageBase < 0x8D000000L) return "DOA2";
                if (containsString("DOA2")) return "DOA2";
                if (isPowerPcElf()) return "G4BE08";
                return "ELF";
            }
        } catch (Exception e) {
            // unmapped image base
        }
        
        // ELF executable (DOA2 is a Dreamcast ELF loaded at 0x8C000000)
        for (var block : memory.getBlocks()) {
            if (!block.isExecute() || !block.isInitialized()) continue;
            
            byte[] magic = new byte[4];
            try {
                memory.getBytes(block.getStart(), magic);
            } catch (Exception e) {
                continue;
            }
            
            boolean elf = magic[0] == 0x7f && magic[1] == 'E' && magic[2] == 'L' && magic[3] == 'F';
            if (!elf) continue;
            
            long base = block.getStart().getOffset();
            if (base >= 0x8C000000L && base < 0x8D000000L) {
                return "DOA2";  // Dreamcast load address
            }
            if (containsString("DOA2")) {
                return "DOA2";
            }
            if (isPowerPcElf()) return "G4BE08";
            return "ELF";
        }
        
        if (containsString("G4BE08")) return "G4BE08";
        if (containsString("DOA2")) return "DOA2";
        
        return "UNKNOWN";
    }
    
    /**
     * True when the loaded image is the flat Dreamcast DOA2 executable: an executable
     * block based in the 0x8C000000 window whose first word is the SH4 startup marker
     * 0x0009.  Ghidra's BinaryLoader leaves the image base at 0 and adds no ELF header,
     * so the ELF and image-base checks cannot identify this build.
     */
    private boolean isDreamcastFlatBinary() {
        try {
            var memory = currentProgram.getMemory();
            for (var block : memory.getBlocks()) {
                if (!block.isInitialized() || !block.isExecute()) continue;
                long base = block.getStart().getOffset();
                if (base < 0x8C000000L || base >= 0x8D000000L) continue;
                byte[] hdr = new byte[2];
                memory.getBytes(block.getStart(), hdr);
                if ((hdr[0] & 0xFF) == 0x09 && (hdr[1] & 0xFF) == 0x00) return true;
            }
        } catch (Exception e) {
            // unmapped block start
        }
        return false;
    }
    
    /**
     * Scan initialized data blocks for an ASCII marker string
     */
    /**
     * True when the loaded image is a big-endian PowerPC ELF (GameCube / Wii).
     * e_machine == 20 at ELF offset 0x12.
     */
    private boolean isPowerPcElf() {
        try {
            var memory = currentProgram.getMemory();
            byte[] hdr = new byte[20];
            memory.getBytes(currentProgram.getImageBase(), hdr);
            if (hdr[0] != 0x7f || hdr[1] != 'E' || hdr[2] != 'L' || hdr[3] != 'F') return false;
            int eMachine = ((hdr[18] & 0xFF) << 8) | (hdr[19] & 0xFF);
            return eMachine == 20;
        } catch (Exception e) {
            return false;
        }
    }
    
    private boolean containsString(String needle) throws Exception {
        var memory = currentProgram.getMemory();
        byte[] pat = needle.getBytes("US-ASCII");
        
        for (var block : memory.getBlocks()) {
            // Flat executables carry their markers inside the executable block itself.
            if (!block.isInitialized()) continue;
            
            long size = block.getSize();
            if (size <= 0) continue;
            int len = (int) Math.min(size, 8L * 1024 * 1024);
            byte[] data = new byte[len];
            try {
                block.getBytes(block.getStart(), data);
            } catch (Exception e) {
                continue;
            }
            
            outer:
            for (int i = 0; i + pat.length <= data.length; i++) {
                for (int j = 0; j < pat.length; j++) {
                    if (data[i + j] != pat[j]) continue outer;
                }
                return true;
            }
        }
        
        return false;
    }
    
    /**
     * Size of a list value, 0 when absent
     */
    private static int listSize(Object o) {
        return (o instanceof List) ? ((List<?>) o).size() : 0;
    }
    
    /**
     * Format a Map as JSON string
     */
    private String formatJson(Map<String, Object> obj) throws Exception {
        return formatJsonRecursive(obj, 0);
    }
    
    private String formatJsonRecursive(Object obj, int indent) throws Exception {
        StringBuilder sb = new StringBuilder();
        String indentStr = "  ".repeat(indent);
        
        if (obj instanceof Map) {
            sb.append("{\n");
            boolean first = true;
            for (var entry : ((Map<?, ?>)obj).entrySet()) {
                if (!first) sb.append(",\n");
                first = false;
                sb.append(indentStr).append("  \"").append(entry.getKey()).append("\": ");
                sb.append(formatJsonRecursive(entry.getValue(), indent + 1));
            }
            sb.append("\n").append(indentStr).append("}");
        } else if (obj instanceof List) {
            sb.append("[\n");
            boolean first = true;
            for (var item : (List<?>)obj) {
                if (!first) sb.append(",\n");
                first = false;
                sb.append(indentStr).append("  ");
                sb.append(formatJsonRecursive(item, indent + 1));
            }
            sb.append("\n").append(indentStr).append("]");
        } else if (obj instanceof String) {
            sb.append("\"").append(obj).append("\"");
        } else if (obj instanceof Number) {
            sb.append(obj);
        } else if (obj == null) {
            sb.append("null");
        } else {
            sb.append("\"").append(obj.toString()).append("\"");
        }
        
        return sb.toString();
    }
    
    /**
     * Find potential state machine patterns in the binary
     * Looks for: jump tables, case dispatch patterns, state variable accesses
     */
    private Map<String, Object> findStateMachinePatterns() throws Exception {
        Map<String, Object> results = new LinkedHashMap<>();
        
        // Look for switch/case patterns (common in state machines)
        // Pattern: cmp reg, value; jbe dispatch; jmp [table + index*4]
        List<String> patterns = findSwitchPatterns();
        if (!patterns.isEmpty()) {
            results.put("switchPatterns", patterns.subList(0, Math.min(10, patterns.size())));
        }
        
        // Find data sections that look like state tables
        List<String> stateTables = findStateTables();
        if (!stateTables.isEmpty()) {
            results.put("stateTables", stateTables.subList(0, Math.min(10, stateTables.size())));
        }
        
        // Look for common state variable access patterns
        List<String> stateVars = findStateVariableAccesses();
        if (!stateVars.isEmpty()) {
            results.put("stateVariables", stateVars.subList(0, Math.min(20, stateVars.size())));
        }
        
        return results;
    }
    
    /**
     * Find state transition patterns - conditional branches that split game flow
     */
    private Map<String, Object> findStateTransitions() throws Exception {
        Map<String, Object> results = new LinkedHashMap<>();
        List<Map<String, String>> transitions = new ArrayList<>();
        
        // Look for conditional branches after specific comparisons
        // Common patterns:
        // - cmp eax, 1 / jz .fight (fight state)
        // - cmp eax, 0 / jz .title (title state)
        // - cmp eax, 2 / jz .demo (demo state)
        
        // Prefer the current address context; fall back to the first discovered function
        Address start = currentAddress;
        if (start == null) {
            var funcs = currentProgram.getFunctionManager().getFunctions(true);
            if (funcs.hasNext()) {
                start = funcs.next().getEntryPoint();
            }
        }
        
        if (start != null) {
            var func = getFunctionContaining(start);
            AddressSetView body = (func != null) ? func.getBody() : new AddressSet(start, start);
            // Find conditional branches in current function
            List<String> conds = findConditionalBranches(body);
            for (String cond : conds.subList(0, Math.min(20, conds.size()))) {
                Map<String, String> t = new LinkedHashMap<>();
                t.put("address", cond);
                t.put("type", "conditional_branch");
                transitions.add(t);
            }
        }
        
        results.put("transitions", transitions);
        return results;
    }
    
    /**
     * Find gameplay-relevant memory regions
     */
    private Map<String, Object> findGameplayRegions() throws Exception {
        Map<String, Object> results = new LinkedHashMap<>();
        List<Map<String, String>> regions = new ArrayList<>();
        
        // Look for known gameplay regions in memory map
        var memory = currentProgram.getMemory();
        for (var block : memory.getBlocks()) {
            String name = block.getName();
            if (name.contains("ram") || name.contains("data") || name.contains("game")) {
                Map<String, String> r = new LinkedHashMap<>();
                r.put("name", name);
                r.put("start", block.getStart().toString());
                r.put("end", block.getEnd().toString());
                r.put("size", String.valueOf(block.getSize()));
                r.put("read", String.valueOf(block.isRead()));
                r.put("write", String.valueOf(block.isWrite()));
                regions.add(r);
            }
        }
        
        results.put("regions", regions.subList(0, Math.min(20, regions.size())));
        return results;
    }
    
    // --- Pattern finding helpers ---
    
    private List<String> findSwitchPatterns() throws Exception {
        List<String> results = new ArrayList<>();
        
        // Look for instruction sequences that indicate switch statements
        // Pattern: CMP followed by JBE followed by JMP [table]
        // This varies by architecture - common x86 pattern:
        //   cmp eax, n
        //   jbe dispatch_table
        //   jmp [dispatch_table + eax*4]
        
        var listing = currentProgram.getListing();
        var codeUnit = listing.getCodeUnitAt(currentAddress);
        
        // Search for common switch patterns in all functions
        var fm = currentProgram.getFunctionManager();
        for (var func : fm.getFunctions(true)) {
            var body = func.getBody();
            var iter = listing.getCodeUnits(body, true);
            
            while (iter.hasNext()) {
                var cu = iter.next();
                if (cu instanceof Instruction) {
                    String disassembly = cu.toString();
                    
                    // Look for compare + conditional branch patterns
                    if (disassembly.contains("cmp") || disassembly.contains("CMP")) {
                        if (iter.hasNext()) {
                            var next = iter.next();
                            if (next instanceof Instruction) {
                                String nextDis = next.toString();
                                if (nextDis.contains("jz") || nextDis.contains("jnz") || 
                                    nextDis.contains("je") || nextDis.contains("jne")) {
                                    results.add(String.format("%s: %s -> %s", 
                                        cu.getAddress(), disassembly, nextDis));
                                    if (results.size() >= 50) return results;
                                }
                            }
                        }
                    }
                }
            }
        }
        
        return results;
    }
    
    private List<String> findStateTables() throws Exception {
        List<String> results = new ArrayList<>();
        
        // Look for sequential data patterns that could be state tables
        var memory = currentProgram.getMemory();
        var data = currentProgram.getDataTypeManager();
        
        for (var block : memory.getBlocks()) {
            if (!block.isExecute()) continue;
            
            var iter = currentProgram.getListing().getInstructions(block.getStart(), true);
            while (iter.hasNext()) {
                var inst = iter.next();
                
                // Check for pointer references that might be jump tables
                var references = inst.getReferencesFrom();
                for (var ref : references) {
                    String type = ref.getReferenceType().toString();
                    if (type.contains("Data") || type.contains("Ordinal")) {
                        results.add(String.format("%s -> %s [%s]", 
                            inst.getAddress(), ref.getToAddress(), type));
                        if (results.size() >= 20) return results;
                    }
                }
            }
        }
        
        return results;
    }
    
    private List<String> findStateVariableAccesses() throws Exception {
        List<String> results = new ArrayList<>();
        
        // Look for memory accesses that might be state variables
        // Common pattern: [base + offset] where offset is small constant
        
        var listing = currentProgram.getListing();
        var fm = currentProgram.getFunctionManager();
        
        for (var func : fm.getFunctions(true)) {
            var body = func.getBody();
            var iter = listing.getCodeUnits(body, true);
            
            while (iter.hasNext()) {
                var cu = iter.next();
                if (cu instanceof Instruction) {
                    String disassembly = cu.toString();
                    
                    // Look for memory accesses with small offsets
                    if (disassembly.contains("[e") && disassembly.contains("+")) {
                        // Extract potential state variable access
                        results.add(String.format("%s: %s", cu.getAddress(), disassembly));
                        if (results.size() >= 30) return results;
                    }
                }
            }
        }
        
        return results;
    }
    
    private List<String> findConditionalBranches(AddressSetView body) throws Exception {
        List<String> results = new ArrayList<>();
        
        var listing = currentProgram.getListing();
        
        for (var cu : listing.getCodeUnits(body, true)) {
            if (cu instanceof Instruction) {
                String disassembly = cu.toString().toLowerCase();
                
                // Look for conditional branches
                if (disassembly.contains("jz") || disassembly.contains("jnz") ||
                    disassembly.contains("je") || disassembly.contains("jne") ||
                    disassembly.contains("jb") || disassembly.contains("ja") ||
                    disassembly.contains("jl") || disassembly.contains("jg")) {
                    results.add(cu.getAddress().toString());
                }
            }
        }
        
        return results;
    }
    
    // --- Game-specific helpers ---
    
    /**
     * Find DOA2 gameplay state patterns
     * - Confirm handler at 0x8c0262e0..0x8c02631e
     * - Commit routine at 0x8c02a1ca
     * - Random function at 0x8c120cf0
     * - TMU0 counter at 0xffd8000c
     */
    private Map<String, Object> findDOA2Patterns() throws Exception {
        Map<String, Object> results = new LinkedHashMap<>();
        List<Map<String, String>> patterns = new ArrayList<>();
        
        // Known DOA2 addresses (Dreamcast LE)
        long[] doa2Addresses = {
            0x8C0262E0,  // Confirm handler
            0x8C02A1CA,  // Commit routine
            0x8C120CF0,  // Random function (LCG)
            0xFFD8000C,  // TMU0 counter
            0x8C239D50,  // Slot selection table
            0x8C239D64   // Costume selection table
        };
        
        for (long addr : doa2Addresses) {
            Map<String, String> p = new LinkedHashMap<>();
            p.put("name", getDOA2AddressName(addr));
            p.put("address", String.format("0x%08X", addr));
            patterns.add(p);
        }
        
        results.put("addresses", patterns);
        
        // Find function at commit address
        var commitAddr = toAddr(0x8C02A1CA);
        var func = getFunctionAt(commitAddr);
        if (func != null) {
            results.put("commit_routine", func.getName());
        }
        
        return results;
    }
    
    /**
     * Find RE4 Mercenaries gameplay state patterns
     * - EmMgr at 0x8027DF20
     * - Player structure at 0x802B3044
     * - Health at player +0x4FB0
     * - Merc timer at 0x80279308
     */
    private Map<String, Object> findRE4MercPatterns() throws Exception {
        Map<String, Object> results = new LinkedHashMap<>();
        List<Map<String, String>> patterns = new ArrayList<>();
        
        // Known RE4 Mercenaries addresses (GameCube/Wii)
        long[][] re4Addresses = {
            {0x8027DF20, 0x000},      // EmMgr table
            {0x802B3044, 0x000},      // Player em base
            {0x802B3044, 0x94},       // Position offset
            {0x802B3044, 0xA4},       // Facing offset
            {0x802B3044, 0x258},      // Aim pitch offset
            {0x802B3044, 0x4FB0},     // Health offset (G_HP)
            {0x802B9780, 0x000},      // Player structure base
            {0x802B2280, 0x000},      // Global state
            {0x80279308, 0x000},      // Merc timer
            {0x8021392C, 0x000},      // Merc state
        };
        
        for (long[] entry : re4Addresses) {
            long base = entry[0];
            long offset = entry[1];
            long fullAddr = base + offset;
            
            Map<String, String> p = new LinkedHashMap<>();
            p.put("name", getRE4AddressName(base, offset));
            p.put("base", String.format("0x%08X", base));
            p.put("offset", String.format("0x%03X", offset));
            p.put("address", String.format("0x%08X", fullAddr));
            patterns.add(p);
        }
        
        results.put("addresses", patterns);
        
        return results;
    }
    
    /**
     * Get human-readable name for DOA2 address
     */
    private String getDOA2AddressName(long addr) {
        switch ((int)addr) {
            case 0x8C0262E0: return "ConfirmHandler";
            case 0x8C02A1CA: return "CommitRoutine";
            case 0x8C120CF0: return "RandomLCG";
            case 0xFFD8000C: return "TMU0Counter";
            case 0x8C239D50: return "SlotTable";
            case 0x8C239D64: return "CostumeTable";
            default: return String.format("Unknown_%08X", addr);
        }
    }
    
    /**
     * Get human-readable name for RE4 address
     */
    private String getRE4AddressName(long base, long offset) {
        switch ((int)base) {
            case 0x8027DF20: return "EmMgr";
            case 0x802B3044: 
                switch ((int)offset) {
                    case 0x94: return "PlayerPosition";
                    case 0xA4: return "PlayerFacing";
                    case 0x258: return "AimPitch";
                    case 0x4FB0: return "PlayerHealth";
                    default: return String.format("Player+0x%03X", offset);
                }
            case 0x802B9780: return "PlayerBase";
            case 0x802B2280: return "GlobalState";
            case 0x80279308: return "MercTimer";
            case 0x8021392C: return "MercState";
            default: return String.format("Unknown_%08X+0x%03X", base, offset);
        }
    }
}
