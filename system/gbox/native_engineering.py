"""Reusable engineering contract for any game, including titles without a reader.

This is a work plan, never a capability or readiness claim. Keep it independent of
catalog/tool imports so dispatch and read-only queue inspection stay cheap.
"""
from __future__ import annotations

from copy import deepcopy
import re

# Exact catalog identities prevent reconnaissance for another port from being
# accepted as progress on the requested export. These are engineering aids,
# never entries in char_coverage.WRITERS or verified unlock profiles.
TITLE_WORK = {
    'c6adbfa00c20aaf9': {
        'platform': 'gamecube', 'disc_id': 'GHAE08',
        'source_format': 'GCZ or ISO; GCDisc reads GCZ directly without extracting an ISO',
        'reader': 'gbox.re2gc_native',
        'command': 'python -m gbox.re2gc_native OWNED_GCZ --out NEW_MANIFEST.json',
        'model_reader': 'gbox.re2gc_models',
        'state_reader': 'gbox.re2gc_state',
        'state_command': 'python -m gbox.re2gc_state --dol OWNED_main.dol --rel OWNED_scenario.rel --snapshot CAPTURE.mem1 --out NEW_STATE.json',
        'state_scope': 'Exact Leon/Claire sources; source-attested read-only MEM1 inventory/equipment decoder and corrected Ghidra analysis images. No live writes or verified unlock profile. See docs/re2gc-state.md.',
        'model_command': 'python -m gbox.re2gc_models OWNED_PLAYER.pld --out NEW_MODEL.glb',
        'validated_scope': '40 player PLD containers; bounded MD1 reader and guarded native writer; 23 textured 15-bone bind-pose GLBs via normal collection routing; 17 extra-part variants explicitly pending; native animation bytes retained but not exported',
        'separate_work': ['17 player variants need proven extra-part attachments; Sonic/Mario donor retargeting and EMD enemy coverage',
                          'GameCube-specific unlock routine and complete category inventory',
                          'live inventory and equip routines for the sidebar',
                          'isolated complete disc build and runtime acceptance'],
        'identity_warning': 'N64 game 46eec2fc627c8f58 / gbox.re2_inventory and PSX game 2d8ef2bdbd4a58fd are different targets; their addresses and acceptance do not apply.',
    },
    'e7ca89bbeb67360d': {
        'platform': 'ps3', 'edition': 'Resident Evil 5 Gold USA v02.00',
        'source_format': '7z folder game; list/extract exact PS3_GAME members, retain PARAM.SFO identity',
        'reader': 'gbox.re5ps3_arc',
        'command': 'python -m gbox.re5ps3_arc OWNED_CHARACTER.arc --out NEW_MANIFEST.json',
        'validated_scope': 'PS3 ARC v8 reader/writer verified with all 151 Chris/Sheva pack resources; MOD header counts only; existing re5 save unlock code is not gameplay-verified',
        'separate_work': ['PS3 ARC/MOD/TEX reader, writer and Sonic/Mario donor retargeting',
                          'confirm every unlock category including Mercenaries/Reunion roster and stages',
                          'PS3-specific live inventory/equip routines and sidebar integration',
                          'complete folder-game mod/export with isolated save overlay and runtime acceptance'],
        'identity_warning': 'Do not reuse RE6 Xbox 360 memory addresses, ARC compression or texture tiling. Existing re5_tool.COVERAGE explicitly leaves Mercenaries characters/stages unconfirmed.',
    },
}


STAGES = {
    'inventory': {
        'playbooks': ['study-title', 'magic-census'],
        'deliverable': 'An authoritative owned-build manifest and one identified native target asset.',
        'checks': [
            'Hash the actual owned source or authoritative manifest by streaming its bytes; do not copy a reference hash.',
            'Record platform, revision, container/member path, byte order, offset base and target slot. Confirm catalog labels against the files.',
            'Separate counted assets from filename guesses. An archive listing or fingerprint is not a model reader.',
        ],
    },
    'analysis': {
        'playbooks': ['study-title', 'string-xref-loader', 'routine-oracle', 'community-spec'],
        'deliverable': 'A reproducible format description and bounded probe for the exact asset.',
        'checks': [
            'Reuse a hash-identified executable/project; confirm CPU, load address, pointer width and endianness before interpreting code.',
            'For Dreamcast SH-4, use decomp_pipeline status/init/setup/prepare/task/check; local models consume task packets and only the independent checker can verify. For Xbox 360 use xenonrecomp or rexglue status/init/analyze/codegen as supported; generated code still requires runtime validation.',
            'Trace the loader and its callers to prove field meanings, relative offsets, compression and skeleton/animation ownership.',
            'Compare a sample with an independent specification, emulator implementation, or the game routine oracle; label unproved fields as hypotheses.',
        ],
    },
    'reader': {
        'playbooks': ['routine-oracle', 'round-trip-proof'],
        'deliverable': 'An editable native asset exported through the registered gBox collection path.',
        'checks': [
            'Preserve target identity, geometry or sprites, texture/palette/material mapping, and skeleton/animation mapping where applicable.',
            'Bound counts, reads, decompression output and pointer traversals by the source extent; reject short headers, truncated names, cycles and out-of-range indices.',
            'Use independently justified fixture bytes and expected values, then validate an owned-build sample. A fixture generated by the same parser assumptions is not independent proof.',
            'Wire the extractor, roster and reader version into characters/char_coverage; test normal collection and editable export, not only a standalone probe.',
        ],
    },
    'writer': {
        'playbooks': ['round-trip-proof', 'welded-fit'],
        'deliverable': 'A routed native writer and isolated mod changing one specified donor/target slot.',
        'checks': [
            'First prove a byte-identical no-op round trip; if the format necessarily normalizes, enumerate and justify every changed byte range and prove semantic equivalence independently.',
            'Then write a visibly changed donor and read it back independently. Prove the intended slot changed and unrelated members remain intact.',
            'Check relocation, alignment, checksums, compression, texture formats, bone mappings and vertex/triangle/memory budgets. Preserve unknown fields and original files.',
            'Register char_coverage.WRITERS and the characters_tool native route; test that the ordinary replacement request reaches this writer and produces the recorded mod hash.',
        ],
    },
    'runtime': {
        'playbooks': ['round-trip-proof'],
        'deliverable': 'Actual gameplay evidence for the exact build, donor, target and mod.',
        'checks': [
            'Confirm the reviewed writer is deployed, then launch the exact mod on an authorized idle worker without interrupting operator games.',
            'Capture the native replacement during gameplay and check movement, animation, materials and controls; a preview, overlay or boot screen is insufficient.',
            'Record source/mod hashes, donor, target slot, deployed revision, worker, session/job IDs and stored screenshots. Readiness applies only to this demonstrated scope.',
        ],
    },
}


def plan(game_id, *, stage='inventory', fingerprint=None):
    """Return an actionable plan even when a catalog game has no existing module."""
    if not re.fullmatch(r'[0-9a-f]{16}', str(game_id)):
        raise ValueError('Invalid game ID')
    if stage is not None and stage not in STAGES:
        raise ValueError('Invalid engineering stage')
    fp = fingerprint or {}
    return {
        'game_id': game_id, 'next_stage': stage,
        'title_work': deepcopy(TITLE_WORK.get(game_id)),
        'scope': 'Engineering plan only; no reader, writer or runtime support is inferred.',
        'start_from': fp.get('start_from') or fp.get('engine_reader') or '',
        'reuse': 'Read re_dossier for this game and re_playbook native-reader-writer. Verify fingerprint suggestions against the owned build before reusing a module.',
        'stages': deepcopy(STAGES),
        'integration': ['gbox/formats', 'gbox/characters.py', 'gbox/char_coverage.py', 'gbox/cast_swap.py'],
        'handoff': 'Keep exact source identity, artifact hashes, focused test command/result, commit/PR/deployment state and one executable next step. Preserve pending native job IDs. Never close a native replacement request on inventory/probe success.',
    }


def prompt(game_id, *, stage='inventory', fingerprint=None):
    packet = plan(game_id, stage=stage, fingerprint=fingerprint)
    stages = [stage] if stage else list(STAGES)
    lines = ['Native reader/writer engineering for game_id=' + game_id + ':', packet['reuse']]
    if packet.get('title_work'):
        title = packet['title_work']
        lines += ['Exact target: ' + title['platform'] + '; ' + title['source_format'],
                  title['identity_warning'], 'Validated engineering scope: ' + title['validated_scope']]
        if title.get('command'):
            lines.append('Native source inventory: ' + title['command'])
        if title.get('state_command'):
            lines.append('State engineering command: ' + title['state_command'])
        if title.get('state_scope'):
            lines.append('State engineering scope: ' + title['state_scope'])
        lines.append('Still required: ' + '; '.join(title['separate_work']))
    if packet['start_from']:
        lines.append('Candidate module (verify compatibility): ' + str(packet['start_from']))
    for name in stages:
        entry = packet['stages'][name]
        lines += [name + ': ' + entry['deliverable'], 'Read playbooks: ' + ', '.join(entry['playbooks'])]
        lines += ['- ' + check for check in entry['checks']]
    return '\n'.join(lines + [packet['handoff']])


def playbook():
    return {
        'id': 'native-reader-writer', 'seed_version': 1,
        'title': 'Engineer and integrate a native asset reader and writer for a new game',
        'goal': 'Turn an owned game build into editable assets and a verified native replacement through the normal gBox routes.',
        'when': ['reader', 'writer', 'native asset', 'unsupported game', 'reimport', 'format parser'],
        'platforms': ['any'], 'tags': ['reader', 'writer', 'engineering', 'validation', 'integration'],
        'steps': [{'do': name + ': ' + entry['deliverable'] + ' ' + ' '.join(entry['checks']),
                   'expect': 'Stored exact-build evidence; related playbooks: ' + ', '.join(entry['playbooks'])}
                  for name, entry in STAGES.items()],
        'pitfalls': [
            'An available tool, passing synthetic probe or merged inventory PR does not establish working native replacement.',
            'Discover tool schemas and worker readiness first. Use start_job for long native operations and preserve IDs instead of launching duplicates.',
            'Keep source changes in the assigned isolated workspace. Publish focused tests and artifacts; deployment and gameplay acceptance remain separate.',
        ],
    }
