"""Read-only probe of Sonic Gems Collection (USA) state saves (gamecode G2XE8P).

Everything in this module is grounded in the owned GameCube revision of
Sonic Gems Collection (USA) and was verified against the extracted disc:

  * main.dol sha256 a57a1d15b993a5881b002089d4ed993da4b43f796988abdad981e9b5269675f9
    (2,065,152 bytes) -- the game code at 0x00 is G2XE8P.
  * Ten ``state_us__museumNN.stm`` and six ``state_us__museumNN.stg``
    memory-card saves of 221,248 bytes each (see STATE_SAVE_SHA256).
  * The ``.stm``/``.stg`` files are GameCube memory-card saves, not loose
    assets: the header carries the game code, a banner, a timestamp, the title
    and the operator-editable save comment.

Nothing here writes a save, a ROM or a progress flag. The module exists so an
unlock routine can be revision-guarded: it names the exact header fields the
game writes, the exact slot naming the game uses on disc, and the exact
evidence that is still missing before any writer may run.
"""
from __future__ import annotations

import struct

GAME_ID = 'fc5914e3ddb540c4'
PLATFORM = 'gamecube'
GAME_CODE = 'G2XE8P'
DOL_SHA256 = 'a57a1d15b993a5881b002089d4ed993da4b43f796988abdad981e9b5269675f9'
DOL_SIZE = 2065152
SAVE_SIZE = 221248
STATE_MAGIC = 0xFF02
SLOT_COUNT = 10
CATEGORIES = ('characters', 'hidden_characters', 'modes', 'levels', 'stages',
              'costumes', 'items', 'extras')

# (field, offset, size) of the memory-card save header written by this revision.
HEADER_FIELDS = (
    ('gamecode', 0x00, 6),
    ('magic_word', 0x06, 2),
    ('banner', 0x08, 16),
    ('timestamp', 0x28, 4),
    ('title', 0x40, 32),
    ('comment', 0x60, 32),
)

# Digests of every state save shipped on the owned disc; an unlock routine must
# refuse to write a slot whose current bytes do not match one of these.
STATE_SAVE_SHA256 = {
    'state_us__museum01.stg': '78cbb2ac70fd5103cd5afaae6a9a7c54c984221a3701da08107429ae82077c7b',
    'state_us__museum01.stm': '60e871e8317ad519942d230ceac4511c82ca957506a4fa7dc61e369884735268',
    'state_us__museum02.stg': '3d28c5c4f9bb9580e539dadf665ae74046546e43613ca449411152ff5689173f',
    'state_us__museum02.stm': 'cbf57f7e16cf7d453655debde930f56c2313013a2b514a533094d113a79a97eb',
    'state_us__museum03.stg': '570a11df8004d673422a0cceec079bb5ae9929169f37b93fcaf1443e0340350f',
    'state_us__museum03.stm': '8daf3f0321e3cd0be6e8cac0e6370eef1f713a9b9f0d82e6902d4c14bd9e9c60',
    'state_us__museum04.stg': '2ebd79cac52c07a92abaa68551dc2797fb48037dc1e7f8ad3a659c27f5d26012',
    'state_us__museum04.stm': '1fb1d534b23bffa04e4313022de6596c06c07c16c8cd4e66ce3cf3d14af4d2b2',
    'state_us__museum05.stg': 'a2e97fb68b589b6041b31f5e2015f0bda118d3a1032183fba29ccecdd4c2a26c',
    'state_us__museum05.stm': '400fb80468a0a04efc5b6712fa87f7cd525382b47fd581ac1010c97de0e9b076',
    'state_us__museum06.stg': 'b3a4918a0626b55b38541f78cbaf70c97dfa31a8316e7f5c84de0c81024ff8ec',
    'state_us__museum06.stm': '02d8a349d0409d93059d441d8c51ef97fb7a9cccf99c42349d49e54c6c39fb9b',
    'state_us__museum07.stm': '6af03c616b108b4aa5d8bc608cda285163670d9605d29fd17ee06e84330b77b6',
    'state_us__museum08.stm': '521b1040a2f5313909a3756c613a9a504c2bd9433f4095db55619802f8d65d55',
    'state_us__museum09.stm': '40f96a261fdfa94ed30f07c0acbbab8920091d35c5486935381a80b18425ad4f',
    'state_us__museum10.stm': '0eae91f554301a954b6ebcb04486459d5f9f0627b42c0084906d785d69b73b8b',
}

# main.dol string table entries and the data-segment table that points at them.
# These are the handles the game uses to reach the state slots.
DOL_STRINGS = {
    'STATE_JP\\MUSEUM01.STM': 0x801CD8E0,
    'STATE_US\\MUSEUM01.STM': 0x801CD9D0,
    'STATE_US\\MUSEUM10.STM': 0x801CDAA8,
    'STATE_US\\MUSEUM01.STG': 0x801CE018,
    'LMUSEUM\\DEFTIME.PRS': 0x801CDC27,
    'MODULE/GEMS.STR': 0x801CE1D0,
    'SONICHEROES': 0x801CCB74,
    'SONIC GEMS COLLECTION': 0x801CCBB0,
    'SONIC GEMSB_': 0x801CCBC8,
    'SONIC GEMS_': 0x801CCC1C,
}
DOL_POINTERS = {
    'STATE_JP\\MUSEUM01.STM': 0x801E4C10,
    'STATE_US\\MUSEUM01.STM': 0x801E4C38,
    'STATE_US\\MUSEUM10.STM': 0x801E4C5C,
    'STATE_US\\MUSEUM01.STG': 0x801E4F78,
}


def parse_header(data: bytes) -> dict:
    """Decode the memory-card save header of this revision."""
    if len(data) < 0x80:
        raise ValueError('save block shorter than the 0x80 header')
    out = {}
    for name, off, size in HEADER_FIELDS:
        chunk = data[off:off + size]
        if name == 'magic_word':
            out[name] = struct.unpack('>H', chunk)[0]
        elif name == 'timestamp':
            out[name] = struct.unpack('>I', chunk)[0]
        else:
            out[name] = chunk.decode('ascii', 'replace').rstrip('\x00')
    return out


def looks_like_state_save(data: bytes) -> bool:
    """True when the bytes carry this revision's game code and header magic."""
    if len(data) != SAVE_SIZE:
        return False
    if data[0:6].decode('ascii', 'replace') != GAME_CODE:
        return False
    return struct.unpack('>H', data[0x06:0x08])[0] == STATE_MAGIC


def parse_save_name(name: str):
    """'state_us__museum03.stm' -> {'region': 'us', 'slot': 3, 'kind': 'stm'}.

    None when the name is not a state save of this game.
    """
    if not name.startswith('state_') or '__' not in name:
        return None
    region, rest = name[len('state_'):].split('__', 1)
    if '.' not in rest:
        return None
    stem, ext = rest.rsplit('.', 1)
    ext = ext.lower()
    if ext not in ('stm', 'stg') or not stem.startswith('museum'):
        return None
    digits = stem[len('museum'):]
    if not digits.isdigit():
        return None
    slot = int(digits)
    if not 1 <= slot <= SLOT_COUNT:
        return None
    return {'region': region.lower(), 'slot': slot, 'kind': ext}


def plan_slots(names):
    """Group a disc file listing into the state slots the game manages."""
    slots = {}
    for name in names:
        info = parse_save_name(name)
        if info is None:
            continue
        key = (info['region'], info['slot'])
        slots.setdefault(key, {'region': info['region'], 'slot': info['slot'],
                               'files': {}})
        slots[key]['files'][info['kind']] = name
    return [slots[k] for k in sorted(slots)]


def profile_gate() -> dict:
    """Honest, unverified gate for the Sonic Gems Collection unlock scope."""
    return {
        'verified': False,
        'reason': ('Sonic Gems Collection (USA) G2XE8P: state-save layout is mapped and '
                    'the save digests are pinned, but no unlock writer exists and no '
                    'category entry has been runtime-verified.'),
        'categories': list(CATEGORIES),
        'evidence': {
            'executable': 'main.dol sha256 ' + DOL_SHA256,
            'executable_size': DOL_SIZE,
            'game_code': GAME_CODE,
            'state_saves': len(STATE_SAVE_SHA256),
            'save_layout': 'GameCube memory-card save header (gamecode/magic/banner/'
                           'timestamp/title/comment) followed by game payload',
            'dol_handles': 'main.dol string table 0x801CD8E0..0x801CCC1C and pointer '
                           'table 0x801E4C10..0x801E4F78',
            'disc_assets': 'museum__museum01..12.adx/.sfd, museum__default.prs, '
                           'museum__deftime.prs, museum__mu_new.prs, movie__museum.sfd',
        },
        'blockers': [
            'The per-entry meaning of the state payload is not mapped yet: the 2-byte '
            'records at 0x80 of each .stm are still unclassified (observed byte0 0x81, '
            'byte1 0x7f with 0x9f at scattered offsets).',
            'The category inventory (characters, hidden_characters, modes, levels, '
            'stages, costumes, items, extras) has no verified entry names yet.',
            'No runtime acceptance has been performed: no boot, no character or mode '
            'selection, no second-launch or rollback check.',
        ],
        'next': ('Open the owned main.dol (sha256 ' + DOL_SHA256[:16] + '...) in the '
                 'worker Ghidra project, xref the 0x801E4C10 pointer table to the '
                 'routine that reads and writes the state slots, then map the 0x80+ '
                 'records to categories before any save writer is written.'),
    }
