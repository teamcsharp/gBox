"""Ghost runs (#1098): every run the operator plays is recorded from the game's RAM and raced against later as
translucent ghosts drawn over the live game.

    worker   start(sid, ad, game, server, headers, alive) at launch: a thread reads the game's RAM once per frame
             (one READ_CORE_RAM round trip on RetroArch = one emulated frame), decodes the player's state with the
             game's profile, cuts it into runs / level attempts / splits (Recorder) and posts
               POST /api/ghosts/live/{sid}   the live player (level, level frame, run frame, camera) ~15x a second
               POST /api/ghosts/runs         each finished run (per-frame track, splits, outcome)
             stop(sid) at session end finishes the run in progress ("session_end").
    server   register(app, auth, store): runs per game (docs "ghost_run" = metadata, "ghost_track" = packed track),
             best-run flags, per-level best segments, rename / delete, the operator's ghost picks (docs "ghost_prefs").
    client   clients/web/viz/ghost-runs.js: the Runs panel in the session view and the overlay canvas over the game
             picture (projection: world position minus the live camera, see ghost_screen()).
    tool     ghost_runs (ops: profiles | status | list | show | rename | delete | pick) for the chat agent / Hermes / MCP.

Games are profiles: the RAM layout, a decoder to one sample per frame and the native picture size. Super Mario Bros.
(NES) is the first one; its addresses are the labels of the doppelganger SMB1 disassembly (SMBDIS, mirrored at
github.com/abnuo/smbdis-dasm, the same source gbox/smb1_inventory.py verified its PRG tables against), checked live in
an isolated Mesen instance (docs/ghost-runs.md, "Verification"). A 2D game needs no camera matrix: the screen position
is the world position minus the scroll position the game keeps in RAM (ScreenLeft_PageLoc/X_Pos), the same value the
game subtracts itself to get Player_Rel_XPos. Injecting a ghost actor into the game is not possible for SMB1 without a
ROM patch (every object slot and all 64 OAM entries are rewritten each frame), so the overlay is the ghost.
Docs: docs/ghost-runs.md.
"""
from __future__ import annotations

import base64
import re
import struct
import threading
import time
import uuid
import zlib
from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel

# ---------------------------------------------------------------------------------------------------------------- SMB1
NES_FPS = 60.0988                         # NTSC NES frame rate (Mesen reports 60.0998)

# RAM labels from the SMB1 disassembly (SMBDIS). CPU addresses = offsets into the 2 KiB internal RAM.
SMB1 = {
    "FrameCounter": 0x0009,               # +1 per game frame (wraps at 256)
    "GameEngineSubroutine": 0x000E,       # player routine: 4 flagpole, 5 end level, 6 lose life, 8 control, 0x0B death
    "Player_State": 0x001D,               # 0 ground, 1 jumping, 2 falling, 3 climbing
    "PlayerFacingDir": 0x0033,            # 1 right, 2 left
    "Player_X_Speed": 0x0057,
    "Player_PageLoc": 0x006D,             # world x = page * 256 + x
    "Player_X_Position": 0x0086,
    "Player_Y_HighPos": 0x00B5,           # 1 = on screen, 0 above, >= 2 below (fell into a pit)
    "Player_Y_Position": 0x00CE,          # top of the 16x32 player box on screen
    "Player_Rel_XPos": 0x03AD,            # screen x the game drew this frame (check: world x - ScreenLeft)
    "Player_Rel_YPos": 0x03B8,
    "Player_SprAttrib": 0x03C4,
    "PlayerGfxOffset": 0x06D5,            # row offset into PlayerGraphicsTable = the animation frame
    "SavedJoypad1Bits": 0x06FC,           # A 0x80 B 0x40 Select 0x20 Start 0x10 Up 8 Down 4 Left 2 Right 1
    "ScreenLeft_PageLoc": 0x071A,         # camera: left edge of the screen in world coordinates
    "ScreenLeft_X_Pos": 0x071C,
    "AreaPointer": 0x0750,                # which map is loaded (main area, bonus room, ...)
    "CurrentPlayer": 0x0753,              # 0 Mario, 1 Luigi
    "PlayerSize": 0x0754,                 # 0 big, 1 small
    "PlayerStatus": 0x0756,               # 0 small, 1 big, 2 fiery
    "NumberofLives": 0x075A,
    "LevelNumber": 0x075C,                # 0-3 within the world
    "WorldNumber": 0x075F,                # 0-7
    "AreaNumber": 0x0760,
    "OperMode": 0x0770,                   # 0 title / demo, 1 game, 2 victory (any castle's axe), 3 game over
    "OperMode_Task": 0x0772,              # game mode: 0 init area, 1 screen routines, 2 setup, 3 game core (playing)
    "GamePauseStatus": 0x0776,
    "GameTimerDisplay": 0x07F8,           # 3 digits, hundreds first
}
SUB_FLAGPOLE, SUB_END_LEVEL, SUB_LOSE_LIFE, SUB_CONTROL, SUB_DEATH = 0x04, 0x05, 0x06, 0x08, 0x0B
DEATH_SUBS = (SUB_LOSE_LIFE, SUB_DEATH)
TELEPORT_PX = 48                          # more than a frame's worth of movement (max ~3 px/frame): a rewind / state load


def decode_smb1(m: bytes) -> dict:
    """One frame of Super Mario Bros. from its 2 KiB RAM."""
    a = SMB1
    t = m[a["GameTimerDisplay"]:a["GameTimerDisplay"] + 3]
    return {
        "fc": m[a["FrameCounter"]], "sub": m[a["GameEngineSubroutine"]], "st": m[a["Player_State"]],
        "face": m[a["PlayerFacingDir"]], "vx": m[a["Player_X_Speed"]],
        "x": m[a["Player_PageLoc"]] * 256 + m[a["Player_X_Position"]],
        "y": m[a["Player_Y_HighPos"]] * 256 + m[a["Player_Y_Position"]],
        "relx": m[a["Player_Rel_XPos"]], "rely": m[a["Player_Rel_YPos"]], "attr": m[a["Player_SprAttrib"]],
        "anim": m[a["PlayerGfxOffset"]], "joy": m[a["SavedJoypad1Bits"]],
        "scr": m[a["ScreenLeft_PageLoc"]] * 256 + m[a["ScreenLeft_X_Pos"]],
        "ap": m[a["AreaPointer"]], "player": m[a["CurrentPlayer"]], "small": m[a["PlayerSize"]] & 1,
        "pw": m[a["PlayerStatus"]], "lives": m[a["NumberofLives"]], "level": m[a["LevelNumber"]],
        "world": m[a["WorldNumber"]], "area": m[a["AreaNumber"]], "oper": m[a["OperMode"]],
        "task": m[a["OperMode_Task"]], "pause": m[a["GamePauseStatus"]],
        "timer": (t[0] % 10) * 100 + (t[1] % 10) * 10 + (t[2] % 10),
    }


@dataclass(frozen=True)
class Profile:
    """A game the recorder understands."""
    key: str
    title: str
    platform: str
    game_ids: frozenset
    title_re: str                         # other dumps of the same game (matched on the catalog title, same platform)
    ram: tuple[int, int]                  # (base, size) read once per frame
    decode: Callable[[bytes], dict]
    screen: tuple[int, int]               # native picture (the overlay maps game pixels onto it)
    fps: float
    box: dict = field(default_factory=dict)   # player box on screen: {"w", "h", "small_h"} (y = top of the box)
    final_world: int = 7                  # SMB1: the axe of world 8 (index 7) ends the game
    source: str = ""

    def public(self) -> dict:
        return {"key": self.key, "title": self.title, "platform": self.platform, "screen": list(self.screen),
                "fps": self.fps, "box": self.box, "sync": ["level", "run"], "overlay": "projection",
                "injection": "unsupported: every SMB1 object slot and OAM entry is rewritten each frame (needs a ROM patch)",
                "source": self.source}


PROFILES = {
    "smb1": Profile(key="smb1", title="Super Mario Bros.", platform="nes",
                    game_ids=frozenset({"49b6a2f65aca26a2"}),
                    title_re=r"^super mario bros\.?(\s*\((world|usa|japan|europe|ju|e|u)[^)]*\))?$",
                    ram=(0x0000, 0x0800), decode=decode_smb1, screen=(256, 240), fps=NES_FPS,
                    box={"w": 16, "h": 32, "small_h": 16},
                    source="SMBDIS (doppelganger) RAM labels; live check in Mesen (docs/ghost-runs.md)"),
}


def profile_for(game: dict | None) -> Profile | None:
    """The profile of a catalog entry / session game dict (game_id first, else platform + title)."""
    if not game:
        return None
    gid = game.get("game_id") or ""
    for p in PROFILES.values():
        if gid in p.game_ids:
            return p
    title, plat = (game.get("title") or "").strip().lower(), (game.get("platform") or "").lower()
    for p in PROFILES.values():
        if plat == p.platform and re.match(p.title_re, title):
            return p
    return None


def level_name(world: int, level: int) -> str:
    return f"{world + 1}-{level + 1}"


# --------------------------------------------------------------------------------------------------------- the track
# One row per recorded game frame. pw packs PlayerStatus (bits 0-1) and "small" (bit 2).
TRACK_FIELDS = ("f", "x", "y", "lv", "ap", "face", "st", "anim", "pw", "joy", "scr", "sub")
TRACK_FMT = "<IHHBBBBBBBHB"
TRACK_ROW = struct.calcsize(TRACK_FMT)
TRACK_VERSION = "smb1.v1"


def row_of(frame: int, s: dict) -> tuple:
    return (frame & 0xFFFFFFFF, s["x"] & 0xFFFF, s["y"] & 0xFFFF, (s["world"] * 4 + s["level"]) & 0xFF, s["ap"] & 0xFF,
            s["face"] & 0xFF, s["st"] & 0xFF, s["anim"] & 0xFF, (s["pw"] & 3) | ((s["small"] & 1) << 2), s["joy"] & 0xFF,
            s["scr"] & 0xFFFF, s["sub"] & 0xFF)


def pack_track(rows: list[tuple]) -> str:
    raw = b"".join(struct.pack(TRACK_FMT, *r) for r in rows)
    return base64.b64encode(zlib.compress(raw, 6)).decode()


def unpack_track(b64: str) -> list[tuple]:
    raw = zlib.decompress(base64.b64decode(b64))
    return [struct.unpack_from(TRACK_FMT, raw, o) for o in range(0, len(raw) - TRACK_ROW + 1, TRACK_ROW)]


def track_columns(rows: list[tuple]) -> dict:
    """Columnar JSON for the overlay: {"f": [...], "x": [...], ...} plus decoded level names."""
    cols = {k: [r[i] for r in rows] for i, k in enumerate(TRACK_FIELDS)}
    return cols


# ------------------------------------------------------------------------------------------------------ the recorder
class Recorder:
    """Cuts a stream of decoded frames into runs.

    run      starts the first time gameplay is seen (OperMode 1 with the game core task running), normally on 1-1 after
             Start; ends complete (the final world's axe), game_over, reset (back to the title), state_loaded (the level
             changed while the player was in control: a save state), or session_end.
    attempt  one try at a level: from its gameplay start to clear (flagpole, axe, or a warp to another level) or death.
    split    per level: first attempt's start to the clearing attempt's end (includes deaths), as a speedrun split.
    frames   game frames, from FrameCounter deltas (a frame missed by the poller still counts; a paused game does not).
    rewind   the level timer going back up while the player is in control (RetroArch rewind, gBox's checkpoint ring or
             a state of the same level) drops the frames that were undone; the run is marked assisted.
    """

    MIN_ROWS = 30                          # runs with less gameplay than this are not kept

    def __init__(self, profile: Profile, game_id: str = "", session_id: str = "", clock=time.time):
        self.p, self.game_id, self.session_id, self.clock = profile, game_id, session_id, clock
        self.prev: dict | None = None
        self.run: dict | None = None
        self.last: dict | None = None      # the latest sample (live view)
        self.finished: list[dict] = []

    # -- helpers
    @staticmethod
    def _in_play(s: dict) -> bool:
        return s["oper"] == 1 and s["task"] == 3

    def _level(self, s: dict) -> str:
        return level_name(s["world"], s["level"])

    def _start_run(self, s: dict, joined: bool):
        lvl = self._level(s)
        self.run = {"run_id": uuid.uuid4().hex[:16], "game_id": self.game_id, "session_id": self.session_id,
                    "profile": self.p.key, "started_at": self.clock(), "start_level": lvl, "frame": 0, "rows": [],
                    "timers": [], "attempts": [], "cur": None, "deaths": 0, "rewinds": 0, "joined": joined,
                    "assisted": joined, "player": "Luigi" if s.get("player") else "Mario"}
        self._open_attempt(s)

    def _open_attempt(self, s: dict):
        r = self.run
        r["cur"] = {"level": self._level(s), "start": r["frame"], "end": None, "result": None, "row0": len(r["rows"])}

    def _close_attempt(self, result: str):
        r = self.run
        cur = r["cur"]
        if cur is None:
            return
        cur["end"], cur["result"] = r["frame"], result
        r["attempts"].append({k: cur[k] for k in ("level", "start", "end", "result")})
        r["cur"] = None

    def _rewind(self, s: dict):
        """The timer went back up: drop the undone frames of this attempt (rows with a lower timer)."""
        r, cur = self.run, self.run["cur"]
        keep = len(r["rows"])
        while keep > cur["row0"] and r["timers"][keep - 1] < s["timer"]:
            keep -= 1
        del r["rows"][keep:], r["timers"][keep:]
        r["frame"] = (r["rows"][-1][0] + 1) if keep > cur["row0"] else cur["start"]
        r["rewinds"] += 1
        r["assisted"] = True

    def _finish(self, outcome: str) -> dict | None:
        r = self.run
        if r is None:
            return None
        if r["cur"] is not None:
            self._close_attempt("death" if outcome == "game_over" else "end")
        self.run = None
        if len(r["rows"]) < self.MIN_ROWS:
            return None
        out = summarize(r, outcome, self.clock(), self.p)
        self.finished.append(out)
        return out

    # -- the stream
    def feed(self, s: dict) -> list[dict]:
        """One decoded frame. Returns the runs that finished on it (usually none)."""
        p, self.prev, self.last = self.prev, s, s
        done: list[dict] = []
        if p is None:
            if self._in_play(s):
                self._start_run(s, joined=True)          # recording began mid-level (gBox restarted, a loaded moment)
                self._record(s)
            return done
        d = (s["fc"] - p["fc"]) & 0xFF
        if d == 0:
            return done                                  # same frame read twice, or the game is paused
        r = self.run
        if r is None:
            if self._in_play(s):
                self._start_run(s, joined=self._in_play(p))
                self._record(s)
            return done
        r["frame"] += d
        cur = r["cur"]
        if s["oper"] == 0:
            return self._end(done, "reset")
        if s["oper"] == 3:
            return self._end(done, "game_over")
        if s["oper"] == 2:                               # a castle's axe: the level is cleared
            if cur is not None:
                self._close_attempt("clear")
            if s["world"] >= self.p.final_world:
                return self._end(done, "complete")
            return done
        both_control = self._in_play(p) and self._in_play(s) and p["sub"] == SUB_CONTROL and s["sub"] == SUB_CONTROL
        if cur is not None:
            if self._level(s) != cur["level"]:
                if both_control:                         # a save state of another level: this run is over
                    self._end(done, "state_loaded")
                    self._start_run(s, joined=True)
                    self._record(s)
                    return done
                self._close_attempt("clear")             # warp pipe / end of level
            elif s["sub"] in DEATH_SUBS and p["sub"] not in DEATH_SUBS:
                self._close_attempt("death")
                r["deaths"] += 1
            elif s["sub"] == SUB_FLAGPOLE and p["sub"] != SUB_FLAGPOLE:
                self._close_attempt("clear")
            elif both_control and s["ap"] == p["ap"] and (
                    s["timer"] > p["timer"] or abs(s["x"] - p["x"]) > max(TELEPORT_PX, 4 * d)):
                self._rewind(s)
        if r["cur"] is None and self._in_play(s) and not self._in_play(p):
            self._open_attempt(s)                        # gameplay starts: after the level / lives screen
        if self._in_play(s):
            self._record(s)
        return done

    def _end(self, done: list, outcome: str) -> list[dict]:
        out = self._finish(outcome)
        if out:
            done.append(out)
        return done

    def _record(self, s: dict):
        r = self.run
        if r["cur"] is None or s["sub"] == 0:
            return                                       # after the flag (walking to the castle), or the area's setup frame
        r["rows"].append(row_of(r["frame"], s))
        r["timers"].append(s["timer"])

    def finish(self, outcome: str = "session_end") -> dict | None:
        return self._finish(outcome)

    def live(self) -> dict:
        """What the overlay needs to place ghosts and the race timer, for the latest frame."""
        s, r = self.last, self.run
        if s is None:
            return {"on": False}
        out = {"on": True, "profile": self.p.key, "in_play": self._in_play(s), "oper": s["oper"],
               "level": self._level(s), "ap": s["ap"], "x": s["x"], "y": s["y"], "relx": s["relx"], "rely": s["rely"],
               "scr": s["scr"], "small": s["small"], "face": s["face"], "fps": self.p.fps}
        if r is not None:
            cur = r["cur"]
            out |= {"run_id": r["run_id"], "run_frame": r["frame"], "start_level": r["start_level"],
                    "deaths": r["deaths"], "assisted": r["assisted"], "splits": splits_of(r["attempts"]),
                    "level_frame": (r["frame"] - cur["start"]) if cur else None,
                    "attempt_level": cur["level"] if cur else None}
        return out


def splits_of(attempts: list[dict]) -> list[dict]:
    """Per cleared level: {level, start, end, frames (first try to clear, deaths included), segment (clearing attempt),
    deaths}."""
    out, first, deaths = [], {}, {}
    for a in attempts:
        first.setdefault(a["level"], a["start"])
        if a["result"] == "death":
            deaths[a["level"]] = deaths.get(a["level"], 0) + 1
        if a["result"] == "clear":
            out.append({"level": a["level"], "start": first[a["level"]], "end": a["end"],
                        "frames": a["end"] - first[a["level"]], "segment": a["end"] - a["start"],
                        "deaths": deaths.get(a["level"], 0)})
    return out


def summarize(r: dict, outcome: str, now: float, profile: Profile) -> dict:
    rows = r["rows"]
    splits = splits_of(r["attempts"])
    frames = r["frame"] if outcome != "complete" or not splits else splits[-1]["end"]
    last = rows[-1]
    return {"run_id": r["run_id"], "game_id": r["game_id"], "session_id": r["session_id"], "profile": r["profile"],
            "name": "", "started_at": r["started_at"], "ended_at": now, "outcome": outcome,
            "start_level": r["start_level"], "end_level": level_name(last[3] // 4, last[3] % 4),
            "player": r["player"], "frames": frames, "time_s": round(frames / profile.fps, 3), "splits": splits,
            "attempts": r["attempts"], "deaths": r["deaths"], "rewinds": r["rewinds"], "assisted": r["assisted"],
            "samples": len(rows), "track_fmt": TRACK_VERSION, "track": pack_track(rows)}


# ------------------------------------------------------------------------------------------ best runs / ghost choice
def category(run: dict) -> str:
    return f"from {run.get('start_level', '?')}" + (" (assisted)" if run.get("assisted") else "")


def annotate(runs: list[dict]) -> tuple[list[dict], dict]:
    """runs (metadata) newest first with best flags; level_bests = {level: {run_id, frames}} (fastest clearing segment
    of runs without rewinds / state loads).
    best           fastest complete run of its category (start level, assisted or not)
    best_progress  where no run of a category is complete: the run that got furthest, fastest to its last split."""
    runs = sorted(runs, key=lambda r: r.get("started_at") or 0, reverse=True)
    for r in runs:
        r["best"] = r["best_progress"] = False
        r["category"] = category(r)
    by_cat: dict[str, list[dict]] = {}
    for r in runs:
        by_cat.setdefault(r["category"], []).append(r)
    for rs in by_cat.values():
        done = [r for r in rs if r.get("outcome") == "complete"]
        if done:
            min(done, key=lambda r: r["frames"])["best"] = True
            continue
        with_splits = [r for r in rs if r.get("splits")]
        if with_splits:
            min(with_splits, key=lambda r: (-len(r["splits"]), r["splits"][-1]["end"]))["best_progress"] = True
    level_bests: dict[str, dict] = {}
    for r in runs:
        if r.get("assisted"):
            continue
        for sp in r.get("splits") or []:
            b = level_bests.get(sp["level"])
            if b is None or sp["segment"] < b["frames"]:
                level_bests[sp["level"]] = {"run_id": r["run_id"], "frames": sp["segment"]}
    return runs, level_bests


def ghost_frame(run: dict, live: dict, mode: str = "level") -> int | None:
    """The ghost run's frame that races the live frame. level: the same time into the same level (the ghost's
    clearing attempt, else its longest try there); run: the same time since the run started."""
    if mode == "run":
        return live.get("run_frame")
    lf, lvl = live.get("level_frame"), live.get("attempt_level") or live.get("level")
    if lf is None:
        return None
    tries = [a for a in run.get("attempts") or [] if a["level"] == lvl]
    if not tries:
        return None
    a = next((a for a in reversed(tries) if a["result"] == "clear"), None) or max(tries, key=lambda t: t["end"] - t["start"])
    return a["start"] + lf


def sample_at(cols: dict, frame: int, max_gap: int = 8) -> dict | None:
    """The ghost's row at a frame (linear x/y between rows up to max_gap frames apart; the last row past the end)."""
    import bisect
    fs = cols["f"]
    if not fs or frame < fs[0]:
        return None
    i = bisect.bisect_right(fs, frame) - 1
    row = {k: cols[k][i] for k in TRACK_FIELDS}
    row["done"] = i == len(fs) - 1 and frame > fs[i]
    if i + 1 < len(fs) and 0 < fs[i + 1] - fs[i] <= max_gap and frame > fs[i] and cols["lv"][i + 1] == row["lv"] \
            and cols["ap"][i + 1] == row["ap"]:
        t = (frame - fs[i]) / (fs[i + 1] - fs[i])
        row["x"] = row["x"] + (cols["x"][i + 1] - row["x"]) * t
        row["y"] = row["y"] + (cols["y"][i + 1] - row["y"]) * t
    return row


def ghost_screen(row: dict, live: dict, profile: Profile = PROFILES["smb1"]) -> dict | None:
    """Project a ghost row onto the live picture (native pixels): same level and map only; x = world x minus the live
    camera; y is already a screen row (SMB1 never scrolls vertically). Off-screen horizontally -> side + distance."""
    if level_name(row["lv"] // 4, row["lv"] % 4) != live.get("level") or row["ap"] != live.get("ap"):
        return None
    w, _ = profile.screen
    small = bool(row["pw"] & 4)
    box = profile.box
    sx = row["x"] - live["scr"]
    y_hi, y = int(row["y"]) // 256, row["y"] - 256
    h = box["small_h"] if small else box["h"]
    top = y + (box["h"] - h)
    out = {"x": sx, "y": top, "w": box["w"], "h": h, "small": small, "face": row["face"], "visible": y_hi == 1,
           "anim": row["anim"]}
    if sx + box["w"] < 0:
        out["side"], out["distance"] = "left", -sx
    elif sx > w:
        out["side"], out["distance"] = "right", sx - w
    return out


# --------------------------------------------------------------------------------------------- worker: live capture
ACTIVE: dict[str, "Capture"] = {}
_LOCK = threading.Lock()
LIVE_INTERVAL = 1 / 15                    # live state posts per second while something changes
POST_RETRIES = 5


def read_block(ad, base: int, size: int) -> bytes:
    """The profile's RAM block in one round trip where the adapter allows it. RetroArch's READ_CORE_MEMORY answers at
    most 256 bytes per request on Mesen (seen 2026-10-13), READ_CORE_RAM (the RetroAchievements view, NES internal RAM
    at $0) answers the whole 2 KiB; other adapters read in 256-byte pieces."""
    if hasattr(ad, "cmd") and hasattr(ad, "_ram_offset"):
        r = ad.cmd(f"READ_CORE_RAM {ad._ram_offset(base):x} {size}", reply=True, timeout=1.0).split()
        if len(r) >= 3 and r[2] != "-1":
            data = bytes.fromhex("".join(r[2:]))
            if len(data) == size:
                return data
    out = bytearray()
    for o in range(0, size, 256):
        n = min(256, size - o)
        b = bytes(ad.read_memory(base + o, n))
        if len(b) != n:
            raise RuntimeError(f"short RAM read at {base + o:#x}: {len(b)} of {n}")
        out += b
    return bytes(out)


class Capture:
    """The per-session recorder on the worker: a reader thread (one RAM read per emulated frame, decode, Recorder) and
    a sender thread (the newest live state at most LIVE_INTERVAL apart, finished runs with retries), so a slow control
    plane never costs the reader a frame."""

    def __init__(self, sid: str, ad, game: dict, profile: Profile, post: Callable[[str, str, dict], None] | None,
                 alive: Callable[[], bool]):
        self.sid, self.ad, self.game, self.p, self.post, self.alive = sid, ad, game, profile, post, alive
        self.rec = Recorder(profile, game.get("game_id", ""), sid)
        self.stop_ev, self.wake = threading.Event(), threading.Event()
        self.thread: threading.Thread | None = None
        self.sender: threading.Thread | None = None
        self.pending: list[dict] = []
        self.lock = threading.Lock()
        self.live_latest: dict | None = None
        self.stats = {"reads": 0, "errors": 0, "runs": 0, "live_posts": 0, "last_error": "", "started": time.time()}

    def status(self) -> dict:
        r = self.rec.run
        up = max(1e-6, time.time() - self.stats["started"])
        return {"state": "recording" if self.thread and self.thread.is_alive() else "stopped", "profile": self.p.key,
                "reads": self.stats["reads"], "reads_per_s": round(self.stats["reads"] / up, 1), "errors": self.stats["errors"],
                "runs_posted": self.stats["runs"], "live_posts": self.stats["live_posts"], "pending_posts": len(self.pending),
                "last_error": self.stats["last_error"],
                "run": {"run_id": r["run_id"], "frame": r["frame"], "level": (r["cur"] or {}).get("level")} if r else None}

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True, name=f"ghost-runs-{self.sid}")
        self.thread.start()
        if self.post:
            self.sender = threading.Thread(target=self._send_loop, daemon=True, name=f"ghost-runs-send-{self.sid}")
            self.sender.start()

    def _loop(self):
        base, size = self.p.ram
        fails = 0
        paced = hasattr(self.ad, "cmd")                          # RetroArch answers in its next frame: never sleep
        while not self.stop_ev.is_set() and self.alive():
            t0 = time.monotonic()
            try:
                m = read_block(self.ad, base, size)
                fails = 0
                self.stats["reads"] += 1
            except Exception as e:                               # noqa: BLE001 - emulator busy / closing
                fails += 1
                self.stats["errors"] += 1
                self.stats["last_error"] = f"{type(e).__name__}: {e}"[:200]
                self.stop_ev.wait(min(2.0, 0.05 * fails))
                continue
            done = self.rec.feed(self.p.decode(m))
            with self.lock:
                self.pending += done
                self.live_latest = self.rec.live()
            self.wake.set()
            if not paced and time.monotonic() - t0 < 0.004:      # an adapter that answers at once: about one per frame
                self.stop_ev.wait(1 / 60)

    def _send_loop(self):
        last_key, last_at = None, 0.0
        while not (self.stop_ev.is_set() and not self.pending):
            self.wake.wait(0.5)
            self.wake.clear()
            self._flush()
            if self.stop_ev.is_set():
                break
            with self.lock:
                live = self.live_latest
            if live is None:
                continue
            key = (live.get("run_frame"), live.get("x"), live.get("scr"), live.get("level"), live.get("oper"))
            wait = LIVE_INTERVAL - (time.monotonic() - last_at)
            if key == last_key:
                continue
            if wait > 0:
                self.stop_ev.wait(wait)
                with self.lock:
                    live = self.live_latest
            last_key, last_at = key, time.monotonic()
            try:
                self.post("POST", f"/api/ghosts/live/{self.sid}", live | {"game_id": self.game.get("game_id", "")})
                self.stats["live_posts"] += 1
            except Exception as e:                               # noqa: BLE001 - the overlay just misses an update
                self.stats["last_error"] = f"live post: {e}"[:200]

    def _flush(self):
        while self.post:
            with self.lock:
                if not self.pending:
                    return
                run = self.pending[0]
            try:
                self.post("POST", "/api/ghosts/runs", run)
            except Exception as e:                               # noqa: BLE001 - kept, retried on the next wake
                self.stats["last_error"] = f"run upload: {e}"[:200]
                return
            with self.lock:
                self.pending.pop(0)
            self.stats["runs"] += 1

    def stop(self, outcome: str = "session_end") -> dict:
        self.stop_ev.set()
        self.wake.set()
        for t in (self.thread, self.sender):
            if t and t is not threading.current_thread():
                t.join(timeout=3)
        run = self.rec.finish(outcome)
        if run:
            with self.lock:
                self.pending.append(run)
        for _ in range(POST_RETRIES):
            self._flush()
            if not self.pending:
                break
            time.sleep(0.5)
        if self.post:
            try:
                self.post("POST", f"/api/ghosts/live/{self.sid}", {"on": False, "ended": True})
            except Exception:                                    # noqa: BLE001
                pass
        return self.status()


def _poster(server: str | None, headers: dict | None):
    if not server:
        return None
    import httpx
    client = httpx.Client(base_url=server, headers=headers or {}, timeout=10)

    def post(method: str, path: str, body: dict):
        r = client.request(method, path, json=body)
        r.raise_for_status()
        return r.json()
    return post


def start(sid: str, ad, game: dict, server: str | None, headers: dict | None, alive: Callable[[], bool]) -> dict:
    """At launch (gbox.tools.launch_game): record this session when its game has a profile."""
    p = profile_for(game)
    if p is None:
        return {"state": "unsupported", "reason": "no ghost-run profile for this game"}
    if "read_memory" not in getattr(ad, "supported", ()) and not hasattr(ad, "read_memory"):
        return {"state": "unsupported", "reason": f"{getattr(ad, 'name', 'adapter')} cannot read RAM"}
    cap = Capture(sid, ad, game, p, _poster(server, headers), alive)
    with _LOCK:
        old = ACTIVE.pop(sid, None)
        ACTIVE[sid] = cap
    if old:
        old.stop("session_end")
    cap.start()
    return {"state": "recording", "profile": p.key}


def stop(sid: str) -> dict | None:
    with _LOCK:
        cap = ACTIVE.pop(sid, None)
    return cap.stop() if cap else None


def get(sid: str) -> Capture | None:
    return ACTIVE.get(sid)


# ---------------------------------------------------------------------------------------------- control plane routes
_LIVE: dict[str, dict] = {}
LIVE_STALE_S = 5.0
META_DROP = ("track", "rows", "timers")
PREF_KEYS = ("shown", "colors", "mode", "pick", "last_n", "hud", "me", "picture")
DEFAULT_PREFS = {"shown": [], "colors": {}, "mode": "level", "pick": "best", "last_n": 3, "hud": True, "me": False,
                 "picture": {"aspect": "4:3", "crop_top": 0, "crop_bottom": 0}}
PALETTE = ("#4fc3f7", "#ffb74d", "#ba68c8", "#81c784", "#f06292", "#fff176", "#4db6ac", "#e57373")


class RunIn(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str
    game_id: str = ""
    track: str = ""


class RunEdit(BaseModel):
    name: str | None = None


class PrefsIn(BaseModel):
    model_config = {"extra": "ignore"}
    shown: list[str] | None = None
    colors: dict[str, str] | None = None
    mode: str | None = None
    pick: str | None = None
    last_n: int | None = None
    hud: bool | None = None
    me: bool | None = None
    picture: dict | None = None


def prefs_of(store, gid: str) -> dict:
    return DEFAULT_PREFS | (store.get("ghost_prefs", gid) or {})


def runs_of(store, gid: str) -> list[dict]:
    return [r for r in store.all("ghost_run") if r.get("game_id") == gid]


def chosen(runs: list[dict], prefs: dict, level_bests: dict) -> list[str]:
    """The run ids the overlay shows: pick best | last | pb_segments (best run + per-level best runs) | custom."""
    pick = prefs.get("pick") or "custom"
    if pick == "best":
        best = [r["run_id"] for r in runs if r.get("best")] or [r["run_id"] for r in runs if r.get("best_progress")]
        return best[:1] or [r["run_id"] for r in runs[:1]]
    if pick == "last":
        return [r["run_id"] for r in runs[:max(1, min(8, int(prefs.get("last_n") or 3)))]]
    if pick == "pb_segments":
        return list(dict.fromkeys(b["run_id"] for b in level_bests.values()))
    if pick == "none":
        return []
    have = {r["run_id"] for r in runs}
    return [i for i in prefs.get("shown") or [] if i in have]


def register(app, auth, store):
    """Routes on the control plane (server.create_app)."""
    from fastapi import Depends, HTTPException

    @app.post("/api/ghosts/live/{sid}")
    def ghosts_live_put(sid: str, body: dict, actor=Depends(auth)):
        if body.get("ended"):
            _LIVE.pop(sid, None)
            return {"ok": True}
        _LIVE[sid] = body | {"t": time.time()}
        return {"ok": True}

    @app.get("/api/ghosts/live/{sid}")
    def ghosts_live_get(sid: str, actor=Depends(auth)):
        v = _LIVE.get(sid)
        if not v or time.time() - v["t"] > LIVE_STALE_S:
            return {"on": False, "session_id": sid}
        return v | {"age": round(time.time() - v["t"], 3), "session_id": sid}

    @app.post("/api/ghosts/runs")
    def ghosts_run_put(run: RunIn, actor=Depends(auth)):
        body = run.model_dump()
        if not re.fullmatch(r"[0-9a-f]{8,32}", body["run_id"]):
            raise HTTPException(422, "run_id is hex")
        if body.get("track"):
            try:
                n = len(unpack_track(body["track"]))
            except Exception as e:                               # noqa: BLE001
                raise HTTPException(422, f"track does not decode: {e}")
            store.put("ghost_track", body["run_id"], {"run_id": body["run_id"], "fmt": body.get("track_fmt", ""),
                                                      "track": body["track"], "rows": n})
        meta = {k: v for k, v in body.items() if k not in META_DROP}
        old = store.get("ghost_run", body["run_id"]) or {}
        if old.get("name"):
            meta["name"] = old["name"]
        store.put("ghost_run", body["run_id"], meta)
        store.audit(actor, "ghost_runs.record", body["run_id"], {"game_id": meta.get("game_id"), "outcome": meta.get("outcome"),
                                                                 "frames": meta.get("frames")})
        return meta

    @app.get("/api/ghosts/game/{gid}")
    def ghosts_game(gid: str, actor=Depends(auth)):
        game = store.catalog_get(gid) or {"game_id": gid}
        p = profile_for(game)
        runs, level_bests = annotate(runs_of(store, gid))
        prefs = prefs_of(store, gid)
        for i, r in enumerate(sorted(runs, key=lambda r: r.get("started_at") or 0)):
            r["number"] = i + 1
            r.setdefault("color", prefs["colors"].get(r["run_id"]) or PALETTE[i % len(PALETTE)])
        return {"game_id": gid, "profile": p.public() if p else None, "runs": runs, "level_bests": level_bests,
                "prefs": prefs, "showing": chosen(runs, prefs, level_bests)}

    @app.get("/api/ghosts/runs/{rid}")
    def ghosts_run_get(rid: str, actor=Depends(auth)):
        meta = store.get("ghost_run", rid)
        if not meta:
            raise HTTPException(404, "no such run")
        tr = store.get("ghost_track", rid) or {}
        cols = track_columns(unpack_track(tr["track"])) if tr.get("track") else {k: [] for k in TRACK_FIELDS}
        return meta | {"track": cols}

    @app.patch("/api/ghosts/runs/{rid}")
    def ghosts_run_edit(rid: str, edit: RunEdit, actor=Depends(auth)):
        meta = store.get("ghost_run", rid)
        if not meta:
            raise HTTPException(404, "no such run")
        if edit.name is not None:
            meta["name"] = edit.name.strip()[:80]
        store.put("ghost_run", rid, meta)
        store.audit(actor, "ghost_runs.rename", rid, {"name": meta.get("name", "")})
        return meta

    @app.delete("/api/ghosts/runs/{rid}")
    def ghosts_run_delete(rid: str, actor=Depends(auth)):
        meta = store.get("ghost_run", rid)
        if not meta:
            raise HTTPException(404, "no such run")
        store.delete("ghost_run", rid)
        store.delete("ghost_track", rid)
        prefs = store.get("ghost_prefs", meta.get("game_id", ""))
        if prefs and rid in (prefs.get("shown") or []):
            prefs["shown"] = [i for i in prefs["shown"] if i != rid]
            store.put("ghost_prefs", meta["game_id"], prefs)
        store.audit(actor, "ghost_runs.delete", rid, {"game_id": meta.get("game_id")})
        return {"deleted": rid}

    @app.post("/api/ghosts/game/{gid}/prefs")
    def ghosts_prefs(gid: str, inp: PrefsIn, actor=Depends(auth)):
        cur = prefs_of(store, gid)
        new = {k: v for k, v in inp.model_dump().items() if v is not None}
        if "mode" in new and new["mode"] not in ("level", "run"):
            raise HTTPException(422, "mode is level | run")
        if "pick" in new and new["pick"] not in ("best", "last", "pb_segments", "custom", "none"):
            raise HTTPException(422, "pick is best | last | pb_segments | custom | none")
        for k, v in (new.get("colors") or {}).items():
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", v or ""):
                raise HTTPException(422, f"colour of {k} is #rrggbb")
        if "colors" in new:
            new["colors"] = cur["colors"] | new["colors"]
        cur |= new
        store.put("ghost_prefs", gid, {k: cur[k] for k in PREF_KEYS})
        return cur


# ------------------------------------------------------------------------------------------------- tool (agents)
class GhostRunsIn(BaseModel):
    op: str = "list"                    # profiles | status | list | show | rename | delete | pick
    game_id: str = ""
    session_id: str = ""                # status: the live recorder of this session (runs on the session's worker)
    run_id: str = ""
    name: str = ""
    pick: str = ""                      # pick: best | last | pb_segments | custom | none
    runs: list[str] = []                # pick custom: these run ids
    mode: str = ""                      # pick: level | run


class GhostRunsOut(BaseModel):
    result: dict | list


def _api(ctx, method: str, path: str, **kw):
    import httpx
    if not ctx.server:
        raise RuntimeError("ghost_runs needs the control plane")
    r = httpx.request(method, ctx.server + path, headers=ctx.headers, timeout=30, **kw)
    r.raise_for_status()
    return r.json()


def _register_tool():
    from .models import Permission as P
    from .registry import tool

    @tool("ghost_runs", "1.0", GhostRunsIn, GhostRunsOut, capabilities=["runtime"], permissions=[P.READ],
          timeout_s=60)
    def ghost_runs(inp: GhostRunsIn, ctx):
        """Ghost runs: every run the operator plays of a supported game (Super Mario Bros. NES) is recorded from RAM
        per frame (position, facing, animation, power-up, level/area, inputs) with splits, and earlier runs race the
        live game as translucent ghosts in the session view. op=profiles: supported games; op=status session_id=..:
        the live recorder; op=list game_id=..: runs with times, splits, best flags; op=show run_id=..: one run;
        op=rename run_id name; op=delete run_id; op=pick game_id pick=best|last|pb_segments|custom|none
        [runs=[ids]] [mode=level|run]: which ghosts the overlay shows."""
        op = inp.op
        if op == "profiles":
            return {"result": [p.public() for p in PROFILES.values()]}
        if op == "status":
            cap = get(inp.session_id)
            return {"result": cap.status() if cap else {"state": "not recording", "session_id": inp.session_id}}
        if op == "list":
            g = _api(ctx, "GET", f"/api/ghosts/game/{inp.game_id}")
            g["runs"] = [{k: r.get(k) for k in ("run_id", "number", "name", "outcome", "start_level", "end_level",
                                                "time_s", "frames", "deaths", "best", "best_progress", "assisted",
                                                "started_at", "splits")} for r in g["runs"]]
            return {"result": g}
        if op == "show":
            r = _api(ctx, "GET", f"/api/ghosts/runs/{inp.run_id}")
            r["track"] = {"rows": len(r["track"]["f"]), "fields": list(TRACK_FIELDS)}
            return {"result": r}
        if op == "rename":
            return {"result": _api(ctx, "PATCH", f"/api/ghosts/runs/{inp.run_id}", json={"name": inp.name})}
        if op == "delete":
            return {"result": _api(ctx, "DELETE", f"/api/ghosts/runs/{inp.run_id}")}
        if op == "pick":
            body = {"pick": inp.pick or "custom"}
            if inp.runs:
                body["shown"] = inp.runs
            if inp.mode:
                body["mode"] = inp.mode
            return {"result": _api(ctx, "POST", f"/api/ghosts/game/{inp.game_id}/prefs", json=body)}
        raise ValueError("op is profiles | status | list | show | rename | delete | pick")


try:                                     # registry import is cheap; keeps the module usable without it in tests
    _register_tool()
except Exception:                        # noqa: BLE001
    pass
