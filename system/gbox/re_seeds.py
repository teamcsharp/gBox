"""Seed knowledge for gBox's reverse-engineering library (gbox/re_lab.py).

PLAYBOOKS: how-to procedures for recurring Ghidra tasks, distilled from what gBox engineers already did successfully
(docs/model_swaps.md, docs/re6.md, docs/mercenaries.md, gbox/re_games.py, profiles/*.json, the knowledge base). Steps name
the agent's exact tools and arguments. They are versioned on the control plane; bump SEED_VERSION in a playbook here
to push a revised seed (lessons learned on the control plane are kept).

TITLE_FACTS: per-title facts that engineers verified live (status "documented", with the doc they come from). They are
merged into a title's dossier the first time it is studied. They are not LLM claims and not evidence artifacts:
"documented" ranks between "hypothesis" and "validated".
"""

PLAYBOOKS = [
    {
        "id": "study-title", "seed_version": 1, "title": "Start reverse-engineering a title (dossier + Ghidra study)",
        "goal": "Have the title's executable in Ghidra with the right processor and registers, and know what gBox "
                "already found, before working on any task in that game.",
        "when": ["ghidra", "reverse engineer", "analyze the executable", "decompile", "disassemble", "study this game",
                 "find the code", "how does the game"],
        "platforms": ["any"], "tags": ["setup", "ghidra", "executable", "dossier"],
        "steps": [
            {"do": "Read what gBox already knows about the title: executable, key addresses with evidence, formats, "
                   "mods, open questions.", "tool": "re_dossier", "args": {"op": "read"},
             "expect": "the dossier text; 'no executable yet' means continue with re_study"},
            {"do": "Extract the main executable (disc -> ELF with the right load address) and run Ghidra auto-analysis "
                   "once. Results are reused for the same executable (sha256).", "tool": "re_study",
             "args": {"analyze": True},
             "expect": "executable (cpu, processor, base, entry, sha256) and analysis (functions, strings) in the dossier"},
            {"do": "If the disc route fails (packed/encrypted executable, arcade ROM set, code that is loaded at run "
                   "time), snapshot the live game's RAM instead: get the game to gameplay first.", "tool": "re_study",
             "args": {"source": "ram", "session_id": "<session_id>", "analyze": True},
             "expect": "a RAM-image ELF at the platform's RAM base"},
            {"do": "Pick the playbook for the actual task and follow it.", "tool": "re_playbook",
             "args": {"op": "list", "query": "<task words>"}},
            {"do": "Record each address you confirm (with how), each dead end and each open question.",
             "tool": "re_dossier", "args": {"op": "record", "kind": "function", "address": "0x...", "name": "...",
                                            "role": "...", "status": "hypothesis"}},
        ],
        "pitfalls": [
            "GameCube/Wii: processor PowerPC:BE:32:default. 'PowerPC:BE:32:Gekko_Broadway' does NOT exist in gBox's "
            "Ghidra 12.1.4 (no Gekko extension installed); functions with paired-single maths decompile only partly.",
            "ghidra_script / analyze_binary can't pass loader options (-loader BinaryLoader -loader-baseAddr): raw images "
            "(PS-X EXE body, 1ST_READ.BIN, N64 boot code, RAM dumps, XEX images) must be wrapped as ELF first. re_study "
            "does this; never hand Ghidra a raw .bin path.",
            "Small-data / global pointer registers: PowerPC code reaches globals through r13/r2, MIPS through gp. "
            "Without them the decompiler shows unresolved loads. Take them from __init_registers / crt0 or from live "
            "registers (debugger op=info). The dossier keeps them (executable.registers) and ghidra_run passes them.",
            "Phantasy Star Online GameCube main.dol is only a loader: the game code exists in RAM after boot (source=ram).",
            "Large executables take minutes (analysis) to much longer (decompile everything): never start the same "
            "analysis twice; re_study and ghidra_run reuse earlier results.",
            "Protected executables are not Ghidra targets: RE4 2023 (Denuvo) uses the engine's reflection instead "
            "(re4r op=dump_types / types).",
            "Unreal Engine 3 games keep gameplay logic in UnrealScript packages: use unreal_script (playbook "
            "unreal-script), not Ghidra on EBOOT.BIN (an encrypted SELF anyway).",
        ],
        "verify": ["the dossier shows executable.sha256 and analysis.functions > 0",
                   "a documented global/function address of the title falls inside the loaded image"],
        "record": ["re_dossier op=note: what was set up and anything unusual (processor, registers, image base)",
                   "re_dossier op=question for whatever is still unresolved"],
        "examples": [
            {"game": "Metal Arms (GameCube)", "note": "DecompileAll on main.dol (dol_to_elf), PowerPC:BE:32:default, "
             "reg:r13:804BABE0 reg:r2:804C2420, 10800 functions", "ref": "docs/model_swaps.md section 8"},
            {"game": "GTA Liberty City Stories (PS2)", "note": "DecompileAll on SLUS_214.23, MIPS:LE:64:64-32addr, "
             "gp:0x3D6EF0 (derived from gp-relative loads)", "ref": "docs/model_swaps.md section 3"},
            {"game": "WWF No Mercy (N64)", "note": "DecompileAll on a 4 MB RDRAM image, MIPS:BE:32:default, base "
             "0x80000000, entry:0x80000400 jalscan", "ref": "docs/model_swaps.md section 9"},
            {"game": "Parasite Eve (PS1)", "note": "SLUS_006.62 text at 0x80010000, gp 0x8009cd70, entry + jalscan",
             "ref": "knowledge base: Parasite Eve PE.IMG format"},
        ],
    },
    {
        "id": "find-value-writer", "seed_version": 1,
        "title": "Find the code that writes a value (HP, ammo, lives, money, timer)",
        "goal": "Go from a value on screen to the routine that changes it, validated by a breakpoint, ready to patch.",
        "when": ["what writes", "which code changes", "which function", "routine that", "hp writer", "damage routine",
                 "ammo", "health", "lives", "timer", "money", "infinite", "decrease", "subtract"],
        "platforms": ["any"], "tags": ["watchpoint", "writer", "bridge", "hp", "ammo"],
        "steps": [
            {"do": "Check the dossier and the knowledge base: the address or even the writer may be known.",
             "tool": "re_dossier", "args": {"op": "read"}},
            {"do": "Locate the value in RAM: search the number shown on screen, change it in game, search again until "
                   "1-5 candidates; confirm with read_memory.", "tool": "memory_search",
             "args": {"session_id": "<session_id>", "op": "start", "type": "u16", "value": "<shown value>"},
             "expect": "then op=next cmp=eq value=<new value>, repeated"},
            {"do": "Watchpoints need a debugger session (Dolphin GameCube/Wii, DuckStation PS1, mGBA GBA, MAME arcade). "
                   "RetroArch sessions have none: skip to the static route (last step).", "tool": "launch_game",
             "args": {"game_id": "<game_id>", "debug": True}},
            {"do": "Trace the writer end to end: write watchpoint, trigger, Ghidra explains the function, an exec "
                   "breakpoint validates it, a knowledge edge is recorded (validated only if the breakpoint fired and "
                   "the value changed).", "tool": "find_code_that_writes",
             "args": {"session_id": "<session_id>", "address": "0x...", "length": 2, "trigger_key": "<key or ''>",
                      "label": "player HP (u16)"},
             "expect": "function entry, decompiled C, callers, edge id, validated true/false"},
            {"do": "Record it in the dossier, citing the edge (validated only if the tool said validated: true).",
             "tool": "re_dossier",
             "args": {"op": "record", "kind": "function", "address": "<entry>", "name": "<function>",
                      "role": "writes <value>", "status": "validated", "evidence": ["<edge id>"]}},
            {"do": "Static route (no watchpoints): references to the object/global and to the field offset, then test "
                   "a candidate with a reversible patch (playbook patch-point).", "tool": "ghidra_run",
             "args": {"op": "refs", "addresses": ["<global or table address>"]},
             "expect": "also ghidra_run op=grep query='0x32c' (the field offset) over the decompiled code"},
        ],
        "pitfalls": [
            "length must equal the value's size (u16 = 2). A 4-byte watch on a u16 also fires for its neighbour field.",
            "The first hit can be an initialiser, a menu redraw or a copy loop: trigger exactly the event (take one "
            "hit, fire one shot) and check the caller (LR) for the gameplay path.",
            "Values are often stored twice (current vs max, HUD copy vs real value: PSO current HP +0x32C, max +0x2B8). "
            "Watch the one the game logic uses (it changes first).",
            "Always resume the CPU afterwards (debugger op=resume): a halted game looks frozen to the operator.",
            "Endianness: GameCube/Wii/N64/Xbox 360/PS3 big-endian; Dreamcast/PS1/PS2/GBA little-endian. ParaLLEl N64 "
            "exposes RDRAM as little-endian 32-bit words (swap per word).",
        ],
        "verify": ["knowledge edge status 'validated' (exec breakpoint at the entry fired AND the value changed)",
                   "or: a reversible patch of the writer changes the behaviour in game (read_memory / look_at_screen)"],
        "record": ["re_dossier op=record kind=function with the edge id as evidence",
                   "re_playbook op=lesson outcome=success|failure with what was different in this game"],
        "examples": [
            {"game": "Phantasy Star Online Ep I&II Plus (GameCube)", "note": "add_hp(obj, amount) = 0x8001140C writes "
             "TObjPlayer+0x32C; validated by gbox.bridge (breakpoint + value change); item-use handler 0x80116634 calls it",
             "ref": "knowledge edges for game 436e0bb84d5337d1; ROADMAP Phase 4"},
            {"game": "Resident Evil 4 Wii Edition (PAL)", "note": "Mercenaries clock decrement 0x800905A4 found with a "
             "write watchpoint on the Spark's Dolphin", "ref": "gbox/re_games.py WII_PAL"},
        ],
    },
    {
        "id": "patch-point", "seed_version": 1,
        "title": "Turn a found routine into a reversible patch (cheat / mod)",
        "goal": "A same-length code or data change that does what the operator asked, saved as a mod with the original "
                "bytes so it can be rolled back.",
        "when": ["patch", "nop", "infinite", "never decrease", "god mode", "cheat", "make it always", "disable",
                 "freeze the timer", "skip", "bypass"],
        "platforms": ["any"], "tags": ["patch", "mod", "cheat", "hook"],
        "steps": [
            {"do": "Read the dossier entry of the routine and its evidence.", "tool": "re_dossier", "args": {"op": "read"}},
            {"do": "See the instruction and the decompiled function around it.", "tool": "ghidra_run",
             "args": {"op": "explain", "addresses": ["<instruction address>"]},
             "expect": "instruction text + decompiled C; on a live session debugger op=disasm shows the same"},
            {"do": "Read the live original bytes; they must match the executable (else the code moved or is "
                   "decompressed elsewhere).", "tool": "read_memory",
             "args": {"session_id": "<session_id>", "address": "0x...", "length": 4}},
            {"do": "Save the change as a mod (original bytes are kept), apply it, verify it is in effect.", "tool": "mod",
             "args": {"session_id": "<session_id>", "op": "save", "name": "<name>", "desc": "<what it does>",
                      "changes": [{"kind": "write", "address": "0x...", "hex": "60000000"}]},
             "expect": "then mod op=apply, op=verify; test in game; op=rollback once to prove it is reversible"},
            {"do": "Record the patch with the mod/job as evidence, then a lesson on the playbook you used.",
             "tool": "re_dossier",
             "args": {"op": "record", "kind": "patch", "address": "0x...", "name": "<mod name>",
                      "role": "<effect>, original <hex>", "status": "validated", "evidence": ["<job id>"]}},
        ],
        "pitfalls": [
            "Pick the smallest same-length change: NOP the store/subtract (PowerPC 60000000, MIPS 00000000, SH-4 0009), "
            "change an immediate (PowerPC 'subi r0,r3,1' 3803ffff -> 38030000), or flip a branch.",
            "MIPS and SH-4 have delay slots: the instruction after a branch runs too.",
            "Recompilers cache translated code: Xenia compiles guest code once (patch before it first runs, as RE6 Auto "
            "QTE does at boot); Dolphin's JIT may keep the old block. Verify the effect, not just the bytes.",
            "On Xenia never store into code pages from guest code (faults); data belongs in .bss / unused RAM.",
            "A shared helper may have several call sites; a check may exist twice (PSO DC serial check: two addresses).",
            "Disc/ROM-level changes go through file_mod / rom_export, never into the library file.",
        ],
        "verify": ["mod op=verify reports the change in effect", "the in-game behaviour changed (read_memory of the "
                   "value over time, or look_at_screen)", "mod op=rollback restores the original bytes"],
        "record": ["re_dossier op=record kind=patch", "save_recipe if the operator will ask for it again"],
        "examples": [
            {"game": "Resident Evil 4 Wii Edition (PAL)", "note": "merc_timer_freeze 0x800905A0 3803ffff -> 38030000; "
             "unlimited_health 0x8009FD10 7c1e0050 -> 60000000", "ref": "gbox/re_games.py WII_PAL.PATCHES"},
            {"game": "Phantasy Star Online Ver.2 (Dreamcast)", "note": "serial check bypass: 01 E0 (mov #1,r0) at "
             "0x8C1E743E and 0x8C2670B6", "ref": "docs/what_this_is.md section 18"},
            {"game": "Resident Evil 6 (Xbox 360)", "note": "Auto QTE: one-word branch at 0x8244646C to a stub at "
             "0x83C16400, written right after boot because Xenia compiles 0x82446078 once", "ref": "docs/re6.md"},
        ],
    },
    {
        "id": "asset-loader-format", "seed_version": 1,
        "title": "Find the model/asset loader and reverse the file format",
        "goal": "Know where the game loads a model/texture/archive and the exact layout, so gBox can read (and later "
                "write) the files.",
        "when": ["model loader", "file format", "asset", "how are models stored", "texture format", "archive",
                 "extract the model", "no reader", "unknown format", "loader"],
        "platforms": ["any"], "tags": ["format", "loader", "models", "textures", "strings"],
        "steps": [
            {"do": "Make sure the executable is analysed (strings + functions).", "tool": "re_study",
             "args": {"analyze": True}},
            {"do": "Find the file extensions / resource type tags the loader uses.", "tool": "ghidra_run",
             "args": {"op": "strings", "query": "\\.(nj|ape|bin|dat|mdl|tex|tpl|pvr|bml|afs)\\b|MESH|TXTR"},
             "expect": "string addresses"},
            {"do": "Who uses those strings: the resource registration and the loader functions.", "tool": "ghidra_run",
             "args": {"op": "refs", "addresses": ["<string address>"]}},
            {"do": "Decompile the loader: header fields, counts, the pointer-fixup loop, decompression calls.",
             "tool": "ghidra_run", "args": {"op": "explain", "addresses": ["<loader entry>"]}},
            {"do": "Check the hypothesis against several real files from the disc (counts, sizes, offsets in range), "
                   "or against the loaded object in RAM.", "tool": "read_memory",
             "args": {"session_id": "<session_id>", "address": "<loaded object>", "length": 256}},
            {"do": "Record the format (hypothesis until a reader round-trips files or the game draws a written file).",
             "tool": "re_dossier",
             "args": {"op": "record", "kind": "format", "name": "<.ext (engine name)>", "role": "<layout summary>",
                      "status": "hypothesis"}},
        ],
        "pitfalls": [
            "Many engines store file offsets that a fixup turns into pointers at load time (Metal Arms .ape: fixup "
            "0x8029DB68). The fixup lists every pointer slot: use it before moving blocks.",
            "Compressed containers (PRS, LZSS, zlib, MIO0): find the decompressor first; the loader calls it before "
            "parsing.",
            "Texture data is in platform formats (GameCube CMPR/I4/RGB5A3, PS2 swizzled PSMT8, Dreamcast VQ/twiddled) "
            "even when the extension says .tga.",
            "Some models are built or decompressed at run time: then read the loaded object from RAM, or use frame "
            "capture (characters op=extract) as the fallback.",
        ],
        "verify": ["a reader parses many files without errors", "re-writing an unmodified file is byte-identical",
                   "a written file renders correctly in game"],
        "record": ["re_dossier op=record kind=format", "re_dossier op=record kind=function for the loader / fixup / "
                   "decompressor", "re_playbook op=lesson"],
        "examples": [
            {"game": "Metal Arms (GameCube)", "note": "MESH type registered by 0x802A3624 ('MESH'/'ape'), MESH create "
             "0x802A63D4 -> fixup 0x8029DB68, packet drawer 0x802EBD48, TXTR 0x802B6EDC", "ref": "docs/model_swaps.md section 8"},
            {"game": "Parasite Eve (PS1)", "note": "PE.IMG package table in the executable (file offset 0x83B78, RAM "
             "0x80093378): 438 x {u32 sector, u32 info}", "ref": "knowledge base"},
            {"game": "GTA Liberty City Stories (PS2)", "note": "CStreaming::RequestSpecialModel 0x18FF80 -> "
             "CDirectory::FindItem 0x1450D8, RequestModel 0x18B400", "ref": "docs/model_swaps.md section 3"},
            {"game": "WWF No Mercy (N64)", "note": "file table loader 0x80003ab0 (DMA from ROM 0x16C31D8), id resolve "
             "0x80003bd0", "ref": "docs/model_swaps.md section 9"},
        ],
    },
    {
        "id": "entity-table", "seed_version": 1, "title": "Map the entity / object table (player, enemies, objects)",
        "goal": "Find where the game keeps its live objects, their classes and fields, so gBox can read and change any "
                "of them.",
        "when": ["entity table", "object list", "enemies", "actors", "player object", "struct", "where is the player",
                 "enemy hp", "positions", "spawn"],
        "platforms": ["any"], "tags": ["entities", "struct", "objects", "semantic profile"],
        "steps": [
            {"do": "Find a field of the player's object first: a value you can change (HP, or position f32 while "
                   "walking: cmp increased/decreased).", "tool": "memory_search",
             "args": {"session_id": "<session_id>", "op": "start", "type": "f32"}},
            {"do": "Find what points at the object: search for its address as a u32 (in the platform's endianness).",
             "tool": "memory_search",
             "args": {"session_id": "<session_id>", "op": "start", "type": "u32", "value": "<object address>"}},
            {"do": "Read around the pointer: consecutive pointers (null-terminated or with a count) = the table; the "
                   "distance between objects of one class = the stride.", "tool": "read_memory",
             "args": {"session_id": "<session_id>", "address": "<table>", "length": 256}},
            {"do": "Identify classes: +0x00 is often a vtable or a class-name pointer; who references it gives the "
                   "constructor and update.", "tool": "ghidra_run", "args": {"op": "refs", "addresses": ["<vtable>"]}},
            {"do": "Find the manager (add/remove/update loops, capacity) from the table's references.",
             "tool": "ghidra_run", "args": {"op": "refs", "addresses": ["<table address>"]}},
            {"do": "Record the table and each field with how it was checked.", "tool": "re_dossier",
             "args": {"op": "record", "kind": "table", "address": "0x...", "name": "entity table",
                      "role": "<count/stride/terminator>", "status": "hypothesis"}},
        ],
        "pitfalls": [
            "Heap objects move between rooms/levels: re-find them from the table each time; never hard-code a heap "
            "address.",
            "The same class layout shifts by a few bytes between platforms/versions (PSO GameCube -> Dreamcast: +4).",
            "Scanning a whole heap over a GDB stub is slow (~50 s for 10 MB): narrow the range.",
        ],
        "verify": ["walk the table and read_memory each object's class + position: matches what is on screen",
                   "change one enemy's field and see it in game"],
        "record": ["re_dossier op=record kind=table / kind=field", "consider a semantic profile (profiles/*.json) "
                   "once fields are validated"],
        "examples": [
            {"game": "Phantasy Star Online Ep I&II Plus (GameCube)", "note": "0x8050D460: player object then 30 "
             "NPC/object pointers, null-terminated; +0x00 class-name pointer (TObjPlayer, TObjEneBeast)",
             "ref": "profiles/pso-gc-plus-us.json"},
            {"game": "Resident Evil 4 (GameCube)", "note": "EmMgr 0x8027DF20: +0 slot array (slot 0 = player), +4 "
             "count (80), +8 stride (0xDE0)", "ref": "gbox/re_games.py"},
            {"game": "Metal Arms (GameCube)", "note": "CFWorldMesh vtable 0x803D5354, heap scan 0x80600000-0x81000000",
             "ref": "docs/model_swaps.md section 8"},
            {"game": "GTA Liberty City Stories (PS2)", "note": "FindPlayerPed 0x107368 returns *(CWorld::Players "
             "0x408E40 + PlayerInFocus)", "ref": "docs/model_swaps.md section 3"},
        ],
    },
    {
        "id": "level-warp", "seed_version": 1, "title": "Find the level/room load and warp the player",
        "goal": "Put the player on any stage/room/world the operator names, by doing what the game's own door or "
                "level-select does.",
        "when": ["put me on", "take me to", "warp", "level select", "final world", "skip to", "stage", "room",
                 "teleport", "boss"],
        "platforms": ["any"], "tags": ["warp", "level", "room", "stage"],
        "steps": [
            {"do": "Dossier + knowledge base first (warp fields may be known).", "tool": "re_dossier",
             "args": {"op": "read"}},
            {"do": "Find the current level/room id: search unknown, go through a door or finish a level, search "
                   "changed; stay, search unchanged; until a few candidates (small, sequential numbers).",
             "tool": "memory_search",
             "args": {"session_id": "<session_id>", "op": "start", "type": "u8"}},
            {"do": "On a debug session find the code that writes the id: the door / transition routine.",
             "tool": "find_code_that_writes",
             "args": {"session_id": "<session_id>", "address": "<id address>", "length": 1, "label": "room id"}},
            {"do": "Decompile the routine: which fields it sets (stage, room, entry point, position) and which state "
                   "value starts the load.", "tool": "ghidra_run", "args": {"op": "explain", "addresses": ["<entry>"]}},
            {"do": "Warp = write the same fields, then trigger the load the same way (the state/flag the routine sets). "
                   "Only from gameplay, not during fades/cutscenes. Save state first.", "tool": "write_memory",
             "args": {"session_id": "<session_id>", "address": "0x...", "hex_bytes": "..."}},
            {"do": "Keep it for next time.", "tool": "save_recipe",
             "args": {"name": "warp_<game>", "description": "...", "steps": []}},
        ],
        "pitfalls": [
            "Writing only the level id does nothing or desyncs: the game loads on a state change.",
            "First-visit events of a room can crash after a warp (RE4 r101): save state first.",
            "Some ids hang the game (OoT entrances 0x457 / 0x517); warp only during gameplay.",
        ],
        "verify": ["look_at_screen shows the target place", "the room/level id reads back as the target"],
        "record": ["re_dossier op=record kind=function (door/load routine) and kind=field (each warp field)",
                   "save_recipe with the verified steps"],
        "examples": [
            {"game": "Resident Evil 4 (GameCube)", "note": "door use 0x8014CA4C: pG+0x28 stage, +0x29 room, +0x2A entry, "
             "+0x2C..0x38 pos/rot, then pG+0x20=4", "ref": "knowledge base: RE4 GC room warp"},
            {"game": "Zelda: Ocarina of Time (N64 v1.2)", "note": "play->nextEntranceIndex + transition; entrance 0x211 / "
             "0x41F work, 0x457 / 0x517 hang", "ref": "gbox/oot.py"},
        ],
    },
    {
        "id": "input-handler", "seed_version": 1, "status": "draft",
        "title": "Locate the controller input handler / pad state",
        "goal": "Find the pad state words and the code that consumes them (for macros, remapping, 'rapid fire', "
                "auto-actions).",
        "when": ["input handler", "controller", "button", "pad", "rapid fire", "auto fire", "remap", "turbo",
                 "press for me"],
        "platforms": ["any"], "tags": ["input", "pad", "controller"],
        "steps": [
            {"do": "Search the pad word: unknown u16, hold a button -> changed, release -> changed, idle -> unchanged, "
                   "repeat until a few candidates.", "tool": "memory_search",
             "args": {"session_id": "<session_id>", "op": "start", "type": "u16"}},
            {"do": "Tell held / pressed-this-frame / previous-frame words apart (pressed is set for one frame only).",
             "tool": "read_memory", "args": {"session_id": "<session_id>", "address": "<candidate>", "length": 16}},
            {"do": "On a debug session find the code that writes the pad word (the pad read routine).",
             "tool": "find_code_that_writes",
             "args": {"session_id": "<session_id>", "address": "<pad word>", "length": 2, "trigger_key": "<button>",
                      "label": "pad state"}},
            {"do": "Who reads it: the player controller and menus.", "tool": "ghidra_run",
             "args": {"op": "refs", "addresses": ["<pad word or its global>"]}},
            {"do": "Record and test: freeze a bit of the held word, the action repeats; then release.",
             "tool": "re_dossier", "args": {"op": "record", "kind": "global", "address": "0x...", "name": "pad state",
                                            "role": "held buttons bitmask", "status": "hypothesis"}},
        ],
        "pitfalls": [
            "Games copy the pad state into several buffers each frame (raw, mapped, edge-detected): the consumer you "
            "want usually reads the mapped one.",
            "freeze_memory fights the per-frame write: prefer patching the consumer or the mapping.",
            "Analog sticks are separate s8/f32 values; menus may read a different buffer than gameplay.",
        ],
        "verify": ["freezing a bit makes the in-game action happen without the button"],
        "record": ["re_dossier op=record", "re_playbook op=lesson (this playbook is a draft: the first success makes it "
                   "proven)"],
        "examples": [],
    },
    {
        "id": "unreal-script", "seed_version": 1,
        "title": "Unreal Engine 3 games (PS3/360): change gameplay through UnrealScript, not machine code",
        "goal": "Find and patch the script function behind a mechanic in a UE3 game.",
        "when": ["unreal", "ue3", "unrealscript", "ps3", "bytecode", "precision aim", "script"],
        "platforms": ["ps3", "xbox360", "windows_native"], "tags": ["ue3", "script", "bytecode"],
        "steps": [
            {"do": "List the packages.", "tool": "unreal_script", "args": {"path": "<USRDIR or package>", "op": "summary"}},
            {"do": "Search names + script for the mechanic.", "tool": "unreal_script",
             "args": {"path": "<USRDIR>", "op": "search", "query": "<regex>"}},
            {"do": "Read the function as UnrealScript.", "tool": "unreal_script",
             "args": {"path": "<USRDIR>", "op": "disasm", "function": "Class.Function"}},
            {"do": "Apply/revert profile presets on the live session (same-length bytecode rewrites located in RAM).",
             "tool": "script_patch", "args": {"session_id": "<session_id>", "op": "locate"}},
        ],
        "pitfalls": ["Edits must keep the bytecode length (JumpIfNot -> Jump).",
                     "Cooked PS3 packages are fully compressed (64 KiB zlib blocks); the in-RAM bytecode equals the disc "
                     "bytecode except object pointers / name indices, so a byte pattern finds the function live."],
        "verify": ["script_patch op=status shows the preset applied", "the mechanic behaves differently in game"],
        "record": ["re_dossier op=record kind=function name='Class.Function' role=...", "a profile preset"],
        "examples": [{"game": "Stranglehold (PS3)", "note": "StrangleholdProjectile_Bullet_PrecisionAim."
                      "ResolvePrecisionAim + StrangleholdPawn.ServerResolveDamage (@01e1 branch, @02a6 DamageScale=1000)",
                      "ref": "profiles/stranglehold-ps3-us.json"}],
    },
]


def _f(kind, address, name, role, ref):
    return {"kind": kind, "address": address, "name": name, "role": role, "ref": ref}


# match: platform + every word of title_has in the catalog title (lower case)
TITLE_FACTS = [
    {"platform": "gamecube", "title_has": ["resident evil 4"], "label": "RE4 GameCube NTSC-U (G4BE08)",
     "executable": {"processor": "PowerPC:BE:32:default", "registers": {"r13": "0x802B9780"}},
     "facts": [
         _f("global", "0x802B2280", "pG", "pointer to GLOBAL work (= 0x8027F7D0): +0x4FA4 u32 money, +0x4FA8 u16 room "
            "(0xSSRR), +0x4FB0 s16 player HP, +0x52F4 enemy-set table (r13-0x7500)", "gbox/re_games.py"),
         _f("global", "0x802B2284", "pSys", "pointer to the system save (= 0x80287E58): +4 'extra' bit flags", "gbox/re_games.py"),
         _f("table", "0x802138E0", "ItemMgr", "+0x14 item array (14-byte items: u16 id, u16 count, ...), +0x1C slot count",
            "gbox/re_games.py"),
         _f("table", "0x8027DF20", "EmMgr", "enemy manager: +0 slot array (slot 0 = player), +4 count (80), +8 stride "
            "(0xDE0); em +0x94 f32 pos[3]", "gbox/re_games.py"),
         _f("global", "0x80279308", "Mercenaries timer", "u32 frames at 30 fps", "gbox/re_games.py"),
         _f("function", "0x80147E6C", "take_item(id, count, 0)", "what picking an item up calls; auto-places it in the case",
            "gbox/re_games.py"),
         _f("function", "0x8001AF74", "ItemMgr::count(mgr, id)", "item count", "gbox/re_games.py"),
         _f("function", "0x8014CA4C", "door use", "sets pG+0x28 stage, +0x29 room, +0x2A entry, +0x2C..0x38 pos/rot, then "
            "pG+0x20=4", "knowledge base: RE4 GC room warp"),
         _f("hook", "0x80122610", "main loop hook site", "'bl 0x80122634' (an empty function) every frame: gBox's dispatcher",
            "gbox/re_games.py"),
     ]},
    {"platform": "wii", "title_has": ["resident evil 4"], "label": "RE4 Wii Edition PAL (RB4P08)",
     "executable": {"processor": "PowerPC:BE:32:default", "registers": {"r13": "0x80444860"}},
     "facts": [
         _f("global", "0x8043D3E0", "pG", "GLOBAL work pointer (r13-0x7480): +0x4FA8 money, +0x4FAC room, +0x4FB4 HP",
            "gbox/re_games.py WII_PAL"),
         _f("function", "0x80090490", "Mercenaries clock routine", "matched from GC 0x800C0F20", "gbox/re_games.py WII_PAL"),
         _f("patch", "0x800905A0", "merc_timer_freeze", "3803ffff -> 38030000: the clock stops", "gbox/re_games.py WII_PAL"),
         _f("patch", "0x8009FD10", "unlimited_health", "7c1e0050 -> 60000000: damage never subtracted", "gbox/re_games.py WII_PAL"),
     ]},
    {"platform": "gamecube", "title_has": ["phantasy star online", "episode i"], "label": "PSO Ep I&II Plus (GPOE8P)",
     "executable": {"processor": "PowerPC:BE:32:default",
                    "note": "main.dol is only a loader: analyse a RAM image after boot (re_study source=ram)"},
     "facts": [
         _f("table", "0x8050D460", "entity table", "player object, then NPC/object pointers, null-terminated",
            "profiles/pso-gc-plus-us.json"),
         _f("global", "0x8050EA10", "TObjPlayer_objs", "players table", "profiles/pso-gc-plus-us.json"),
         _f("function", "0x8001140C", "add_hp(obj, amount)", "hp += amount, bounded by max HP (+0x2B8); writes +0x32C",
            "knowledge edge (gbox.bridge, validated)"),
         _f("function", "0x80116634", "item-use handler", "vtable slot at 0x8049F820; Monomate path calls add_hp",
            "knowledge edge (gbox.bridge, validated)"),
         _f("field", "+0x32C", "TObjPlayer.hp", "u16 current HP (max at +0x2B8); TP +0x32E / +0x2BA",
            "profiles/pso-gc-plus-us.json"),
         _f("field", "+0x38", "TObjPlayer.pos", "f32 x/y/z; angle int32 at +0x60", "profiles/pso-gc-plus-us.json"),
     ]},
    {"platform": "dreamcast", "title_has": ["phantasy star online", "ver. 2"], "label": "PSO Ver.2 Dreamcast (2OEF)",
     "executable": {"processor": "SuperH4:LE:32:default", "base": "0x8C010000"},
     "facts": [
         _f("table", "0x8C477D40", "entity table", "TObjPlayer, TObjNpc*, TObjCityDoor*..., null-terminated",
            "profiles/pso-v2-dc-us.json"),
         _f("global", "0x8C42D92C", "player pointer", "holds the TObjPlayer pointer (also in the CodeBreaker HP code)",
            "profiles/pso-v2-dc-us.json"),
         _f("field", "+0x330", "TObjPlayer.hp", "u16 HP (GameCube +0x32C shifted by 4)", "profiles/pso-v2-dc-us.json"),
         _f("field", "+0xC20", "TObjPlayer.meseta", "u32 live meseta (the menu reads it)", "knowledge base: PSO meseta"),
         _f("function", "0x8C022428", "equip(player, item, 0)", "slot = item vtable+0x80(); 7 slot pointers at +0xBCC",
            "knowledge base: PSO multi-equip"),
         _f("patch", "0x8C1E743E", "serial check bypass 1", "01 E0 (mov #1,r0)", "docs/what_this_is.md"),
         _f("patch", "0x8C2670B6", "serial check bypass 2", "01 E0 (mov #1,r0)", "docs/what_this_is.md"),
     ]},
    {"platform": "gamecube", "title_has": ["agent under fire"], "label": "007 Agent Under Fire GameCube USA (GW7E69)",
     "executable": {"processor": "PowerPC:BE:32:default", "registers": {"r13": "0x804EB040", "r2": "0x804EC2A0"},
                    "note": "Bond.elf (/base.elf/Bond.elf, sha256 1a9c0d19...) keeps .symtab and .rela.*: 17636 "
                            "CodeWarrior-mangled symbols; Quake III / Ritual UberTools lineage (FAKK2 names)"},
     "facts": [
         _f("global", "0x804E38B0", "g_entities", "gentity_t* table, 0x2B0 bytes each; count at globals+0x80 "
            "(0x803F0210); +0x1E4 inuse, +0x24C Entity*, +0x5C s.modelindex, +0x124 svflags (0x80 hidden), "
            "+0x214/+0x220 absmin/absmax, +0x22C currentOrigin", "profiles/auf-gcn-us.json"),
         _f("global", "0x804E3530", "gClientArr", "gclient_t* array (stride at gClientSize 0x804E3534 = 0x860, count "
            "gNumClients 0x804E3068, viewed index currentPlayer 0x804E34CC): +0x74 eye, +0x68 angles (pitch,yaw,roll "
            "deg), +0x2D0 fov deg; scripted camera +0x2DC/+0x2E8/+0x2F4 while pm_flags(+0xC) & 0x100",
            "profiles/auf-gcn-us.json"),
         _f("field", "+0x4", "Entity.vtable", "vtable pointer (Class keeps it at +4); +0x1C classname, +0x28 model "
            "(str -> strdata.data), +0x8C origin, +0x98 angles, +0x2C/+0x38 mins/maxs, +0x14 edict, +0x18 client",
            "profiles/auf-gcn-us.json"),
         _f("table", "0x802612C0", "__vt__5Actor", "NPC class vtable; Player 0x80254E70, DeathmatchPlayer 0x802482C0, "
            "Bot 0x80287BB4, Sentient 0x80259E4C (246 ClassDefs from the __sinit_* initialisers)",
            "profiles/auf-gcn-us.json"),
         _f("function", "0x800990D0", "G_NextEntity(Entity*)", "walks g_entities[0..num_entities) skipping !inuse",
            "docs/auf-entity-analysis.md"),
         _f("function", "0x800138A0", "R_BuildCameraMatrix(player, mtx, fov*, angles*)", "camera from gclient_t; "
            "R_RenderPlayerView_Sub 0x800149F8 -> R_Draw 0x800142B0 -> R_SetupProjection 0x80014270 -> "
            "veMatPerspective 0x8019B4D0 (m00 = cot/aspect, m11 = cot: vertical fov)", "docs/auf-entity-analysis.md"),
         _f("function", "0x80075D00", "Entity::setModel(const char*)", "gi.setmodel -> edict s.modelindex; model str "
            "at Entity+0x28, handle at +0x144", "docs/auf-entity-analysis.md"),
     ]},
    {"platform": "gamecube", "title_has": ["metal arms"], "label": "Metal Arms GameCube USA (GM5E7D)",
     "executable": {"processor": "PowerPC:BE:32:default", "registers": {"r13": "0x804BABE0", "r2": "0x804C2420"}},
     "facts": [
         _f("function", "0x8029DB68", ".ape pointer fixup", "lists every pointer slot of an FMesh", "docs/model_swaps.md s8"),
         _f("function", "0x802A63D4", "MESH resource create", "calls the fixup", "docs/model_swaps.md s8"),
         _f("function", "0x802A3624", "MESH type registration", "'MESH' / 'ape'", "docs/model_swaps.md s8"),
         _f("function", "0x802B6EDC", "TXTR type registration", "texture resource; create 0x802B7D14 -> 0x802B7474",
            "docs/model_swaps.md s8"),
         _f("function", "0x802EBD48", "packet drawer", "sets VAT 7 from the VB", "docs/model_swaps.md s8"),
         _f("function", "0x801C9B20", "player update", "called with Player_aPlayer", "docs/model_swaps.md s8"),
         _f("global", "0x80481AF8", "Player_aPlayer", "0x24C8 bytes each; +0x18DC the entity he controls now",
            "docs/model_swaps.md s8"),
         _f("global", "0x804A2DE0", "camera-to-world", "3 axis rows + position", "docs/model_swaps.md s8"),
         _f("global", "0x803D5354", "CFWorldMesh vtable", "heap scan finds bots", "docs/model_swaps.md s8"),
         _f("format", "", ".ape (FMesh)", "file offsets fixed up into pointers; bones 0x138 bytes; rigid packets per bone",
            "docs/model_swaps.md s8"),
         _f("format", "", ".mst (master file)", "'GNAF' magic, 36-byte entries {name[20], offset, size, mtime, crc}",
            "docs/model_swaps.md s8"),
     ]},
    {"platform": "ps2", "title_has": ["liberty city stories"], "label": "GTA Liberty City Stories PS2 (SLUS-21423)",
     "executable": {"processor": "MIPS:LE:64:64-32addr", "registers": {"gp": "0x3D6EF0"}},
     "facts": [
         _f("function", "0x107368", "FindPlayerPed", "returns *(CWorld::Players 0x408E40 + PlayerInFocus 0x3D9BC8); 162 callers",
            "docs/model_swaps.md s3"),
         _f("function", "0x18FF80", "CStreaming::RequestSpecialModel(id, name, flags)", "model streaming entry",
            "docs/model_swaps.md s3"),
         _f("function", "0x1450D8", "CDirectory::FindItem", "IMG directory lookup", "docs/model_swaps.md s3"),
         _f("function", "0x18B400", "RequestModel", "", "docs/model_swaps.md s3"),
         _f("global", "0x3D8720", "CModelInfo::ms_modelInfoPtrs", "pointer; numModelInfos at 0x3D9BA0", "docs/model_swaps.md s3"),
         _f("function", "0x1F3728", "intro movies", "jal 0x35A020 four times", "docs/model_swaps.md s3"),
         _f("field", "+0x58", "CPed.modelIndex", "s16; position +0x30, vehicle +0x534, in-vehicle +0x538",
            "docs/model_swaps.md s3"),
     ]},
    {"platform": "n64", "title_has": ["no mercy"], "label": "WWF No Mercy USA Rev A (NW4E 1.1)",
     "executable": {"processor": "MIPS:BE:32:default", "base": "0x80000000",
                    "note": "analysed as a 4 MB RDRAM image (entry:0x80000400 jalscan); boot segment ROM 0x1000 -> 0x80000400"},
     "facts": [
         _f("function", "0x80003ab0", "file table loader", "malloc(0x1300C), DMA from ROM 0x16C31D8", "docs/model_swaps.md s9"),
         _f("function", "0x80003bd0", "file id resolve", "hangs for ids outside 1..0x4C02", "docs/model_swaps.md s9"),
         _f("function", "0x80018a3c", "build part list(costume, partlist)", "called at 0x8001495C", "docs/model_swaps.md s9"),
         _f("function", "0x80015d8c", "load parts", "", "docs/model_swaps.md s9"),
         _f("table", "0x800A8980", "part lists", "0x270 bytes per slot", "docs/model_swaps.md s9"),
         _f("global", "0x80076264", "wrestler number per slot", "s16 + 2*slot", "docs/model_swaps.md s9"),
     ]},
    {"platform": "xbox360", "title_has": ["resident evil 6"], "label": "Resident Evil 6 Xbox 360 (BH6MasterRelease)",
     "executable": {"base": "0x82000000", "note": "default.xex decoded with gbox.re6.xex_image"},
     "facts": [
         _f("global", "0x83CA52FC", "sPlayer", "+0x28.. player character pointers", "docs/re6.md"),
         _f("field", "+0xF20", "uPlayer.life", "s16; LifeMax +0xF22; inventory +0x3EF0 (24 cItem x 0x1C)", "docs/re6.md"),
         _f("function", "0x82B1C1C8", "uPlayer::setItem", "give/clear inventory slots", "docs/re6.md"),
         _f("function", "0x82446078", "QTE ButtonUnit update", "switch on prompt type", "docs/re6.md"),
         _f("patch", "0x8244646C", "Auto QTE", "one-word branch to a stub at 0x83C16400 (r28 = success)", "docs/re6.md"),
         _f("function", "0x824D8800", "unused debug unlock-all", "this = save manager [0x83CA4F98]", "docs/re6.md"),
     ]},
    {"platform": "psx", "title_has": ["parasite eve"], "label": "Parasite Eve USA (SLUS-00662)",
     "executable": {"processor": "MIPS:LE:32:default", "base": "0x80010000", "registers": {"gp": "0x8009CD70"}},
     "facts": [
         _f("table", "0x80093378", "PE.IMG package table", "~438 x {u32 start sector, u32 packed info}", "knowledge base"),
         _f("function", "0x8003D94C", "UV relocation", "model entry word -> texture page coordinates", "knowledge base"),
         _f("patch", "0x8003B230", "back-face cull (renderer 1)", "nclip; blez -> 00000000 draws back faces "
            "(also 0x8003B380, 0x8003B4D0, 0x8003B620)", "knowledge base"),
     ]},
    {"platform": "n64", "title_has": ["ocarina of time"], "label": "Zelda: Ocarina of Time N64 (v1.2)",
     "executable": {"processor": "MIPS:BE:32:default"},
     "facts": [
         _f("global", "0x8011AC80", "gSaveContext", "v1.2; ZELDAZ marker", "gbox/oot.py"),
         _f("global", "0x801C8D60", "gPlayState", "v1.2; +0x11E1A nextEntranceIndex, +0x11E15 transition", "gbox/oot.py"),
     ]},
    {"platform": "n64", "title_has": ["super mario 64"], "label": "Super Mario 64 USA",
     "executable": {"processor": "MIPS:BE:32:default"},
     "facts": [
         _f("format", "0x0F5330", "segment 0x04 (MIO0)", "group0 model data, ROM 0x0F5330-0x108590", "gbox/sm64_mario.py"),
         _f("format", "0x108590", "segment 0x17 (geo layouts)", "ROM 0x108590-0x10B3C0; Mario geo 0x17002DD4", "gbox/sm64_mario.py"),
         _f("format", "0x4CE710", "Mario animation DMA table", "u32 count 0xD1, then (offset, size)", "gbox/sm64_mario.py"),
     ]},
    {"platform": "ps3", "title_has": ["stranglehold"], "label": "Stranglehold PS3 (BLUS30081, UE3)",
     "executable": {"note": "Unreal Engine 3: gameplay is UnrealScript in CookedPS3 packages (playbook unreal-script)"},
     "facts": [
         _f("function", "", "StrangleholdProjectile_Bullet_PrecisionAim.ResolvePrecisionAim", "hit vs miss cinema",
            "profiles/stranglehold-ps3-us.json"),
         _f("function", "", "StrangleholdPawn.ServerResolveDamage", "@01e1 precision-aim branch, @02a6 DamageScale=1000",
            "profiles/stranglehold-ps3-us.json"),
     ]},
]
