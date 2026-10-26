"""Instant operator commands for the Mercenaries autobot (operator 2026-10-24: "get away from the line", "go to the next
time bonus", "fight" - and the bot does it immediately; boilerplate commands from a dropdown at the front of the chat).

The chat box and its dropdown POST /api/sessions/<sid>/directive (a command id, or typed words matched by match()); the
control plane keeps the newest per session (post / latest). The worker's telemetry thread polls it twice a second and
writes it into the live stats (directive, directive_seq, directive_until), which both bots read each tick (current()).
A directive never presses a key by itself: it changes what the bot decides, so every normal safeguard stays in force.
"""
from __future__ import annotations

import re
import threading
import time

# id -> label (dropdown), what the bot does, seconds a standing mode lasts (0 = one-shot, done on the next tick)
COMMANDS = {
    'fight': {'label': 'Fight them! (stop standing there, fight the foes)', 'hold_s': 15},
    'next_area': {'label': 'Go to the next area', 'hold_s': 0},
    'explore': {'label': 'Navigate more of the level', 'hold_s': 15},
    'hunt': {'label': 'Go after the enemies (seek, find and dispatch them)', 'hold_s': 20},
    'score': {'label': 'Go for score increases (build the combo)', 'hold_s': 20},
    'repetitive': {'label': 'You are doing a repetitive action (stop it, go forward)', 'hold_s': 8},
    'mine': {'label': 'Drop a mine and flee', 'hold_s': 0},
    # operator 2026-10-26 (#3889): "have the bot drop landmines while fleeing an area" - a standing mode: RE5's mine controller
    # is made due again each time its last mine is planted and left (6 m on), so he plants, moves on, plants ... (re5_ps3._mine_trail)
    'mine_trail': {'label': 'Drop mines while leaving the area (plant, move on, repeat)', 'hold_s': 45},
    'missing': {'label': 'You are missing (adjust the aim for this weapon)', 'hold_s': 0},
}
MAX_HOLD_S = 600.0                                              # the longest a caller may make a standing mode last
# typed words -> command (checked in order; the first match wins). Conservative: a plain note stays a plain note.
PATTERNS = (
    ('repetitive', r'\b(repetitive|repeating|same thing|stuck in a loop|looping|going in circles|stop doing (that|this|it))\b'),
    ('mine_trail', r'\bmines? trail\b|\b(drop|plant|lay|place|dropping|planting|laying) (land ?)?mines (while|as|when) (you |we )?'
                   r'(flee\w*|leav\w*|run\w*|retreat\w*|escap\w*|get\w* (away|out))|\bkeep (dropping|planting|laying) (land ?)?mines\b'
                   r'|\b(land ?)?mines while (fleeing|leaving|running|retreating|escaping)\b'),
    ('mine', r'\b(drop|plant|lay|place) (a |the )?mine\b|\bmine (and|then) (flee|run)\b'),
    ('missing', r'\b(you are |you\'re |keep |keeps )?(missing|miss(es)? (him|them|every|mostly))\b|\b(aim|shooting) (is )?(off|wrong|left|right)\b'),
    ('next_area', r'\b(next|another) (area|time bonus|bonus|hourglass|room|objective|checkpoint)\b|\bgo (to )?(the )?next\b|\bmove on\b'),
    ('score', r'\b(score|combo)\b.*\b(up|increas\w*|more|build|higher)\b|\b(increas\w*|raise|build|get) (the |your )?(score|combo)\b'),
    ('hunt', r'\b(go after|hunt|seek|find|chase) (the |those |these )?(enemies|enemy|foes|zombies|majini|ganados|them)\b'),
    ('explore', r'\b(explore|navigate (more|the level|the map)|map (the )?(level|world)|see more of the level)\b'),
    ('fight', r'^\W*(fight( them| these| him)?|attack|shoot( them| him)?|stop standing( there)?|engage)\W*$'
              r'|\b(fight (them|these|him|the)|stop standing|get away from the (line|wall)|dispatch (them|him))\b'),
)

_LATEST: dict[str, dict] = {}
_LOCK = threading.Lock()
_SEQ = [0]
MAX_SESSIONS = 64


def match(text: str) -> str | None:
    """The command a typed note asks for, else None (the note is then only a coaching note)."""
    low = ' '.join(str(text or '').lower().split())
    if not 2 <= len(low) <= 160:
        return None
    return next((cid for cid, pattern in PATTERNS if re.search(pattern, low)), None)


def post(sid: str, command: str, now: float | None = None, source: str = 'operator', hold_s: float | None = None) -> dict:
    """Store the newest command for the session; hold_s (0 .. MAX_HOLD_S) overrides how long a standing mode lasts."""
    if command not in COMMANDS:
        raise ValueError('Unknown command: ' + ', '.join(COMMANDS))
    hold = float(COMMANDS[command]['hold_s'])
    if hold_s is not None:
        try:
            hold = float(hold_s)
        except (TypeError, ValueError):
            raise ValueError(f'hold_s: seconds 0 .. {MAX_HOLD_S:g}') from None
        if not 0 <= hold <= MAX_HOLD_S:
            raise ValueError(f'hold_s: seconds 0 .. {MAX_HOLD_S:g}')
    now = time.time() if now is None else now
    with _LOCK:
        _SEQ[0] += 1
        row = {'seq': _SEQ[0], 'command': command, 'label': COMMANDS[command]['label'], 'at': now,
               'until': now + hold, 'source': source}
        _LATEST[sid] = row
        for old in sorted(_LATEST, key=lambda k: _LATEST[k]['at'])[:-MAX_SESSIONS]:
            _LATEST.pop(old, None)
    return dict(row)


def latest(sid: str) -> dict | None:
    with _LOCK:
        row = _LATEST.get(sid)
    return dict(row) if row else None


def apply_to_stats(stats: dict, row: dict | None) -> None:
    """Worker side: the polled directive into the live stats dict the bot reads (same process, other thread)."""
    if not row or stats.get('directive_seq') == row.get('seq'):
        return
    stats.update(directive=row['command'], directive_until=row['until'], directive_at=row['at'],
                 directive_seq=row['seq'], directive_status='received')


class Reader:
    """One bot's view of the directive stats: current() -> (command or None, fresh)."""

    def __init__(self):
        self.seen = None

    def current(self, stats: dict, now: float | None = None) -> tuple[str | None, bool]:
        cmd, seq = stats.get('directive'), stats.get('directive_seq')
        if not cmd or seq is None:
            return None, False
        now = time.time() if now is None else now
        fresh = seq != self.seen
        self.seen = seq
        if fresh or now < float(stats.get('directive_until') or 0):
            return cmd, fresh
        return None, False


def poll_loop(sid: str, server: str, headers: dict, stats_of, alive, client=None, every: float = 0.5,
              delay: float = 1.0) -> None:
    """Worker thread body: GET the newest directive twice a second while the run lives (httpx only here)."""
    import httpx
    time.sleep(delay)                                          # the run's thread is registered a moment after telemetry starts
    with (client or httpx.Client(base_url=server, headers=headers, timeout=5)) as c:
        while alive():
            try:
                r = c.get(f'/api/sessions/{sid}/directive')
                if r.status_code == 200:
                    stats = stats_of()
                    if stats is not None:
                        apply_to_stats(stats, r.json().get('directive'))
            except Exception:                                  # noqa: BLE001 - a missed poll never touches the game
                pass
            time.sleep(every)
