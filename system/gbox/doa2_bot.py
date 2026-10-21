"""Dead or Alive 2 Limited Edition (Dreamcast, Flycast) autoplay playbook: always in a fight, never on a title screen.

A thin shim since 2026-10-20: the game lives in the fighting engine as a title (gbox/fightbot/titles/doa2_dc.py: its
RAM, the hold reflex on the opponent's attack-input edge, the menu route), the loop is the engine's endless Survival
loop (gbox/fightbot/survival.py: jump states, menus, the safety net, nudges and hang detection). The playbook name,
its constants and play()'s behavior are unchanged (tests/test_doa2_bot.py)."""
from __future__ import annotations

import time

from .fightbot import survival
from .fightbot.titles import doa2_dc as TITLE
from .fightbot.titles.doa2_dc import (DEMO, EXPLORE, FREE, GAME_IDS, HOLD_S, HOLDS, HP_MAX, JUDGE_S,  # noqa: F401
                                      JUMP_LAND, JUMP_REFRESH, MAX_FAILED_JUMPS, NUDGE_WAIT, OUT_JUMP, P1_HP, P2_HP,
                                      ROUTE, SAFETY_HP, STILL_FOR, WARN, WATCH, Reflex, matches, state)


def setup(ad) -> list[str]:
    return []


def play(ad, send, stopped, style=None, clock=time.time, sleep=time.sleep, stats: dict | None = None,
         holds: bool | None = None) -> dict:
    """stats (optional, filled live for the watch panel): fights_s, jumps, routes, saves, safety, hung, plus the
    current p1/p2 health and whether a fight is on."""
    return survival.play(TITLE, ad, send, stopped, style=style, clock=clock, sleep=sleep, stats=stats, holds=holds)
