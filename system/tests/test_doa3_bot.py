"""DOA3 on the fighting engine (gbox.fightbot.titles.doa3_xbox, gbox.doa3_bot): frames, holds, the playbook."""
import struct
from types import SimpleNamespace

from gbox import doa3_bot, doa3_pad, ram_map
from gbox.fightbot import vocab
from gbox.fightbot.titles import doa3_xbox as D
from gbox.fightbot.world import Attack, Fighter, World


class Ram:
    def __init__(self):
        self.ram = bytearray(0x900000)
        struct.pack_into("<Q", self.ram, D.QPC_HZ, 10_000_000)       # a 10 MHz performance counter

    def read(self, a, n):
        return bytes(self.ram[a:a + n])

    def write(self, a, data):
        self.ram[a:a + len(data)] = data

    def frames(self, n, ms=1000 / 60):
        """The main loop ran n more frames."""
        qpc, ring = struct.unpack_from("<Q", self.ram, D.QPC)[0], struct.unpack_from("<I", self.ram, D.RING)[0]
        struct.pack_into("<Q", self.ram, D.QPC, qpc + int(n * ms * 10_000))
        struct.pack_into("<I", self.ram, D.RING, (ring + n) & 7)


def test_the_map_loads_and_names_the_engine_vocabulary():
    m = ram_map.load(D.MAP_ID)
    assert m.spec["fight"]["title"] == "gbox.fightbot.titles.doa3_xbox"
    rep = vocab.check(m)
    assert rep["filled"]["p2.move"] == "p2.move" and "screen" in rep["driver"]
    assert ram_map.find({"game_id": "f03a801797a90506"}).id == D.MAP_ID      # the QuickSwap copy too


def test_frames_follow_the_ring_and_the_counter_when_it_wraps():
    ram, t = Ram(), D.Doa3()
    assert t.frame(ram) == 0
    assert t.frame(ram) == 0                                     # nothing ran
    ram.frames(1)
    assert t.frame(ram) == 1
    ram.frames(3)
    assert t.frame(ram) == 4                                     # three frames between two polls
    ram.frames(8)                                                # the ring is back where it was: the counter says 8
    assert t.frame(ram) == 12
    ram.frames(2)
    assert t.frame(ram) == 14 and not t.ring_dead                # and the ring moves again: it counts again


def test_frames_fall_back_to_the_counter_when_the_ring_never_moves():
    ram, t = Ram(), D.Doa3()
    t.frame(ram)
    for n in (1, 2, 3, 4, 5):
        qpc = struct.unpack_from("<Q", ram.ram, D.QPC)[0]
        struct.pack_into("<Q", ram.ram, D.QPC, qpc + int(1000 / 60 * 10_000))   # one frame, the ring still
        t.frame(ram)
    assert t.ring_dead and t.count >= 2                          # after 3 still-ring frames it counts by the clock


def test_holds_go_back_from_the_side_p1_is_on_and_lead_with_the_signature_height():
    t = D.Doa3()
    w = World(frame=0, t=0, screen="fight", p1=Fighter(side=1), p2=Fighter(side=-1))
    names = [a.name for a in t.answers(Attack(height="low"), w)]
    assert names[0] == "hold_low" and set(names) == {"hold_high", "hold_mid", "hold_low", "hold_mid_kick"}
    hold = next(a for a in t.answers(Attack(), w) if a.name == "hold_high")
    assert hold.at(0) == ("left", "up", D.FREE)                  # directions first, back = left on the left side
    w.p1.side = -1
    hold = next(a for a in t.answers(Attack(), w) if a.name == "hold_high")
    assert hold.at(0) == ("right", "up", D.FREE)
    assert t.input_bits(hold, w) == 0x20 | 0x40 | 0x1            # the game's own bits for up, right, F
    assert [a.name for a in t.answers(Attack(kind="throw"), w)] == ["throw_escape"]


def test_a_caught_attack_is_judged_by_the_games_paired_move_flag():
    t = D.Doa3()
    hold = t.answers(Attack(), World(0, 0, "fight", Fighter(side=1), Fighter(side=-1)))[0]
    before = World(0, 0, "fight", Fighter(side=1), Fighter(side=-1))
    caught = World(5, 0, "fight", Fighter(side=1), Fighter(side=-1, tags={"state": ["held"]}))
    assert t.outcome(before, caught, hold) == (30.0, True, "held")               # health unmapped: the flag decides
    thrown = World(5, 0, "fight", Fighter(side=1, tags={"state": ["held"]}), Fighter(side=-1))
    assert t.outcome(before, thrown, hold) == (-30.0, True, "thrown")
    assert t.outcome(before, before, hold) == (0.0, None, "unknown")             # nothing to tell: not a whiff
    ram = Ram()
    ram.ram[0x484CE2] = 1                                                      # the map's p2.paired -> state held
    assert t.read(ram).p2.has("held") and not t.read(ram).p1.has("held")


def test_punishes_are_options_the_first_a_string():
    t = D.Doa3()
    options = t.punish(None, "held")
    assert [a.name for a in options] == ["ppk", "low_kick", "kick"] and all(a.kind == "punish" for a in options)
    p = options[0]
    assert p.length == 21
    assert [p.at(k) for k in (0, 3, 9, 18)] == [(D.PUNCH,), (), (D.PUNCH,), (D.KICK,)]


class Game(Ram):
    """DOA3 as the playbook sees it: the title waits for START on any port, the menu for A, a fight runs 40 frames
    (P2 presses P every 15 frames) and ends in a KO, then the menus come back. The loop's frame clock advances one
    frame per poll of the clock block."""

    def __init__(self):
        super().__init__()
        self.mode, self.phase, self.fights, self.t = 2, 0, 0, 0
        self.put()

    def put(self):
        self.ram[0x480B70], self.ram[0x47E727] = self.mode, self.phase

    def pad(self):
        buttons = struct.unpack_from("<H", self.ram, doa3_pad.STATE_AT + 4)[0]
        return buttons, self.ram[doa3_pad.STATE_AT + 6]               # START bit, the A button's byte

    def read(self, a, n):
        if a == D.CLOCK[0]:
            self.frames(1)
            self.t += 1
            if self.mode == 1 and self.phase == 3:
                struct.pack_into("<H", self.ram, 0x48A496, 0x2 if self.t % 15 == 0 else 0)
                if self.t - self.fight_at >= 40:
                    self.phase = 4
            elif self.mode == 1 and self.phase == 4 and self.t - self.fight_at >= 50:
                self.mode, self.phase = 0, 0
            self.put()
        return super().read(a, n)

    def write(self, a, data):                                       # the game polls the pad every frame: a press
        super().write(a, data)                                      # is seen even if released before our next read
        buttons, a_button = self.pad()
        if self.mode == 2 and buttons & 0x10 and struct.unpack_from("<I", self.ram, doa3_pad.HANDLE_AT)[0] == doa3_pad.SENTINEL:
            self.mode = 0
        elif self.mode == 0 and a_button:
            self.mode, self.phase, self.fight_at = 1, 3, self.t
            self.fights += 1
        self.put()


def test_survival_runs_menus_and_fights_from_ram_with_the_virtual_pad(tmp_path):
    game = Game()
    pad = doa3_pad.VirtualPad(game)
    ad = SimpleNamespace(name="doa3_native", channel=lambda: SimpleNamespace(read=game.read),
                         pad=lambda: pad, send_input=lambda rows: pad.apply(rows, sleep=lambda s: None),
                         config=SimpleNamespace(runtime=tmp_path), read_memory=game.read)
    assert doa3_bot.setup(ad) == []
    polls = {"n": 0}

    def stopped():
        polls["n"] += 1
        return game.fights >= 3 and game.mode == 0
    now = [0.0]
    stats = doa3_bot.play(ad, ad.send_input, stopped, clock=lambda: now[0],
                          sleep=lambda s: now.__setitem__(0, now[0] + s))
    assert game.fights >= 3                                        # title -> menu -> fight, three times
    assert stats["menu_presses"] >= 4 and stats["fight_end"] in ("menu", "round_end", "unknown")
    assert stats["attacks"] >= 3 and stats["frames"] >= 100       # P2's punches seen as attack-input edges
    assert stats["hung"] is False
    assert (tmp_path / "fightbot" / D.MAP_ID / "book.json").is_file()


def test_a_cast_build_names_the_fighters_it_swapped(tmp_path):
    import json
    marker = {"slots": [{"slot": "fighter:zack", "donor": "sa1_sonic"}, {"slot": "fighter:kasumi", "donor": "x"},
                        {"slot": "stage:x"}, {"slot": "fighter:hika", "donor": "y"}]}
    assert D.swapped_fighters(marker) == [0, 5]                  # hika isn't pinned yet: left out
    cache = tmp_path / "cache"
    (cache / "mods" / D.MAP_ID / "doa3_zac_sa1_sonic").mkdir(parents=True)
    (cache / "mods" / D.MAP_ID / "doa3_zac_sa1_sonic" / ".gbox-mod.json").write_text(json.dumps(marker))
    ad = SimpleNamespace(game={"mod": "doa3_zac_sa1_sonic"}, config=SimpleNamespace(cache=cache, runtime=tmp_path))
    stats = {}
    dep = doa3_bot.Deployment(ad, stats=stats)
    assert dep.title.swapped == [0, 5] and stats["cast_fighters"] == "0,5"
    ad.game = {"mod": "../escape"}
    assert doa3_bot.Deployment.cast_fighters(ad) == [] and doa3_bot.Deployment.cast_fighters(SimpleNamespace()) == []


def test_the_evidence_sheet_puts_real_frames_side_by_side():
    import io
    from PIL import Image
    frames = []
    for color in ((255, 0, 0), (0, 255, 0)):
        buf = io.BytesIO()
        Image.new("RGB", (640, 480), color).save(buf, "PNG")
        frames.append(buf.getvalue())
    out = Image.open(io.BytesIO(doa3_bot.sheet([(0.05, frames[0]), (0.25, frames[1])], "hold_mid -> held")))
    assert out.size == (960, 382)                                  # two 480x360 frames and a caption strip
    assert out.getpixel((100, 200)) == (255, 0, 0) and out.getpixel((700, 200)) == (0, 255, 0)
    assert doa3_bot.sheet([(0, b"not an image")], "x") == b"not an image"


def test_start_is_refused_in_a_game_unless_p1_is_the_virtual_pad(tmp_path):
    ram = Ram()
    dep = doa3_bot.Deployment(SimpleNamespace(config=SimpleNamespace(runtime=tmp_path)))

    def allowed(mode, p1_port):
        ram.ram[0x480B70], ram.ram[0x2FD550] = mode, p1_port
        return dep.allow("start", dep.state(ram.read))
    assert not allowed(1, 0)                                      # a game P1 plays on port 1: START would join
    assert allowed(1, 3) and allowed(2, 0) and allowed(0, 0)      # P1 is port 4; the title; the menus
    assert dep.allow("b", {}) and not dep.allow("start", {})      # nothing read yet: no START


def test_a_paid_hold_leaves_a_real_frame_as_evidence(tmp_path):
    import time
    uploads = []
    ad = SimpleNamespace(get_frame=lambda: b"\x89PNG frame", config=SimpleNamespace(runtime=tmp_path))
    stats = {}
    dep = doa3_bot.Deployment(ad, stats=stats, upload=lambda *a, **k: uploads.append((a, k)) or "ab" * 32)
    dep.EVIDENCE_BURST_S = (0, 0)
    hold = D.Doa3().answers(Attack(), World(0, 0, "fight", Fighter(side=1), Fighter(side=-1)))[0]
    dep.evidence(hold, "held", 30.0, World(120, 0, "fight", Fighter(), Fighter()))
    dep.evidence(hold, "taken", -10.0, World(130, 0, "fight", Fighter(), Fighter()))    # didn't pay: no frame
    for _ in range(200):
        if uploads:
            break
        time.sleep(0.01)
    (name, data, media), prov = uploads[0]
    assert data == b"\x89PNG frame" and media == "image/png" and prov["outcome"] == "held" and len(uploads) == 1
    assert (tmp_path / "fightbot" / D.MAP_ID / "frames" / name).read_bytes() == b"\x89PNG frame"
    for _ in range(200):
        if stats.get("evidence_n"):
            break
        time.sleep(0.01)
    assert stats["evidence_n"] == 1 and stats["evidence_last"] == "ab" * 32


def test_the_playbook_matches_only_the_native_runner_and_claims_the_pad():
    assert doa3_bot.matches(SimpleNamespace(name="doa3_native"), {"game_id": "b8edf7040116f3aa"})
    assert not doa3_bot.matches(SimpleNamespace(name="cxbx"), {"game_id": "b8edf7040116f3aa"})
    assert not doa3_bot.matches(SimpleNamespace(name="doa3_native"), {"game_id": "1de2e7634f3161ff"})
    ram = Ram()
    ad = SimpleNamespace(pad=lambda: doa3_pad.VirtualPad(ram))
    assert doa3_bot.setup(ad) == []
    assert struct.unpack_from("<I", ram.ram, doa3_pad.HANDLE_AT)[0] == doa3_pad.SENTINEL
    struct.pack_into("<I", ram.ram, doa3_pad.HANDLE_AT, 0x58490004)
    assert "virtual pad" in doa3_bot.setup(ad)[0]                # a real 4th pad: reported, not taken
