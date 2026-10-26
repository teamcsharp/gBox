// RE4MercGameState.java - Ghidra script to locate RE4 Mercenaries gameplay state patterns
// Upstream: gBox Ghidra Bridge adapter pattern for Resident Evil 4 (GameCube G4BE08)
// License: MIT (follows ghidra-bridge)
//
// This script locates key RE4 Mercenaries addresses:
// - EmMgr (Enemy Manager) table at 0x8027DF20
// - Player structure at 0x802B3044
// - Global state at 0x802B2280
// - Room state at 0x80279308 (Merc Timer)
// - Health tracking at player +0x4FB0 (G_HP)
// - Ganado health at EmMgr slot +0x320 (EM_HP)
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
 * RE4MercGameState: Locate RE4 Mercenaries gameplay state patterns
 * 
 * This script scans a RE4 Mercenaries executable to identify:
 * - EmMgr (enemy manager) table structure
 * - Player structure and fields
 * - Room/event state addresses
 * - Health tracking memory
 * - Combo state locations
 */
public class RE4MercGameState extends GhidraScript {

    private static final int G4BE08_BASE = 0x80000000;  // GameCube Wii base
    private static final String GAME_ID = "G4BE08";
    
    // Key addresses from gbox/re4_merc_bot.py
    private static final int EMMGR = 0x8027DF20;          // Enemy Manager table
    private static final int P_PLAYER = 0x802B3044; // player base (was 0x802B9780 - 0x673C)  // Player base
    private static final int P_GLOBAL = 0x802B2280;       // Global state
    private static final int G_ROOM = 0x4FA8;             // Room state offset
    private static final int MERC_TIMER = 0x80279308;     // Mercenaries timer
    private static final int MERC = 0x8021392C;           // Mercenaries state
    private static final int G_HP = 0x4FB0;               // Player health offset
    private static final int EM_HP = 0x320;               // Ganado health offset
    
    private Map<String, Object> results = new LinkedHashMap<>();
    private List<String> warnings = new ArrayList<>();
    
    @Override
    public void run() throws Exception {
        println("=== RE4MercGameState ===");
        println("Scanning for RE4 Mercenaries gameplay state patterns...");
        
        // Verify game ID
        if (!verifyGameID()) {
            println("WARNING: Game ID verification failed - results may be inaccurate");
        }
        
        // Locate key state addresses
        findEmMgr();
        findPlayerStructure();
        findGlobalState();
        findRoomState();
        findHealthTracking();
        findGanadoHealth();
        findMercenariesState();
        
        // Output results
        println("\n=== Results ===");
        printResults();
        
        // Write results as artifact
        println("\n=== Artifact ===");
        String result = formatResults();
        println(result);
    }
    
        private boolean verifyGameID() throws Exception {
        var memory = currentProgram.getMemory();
        
        // 1. GameCube / Wii main ELF.  The "G4BE08" disc id lives in the DOL
        //    header, not at 0x80000000, so it is unmapped in an ELF import and
        //    the old read always failed.  The ELF image base is 0x80003100 and
        //    e_machine is 20 (PowerPC) for both GameCube and Wii.
        try {
            var base = currentProgram.getImageBase();
            byte[] hdr = new byte[20];
            memory.getBytes(base, hdr);
            if (hdr[0] == 0x7f && hdr[1] == 'E' && hdr[2] == 'L' && hdr[3] == 'F') {
                int eMachine = ((hdr[18] & 0xFF) << 8) | (hdr[19] & 0xFF);
                if (eMachine == 20) {
                    println(String.format("GameCube/Wii ELF detected at %s (e_machine=20)", base));
                    return true;
                }
            }
        } catch (Exception e) {
            // no ELF image base mapped
        }
        
        // 2. DOL image header magic "G4BE".
        for (var block : memory.getBlocks()) {
            if (!block.isInitialized() || block.isExecute()) continue;
            byte[] magic = new byte[4];
            try {
                block.getBytes(block.getStart(), magic);
            } catch (Exception e) {
                continue;
            }
            if (magic[0] == 'G' && magic[1] == '4' && magic[2] == 'B' && magic[3] == 'E') {
                println(String.format("GameCube DOL header detected at %s", block.getStart()));
                return true;
            }
        }
        
        // 3. Disc id string in initialised data (full disc image import).
        byte[] pat = GAME_ID.getBytes("US-ASCII");
        for (var block : memory.getBlocks()) {
            if (!block.isInitialized()) continue;
            int len = (int) Math.min(block.getSize(), 16L * 1024 * 1024);
            if (len <= pat.length) continue;
            byte[] buf = new byte[len];
            try {
                block.getBytes(block.getStart(), buf);
            } catch (Exception e) {
                continue;
            }
            outer:
            for (int k = 0; k + pat.length <= buf.length; k++) {
                for (int j = 0; j < pat.length; j++) {
                    if (buf[k + j] != pat[j]) continue outer;
                }
                println(String.format("Found game id '%s' at %s", GAME_ID, block.getStart().add(k)));
                return true;
            }
        }
        
        warnings.add("Game ID not found in expected location");
        return false;
    }

    
    private void findEmMgr() throws Exception {
        println("\n--- Finding EmMgr (Enemy Manager) ---");
        
        results.put("em_mgr_address", String.format("0x%08X", EMMGR));
        println(String.format("EmMgr expected at: 0x%08X", EMMGR));
        
        // Find references to the EmMgr address
        var emMgrAddr = toAddr(EMMGR);
        var references = referencesTo(emMgrAddr, 100);
        var refList = new ArrayList<Map<String, String>>();
        
        for (var ref : references) {
            var refEntry = new LinkedHashMap<String, String>();
            refEntry.put("from", ref.getFromAddress().toString());
            refEntry.put("type", ref.getReferenceType().toString());
            refList.add(refEntry);
            
            if (refList.size() >= 50) break;
        }
        
        if (!refList.isEmpty()) {
            results.put("em_mgr_references", refList);
            println(String.format("Found %d references to EmMgr", refList.size()));
        }
        
        // Search for EmMgr structure members
        findEmMgrStructure(EMMGR);
    }
    
    private void findPlayerStructure() throws Exception {
        println("\n--- Finding Player Structure ---");
        
        results.put("player_address", String.format("0x%08X", P_PLAYER));
        println(String.format("Player structure expected at: 0x%08X", P_PLAYER));
        
        // Find references to player structure
        var playerAddr = toAddr(P_PLAYER);
        var references = referencesTo(playerAddr, 100);
        var refList = new ArrayList<Map<String, String>>();
        
        for (var ref : references) {
            var refEntry = new LinkedHashMap<String, String>();
            refEntry.put("from", ref.getFromAddress().toString());
            refEntry.put("type", ref.getReferenceType().toString());
            refList.add(refEntry);
            
            if (refList.size() >= 50) break;
        }
        
        if (!refList.isEmpty()) {
            results.put("player_references", refList);
            println(String.format("Found %d references to player structure", refList.size()));
        }
        
        // Search for player structure members (known offsets)
        var playerBase = toAddr(P_PLAYER);
        var memberOffsets = new int[]{0x94, 0xA4, 0x258, 0x4FB0};  // position, facing, aim pitch, health
        
        for (int offset : memberOffsets) {
            var memberAddr = toAddr(P_PLAYER + offset);
            var memRefList = new ArrayList<Map<String, String>>();
            var memRefs = referencesTo(memberAddr, 50);
            
            for (var ref : memRefs) {
                var refEntry = new LinkedHashMap<String, String>();
                refEntry.put("from", ref.getFromAddress().toString());
                refEntry.put("offset", String.format("0x%03X", offset));
                refEntry.put("type", ref.getReferenceType().toString());
                memRefList.add(refEntry);
            }
            
            if (!memRefList.isEmpty()) {
                results.put(String.format("player_member_0x%03X", offset), memRefList);
                println(String.format("Found %d references to player +0x%03X", memRefList.size(), offset));
            }
        }
    }
    
    private void findGlobalState() throws Exception {
        println("\n--- Finding Global State ---");
        
        results.put("global_address", String.format("0x%08X", P_GLOBAL));
        println(String.format("Global state expected at: 0x%08X", P_GLOBAL));
        
        var globalAddr = toAddr(P_GLOBAL);
        var references = referencesTo(globalAddr, 100);
        var refList = new ArrayList<Map<String, String>>();
        
        for (var ref : references) {
            var refEntry = new LinkedHashMap<String, String>();
            refEntry.put("from", ref.getFromAddress().toString());
            refEntry.put("type", ref.getReferenceType().toString());
            refList.add(refEntry);
            
            if (refList.size() >= 50) break;
        }
        
        if (!refList.isEmpty()) {
            results.put("global_references", refList);
            println(String.format("Found %d references to global state", refList.size()));
        }
    }
    
    private void findRoomState() throws Exception {
        println("\n--- Finding Room State ---");
        
        var roomAddr = toAddr(P_PLAYER + G_ROOM);
        results.put("room_address", String.format("0x%08X", roomAddr.getOffset()));
        println(String.format("Room state expected at: 0x%08X", roomAddr.getOffset()));
        
        var references = referencesTo(roomAddr, 100);
        var refList = new ArrayList<Map<String, String>>();
        
        for (var ref : references) {
            var refEntry = new LinkedHashMap<String, String>();
            refEntry.put("from", ref.getFromAddress().toString());
            refEntry.put("type", ref.getReferenceType().toString());
            refList.add(refEntry);
            
            if (refList.size() >= 50) break;
        }
        
        if (!refList.isEmpty()) {
            results.put("room_references", refList);
            println(String.format("Found %d references to room state", refList.size()));
        }
    }
    
    private void findHealthTracking() throws Exception {
        println("\n--- Finding Health Tracking ---");
        
        var healthAddr = toAddr(P_PLAYER + G_HP);
        results.put("health_address", String.format("0x%08X", healthAddr.getOffset()));
        println(String.format("Health tracking expected at: 0x%08X (player +0x%03X)", 
            healthAddr.getOffset(), G_HP));
        
        // Find health-related patterns
        var func = getFunctionAt(healthAddr);
        if (func != null) {
            results.put("health_function", func.getName());
        }
        
        var references = referencesTo(healthAddr, 100);
        var refList = new ArrayList<Map<String, String>>();
        
        for (var ref : references) {
            var refEntry = new LinkedHashMap<String, String>();
            refEntry.put("from", ref.getFromAddress().toString());
            refEntry.put("type", ref.getReferenceType().toString());
            refList.add(refEntry);
            
            if (refList.size() >= 50) break;
        }
        
        if (!refList.isEmpty()) {
            results.put("health_references", refList);
            println(String.format("Found %d references to health tracking", refList.size()));
        }
    }
    
    private void findGanadoHealth() throws Exception {
        println("\n--- Finding Ganado Health ---");
        
        results.put("ganado_health_offset", String.format("0x%03X", EM_HP));
        println(String.format("Ganado health offset: +0x%03X from EmMgr slot", EM_HP));
        
        // Search for patterns that access ganado health
        var searchAddr = toAddr(EMMGR);
        var func = getFunctionAt(searchAddr);
        
        if (func != null) {
            var body = func.getBody();
            var iter = currentProgram.getListing().getCodeUnits(body, true);
            var healthPatterns = new ArrayList<Map<String, String>>();
            
            while (iter.hasNext()) {
                var cu = iter.next();
                if (cu instanceof Instruction) {
                    String disassembly = cu.toString();
                    
                    if (disassembly.contains(String.format("0x%03X", EM_HP))) {
                        var patternEntry = new LinkedHashMap<String, String>();
                        patternEntry.put("address", cu.getAddress().toString());
                        patternEntry.put("instruction", disassembly);
                        healthPatterns.add(patternEntry);
                        
                        if (healthPatterns.size() >= 30) break;
                    }
                }
            }
            
            if (!healthPatterns.isEmpty()) {
                results.put("ganado_health_patterns", healthPatterns);
                println(String.format("Found %d ganado health access patterns", healthPatterns.size()));
            }
        }
    }
    
    private void findMercenariesState() throws Exception {
        println("\n--- Finding Mercenaries State ---");
        
        results.put("merc_timer_address", String.format("0x%08X", MERC_TIMER));
        results.put("merc_state_address", String.format("0x%08X", MERC));
        println(String.format("Mercenaries timer at: 0x%08X", MERC_TIMER));
        println(String.format("Mercenaries state at: 0x%08X", MERC));
        
        // Find timer references
        var timerAddr = toAddr(MERC_TIMER);
        var timerRefs = referencesTo(timerAddr, 50);
        var timerRefList = new ArrayList<Map<String, String>>();
        
        for (var ref : timerRefs) {
            var refEntry = new LinkedHashMap<String, String>();
            refEntry.put("from", ref.getFromAddress().toString());
            refEntry.put("type", ref.getReferenceType().toString());
            timerRefList.add(refEntry);
        }
        
        if (!timerRefList.isEmpty()) {
            results.put("merc_timer_references", timerRefList);
            println(String.format("Found %d references to Merc timer", timerRefList.size()));
        }
        
        // Find state references
        var stateAddr = toAddr(MERC);
        var stateRefs = referencesTo(stateAddr, 50);
        var stateRefList = new ArrayList<Map<String, String>>();
        
        for (var ref : stateRefs) {
            var refEntry = new LinkedHashMap<String, String>();
            refEntry.put("from", ref.getFromAddress().toString());
            refEntry.put("type", ref.getReferenceType().toString());
            stateRefList.add(refEntry);
        }
        
        if (!stateRefList.isEmpty()) {
            results.put("merc_state_references", stateRefList);
            println(String.format("Found %d references to Merc state", stateRefList.size()));
        }
    }
    
    private void findEmMgrStructure(int base) throws Exception {
        // Search for EmMgr structure member access patterns
        // Known: flags & 0x601 and +0x398 != 0xFF for live enemies
        // +0x94 position, +0x320 health
        
        var baseAddr = toAddr(base);
        var body = currentProgram.getMemory();
        
        // Search for instruction patterns that access EmMgr slots
        var searchFuncs = currentProgram.getFunctionManager().getFunctions(true);
        var emMgrPatterns = new ArrayList<Map<String, String>>();
        
        for (var func : searchFuncs) {
            var funcBody = func.getBody();
            var iter = currentProgram.getListing().getCodeUnits(funcBody, true);
            
            while (iter.hasNext()) {
                var cu = iter.next();
                if (cu instanceof Instruction) {
                    String disassembly = cu.toString();
                    
                    // Look for EmMgr-related patterns
                    if (disassembly.contains("0x601") || 
                        disassembly.contains("0x398") ||
                        disassembly.contains("0xFF") ||
                        disassembly.contains("0x320")) {
                        
                        var patternEntry = new LinkedHashMap<String, String>();
                        patternEntry.put("address", cu.getAddress().toString());
                        patternEntry.put("function", func.getName());
                        patternEntry.put("instruction", disassembly);
                        emMgrPatterns.add(patternEntry);
                        
                        if (emMgrPatterns.size() >= 50) break;
                    }
                }
            }
            
            if (emMgrPatterns.size() >= 50) break;
        }
        
        if (!emMgrPatterns.isEmpty()) {
            results.put("em_mgr_patterns", emMgrPatterns);
            println(String.format("Found %d EmMgr structure access patterns", emMgrPatterns.size()));
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
