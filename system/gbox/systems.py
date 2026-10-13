"""HyperSpin/Attract-Mode system names -> gBox platform id + default libretro core (+ BIOS needs).

Matching is by case-insensitive substring on the emulator's `system` name, emulator name, then rompath, first rule wins.
`core=None` means no Linux/arm64 libretro path: those games launch on a Windows node via the drive's RocketLauncher.
Core availability != playability: a game is only marked playable after a launch test succeeds.
"""
import re

# (match regex, platform, core, bios subpaths under the RetroArch system dir)
RULES: list[tuple[str, str, str | None, list[str]]] = [
    # --- Sega ---
    (r"dreamcast", "dreamcast", "flycast", ["dc"]),
    (r"naomi|atomiswave", "naomi", "flycast", ["dc", "../../Flycast/data/naomi.zip->dc/naomi.zip"]),   # naomi.zip sits with Flycast on the drive
    (r"hikaru|model 2|model 3|ringedge|ringwide|triforce|lindbergh|chihiro", "sega_arcade_pc", None, []),
    (r"saturn", "saturn", "yabasanshiro", ["saturn_bios.bin", "sega_101.bin", "mpr-17933.bin"]),
    (r"32x", "sega32x", "picodrive", []),
    (r"sega cd|mega-cd|mega cd", "segacd", "genesis_plus_gx", ["bios_CD_U.bin", "bios_CD_E.bin", "bios_CD_J.bin"]),
    (r"pico", "segapico", "picodrive", []),
    (r"genesis|mega drive|nomad|streets of rage", "genesis", "genesis_plus_gx", []),
    (r"master system|mark 3|mark iii|samsung gamboy", "sms", "genesis_plus_gx", []),
    (r"othello multivision", "sg1000", "genesis_plus_gx", []),
    (r"game gear", "gamegear", "genesis_plus_gx", []),
    (r"sg-1000", "sg1000", "genesis_plus_gx", []),
    # --- Nintendo ---
    (r"gamecube|game cube", "gamecube", "dolphin", []),
    (r"wiiware|wii(?! u)", "wii", "dolphin", []),
    (r"wii u", "wiiu", None, []),
    (r"switch", "switch", None, []),
    (r"3ds", "3ds", "citra", []),
    (r"nintendo ds|\bnds\b", "nds", "melonds", []),
    (r"n64dd|64dd", "n64dd", "parallel_n64", ["64DD_IPL.bin"]),
    (r"nintendo 64|\bn64\b", "n64", "parallel_n64", []),        # mupen64plus_next has no linux/aarch64 build
    (r"game boy advance|pokemon hacks", "gba", "mgba", []),
    (r"super game boy", "sgb", "mesen2", []),
    (r"game boy color", "gbc", "gambatte", []),
    (r"game boy|pokemon classics", "gb", "gambatte", []),
    (r"virtual boy", "virtualboy", "mednafen_vb", []),
    (r"pok.mon mini|pokimon mini", "pokemini", "pokemini", []),
    (r"game & watch", "gameandwatch", "gw", []),
    (r"famicom disk", "fds", "mesen", ["disksys.rom"]),
    (r"satellaview|bs-x|sufami|super famicom|super nintendo|snes|super mario world|super metroid", "snes", "snes9x", []),
    (r"msu-1", "snes", "bsnes", []),
    (r"famicom|nintendo entertainment|\bnes\b|nintendo classic mini|technos nintendo|nintendo prototypes", "nes", "mesen", []),
    # --- Sony ---
    (r"pocketstation", "pocketstation", "pokketstation", ["pocketstation.bin"]),   # BIOS required (not on the drive yet)
    (r"playstation portable|playstation minis|\bpsp\b", "psp", "ppsspp", []),
    (r"playstation 2|\bps2\b", "ps2", "pcsx2", ["pcsx2/bios", "ps2->pcsx2/bios"]),   # HyperSpin keeps PS2 BIOS in system/ps2
    (r"playstation 3|ps3", "ps3", None, []),                    # RPCS3 on Windows nodes (no libretro core)
    (r"playstation 4|playstation 5", "ps_modern", None, []),
    (r"playstation", "psx", "pcsx_rearmed", ["scph5500.bin", "scph5501.bin", "scph5502.bin", "scph1001.bin"]),
    # --- NEC / SNK / others ---
    (r"pc-fx", "pcfx", "mednafen_pcfx", ["pcfx.rom"]),
    (r"supergrafx", "supergrafx", "mednafen_supergrafx", []),
    (r"pc engine-cd|turbografx-cd", "pcecd", "mednafen_pce", ["syscard3.pce"]),
    (r"pc engine|turbografx", "pce", "mednafen_pce", []),
    (r"neo geo cd", "neocd", "neocd", ["neocd"]),
    (r"neo geo pocket", "ngp", "mednafen_ngp", []),
    (r"3do", "3do", "opera", ["panafz10.bin"]),
    (r"cd-i", "cdi", "same_cdi", ["same_cdi"]),          # full MAME set incl. the servo MCU ROM lives in same_cdi/bios
    (r"jaguar", "jaguar", "virtualjaguar", []),
    (r"lynx", "lynx", "handy", ["lynxboot.img"]),
    (r"atari st", "atarist", "hatari", ["tos.img"]),
    (r"atari 8-bit|atari 5200", "atari8", "atari800", ["5200.rom", "ATARIXL.ROM", "ATARIBAS.ROM"]),
    (r"atari 7800", "atari7800", "prosystem", ["7800 BIOS (U).rom"]),
    (r"atari 2600", "atari2600", "stella", []),
    (r"wonderswan", "wonderswan", "mednafen_wswan", []),
    (r"colecovision", "coleco", "gearcoleco", ["colecovision.rom"]),
    (r"intellivision", "intellivision", "freeintv", ["exec.bin", "grom.bin"]),
    (r"odyssey 2", "odyssey2", "o2em", ["o2rom.bin"]),
    (r"channel f", "channelf", "freechaf", ["sl31253.bin", "sl31254.bin", "sl90025.bin"]),
    (r"vectrex", "vectrex", "vecx", []),
    (r"supervision", "supervision", "potator", []),
    (r"mega duck", "megaduck", "sameduck", []),
    (r"amiga|cdtv", "amiga", "puae", ["kick34005.A500", "kick40068.A1200", "kick40060.CD32"]),
    (r"commodore 64|max machine", "c64", "vice_x64sc", []),
    (r"vic-20", "vic20", "vice_xvic", []),
    (r"amstrad", "cpc", "cap32", []),
    (r"zx spectrum", "zxspectrum", "fuse", []),
    (r"msx", "msx", "bluemsx", ["Machines", "Databases"]),
    (r"x68000", "x68000", "px68k", ["keropi"]),
    (r"sharp x1", "x1", "x1", []),
    (r"apple ii", "apple2", "applewin", []),
    (r"ms-dos", "dos", "dosbox_pure", []),
    (r"scummvm", "scummvm", "scummvm", []),
    (r"doom", "doom", None, []),     # HyperSpin Doom = GZDoom mods launched by .bat files: run them on Windows via RocketLauncher
    (r"chailove", "chailove", "chailove", []),
    (r"bbc micro", "bbcmicro", "b2", []),
    (r"arcadia 2001", "arcadia2001", "amiarcadia", []),
    (r"super cassette vision", "scv", "emuscv", []),
    (r"dice", "dice", "dice", []),
    (r"phantom system|gluk video", "nes", "mesen", []),
    (r"pacmame|hacked games|street fighter hack", "arcade_hbmame", "hbmame", []),
    (r"gaelco", "arcade", "mame", []),
    # computers / rare consoles without a dedicated arm64 libretro core: Windows node (RocketLauncher + MAME/MESS)
    (r"acorn electron|vector-06c|mikrosha|mz-2500|sam coupe|astrocade|hector|creativision|pv-1000|sord m5|"
     r"exidy sorcerer|super acan|game pocket|adventure vision|touhou|namco system es3", "computer_misc", None, []),
    # --- Windows-only (PC launchers, modern consoles, special hardware) ---
    (r"xbox 360|xbox360", "xbox360", None, []),          # Xenia on Windows nodes (gbox/xenia.py)
    (r"xbox|teknoparrot|taito type x|nesicaxlive|examu|pc games|arcadepc|future pinball|pinball|flash games|"
     r"java games|mugen|openbor|ouya|popcap|laserdisc|daphne|american laser|mfme|locomalito|angry birds|darksiders|"
     r"settings|magazines|wow action|jukebox|ledblinky", "windows_native", None, []),
    # --- Arcade (MAME / FBNeo sets, and every virtual MAME collection) ---
    (r"final burn|fbneo|capcom play system iii", "arcade_fbneo", "fbneo", []),
    (r"hbmame", "arcade_hbmame", "hbmame", []),
]

ARCADE = ("arcade", "mame", [])
_compiled = [(re.compile(p, re.I), plat, core, bios) for p, plat, core, bios in RULES]


def classify(system: str, emulator: str = "", rompath: str = "") -> tuple[str, str | None, list[str]]:
    """Return (platform, default core or None, bios subpaths). Any collection drawing on the shared MAME set is arcade."""
    if re.search(r"(^|[/\\])hbmame[/\\]", rompath, re.I):
        return "arcade_hbmame", "hbmame", []
    if re.search(r"(^|[/\\])mame[/\\]", rompath, re.I):
        return ARCADE
    folder = re.match(r"collections[/\\]([^/\\]+)", rompath or "", re.I)
    # franchise collections ("Crash Bandicoot Collection") point into a real system folder: the folder decides
    order = (system, emulator, folder.group(1) if folder else "")
    if folder and re.search(r"collection", f"{system} {emulator}", re.I):
        order = (folder.group(1), system, emulator)
    for text in order:
        for rx, plat, core, bios in _compiled:
            if text and rx.search(text):
                if plat == "windows_native" and folder:
                    # a launcher system that also scans a console's rom folder (HyperSpin's "Microsoft XBOX" lists
                    # collections\Sony Playstation 2\roms\USA): those files are that console's discs (Metal Gear
                    # Solid 2 Substance, Enter the Matrix, Path of Neo, GTA Vice City are PS2 CHDs), so the folder
                    # decides when it names a platform gBox has an emulator core for
                    fp = _first(folder.group(1))
                    if fp and fp[0] not in ("windows_native", "unknown") and fp[1]:
                        return fp
                return plat, core, bios
    if re.search(r"\bmame\b", f"{system} {emulator}", re.I):
        return ARCADE
    return "unknown", None, []


def _first(text: str):
    for rx, plat, core, bios in _compiled:
        if text and rx.search(text):
            return plat, core, bios
    return None


def core_for(platform: str) -> tuple[str | None, list[str]]:
    for _, plat, core, bios in RULES:
        if plat == platform:
            return core, bios
    return (ARCADE[1], []) if platform == "arcade" else (None, [])
