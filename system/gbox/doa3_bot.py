"""Dead or Alive 3 (Xbox, USA) autoplay playbook: endless Survival, holding the CPU's strikes and punishing them.

The game is the fighting engine's second title (gbox/fightbot/titles/doa3_xbox.py); this module deploys it:
  * reads: the adapter's verified fast channel (doa3_memory.Channel): one ReadProcessMemory a read, per frame;
  * presses: gBox's virtual pad on the game's 4th port (doa3_pad), never the player's own controller;
  * where the game is: its own RAM (the map's screen signatures), never the picture;
  * between fights: the menus the screen says (Survival, a fighter, continue); in a fight: the frame-synced engine
    (fightbot.runner) holds the attacks the map's signatures (or the move book) say are coming, then punishes;
  * learning: the move book per worker (runtime/fightbot/<map id>/book.json) and the lessons log
    (runtime/fightbot/<map id>/runs/<run>.jsonl): hits taken with the attacker's state just before them.
The same title plays the cast builds (#1976 Sonic, #1977 Sonic vs Mario): characters and attacks are RAM values,
never looks, and the build changes only the disc's assets."""
from __future__ import annotations

import time

from .fightbot import survival
from .fightbot.book import Book
from .fightbot.engine import Engine
from .fightbot.lessons import Run
from .fightbot.runner import Sender, fight
from .fightbot.titles import doa3_xbox

GAME_IDS = doa3_xbox.GAME_IDS


def sheet(shots, caption: str) -> bytes:
    """Real game frames side by side (each labelled with its time after the event), as one PNG. Nothing is drawn
    on the frames themselves; a frame that isn't an image is left out."""
    import io
    try:
        from PIL import Image, ImageDraw
    except ImportError:                            # no Pillow: the first frame as it came
        return shots[0][1]
    frames = []
    for at, data in shots:
        try:
            im = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:                          # noqa: BLE001
            continue
        im.thumbnail((480, 360))
        frames.append((at, im))
    if not frames:
        return shots[0][1]
    w, h = sum(im.width for _, im in frames), max(im.height for _, im in frames) + 22
    out = Image.new("RGB", (w, h), (16, 16, 16))
    draw = ImageDraw.Draw(out)
    x = 0
    for at, im in frames:
        out.paste(im, (x, 22))
        draw.text((x + 6, 4), f"+{int(at * 1000)} ms  {caption}", fill=(235, 235, 235))
        x += im.width
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


def matches(ad, g: dict) -> bool:
    return getattr(ad, "name", "") == "doa3_native" and g.get("game_id") in GAME_IDS


def setup(ad) -> list[str]:
    """Claim the virtual pad (port 4) before the first press; a failure is reported, not raised."""
    try:
        ad.pad().claim()
        return []
    except Exception as error:                     # noqa: BLE001 - a real 4th pad, a closed channel: say so
        return [f"virtual pad: {error}"]


class Deployment:
    """What fightbot.survival needs from DOA3: where the game is, the menu presses, and the fight itself."""
    STILL_FOR, NUDGE_WAIT = 12.0, 12.0
    NUDGE_KEYS = ("start", "b")                    # out of a fight only (START in a fight joins as a challenger)
    MENU_GAP = 0.5
    MENU_IDLE = 20.0                               # a screen no rule maps (name entry ...): START, A
    READ_FAIL_S = 60.0                             # RAM unreadable this long (the runner gone): hung, relaunch

    def __init__(self, ad, title=None, book=None, lessons=None, stats=None, upload=None):
        self.ad, self.upload, self.stats = ad, upload, stats
        self.title = title or doa3_xbox.Doa3()
        root = None
        try:
            root = ad.config.runtime / "fightbot"
        except Exception:                          # noqa: BLE001 - no config (tests): in memory only
            pass
        self.book = book or Book(root / doa3_xbox.MAP_ID / "book.json" if root else None)
        self.lessons = lessons if lessons is not None else Run(root, doa3_xbox.MAP_ID)
        self.engine = Engine(self.title, self.book, self.lessons, stats)
        self.engine.on_judged = self.evidence
        self.title.swapped = self.cast_fighters(ad)        # a cast build: pick the fighters it swapped (the show)
        if stats is not None and self.title.swapped:
            stats["cast_fighters"] = ",".join(map(str, self.title.swapped))
        self.frames_dir = root / doa3_xbox.MAP_ID / "frames" if root else None
        self.captured = 0
        self.WATCH = doa3_xbox.CLOCK               # the frame clock: still = the game loop stopped

    EVIDENCE_FIRST, EVIDENCE_EVERY = 6, 25
    EVIDENCE_BURST_S = (0.05, 0.25, 0.5, 0.9)       # seconds after the judgement: four real frames side by side

    def evidence(self, answer, label, reward, w):
        """A hold that paid: the game's own frame of it a moment later (the hold animation), saved next to the
        lessons as real-frame evidence. The capture runs on its own thread: the fight loop never waits for it."""
        if answer.kind != "answer" or reward <= 0 or self.frames_dir is None or not hasattr(self.ad, "get_frame"):
            return
        self.paid = getattr(self, "paid", 0) + 1
        if self.captured >= self.EVIDENCE_FIRST and self.paid % self.EVIDENCE_EVERY:
            return
        self.captured += 1
        name = f"{self.lessons.run_id}-f{w.frame}-{answer.name}-{label}.png"

        def grab():
            import time as _t
            t0 = _t.monotonic()
            try:
                shots = []
                for at in self.EVIDENCE_BURST_S:              # a short burst: the hold, then what it did
                    _t.sleep(max(0.0, t0 + at - _t.monotonic()))
                    shots.append((at, self.ad.get_frame()))
                data = sheet(shots, f"{answer.name} -> {label}")
                self.frames_dir.mkdir(parents=True, exist_ok=True)
                (self.frames_dir / name).write_bytes(data)
                sha = self.upload(name, data, "image/png", answer=answer.name, outcome=label,
                                  frame=w.frame) if self.upload else None
                if sha and self.stats is not None:
                    self.stats["evidence_n"] = self.stats.get("evidence_n", 0) + 1
                    self.stats["evidence_last"] = sha
                self.lessons.log("evidence", w.frame, file=name, sha256=sha, answer=answer.name, outcome=label,
                                 reward=reward)
            except Exception as error:             # noqa: BLE001 - no frame now: the next success tries again
                self.lessons.log("evidence_failed", w.frame, error=str(error)[:200])
        import threading
        threading.Thread(target=grab, daemon=True, name="doa3-evidence").start()

    @staticmethod
    def cast_fighters(ad) -> list[int]:
        """The fighters this session's cast build swapped: its .gbox-mod.json marker in the worker's mod cache
        (cache/mods/<game id>/<mod>/), written by the cast writer. [] for the stock game or an unreadable marker."""
        import json
        try:
            mod = (getattr(ad, "game", None) or {}).get("mod") or ""
            if not mod or "/" in mod or "\\" in mod or mod.startswith("."):
                return []
            path = ad.config.cache / "mods" / doa3_xbox.MAP_ID / mod / ".gbox-mod.json"
            return doa3_xbox.swapped_fighters(json.loads(path.read_text(encoding="utf-8")))
        except Exception:                          # noqa: BLE001 - no marker: any fighter
            return []

    def reader(self, ad):
        """Every read goes to the adapter's current channel: a closed one is replaced at the next read."""
        return lambda a, n: ad.channel().read(a, n)

    def allow(self, key, st) -> bool:
        """START in a game (game.mode 1) on a port that isn't P1's joins as a challenger (0x00082307: the join path
        runs only in mode 1): refused there whatever screen the map's signatures say, unless P1 already is port 4."""
        if key != "start":
            return True
        values = getattr(st.get("world"), "values", None)
        if values is None:
            return False
        ports = values.get("players.port")
        return values.raw.get("game.mode") != 1 or (isinstance(ports, list) and bool(ports) and ports[0] == 3)

    def nudge_keys(self, st) -> tuple:
        """START only where it can't join a fight as a challenger: out of a game, or when P1 already is port 4."""
        w = st.get("world")
        values = getattr(w, "values", None)
        ports = values.get("players.port") if values is not None else None
        p1_on_pad = isinstance(ports, list) and ports and ports[0] == 3
        if st.get("screen") in ("title", "demo", "menu") or p1_on_pad:
            return ("start", "b")
        return ("b",)

    def state(self, rd) -> dict:
        w = self.title.read(rd)
        if self.stats is not None:                 # the game's own clock moving: black frames are a fade, not a hang
            self.stats["ram_progress"] = self.title.frame(rd)
        return {"screen": w.screen, "fighting": w.screen in self.title.fight_screens, "demo": int(w.screen in ("title", "demo")),
                "p1": w.p1.hp or 0, "p2": w.p2.hp or 0, "world": w}

    def menu_key(self, st) -> str | None:
        return self.title.menu(st["world"])

    def fight(self, ad, rd, send, stopped, stats) -> str:
        self.engine.stats = stats
        self.engine.reset()                        # nothing pending from the last fight is judged against this one
        sender = Sender(send)
        try:
            return fight(self.title, rd, sender, self.engine, stopped, stats=stats)
        finally:
            sender.close()
            self.engine.finish()
            self.book.save()
            stats["book"] = self.book.summary()


def play(ad, send, stopped, clock=time.time, sleep=time.sleep, stats: dict | None = None, upload=None) -> dict:
    """stats (filled live for the watch panel): the survival loop's (fights_s, menu presses, hung, the screen) and
    the engine's (attacks seen, answers, parried, hits taken, damage both ways, punishes, input and reaction latency
    in frames, frames skipped). upload(name, data, media_type, **provenance) -> sha256 (autoplay passes one): the
    evidence frames go to the control plane as artifacts (stats evidence_n / evidence_last)."""
    stats = stats if stats is not None else {}
    dep = Deployment(ad, stats=stats, upload=upload)
    stats["map_rev"] = dep.title.block.get("rev")     # which deployed map this run read (tuning without a relaunch)
    try:
        return survival.play(dep, ad, send, stopped, clock=clock, sleep=sleep, stats=stats, holds=False)
    finally:
        dep.book.save()
