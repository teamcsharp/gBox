"""Unlock research profile for Dead or Alive 5 Ultimate: Arcade (sega_arcade_pc).

This module provides the static profile for game_id=75957a5c46d70c90.
The on-load routine is gated behind runtime verification and remains pending
until the exact-revision unlock implementation is deployed and runtime-tested.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

DOA5_ID = '75957a5c46d70c90'
DOA5_TEMPLATE_NAME = f'{DOA5_ID}-unlock.json'
DOA5_PLATFORM = 'sega_arcade_pc'


def template_path() -> Path:
    return Path(__file__).resolve().parent.parent / 'profiles' / 'gamedata' / DOA5_TEMPLATE_NAME


def template_digest() -> str:
    try:
        raw = template_path().read_bytes()
    except OSError:
        return ''
    return hashlib.sha256(raw).hexdigest()


def profile() -> dict:
    """Return the review-ready unlock profile for the owned DOA5 Ultimate Arcade revision.

    Verified=False until the exact native routine, save overlay and runtime acceptance
    are recorded in profiles/gamedata/{DOA5_ID}-unlock.json.
    """
    return {
        'status': 'research_pending',
        'profile': 'doa5-arcade-unlock-v0',
        'verified': False,
        'game_id': DOA5_ID,
        'platform': DOA5_PLATFORM,
        'scope': ['characters', 'hidden_characters', 'modes', 'levels', 'stages',
                  'costumes', 'items', 'extras'],
        'exclusions': ['No online competitive advantage patches', 'No account entitlement changes',
                       'No invented absent DLC'],
        'evidence': {
            'implementation': 'gbox.doa5_arcade_unlock.unlock_on_load',
            'native_routine': 'pending',
            'template': f'profiles/gamedata/{DOA5_TEMPLATE_NAME}',
            'verification': 'Pending fresh boot, per-category selection/play, second launch, rollback.',
        },
        'save_effect': 'Planned isolated unlock save overlay or monotonic progress edits with backup and rollback.',
        'requires_save_upgrade_opt_in': True,
        'next_step': 'Open the owned executable in REA/Ghidra on an x64 worker, resolve lock-check functions and xrefs, '
                     'build the complete category inventory, pin expected bytes/checksums/region, then implement '
                     'gbox.doa5_arcade_unlock.unlock_on_load and register the verified template.',
    }


def pre_launch(game: dict, ctx, mod: str = '') -> dict:
    """Return the launch-hook result for DOA5 Arcade. Currently always research_pending."""
    prof = profile()
    return {
        'state': 'research_pending',
        'applied': False,
        'reason': prof['evidence']['verification'],
        'profile': prof['profile'],
        'scope': prof['scope'],
        'exclusions': prof['exclusions'],
    }
