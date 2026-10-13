"""`sonic_adventure_2`: Sonic Adventure 2 live: finish the stage now, A rank ("S rank"), all emblems, status (#217).

ops: games | status | finish_level | rank (rank="A", finish=true) | emblems (count=0 = all)
  finish_level  ends the stage the way the game's own "collect 100 rings" mission does: the per-frame check
                `if (MissionNum == 1 && !TwoPlayerMode && level ok && Rings[0] >= 100 && !LevelCleared) AwardWin(0)`
                runs in the game's main loop, so gBox sets MissionNum = 1 (mission 2) and Rings = 100 for the frames it
                takes the game to call AwardWin(0) (LevelCleared turns 1, the timer stops), then puts the real mission
                number and ring count back before the results screen reads them. No code is patched, no function is
                called from outside: the game finishes the stage itself, and its results screen grades and saves the
                mission the player was on (rank, emblem, records).
  rank          SA2 has no S rank: A is the top grade (E D C B A), so "S rank" = A. The results screen grades from
                the per-level rank tables: missions 1/4/5 by (Score + time bonus) / 100 against the score table, missions
                2/3 by the clock (min*60 + sec, +1 with frames) against the time table. gBox finishes the stage (finish=
                true), and once the timer has stopped writes Score = the A threshold x 100 (missions 1/4/5) or the
                clock = A time - 1 s (missions 2/3), so the game's own grading gives A and saves it with the emblem.
  emblems       the game recounts EmblemCount from the save itself (the recount routine below): every mission of 29
                stages + Route 101/280 whose saved rank byte is non-zero (5 missions each = 155), plus 25 one-byte
                flags (kart races, boss attack / chao race extras) = 180. gBox writes the missing ones (rank byte 5 = A,
                flags 1) into the save in RAM, sets EmblemCount to the recount, reads it all back. It reaches the memory
                card / VMU the next time the game saves (finish any stage, or the game's own save prompt).
  status        stage, character, mission, score, time, rings, lives, emblems, LevelCleared, the rank the results
                screen would give right now.

Where the addresses come from (no community RAM map for the Dreamcast build exists; X-Hax sa2-mod-loader
SA2Variables.h covers the 2012 PC port only and its GameCube-derived layout is used as a naming guide):
  Dreamcast USA (1ST_READ.BIN sha1 0817898aac799a8de5e8a9021d817bd7ef33a9e3, loaded at 0x8C010000; the operator's
  disc, gBox game d95ed7ed1e40552a) - SH-4 disassembly:
    * timer tick 0x8C052BDC: global block G = 0x8C0DB20C (+0x1A TimerStopped, +0x1B/+0x1C/+0x1D minutes/seconds/frames
      with 99:59:59 cap); 0x8C052C18 is the store the published CodeBreaker "Stop Timer" 01052C18 0009 turns into a nop.
    * TimerStop 0x8C052BD4 (G+0x1A = 1); GetLives 0x8C052BC0 reads s16 Lives[2] at 0x8C0DB26C (CodeBreaker
      "Unlimited Lives" 010DB26C); Rings s16[2] 0x8C0DB270 ("Max Infinite Rings" 010DB270 03E7); Score s32 0x8C0DB294
      ("Max Score" 020DB294 05F5E0FF; read by the results score function 0x8C054350 at G+0x88).
    * AwardWin(player) 0x8C027E40: stops the timer, sets G+0x43 = 1 (LevelCleared). Called by the main loop's 100-ring
      check at 0x8C0269F2 (MissionNum G+0x22 == 1, TwoPlayerMode G+0x1E == 0, CurrentLevel <= 46 or == 70, Rings >= 100,
      G+0x43 == 0), by Knuckles/Rouge emerald hunts (0x8C0860B2) and goal objects (0x8C047C74).
    * CurrentLevel s16 0x8C24EE64 (CodeBreaker "Level Modifier" 0024EE64; compared with 35..38 Cannon's Core, 70, 90
      Chao World), CurrentCharacter s32 0x8C24EE6C ("Always Tails" 0124EE6C 0006 = MechTails; level loader 0x8C023EC0
      compares it with 6/7), GameState s16 0x8C24EE60 (3 at level load, 16 in game, 17 paused - the PC enum).
    * results grading: score 0x8C054350 (tables Mission1/4/5Scores 0x8C0E5ABC/5BEA/5D18, {s16 level, D, C, B, A} x 100),
      time 0x8C054FB0 (Mission2/3Times 0x8C0E5E46/5F79, {u8 level, 4 x {min, sec}}); both store the rank 0..4 at G+0x42.
    * save (in RAM) 0x8C26A664: EmblemCount u8 +0x0D (EMBLEMGET overlay reads it at 0x8C5003E4; play-time-to-180
      counter 0x8C0BC960); results save 0x8C0BB7E0 writes rank+1 to save+0x6C+level*0x88+mission; the recount routine
      0x8C0BC5A0 counts the 29 stages of the table at 0x8C0FC09C, Route 101/280 at save+0x18DC/+0x1964, flags at
      save+0x1BAC (10), kart save+0x19F8 + 13*i (3), save+0x1E14 (12); 180 unlocks Green Hill (0x8C0BC872).
  GameCube USA (SA2 Battle GSNE8P, main.dol from the operator's disc, gBox game 732106c0ef8df816) - PowerPC:
    * same global block as the PC port: G = 0x801CC168 (timer +0x1B, TwoPlayerMode +0x1E, MissionNum +0x23, rank +0x41,
      LevelCleared +0x42, Lives +0x64, Rings +0x68, PerfectRings +0x6E, Score +0x90): time grading 0x8005FFE8, score
      grading 0x80060F84 (lwz 0x90(G)), 100-ring check 0x8001E57C (level <= 60 or == 70) -> AwardWin 0x8001C810.
    * r13 = 0x803B52C0: GameState s16 0x803AD81A (-0x7AA6, == 16 in game), CurrentLevel s16 0x803AD820 (-0x7AA0),
      CurrentCharacter s32 0x803AD828 (-0x7A98, compared with 6/7).
    * save 0x801F2340 (= 0x801E7820 + 0x10000 - 0x54E0): EmblemCount +0x0D, ranks +0x38 + level*0xC4 + mission (the PC
      SaveData layout), Route 101/280 +0x2E28/+0x2EEC, flags +0x3224 (5), +0x3231 (4), kart +0x2FBC + 13*i (3),
      +0x348D (13); recount routine 0x80057EB4..0x8005A4B4 (180 -> unlock 0x62, Green Hill).
  Rank tables, level ids, character ids and the stage list are identical in both builds.
live_checked is False for both until the maintainer runs the check in docs/sa2_mods.md on the agent test PC.
Europe / Japan builds are refused (not mapped).

Register with:  from . import sa2_mods  # noqa: F401
"""
import re
import struct
import time

from pydantic import BaseModel

from .models import Permission as P
from .registry import tool

# ------------------------------------------------------------------------------------------------------ names
LEVELS = {0: "Basic Test", 1: "Knuckles Test", 2: "Sonic Test", 3: "Green Forest", 4: "White Jungle", 5: "Pumpkin Hill",
          6: "Sky Rail", 7: "Aquatic Mine", 8: "Security Hall", 9: "Prison Lane", 10: "Metal Harbor", 11: "Iron Gate",
          12: "Weapons Bed", 13: "City Escape", 14: "Radical Highway", 15: "Weapons Bed (2P)", 16: "Wild Canyon",
          17: "Mission Street", 18: "Dry Lagoon", 19: "Sonic vs. Shadow 1", 20: "Tails vs. Eggman 1", 21: "Sand Ocean",
          22: "Crazy Gadget", 23: "Hidden Base", 24: "Eternal Engine", 25: "Death Chamber", 26: "Egg Quarters",
          27: "Lost Colony", 28: "Pyramid Cave", 29: "Tails vs. Eggman 2", 30: "Final Rush", 31: "Green Hill",
          32: "Meteor Herd", 33: "Knuckles vs. Rouge", 34: "Cannon's Core (Sonic)", 35: "Cannon's Core (Eggman)",
          36: "Cannon's Core (Tails)", 37: "Cannon's Core (Rouge)", 38: "Cannon's Core (Knuckles)",
          39: "Mission Street (2P)", 40: "Final Chase", 41: "Wild Canyon (2P)", 42: "Sonic vs. Shadow 2", 43: "Cosmic Wall",
          44: "Mad Space", 45: "Sand Ocean (2P)", 46: "Dry Lagoon (2P)", 47: "Pyramid Race", 48: "Hidden Base (2P)",
          49: "Pool Quest", 50: "Planet Quest", 51: "Deck Race", 52: "Downtown Race", 53: "Cosmic Wall (2P)",
          54: "Grind Race", 55: "Lost Colony (2P)", 56: "Eternal Engine (2P)", 57: "Metal Harbor (2P)", 58: "Iron Gate (2P)",
          59: "Death Chamber (2P)", 60: "Big Foot", 61: "Hot Shot", 62: "Flying Dog", 63: "King Boom Boo", 64: "Egg Golem (Sonic)",
          65: "Biolizard", 66: "Finalhazard", 67: "Egg Golem (Eggman)", 70: "Route 101 / Route 280", 71: "Kart Race",
          90: "Chao World"}
BOSSES = {19, 20, 29, 33, 42, 60, 61, 62, 63, 64, 65, 66, 67}
CHARACTERS = {0: "Sonic", 1: "Shadow", 2: "Tails", 3: "Eggman", 4: "Knuckles", 5: "Rouge", 6: "Tails (Cyclone)",
              7: "Eggman (Egg Walker)", 8: "Amy", 9: "Super Sonic", 10: "Super Shadow", 12: "Metal Sonic",
              13: "Chao Walker", 14: "Dark Chao Walker", 15: "Tikal", 16: "Chaos"}
RANKS = "EDCBA"                          # the results screen's rank 0..4; the save keeps rank + 1 (0 = not cleared)
GAME_STATES = {0: "inactive", 1: "loading", 3: "loading level", 7: "load finished", 16: "in game", 17: "paused",
               19: "going to next level"}
IN_GAME, PAUSED = 16, 17
# the 29 action stages the emblem recount walks (DC 0x8C0FC09C, GC 0x801B33E8: identical); Cannon's Core saves under 34
EMBLEM_STAGES = (13, 10, 3, 28, 22, 30, 9, 17, 23, 24, 16, 5, 7, 25, 32, 14, 4, 6, 40, 11, 21, 27, 12, 43, 18, 26, 8, 44, 34)


def norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


# ------------------------------------------------------------------------------------------------------ layouts
def _dc():
    g = 0x8C0DB20C
    save = 0x8C26A664
    return {
        "name": "Sonic Adventure 2 (USA) - Dreamcast", "platform": "dreamcast", "endian": "<",
        "build": "1ST_READ.BIN sha1 0817898aac799a8de5e8a9021d817bd7ef33a9e3 (gBox game d95ed7ed1e40552a)",
        "signature": (0x8C0E5ABC, bytes.fromhex("0d005a006e008c00b400")),     # Mission1Scores[0] = City Escape 90/110/140/180
        "fields": {                                                           # name: (address, struct format)
            "game_state": (0x8C24EE60, "h"), "level": (0x8C24EE64, "h"), "character": (0x8C24EE6C, "i"),
            "timer_stopped": (g + 0x1A, "b"), "minutes": (g + 0x1B, "b"), "seconds": (g + 0x1C, "b"), "frames": (g + 0x1D, "b"),
            "two_player": (g + 0x1E, "b"), "mission": (g + 0x22, "b"), "rank": (g + 0x42, "b"), "cleared": (g + 0x43, "b"),
            "lives": (0x8C0DB26C, "h"), "rings": (0x8C0DB270, "h"), "perfect_rings": (0x8C0DB276, "h"), "score": (0x8C0DB294, "i"),
            "emblem_count": (save + 0x0D, "B"),
        },
        "ring_finish_levels": (46, 70),                 # the 100-ring check runs for CurrentLevel <= 46 or == 70
        "score_tables": {0: 0x8C0E5ABC, 3: 0x8C0E5BEA, 4: 0x8C0E5D18}, "time_tables": {1: 0x8C0E5E46, 2: 0x8C0E5F79},
        "save": save, "level_ranks": (0x6C, 0x88), "routes": (0x18DC, 0x1964),
        "emblem_flags": [(0x1BAC + i, "extra") for i in range(10)] + [(0x19F8 + 13 * i, "kart race") for i in range(3)]
                        + [(0x1E14 + i, "extra") for i in range(12)],
        "code": "codebreaker", "live_checked": False,
        "sources": [
            "SH-4 disassembly of the operator's 1ST_READ.BIN: timer tick 0x8C052BDC (G=0x8C0DB20C +0x1A..+0x1D), TimerStop "
            "0x8C052BD4, AwardWin 0x8C027E40 (G+0x43=1), main-loop 100-ring check 0x8C0269F2 (G+0x22 mission, G+0x1E 2P, "
            "level<=46|70), results grading 0x8C054350/0x8C054FB0 (rank -> G+0x42), results save 0x8C0BB7E0, emblem recount "
            "0x8C0BC5A0 (save 0x8C26A664, EmblemCount +0x0D)",
            "CodeBreaker SA2 (USA) raw codes (almarsguides.com): Unlimited Lives 010DB26C, Max Infinite Rings 010DB270 03E7, "
            "Max Score 020DB294 05F5E0FF, Stop Timer 01052C18 0009 (nop on the seconds store), Level Modifier 0024EE64, "
            "Always Tails 0124EE6C 0006",
            "X-Hax sa2-mod-loader SA2Variables.h/SA2Enums.h (PC port): names of the global block fields, LevelIDs, "
            "Characters, GameStates",
        ],
    }


def _gc():
    g = 0x801CC168
    save = 0x801F2340
    return {
        "name": "Sonic Adventure 2: Battle (USA) - GameCube", "platform": "gamecube", "endian": ">",
        "build": "GSNE8P main.dol (gBox game 732106c0ef8df816)", "disc_id": b"GSNE8P",
        "signature": (0x801B34C8, bytes.fromhex("000d005a006e008c00b4")),
        "fields": {
            "game_state": (0x803AD81A, "h"), "level": (0x803AD820, "h"), "character": (0x803AD828, "i"),
            "timer_stopped": (g + 0x1A, "b"), "minutes": (g + 0x1B, "b"), "seconds": (g + 0x1C, "b"), "frames": (g + 0x1D, "b"),
            "two_player": (g + 0x1E, "b"), "mission": (g + 0x23, "b"), "rank": (g + 0x41, "b"), "cleared": (g + 0x42, "b"),
            "lives": (g + 0x64, "h"), "rings": (g + 0x68, "h"), "perfect_rings": (g + 0x6E, "h"), "score": (g + 0x90, "i"),
            "emblem_count": (save + 0x0D, "B"),
        },
        "ring_finish_levels": (60, 70),
        "score_tables": {0: 0x801B34C8, 3: 0x801B35F8, 4: 0x801B3728}, "time_tables": {1: 0x801B3858, 2: 0x801B398C},
        "save": save, "level_ranks": (0x38, 0xC4), "routes": (0x2E28, 0x2EEC),
        "emblem_flags": [(0x3224 + i, "extra") for i in range(5)] + [(0x3231 + i, "extra") for i in range(4)]
                        + [(0x2FBC + 13 * i, "kart race") for i in range(3)] + [(0x348D + i, "extra") for i in range(13)],
        "code": "gecko", "live_checked": False,
        "sources": [
            "PowerPC disassembly of the operator's GSNE8P main.dol: G=0x801CC168 (PC-port layout) from time grading 0x8005FFE8 "
            "and score grading 0x80060F84 (Score lwz 0x90(G), rank stbu 0x41(G)); 100-ring check 0x8001E57C (mission +0x23, "
            "2P +0x1E, level<=60|70, cleared +0x42) -> AwardWin 0x8001C810; r13=0x803B52C0 (__init_registers 0x80003264): "
            "GameState -0x7AA6, CurrentLevel -0x7AA0, CurrentCharacter -0x7A98",
            "emblem recount 0x80057EB4..0x8005A4B4: save 0x801F2340, EmblemCount +0x0D, level ranks +0x38 + L*0xC4, "
            "stage list 0x801B33E8; 180 -> unlock 0x62 (Green Hill)",
            "X-Hax sa2-mod-loader SA2Variables.h (PC port): same global-block offsets (TimerMinutes +0x1B, MissionNum +0x23, "
            "CurrentLevelRank +0x41, Life_Count +0x64, RingCount +0x68, ScoreP1 +0x90) and SaveData.Levels at +0x38, 0xC4 each",
        ],
    }


LAYOUTS = {"dc_us": _dc(), "gc_us": _gc()}
GAPS = {"dc_eu": "Dreamcast Europe (MK-51117-50) / Japan: not mapped; the code and data addresses differ from the USA "
                 "1ST_READ.BIN. Add a layout after a disassembly + live check.",
        "dc_jp": "Dreamcast Japan: not mapped (see dc_eu).",
        "gc_eu": "SA2 Battle Europe (GSNP8P) / Japan (GSNJ8P): not mapped; main.dol differs from GSNE8P.",
        "gc_jp": "SA2 Battle Japan: not mapped (see gc_eu)."}


def detect(title: str, platform: str) -> tuple[str | None, str]:
    """(layout key, note). None when this is not Sonic Adventure 2; dc_eu/gc_jp... name an unmapped build."""
    t = norm(title)
    if "sonic adventure 2" not in t and "sa2" not in t.split():
        return None, f"'{title}' is not Sonic Adventure 2"
    plat = {"dreamcast": "dc", "naomi": "dc", "gamecube": "gc", "wii": "gc"}.get(platform or "")
    if plat is None and not platform:
        plat = "gc" if "battle" in t else "dc"
    if plat is None:
        return None, f"Sonic Adventure 2 on {platform}: only the Dreamcast and GameCube (Battle) builds are mapped"
    if re.search(r"\b(europe|eur|pal|e)\b", t):
        return f"{plat}_eu", GAPS[f"{plat}_eu"]
    if re.search(r"\b(japan|jpn|jp|j)\b", t):
        return f"{plat}_jp", GAPS[f"{plat}_jp"]
    if re.search(r"\b(usa|us|u|ntsc u|world)\b", t):
        return f"{plat}_us", ""
    return f"{plat}_us", "no region tag in the title: assuming the USA build (the only mapped one); the signature check confirms it"


# ------------------------------------------------------------------------------------------------------ memory
class Mem:
    """Typed reads/writes on the session adapter with a few retries (Dolphin's GDB stub refuses an access that lands
    while the CPU is in an exception handler; a moment later it works). Flycast/RetroArch and Dolphin both hand back
    the console's own bytes, so the layout's endianness applies as is."""

    def __init__(self, ad, lay: dict):
        self.ad, self.lay, self.e = ad, lay, lay["endian"]

    def _retry(self, fn, *a):
        last = None
        for i in range(5):
            try:
                return fn(*a)
            except Exception as e:                          # noqa: BLE001 - stub hiccup, retried
                last = e
                time.sleep(0.03 * (i + 1))
        raise last

    def rd(self, a: int, n: int) -> bytes:
        return bytes(self._retry(self.ad.read_memory, a, n))

    def wr(self, a: int, data: bytes):
        self._retry(self.ad.write_memory, a, bytes(data))

    def get(self, name: str) -> int:
        a, f = self.lay["fields"][name]
        return struct.unpack(self.e + f, self.rd(a, struct.calcsize(f)))[0]

    def put(self, name: str, v: int):
        a, f = self.lay["fields"][name]
        self.wr(a, struct.pack(self.e + f, v))


def check_signature(m: Mem) -> str | None:
    """None when the build matches the layout, else why not."""
    lay = m.lay
    if lay.get("disc_id"):
        try:
            gid = m.rd(0x80000000, 6)
        except Exception as e:                              # noqa: BLE001
            return (f"no game memory access ({type(e).__name__}: {e}); SA2 Battle needs the Spark's Dolphin session "
                    "(RetroArch's Dolphin core exposes no memory to gBox)")
        if gid != lay["disc_id"]:
            return f"this disc is {gid!r}, not {lay['disc_id']!r} (only the USA SA2 Battle is mapped)"
    a, sig = lay["signature"]
    got = m.rd(a, len(sig))
    if got != sig:
        return f"build check failed: {a:#x} holds {got.hex()} instead of {sig.hex()} (City Escape's rank table) - another revision?"
    return None


# ------------------------------------------------------------------------------------------------------ rank tables
def _rank_entry(m: Mem, mission: int, level: int) -> dict | None:
    """The rank thresholds the results screen uses for this level + mission (0-based), read from game memory:
    {"kind": "score", "D".."A": points} or {"kind": "time", "D".."A": seconds}; None when the stage has no table."""
    lay, e = m.lay, m.e
    if mission in lay["score_tables"]:
        a = lay["score_tables"][mission]
        for i in range(40):
            lv, d, c, b, aa = struct.unpack(e + "5h", m.rd(a + 10 * i, 10))
            if lv == 91 or lv < 0:
                return None
            if lv == level:
                return {"kind": "score", "table": f"{a:#x}", "D": d * 100, "C": c * 100, "B": b * 100, "A": aa * 100}
        return None
    if mission in lay["time_tables"]:
        a = lay["time_tables"][mission]
        for i in range(40):
            raw = m.rd(a + 9 * i, 9)
            if raw[0] == 91:
                return None
            if raw[0] == level:
                t = [raw[1 + 2 * k] * 60 + raw[2 + 2 * k] for k in range(4)]
                return {"kind": "time", "table": f"{a:#x}", "D": t[0], "C": t[1], "B": t[2], "A": t[3]}
        return None
    return None


def rank_entry_for(m: Mem, st: dict) -> dict | None:
    entry = _rank_entry(m, st["mission"], st["level"])
    if not entry and 35 <= st["level"] <= 38:                 # Cannon's Core parts share the Sonic part's score row
        entry = _rank_entry(m, st["mission"], 34)
    return entry


def time_bonus(seconds: int) -> int:
    """The results screen's time bonus (DC 0x8C054364 / GC 0x80060FB8): 10000 - 20 * (seconds - 60), floor 0."""
    b = 10000 - 20 * (max(seconds, 60) - 60)
    return b if b > 0 else 0


def grade(st: dict, entry: dict | None) -> str | None:
    """The rank letter the results screen would give for the current values (None: no table for this stage)."""
    if not entry:
        return None
    r = 0
    if entry["kind"] == "score":
        if st["rings"] >= st["perfect_rings"]:
            return "A"                                       # perfect: the score function returns rank 4 directly
        total = (st["score"] + time_bonus(st["minutes"] * 60 + st["seconds"])) // 100 * 100
        for k in "DCBA":
            if total < entry[k]:
                break
            r += 1
    else:
        t = st["minutes"] * 60 + st["seconds"] + (1 if st["frames"] > 0 else 0)
        for k in "DCBA":
            if t > entry[k]:
                break
            r += 1
    return RANKS[r]


# ------------------------------------------------------------------------------------------------------ emblems
def emblem_slots(lay: dict) -> list[dict]:
    """The 180 bytes the game's emblem recount reads, in its order: {address, kind ('rank'|'flag'), label}."""
    s, (off, stride), out = lay["save"], lay["level_ranks"], []
    for lv in EMBLEM_STAGES:
        for mi in range(5):
            out.append({"address": s + off + lv * stride + mi, "kind": "rank", "label": f"{LEVELS[lv]} mission {mi + 1}"})
    for name, roff in zip(("Route 101", "Route 280"), lay["routes"]):
        for mi in range(5):
            out.append({"address": s + roff + mi, "kind": "rank", "label": f"{name} mission {mi + 1}"})
    for o, what in lay["emblem_flags"]:
        out.append({"address": s + o, "kind": "flag", "label": f"{what} emblem (save+{o:#x})"})
    return out


def read_emblems(m: Mem) -> dict:
    slots = emblem_slots(m.lay)
    have = [sl for sl in slots if m.rd(sl["address"], 1)[0]]
    return {"count": m.get("emblem_count"), "earned": len(have), "total": len(slots),
            "missing": [sl["label"] for sl in slots if sl not in have][:12]}


def codes_for(lay: dict, writes: list[tuple[int, int, int]]) -> list[str]:
    """(address, size, value) -> CodeBreaker (Dreamcast, '0TAAAAAA VVVVVVVV', T 0/1/2 = 8/16/32-bit) or Gecko
    (GameCube, 00/02/04) lines: what cheats op=add would take for the same constant writes."""
    out = []
    for a, n, v in writes:
        if lay["code"] == "codebreaker":
            out.append(f"0{ {1: 0, 2: 1, 4: 2}[n]}{a & 0xFFFFFF:06X} {v & 0xFFFFFFFF:08X}")
        else:
            out.append(f"{ {1: 0, 2: 2, 4: 4}[n] | ((a >> 24) & 1):02X}{a & 0xFFFFFF:06X} {v & 0xFFFFFFFF:08X}")
    return out


def give_emblems(m: Mem, count: int = 0) -> dict:
    """Mark missing emblems earned (count=0: all 180) in the save in RAM, then set EmblemCount to the recount."""
    slots = emblem_slots(m.lay)
    want = len(slots) if not count or count <= 0 else int(count)
    written, codes = [], []
    for sl in slots:
        if len(written) >= want:
            break
        if m.rd(sl["address"], 1)[0]:
            continue
        v = 5 if sl["kind"] == "rank" else 1                  # rank byte 5 = A (results store rank + 1)
        m.wr(sl["address"], bytes([v]))
        written.append(sl)
        codes.append((sl["address"], 1, v))
    earned = sum(1 for sl in slots if m.rd(sl["address"], 1)[0])
    m.put("emblem_count", min(earned, 255))
    back = m.get("emblem_count")
    ok = all(m.rd(sl["address"], 1)[0] for sl in written) and back == earned
    return {"added": len(written), "added_labels": [sl["label"] for sl in written][:10], "emblems": back,
            "total": len(slots), "verified": ok, "codes": codes_for(m.lay, codes + [(m.lay["fields"]["emblem_count"][0], 1, back)])
            if len(codes) <= 12 else f"{len(codes) + 1} byte writes (too many to list; op=emblems does them)"}


# ------------------------------------------------------------------------------------------------------ live ops
def read_state(m: Mem) -> dict:
    st = {k: m.get(k) for k in ("game_state", "level", "character", "timer_stopped", "minutes", "seconds", "frames",
                                "two_player", "mission", "rank", "cleared", "lives", "rings", "perfect_rings", "score",
                                "emblem_count")}
    st["level_name"] = LEVELS.get(st["level"], f"level {st['level']}")
    st["character_name"] = CHARACTERS.get(st["character"], f"character {st['character']}")
    st["state_name"] = GAME_STATES.get(st["game_state"], f"state {st['game_state']}")
    st["mission_number"] = st["mission"] + 1
    st["time"] = f"{st['minutes']}:{st['seconds']:02d}.{st['frames']:02d}"
    return st


def _finishable(lay: dict, st: dict) -> str | None:
    hi, extra = lay["ring_finish_levels"]
    lv = st["level"]
    if st["game_state"] not in (IN_GAME, PAUSED):
        return f"not in a stage (game state {st['state_name']}); start a stage first"
    if st["two_player"]:
        return "2-player battle: the game only finishes 1-player stages this way"
    if not (0 <= lv <= hi or lv == extra):
        return (f"{st['level_name']} (level {lv}) is outside the stages whose 100-ring check runs (level <= {hi} or "
                f"{extra}): boss fights 60+, kart races and Chao World are not covered")
    return None


def finish_level(m: Mem, timeout_s: float = 3.0, poll_s: float = 0.02) -> dict:
    """Make the game call its own AwardWin(0) via the mission-2 (100 rings) check, then restore mission + rings."""
    st = read_state(m)
    why = _finishable(m.lay, st)
    if why:
        return {"finished": False, "error": why, "state": st}
    if st["cleared"]:
        return {"finished": True, "verified": True, "already": True, "note": "the stage is already cleared (results pending)"}
    mission, rings = st["mission"], st["rings"]
    m.put("mission", 1)
    m.put("rings", max(rings, 100))
    deadline, fired = time.monotonic() + max(0.1, timeout_s), False
    try:
        while time.monotonic() < deadline:
            if m.get("cleared"):
                fired = True
                break
            time.sleep(poll_s)
    finally:
        m.put("mission", mission)                       # the results screen grades and saves the real mission
        m.put("rings", rings)
    back = read_state(m)
    res = {"finished": fired, "verified": fired and back["cleared"] == 1 and back["mission"] == mission and back["rings"] == rings,
           "level": st["level_name"], "mission": mission + 1, "character": st["character_name"],
           "restored": {"mission": back["mission"] + 1, "rings": back["rings"]}, "timer_stopped": back["timer_stopped"],
           "codes_note": "no constant cheat code does this: a CodeBreaker/Gecko 'mission 2 + 100 rings' code would end "
                         "every stage as mission 2"}
    if st["level"] in BOSSES:
        res["note"] = "boss stage: AwardWin is the same call the goal ring uses; untested on bosses"
    if not fired:
        res["error"] = ("the game did not end the stage within "
                        f"{timeout_s:g}s ({'paused: unpause and ask again' if st['game_state'] == PAUSED else 'is the stage running?'}); "
                        "mission and rings were put back")
    return res


def set_rank(m: Mem, letter: str = "A", finish: bool = True, timeout_s: float = 3.0) -> dict:
    want = (letter or "A").strip().upper()[:1]
    note = []
    if want == "S":
        want = "A"
        note.append("Sonic Adventure 2 has no S rank: A is the top grade (E D C B A)")
    if want not in "DCBA" or not want:
        return {"error": f"rank must be A, B, C or D (got {letter!r})"}
    st = read_state(m)
    entry = rank_entry_for(m, st)
    if not entry:
        return {"error": f"{st['level_name']} mission {st['mission'] + 1} has no rank table (bosses, races, Route 101/280 "
                         "and Chao World are not graded this way)", "state": st}
    res = {"rank": want, "level": st["level_name"], "mission": st["mission"] + 1, "thresholds": entry}
    if finish:
        fin = finish_level(m, timeout_s)
        res["finish"] = fin
        if not fin.get("finished"):
            res["error"] = fin.get("error", "the stage did not finish")
            return res
    writes = []
    if entry["kind"] == "score":
        target = entry[want]
        if m.get("score") < target:
            m.put("score", target)
        writes.append((m.lay["fields"]["score"][0], 4, max(target, m.get("score"))))
    else:
        secs = entry[want] - 1 if finish else max(0, entry[want] // 2)
        secs = max(0, secs)
        cur = m.get("minutes") * 60 + m.get("seconds") + (1 if m.get("frames") > 0 else 0)
        if cur > secs:
            m.put("minutes", secs // 60)
            m.put("seconds", secs % 60)
            m.put("frames", 0)
        for k in ("minutes", "seconds", "frames"):
            writes.append((m.lay["fields"][k][0], 1, m.get(k)))
    back = read_state(m)
    got = grade(back, entry)
    res.update(score=back["score"], time=back["time"], grade_now=got, verified=(RANKS.index(got or "E") >= RANKS.index(want)),
               codes=codes_for(m.lay, writes))
    if not finish:
        note.append("finish=false: the clock keeps running until the goal; a time mission keeps the grade only if the "
                    "stage ends within the headroom")
    if note:
        res["note"] = "; ".join(note)
    return res


# ------------------------------------------------------------------------------------------------------ engine
OPS = ("games", "status", "finish_level", "rank", "emblems")
OP_ALIASES = {"state": "status", "read": "status", "info": "status", "finish": "finish_level", "skip": "finish_level",
              "skip_level": "finish_level", "end_level": "finish_level", "complete": "finish_level", "clear": "finish_level",
              "s_rank": "rank", "a_rank": "rank", "grade": "rank", "emblem": "emblems", "all_emblems": "emblems"}


def run(ad, title: str, platform: str, op: str = "status", rank: str = "A", count: int = 0, finish: bool = True,
        timeout_s: float = 3.0) -> dict:
    """Engine entry (tests drive it through a fake adapter)."""
    op = norm(op).replace(" ", "_") or "status"
    op = OP_ALIASES.get(op, op)
    key, note = detect(title, platform)
    if op == "games":
        return {"games": {k: {"name": v["name"], "build": v["build"], "live_checked": v["live_checked"], "sources": v["sources"]}
                          for k, v in LAYOUTS.items()}, "gaps": GAPS, "ops": OPS, "detected": key, "note": note}
    if key is None:
        return {"error": note, "games": [v["name"] for v in LAYOUTS.values()]}
    if key not in LAYOUTS:
        return {"error": f"{title}: {note}", "games": [v["name"] for v in LAYOUTS.values()]}
    if op not in OPS:
        return {"error": f"unknown op '{op}' (" + " | ".join(OPS) + ")"}
    lay = LAYOUTS[key]
    m = Mem(ad, lay)
    bad = check_signature(m)
    if bad:
        return {"error": f"{lay['name']}: {bad}", "layout": key}
    res = {"game": lay["name"], "layout": key, "op": op, "live_checked": lay["live_checked"]}
    if note:
        res["note"] = note
    if op == "status":
        st = read_state(m)
        entry = rank_entry_for(m, st)
        res.update(state=st, emblems=read_emblems(m), rank_table=entry, grade_now=grade(st, entry),
                   finishable=_finishable(lay, st) or "yes")
        return res
    if op == "finish_level":
        res.update(finish_level(m, timeout_s))
        return res
    if op == "rank":
        res.update(set_rank(m, rank, finish, timeout_s))
        return res
    res.update(give_emblems(m, count))
    res["note"] = ((res.get("note", "") + " ") if res.get("note") else "") + (
        "saved in RAM; it reaches the memory card / VMU the next time the game saves (finish any stage). The game "
        "recounts emblems from these bytes itself; 180 unlocks Green Hill.")
    return res


# ------------------------------------------------------------------------------------------------------ gBox tool
class SA2In(BaseModel):
    session_id: str
    op: str = "status"         # games | status | finish_level | rank | emblems
    rank: str = "A"            # rank: A (S = A: SA2's top grade), B, C, D
    count: int = 0             # emblems: how many to add (0 = all 180)
    finish: bool = True        # rank: also finish the stage (the grade is set after the timer stops)
    timeout_s: float = 3.0     # finish_level: how long to wait for the game to end the stage


class SA2Out(BaseModel):
    result: dict


@tool("sonic_adventure_2", "1.0", SA2In, SA2Out, capabilities=["runtime", "memory"], permissions=[P.MEMORY_WRITE],
      side_effects=["ends the current stage / writes score, clock and emblem bytes in live emulated memory"], timeout_s=60)
def sonic_adventure_2(inp: SA2In, ctx):
    """Sonic Adventure 2 (Dreamcast USA) / SA2 Battle (GameCube USA) on the live session, verified by read-back:
    op=finish_level ends the current stage now (the game's own AwardWin via the 100-ring mission check; the real
    mission is graded and saved); op=rank rank=A finishes the stage with an A ('S rank' = A, SA2's top grade);
    op=emblems (count=0 = all 180) marks missing emblems earned in the save; op=status reads stage, character,
    mission, score, time, rings, emblems and the grade the results screen would give."""
    from .tools import SESSIONS
    ad, g = SESSIONS[inp.session_id]
    return {"result": run(ad, g.get("title", ""), g.get("platform", ""), inp.op, inp.rank, inp.count, inp.finish, inp.timeout_s)}
