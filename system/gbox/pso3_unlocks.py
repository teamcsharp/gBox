"""Unlock research for the owned Phantasy Star Online Episode III - C.A.R.D. Revolution (USA).

Revision-guarded and evidence-first. This module never writes a save, patches RAM or
touches entitlements: the profile stays unverified until an idle worker has been
observed selecting and playing every catalogued entry.

Static evidence (Spark, 2026-10-20) comes from the owned executable PsoV3.dol of
game_id 5b5ecb4c36a13584, de-paired and imported into Ghidra project pso3
(23911 functions, 8876 strings).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

GAME_ID = '5b5ecb4c36a13584'
PLATFORM = 'gamecube'
DISC_TITLE = 'Phantasy Star Online Episode III - C.A.R.D. Revolution (USA)'
DISC_CODE = 'GPSE8P'
MAIN_EXECUTABLE = 'PsoV3.dol'
DOL_SHA256 = 'b02c3091542afc82fc62a1ddbe5f575f70aff6225778be1c12e0652bf47e82c2'
DEPAIRED_ELF_SHA256 = '708174dfe09fe729a08b0dfd2d4696cee8bacdcde10cd177255158d41efc601d'
GHIDRA_PROJECT = 'pso3'
ARTIFACT = 'profiles/gamedata/5b5ecb4c36a13584-unlock.json'
ARTIFACT_SHA256 = '36e3f301dea1a55ba74de2d3eb75aefaf1e5229f7be380af936274e2c40f273f'
CATEGORIES = ('characters', 'hidden_characters', 'modes', 'levels', 'stages',
              'costumes', 'items', 'extras')
STATES = ('static_candidate', 'unknown', 'not_present', 'verified')


def _artifact_path() -> Path:
    return Path(__file__).resolve().parent.parent / ARTIFACT


def load_artifact() -> dict:
    """Parsed, digest-checked research artifact; raises ValueError when it changed."""
    data = json.loads(_artifact_path().read_text(encoding='utf-8'))
    digest = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if digest != ARTIFACT_SHA256:
        raise ValueError('research artifact changed; this profile needs new verification')
    return data


def dol_revision(dol: bytes) -> str:
    """Revision key of a candidate executable: the sha256 of the owned main DOL."""
    return hashlib.sha256(dol).hexdigest()


def revision_matches(dol: bytes) -> bool:
    """True only for the exact owned GPSE8P executable this research describes."""
    return dol_revision(dol) == DOL_SHA256


def inventory() -> list:
    """Every catalogued entry with its evidence state (never a claim of unlocked)."""
    return load_artifact()['inventory']


def lock_trace_targets() -> list:
    """Static entry points the next run must trace to the save flags they read."""
    return load_artifact()['lock_trace_targets']


def save_layout() -> list:
    """Save files this build reads, with the addresses their names were found at."""
    return load_artifact()['save_layout']


def acceptance_plan() -> dict:
    return load_artifact()['acceptance']


def profile() -> dict:
    """The research profile: honest, unverified, and never applied by the fast path."""
    try:
        data = load_artifact()
    except (OSError, ValueError) as error:
        return {'status': 'unavailable', 'profile': None, 'verified': False, 'scope': [],
                'items': [], 'exclusions': [], 'game_id': GAME_ID,
                'reason': 'PSO Episode III research artifact unavailable: ' + str(error)}
    return {'status': 'pending_runtime_verification',
            'profile': data['profile'],
            'verified': False,
            'game_id': GAME_ID,
            'platform': PLATFORM,
            'scope': data['scope'],
            'exclusions': data['exclusions'],
            'items': data['inventory'],
            'evidence': {'revision': data['revision'], 'save_layout': data['save_layout'],
                         'lock_trace_targets': data['lock_trace_targets'],
                         'artifact': ARTIFACT, 'artifact_sha256': ARTIFACT_SHA256,
                         'static_only': True},
            'save_effect': data['save_effect'],
            'acceptance': data['acceptance'],
            'reason': data['reason'],
            'next': data['next']}
