"""Two players in one Switch emulator session on a Linux node (Citron NEO / Eden): Player 2's keyboard pad, written per
launch, and the controller applet the games open for split screen (docs/research/switch-coop-bot.md).

Operator 2026-10-27: "play and have the bot be my teammate in split screen" and "have the bot team up with itself
playing two play split screen and bots control both players". Player 1 keeps the emulator's default keyboard pad
(gbox.yuzu_runtime.SWITCH_KEYS: the operator's forwarded pad and a solo bot), Player 2 gets keys nobody else uses:

    a co-op launch    the session's own copy of the emulator's config folder (XDG_CONFIG_HOME), with
                      player_1_connected=true, a Pro Controller and every player_1_* binding on P2_KEYS. The shared
                      config (MercMode's solo boots, the other sessions) is never touched, so nothing leaks into the
                      next launch and two launches never race on one file.
    send_input_player only pad names with a P2 key, only player 2, only on a co-op launch whose config this session
                      verified; the whole batch is validated before any key goes out, never a fallback to Player 1.
    the applet        both games call nn::hid::ShowControllerSupport (1-2 players, multi-player mode) when split screen
                      is chosen, and Citron answers with its Qt "Controller Applet" dialog until OK: a co-op session
                      watches for it and presses Return (the dialog's default button) on it.

The emulator reads controllers only at boot: a running session gets Player 2 by restart_title (same session, display and
stream), never by a config write alone.
"""
from __future__ import annotations

import shutil
import threading
import time
import uuid
from pathlib import Path

from .registry import Unsupported

# Player 2: pad name -> (xdotool keysym, the Qt key code the emulator's keyboard engine binds). Every key is in the
# default Xvfb keymap (an xdotool keysym outside it is remapped onto one spare keycode, which breaks two keys held at
# once) and used neither by Player 1 (C X V Z Q E R T M N F G, arrows, WASD, IJKL, Shift, 7 / 8 the motion keys) nor
# by the emulator's hotkeys (F2, F4-F6, F8-F11, Esc, '-', '=', Ctrl chords). Holding Shift would turn the digits and
# punctuation into other Qt codes: no gBox path sends Shift.
P2_KEYS = {
    "lup": ("y", 89), "ldown": ("h", 72), "lleft": ("b", 66), "lright": ("o", 79),
    "zl": ("p", 80), "zr": ("u", 85),
    "rup": ("1", 49), "rdown": ("2", 50), "rleft": ("3", 51), "rright": ("4", 52),
    "a": ("5", 53), "b": ("6", 54), "x": ("9", 57), "y": ("0", 48),
    "l": ("bracketleft", 91), "r": ("bracketright", 93),
    "plus": ("semicolon", 59), "minus": ("apostrophe", 39),
    "dup": ("comma", 44), "ddown": ("period", 46), "dleft": ("slash", 47), "dright": ("backslash", 92),
    "lstick": ("grave", 96),
}
ALIASES = {"l2": "zl", "r2": "zr", "start": "plus", "select": "minus",
           "up": "dup", "down": "ddown", "left": "dleft", "right": "dright"}
# the emulator's NativeButton names (src/common/settings_input.h) in its config: player_<n>_button_<name>
BUTTONS = ("a", "b", "x", "y", "lstick", "rstick", "l", "r", "zl", "zr", "plus", "minus", "dleft", "dup", "dright",
           "ddown", "slleft", "srleft", "home", "screenshot", "slright", "srright")
STICKS = {"lstick": ("lup", "ldown", "lleft", "lright"), "rstick": ("rup", "rdown", "rleft", "rright")}
PRO_CONTROLLER = "0"                    # Settings::ControllerType::ProController
MAX_BATCH = 128
APPLET_NAME = "^Controller Applet$"     # QtControllerSelectorDialog's window title (qt_controller.ui)
APPLET_POLL_S = 0.7
APPLET_RETRY_S = 2.0                    # a dialog still up this long after Return (OK disabled?) is pressed again
APPLET_MAX_PRESSES = 6                  # per dialog window: then it is left for the operator and reported
COOP_DIR = "coop-config"                # under the emulator's home: one folder per co-op session


def players_requested(launch) -> int:
    """2 when a launch asks for split screen: game.launch.coop {"players": 2, ...} (the operator's PiP), or the MercMode
    block's coop ("bots": a bot+bot turn); 1 otherwise."""
    if not isinstance(launch, dict):
        return 1
    coop = launch.get("coop")
    if isinstance(coop, dict) and coop.get("players") == 2:
        return 2
    merc = launch.get("mercmode")
    if isinstance(merc, dict) and merc.get("coop") in ("bots", "bots_p1_p2"):
        return 2
    return 1


def binding(code: int) -> str:
    """One keyboard button as the emulator's config stores it (a quoted Common::ParamPackage)."""
    return f'"toggle:0,code:{int(code)},engine:keyboard"'


def _nested(code: int) -> str:
    # a ParamPackage inside a ParamPackage: ':' -> $0, ',' -> $1 (src/common/param_package.cpp)
    return f"toggle$00$1code$0{int(code)}$1engine$0keyboard"


def stick(directions: tuple[str, str, str, str]) -> str:
    up, down, left, right = (P2_KEYS[d][1] for d in directions)
    return (f'"modifier_scale:0.500000,modifier:{_nested(0)},right:{_nested(right)},left:{_nested(left)},'
            f'down:{_nested(down)},up:{_nested(up)},engine:analog_from_button"')


def controls() -> dict:
    """The [Controls] values a co-op launch writes: Player 2 connected as a Pro Controller on P2_KEYS, every button and
    both sticks written (an unwritten binding would take the emulator's default, Player 1's keys); the buttons without a
    P2 key, and the motion keys, unbound (code 0)."""
    values = {"player_1_connected": "true", "player_1_type": PRO_CONTROLLER}
    for name in BUTTONS:
        values[f"player_1_button_{name}"] = binding(P2_KEYS.get(name, (None, 0))[1])
    for name, dirs in STICKS.items():
        values[f"player_1_{name}"] = stick(dirs)
    values["player_1_motionleft"] = values["player_1_motionright"] = binding(0)
    return values


def _ini_get(text: str, section: str, key: str) -> str | None:
    in_section = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            in_section = s[1:-1] == section
        elif in_section and "=" in line and line.split("=", 1)[0].strip() == key:
            return line.split("=", 1)[1].strip()
    return None


def _codes(value: str | None) -> dict:
    """A stored binding's fields, order-free (the emulator rewrites its config at boot, its own key order)."""
    body = (value or "").strip().strip('"')
    return dict(part.split(":", 1) for part in body.split(",") if ":" in part)


def config_ok(text: str) -> tuple[bool, str]:
    """Whether a config file connects Player 2 on exactly P2_KEYS (read back after the emulator's own rewrite)."""
    if (_ini_get(text, "Controls", "player_1_connected") or "").lower() != "true":
        return False, "Player 2 is not connected in this launch's controller config"
    if (_ini_get(text, "Controls", "player_1_type") or "") != PRO_CONTROLLER:
        return False, "Player 2 is not a Pro Controller in this launch's controller config"
    for name in BUTTONS:
        want = str(P2_KEYS.get(name, (None, 0))[1])
        got = _codes(_ini_get(text, "Controls", f"player_1_button_{name}"))
        if got.get("engine") != "keyboard" or got.get("code") != want:
            return False, f"Player 2's {name} binding differs from gBox's Player 2 keys"
    for name, dirs in STICKS.items():
        got = (_ini_get(text, "Controls", f"player_1_{name}") or "").replace('"', "")
        for direction, pad in zip(("up", "down", "left", "right"), dirs):
            if f"{direction}:{_nested(P2_KEYS[pad][1])}" not in got:
                return False, f"Player 2's {name} {direction} binding differs from gBox's Player 2 keys"
    return True, "Player 2 keyboard pad configured for this launch"


def session_config(adapter, shared_xdg: Path, emulator_dir: Path) -> Path:
    """This co-op launch's own XDG_CONFIG_HOME: a fresh copy of the emulator's config folder (qt-config.ini after this
    launch's settings and LayeredFS selection, the per-title files) with Player 2 written in. Returns the new
    XDG_CONFIG_HOME; the shared folder is only read."""
    from .adapters import ini_set
    try:
        rel = emulator_dir.relative_to(shared_xdg)
    except ValueError:
        raise Unsupported("the emulator's config folder is not under its XDG_CONFIG_HOME; Player 2 cannot be "
                          "configured for this launch alone") from None
    token = getattr(adapter, "_coop_token", None) or uuid.uuid4().hex[:12]
    adapter._coop_token = token
    root = shared_xdg.parent / COOP_DIR / token
    target = root / rel
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    if emulator_dir.is_dir():
        shutil.copytree(emulator_dir, target)
    else:
        target.mkdir(parents=True, exist_ok=True)
    path = target / "qt-config.ini"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    for key, value in controls().items():
        text = ini_set(text, "Controls", f"{key}\\default", "false")
        text = ini_set(text, "Controls", key, value)
    path.write_text(text, encoding="utf-8")
    ok, why = config_ok(path.read_text(encoding="utf-8"))
    if not ok:
        raise Unsupported(f"Player 2 configuration read back wrong: {why}")
    adapter._coop_config_path = path
    return root


def drop_session_config(adapter) -> None:
    path = getattr(adapter, "_coop_config_path", None)
    token = getattr(adapter, "_coop_token", None)
    if path is not None and token and token in Path(path).parts:
        root = Path(*Path(path).parts[:Path(path).parts.index(token) + 1])
        shutil.rmtree(root, ignore_errors=True)
    adapter._coop_config_path = None


def launched(adapter) -> None:
    """After the emulator started: this launch's Player 2 record (its pid and config) for readiness()."""
    proc = getattr(adapter, "proc", None)
    path = getattr(adapter, "_coop_config_path", None)
    adapter._coop_launch = ({"pid": proc.pid, "config": str(path)}
                            if getattr(adapter, "coop_players", 1) == 2 and path and proc is not None else None)


def readiness(adapter) -> dict:
    """Is Player 2's pad live in this exact process: a co-op launch record for the running pid whose config still
    connects Player 2 on P2_KEYS. Configuration only: Player 2 joining the game is the title's RAM to prove."""
    out = {"player": 2, "prepared": getattr(adapter, "coop_players", 1) == 2, "verified": False,
           "requires_relaunch": True, "keys": {k: v[0] for k, v in P2_KEYS.items()},
           "reason": "This launch has no Player 2 controller; prepare it and restart the title in this session"}
    record = getattr(adapter, "_coop_launch", None)
    proc = getattr(adapter, "proc", None)
    try:
        alive = proc is not None and proc.poll() is None
        if record and alive and getattr(proc, "pid", None) == record["pid"]:
            ok, why = config_ok(Path(record["config"]).read_text(encoding="utf-8"))
            out.update(verified=ok, requires_relaunch=not ok, reason=why if ok else why + "; restart the title")
    except (OSError, KeyError, TypeError, ValueError):
        pass
    applet = public(getattr(adapter, "_coop_applet", None))
    if applet:
        out["applet"] = applet
    return out


def events(adapter, rows, player=2) -> list[tuple[str, bool]]:
    """Validate a whole Player 2 batch before any key is sent: [(keysym, down)]. Unsupported, with nothing sent, for
    another player, an unverified launch, an unknown button or a bad state."""
    if type(player) is not int or player != 2:
        raise Unsupported("Teammate input may only address Player 2; no input was sent")
    if not readiness(adapter)["verified"]:
        raise Unsupported("This launch has no verified Player 2 controller; no input was sent")
    if not isinstance(rows, (list, tuple)) or len(rows) > MAX_BATCH:
        raise Unsupported("Player 2 input batch exceeds its bound; no input was sent")
    out = []
    for row in rows:
        if not isinstance(row, dict) or type(row.get("player", 2)) is not int or row.get("player", 2) != 2:
            raise Unsupported("Teammate input may only address Player 2; no input was sent")
        key = str(row.get("key", "")).casefold()
        key = ALIASES.get(key, key)
        if key not in P2_KEYS:
            raise Unsupported(f"Player 2 has no key for {row.get('key')!r}; no input was sent")
        down = row.get("down", True)
        if type(down) is not bool:
            raise Unsupported("Invalid Player 2 button state; no input was sent")
        out.append((P2_KEYS[key][0], down))
    return out


def xdotool_args(rows: list[tuple[str, bool]]) -> list[str]:
    args, pressed = [], set()
    for key, down in rows:
        if not down and key in pressed:
            args += ["sleep", "0.06"]                      # a press and its release in one batch: the game sees it
        if down:
            pressed.add(key)
        args += ["keydown" if down else "keyup", key]
    return args


# --- the controller applet ------------------------------------------------------------------------------------------
def accept_applet(adapter, now: float | None = None) -> int:
    """Press Return on each visible Controller Applet dialog on this session's display (focus it first: there is no
    window manager, keys go to the focused window); returns how many were pressed. Each window is pressed at most
    APPLET_MAX_PRESSES times, APPLET_RETRY_S apart (a dialog whose OK stays disabled is left and reported)."""
    now = time.monotonic() if now is None else now
    state = getattr(adapter, "_coop_applet", None)
    if state is None:
        state = adapter._coop_applet = {"seen": 0, "presses": 0, "accepted": 0, "left": 0, "last": None}
    windows = adapter._xdo_out("search", "--onlyvisible", "--name", APPLET_NAME).split()
    book = state.setdefault("_windows", {})
    for wid in list(book):
        if wid not in windows:                             # gone: the press took it
            state["accepted"] += 1
            book.pop(wid)
    pressed = 0
    for wid in windows:
        row = book.setdefault(wid, {"presses": 0, "at": -1e9})
        if wid not in state.setdefault("_seen", set()):
            state["_seen"].add(wid)
            state["seen"] += 1
        if row["presses"] >= APPLET_MAX_PRESSES:
            if not row.get("left"):
                row["left"] = True
                state["left"] += 1
            continue
        if now - row["at"] < APPLET_RETRY_S:
            continue
        try:
            adapter._xdo("windowfocus", wid)
            adapter._xdo("key", "Return")
        except Exception:                                  # noqa: BLE001 - the dialog closed meanwhile
            continue
        row["presses"] += 1
        row["at"] = now
        state["presses"] += 1
        state["last"] = time.time()
        pressed += 1
    return pressed


def watch_applet(adapter, alive) -> threading.Thread:
    """A co-op session's watcher: accept_applet every APPLET_POLL_S while alive() (the session's own launch)."""
    def run():
        while alive():
            try:
                accept_applet(adapter)
            except Exception:                              # noqa: BLE001 - the display may be going away
                pass
            time.sleep(APPLET_POLL_S)
    t = threading.Thread(target=run, daemon=True, name=f"{getattr(adapter, 'name', 'switch')}-coop-applet")
    t.start()
    return t


def public(state: dict | None) -> dict | None:
    """The applet book without its private bookkeeping (query_runtime / readiness)."""
    return {k: v for k, v in state.items() if not k.startswith("_")} if state else None

