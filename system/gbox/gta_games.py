"""Per-game addresses for `gta_mods` (gbox/gta_mods_tool.py): the PS2 GTAs (NTSC-U discs in the library).

All addresses are EE RAM addresses of the retail USA ELFs (RetroArch/pcsx2_libretro exposes EE RAM at offset 0, so the
native address is the RAM offset). GTA III's ELF ships with its symbol table, so its names are the real C++ symbols;
the other games were mapped from their ELFs (strings/xrefs + GTA III/re3 code shapes) and checked live.

Keys used by the tool:
  match/serial/crc     - detection (title regex; the ELF CRC PCSX2 prints)
  hook_frame           - a `jal` inside CGame::Process that runs once per unpaused frame (dispatcher replaces it)
  hook_frame_fn        - its original target
  hook_post            - a later per-frame `jal` (after the world/peds were processed): the post-frame stub
  hook_post_fn         - its original target
  boot_vt / boot_fn    - a vtable slot (DATA page, safe to write from outside) called within a frame: the one-time
                         bootstrap that lets the EE itself apply code patches (outside writes to compiled code
                         pages crash pcsx2_libretro)
  punch_site/_fn       - `jal CPhysical::ApplyMoveForce` in CPed::FightStrike (victim knock-back); attacker reg
  fn.*                 - game functions the cave calls
  off.*                - struct offsets
  flags.*              - cheat flags / tunables in data memory
  pads / pad_btn       - CPad::Pads[0] and {button: (NewState offset, OldState offset)} for car_jump (stick clicks;
                         CPad::UpdatePads runs at the top of CGame::Process, before the dispatcher, so New && !Old is
                         a press edge)
  ped_pool_ptr / ped_stride - CPools::ms_pPedPool (CPool {objects, flags, size, ..}; flags bit 7 = free) and slot size
  fps                  - game frames per second (ped_rain timing)
A game only gets the ops whose keys it has; the cave leaves the rest out.
"""

GAMES = {
    "gta3": {
        "name": "Grand Theft Auto III", "match": r"grand theft auto iii|gta ?3|gta iii", "serial": "SLUS-20062",
        "crc": "5E115FB6", "elf": "SLUS_200.62",
        "check": (0x00100008, 0x3C1A0060),           # sanity word at the ELF entry (lui k0 ...) - filled at runtime check
        "hook_frame": 0x0027A7F0, "hook_frame_fn": 0x00280C30,      # CGame::Process: jal CPad::DoCheats()
        "hook_post": 0x0027A938, "hook_post_fn": 0x00251DE0,        # CGame::Process: jal CCamera::Process()
        "boot_vt": 0x004120A8, "boot_fn": 0x001EBC30,               # __vt__10CPlayerPed[ProcessControl]
        "punch_site": 0x003410C0, "punch_attacker_reg": "s5",       # FightStrike: jal ApplyMoveForce(victim=s0)
        "fn": {
            "FindPlayerPed": 0x00291560, "FindPlayerCoors": 0x00291740, "FindPlayerVehicle": 0x002916A0,
            "ApplyMoveForce": 0x0028FC60, "AddExplosion": 0x001976B0, "rand": 0x00109E88,
            "RequestModel": 0x002E1F00, "LoadAllRequestedModels": 0x002DE230,
            "VehicleNew": 0x001C0310, "AutomobileCtor": 0x001B7190, "WorldAdd": 0x002AC8F0,
            "WarpPedIntoCar": 0x001CCC40, "UpdateRwFrame": 0x0026B050, "SetRotate": 0x001818E0,
            "AddPed": 0x001EE490,            # CPopulation::AddPed(ePedType, model, CVector const&) -> CPed*
            "RemovePed": 0x001EE450,         # CPopulation::RemovePed(CPed*): CWorld::Remove + delete
        },
        "veh_size": 0x650,
        "off": {"pos": 0x30, "speed": 0x94, "mass": 0xDC, "veh_status": 0x64, "veh_doorlock": 0x250,
                "pl_ped": 0x0, "ped_in_veh": 0x358, "ped_veh": 0x354, "health": 0x2C0, "ped_type": 0x378, "model": 0x70},
        "status_mask": 0x07, "status_abandoned": 0x20,
        "info_base": 0x005F4FC0, "info_stride": 16, "info_loadstate": 8,
        "veh_pool_ptr": 0x0041685C, "ped_pool_ptr": 0x00416858,
        "players": 0x00510380, "player_focus": 0x004169D8, "player_stride": 0x110,
        # car_jump: CPad::Pads (GetPad: Pads + n*0x78); HornJustDown reads LeftShock at +0x24 / OldState +0x4C
        "pads": 0x00508F40, "pad_btn": {"l3": (0x24, 0x4C), "r3": (0x26, 0x4E)}, "pad_default": "r3",
        "ped_stride": 0x5B0,                       # CPool<CPed,CPlayerPed>::GetIndex divides by 0x5B0
        "flags": {
            "flying_cars": 0x00415E48,            # CVehicle::bAllDodosCheat (the CHITTYCHITTYBB cheat)
            "wheels_only": 0x00415E44,
            "ped_density": 0x00413648,            # CPopulation::PedDensityMultiplier (float, 1.0)
            "car_density": 0x0041367C,            # CCarCtrl::CarDensityMultiplier (float, 1.0)
        },
        # CPed::FinishLaunchCB: player jump = ApplyMoveForce(0, 0, 8.5) -> `lui v0, 0x4108` (8.5f)
        "jump_site": 0x001CD780, "jump_lui_reg": "v0", "jump_default": 8.5, "ped_mass": 70.0, "gravity": 0.008, "fps": 30,
        "handling": None,                          # filled below
        "models": {"rhino": 122, "heli": 126, "heli_name": "Dodo (GTA III has no drivable helicopter)"},
        "explosion_types": {"grenade": 0, "molotov": 1, "rocket": 2, "car": 3, "car_quick": 4, "heli": 5,
                            "mine": 6, "barrel": 7, "tank_grenade": 8},
    },
    "lcs": {
        # Liberty City Stories (SLUS-21423, ELF CRC 7EA439F5). No symbols: mapped from the ELF with Ghidra (DecompileAll on
        # an EE->MIPS64 conversion, gbox-data/analysis/gta/) + capstone, using GTA III/re3 code shapes; pools/player/vtable
        # checked against a live RAM read. Only car_jump and ped_rain are mapped so far (no punch/tank/heli/giant here).
        "name": "Grand Theft Auto: Liberty City Stories", "match": r"liberty city stories|lcs", "serial": "SLUS-21423",
        "crc": "7EA439F5", "elf": "SLUS_214.23",
        # CGame::Process (0x2FBAF0): CPad::UpdatePads at 0x2FBB9C, then the unpaused part; this `jal` is unconditional there
        "hook_frame": 0x002FBD20, "hook_frame_fn": 0x001CE1B0,
        "boot_vt": 0x003CB2CC, "boot_fn": 0x00347030,  # CPlayerPed vtable (0x3CB278) entry +0x50: ProcessControl
        "fn": {
            "FindPlayerPed": 0x00107368,      # Players[focus].m_pPed (Players 0x408E40, stride 0x190, focus u8 0x3D9BC8)
            "FindPlayerVehicle": 0x00107278,  # ped+0x538 (in vehicle) ? ped+0x534 : 0
            "rand": 0x0034FCE0,               # Park-Miller, 31-bit
            "AddPed": 0x002EE638,             # CPopulation::AddPed(type, model, CVector*, a3): new + ctor + SetPosition + CWorld::Add
            "RemovePed": 0x002EEDB0,          # CPopulation::RemovePed(ped): CWorld::Remove (0x173718) + virtual dtor(3)
        },
        "off": {"pos": 0x30, "speed": 0x70, "ped_in_veh": 0x538, "ped_veh": 0x534, "pl_ped": 0x0,
                "ped_type": 0x560, "model": 0x58},   # speed: CPhysical::ApplyGravity (0x2BCBD8) does speed.z(+0x78) -= 0.008*step
        "gravity": 0.008, "fps": 30,
        "players": 0x00408E40, "player_focus": 0x003D9BC8, "player_stride": 0x190,
        # CPad::Pads 0x408C60 (GetPad: +n*0xBC). CPad::Update (0x16F8D8) copies NewState (+2..+0x31) to OldState (+0x32..)
        # and maps pad bits 0x200 (L3) -> +0x2E, 0x400 (R3) -> +0x30.
        "pads": 0x00408C60, "pad_btn": {"l3": (0x2E, 0x5E), "r3": (0x30, 0x60)}, "pad_default": "l3",
        "ped_pool_ptr": 0x003D5AE8, "ped_stride": 0xCD0,   # CPools::Initialise (0x22E6D0): "Peds", 70 x 0xCD0
        "veh_pool_ptr": 0x003D5AEC,
    },
}
