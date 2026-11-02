"""Exact 3OE2 shared-runtime access policy; never a campaign completion receipt.

Staged only. Native menu acceptance is still required before deployment.
This unlocks proven area gates and mission availability bits. It does not claim
that every principal/lab conversation flag, mission mode or boss entry is known.
"""
from dataclasses import dataclass
import hashlib
import struct

from .pso_gc_live import GC, dispatcher_lock
from . import pso_coop_mapping as mapping

BITMAP = 0x805127F8
DIFFICULTY = 0x805D5550
EPISODE = 0x805D6060
MODE = 0x805D34B8
VISITED = 0x805D5B50
SET_FLAG = 0x801F469C
SET_DESTINATION = 0x80186A00

# Both branches of 801868A8 / 801867F4: offline MULTI uses the first
# element of each pair, and offline single-player uses the second.
AREA_FLAGS = (0x17, 0x18, 0x20, 0x21, 0x2A, 0x30,
              0x4C, 0x4D, 0x4F, 0x50, 0x52, 0x53)
# Only flags SET by the stock availability builder 8021A05C. The odd
# prerequisite/completion flags 65..95 are deliberately absent.
MISSION_FLAGS = tuple(range(0x64, 0x95, 2)) + (0x9F, 0xA2, 0xA4)
FLAGS = tuple(sorted(set(AREA_FLAGS + MISSION_FLAGS)))
DESTINATIONS = {1: tuple(range(1, 11)), 2: tuple(range(1, 12)) + (16, 17)}
GUARDS = {
    SET_FLAG: (156, '4d5c37b3c907e5f2b687fa02035223c922cab0e3e6afc1837e79604dc3431041'),
    SET_DESTINATION: (60, '20edae6c07e58c1270497cecaae046aecbc6cbe2d1c9ed1cf78d34a7372a270d'),
    0x80186A3C: (124, 'c2b6a43c94abc19f49055b93d54dab292cbba3ba6966badce7a253c57f6ec30f'),
    0x801868A8: (344, '52964a0edaa973127998c0733afd40fa04aba826d9bbd4ca7acbcf2cd8a46ea1'),
    0x801F44BC: (164, '7811989e7a51cf783d1760c5001e3f0b9c6701809230bbeb088ec2072279b244'),
    0x8001E5C8: (8, '03150fdf5a8e6f15b29ca5fa1b6000d0cdac8700baed163cb12bdbd83e02274d'),
}
_SEAL = object()
ATTRIBUTE = '_pso_access_policy_receipt'


def flag_set(bitmap, difficulty, flag):
    if (len(bitmap) != 0x200 or type(difficulty) is not int or difficulty not in range(4)
            or type(flag) is not int or flag not in range(0x400)):
        raise ValueError('Invalid native quest bitmap coordinates')
    return bool(bitmap[difficulty * 0x80 + (flag >> 3)] & (0x80 >> (flag & 7)))


@dataclass
class Receipt:
    seal: object
    adapter: object
    process: object
    environment: dict
    players: tuple
    difficulty: int
    episode: int
    status: str
    details: dict


@dataclass
class Journal:
    seal: object
    adapter: object
    process: object
    receipts: list


def _u32(ad, address):
    return struct.unpack('>I', ad.read_memory(address, 4))[0]


def _check(ad, reader, sid, game, stopped):
    if stopped():
        raise InterruptedError('Access policy stopped before native work')
    environment = mapping._environment(ad, sid, game)
    state = reader.snapshot()
    players = mapping._players(state)
    if (state.get('floor') != 0 or state.get('episode') not in (1, 2)
            or type(state.get('difficulty')) is not int or state['difficulty'] not in range(4)
            or state.get('difficulty_verified') is not True):
        raise ValueError('Access policy requires both initialized players in verified town')
    if (_u32(ad, MODE) != 2 or _u32(ad, DIFFICULTY) != state['difficulty']
            or _u32(ad, EPISODE) != state['episode'] - 1):
        raise ValueError('Native offline MULTI/episode/difficulty binding differs')
    for address, (length, expected) in GUARDS.items():
        if hashlib.sha256(ad.read_memory(address, length)).hexdigest() != expected:
            raise ValueError(f'Exact access-policy executable differs at {address:#x}')
    for slot in (0, 1):
        pointer = GC(ad, slot, pin_player=True).check(require_probe=False)
        if pointer != int(players[slot][1], 16):
            raise ValueError('Native player changed during access-policy proof')
    fresh = reader.snapshot()
    if (mapping._players(fresh) != players or fresh.get('floor') != 0
            or fresh.get('episode') != state['episode'] or fresh.get('difficulty') != state['difficulty']):
        raise ValueError('Native state changed during access-policy proof')
    if stopped() or mapping._environment(ad, sid, game) != environment:
        raise InterruptedError('Access-policy binding changed before native work')
    return environment, players, state['difficulty'], state['episode']


def apply_once(ad, reader, sid, game, stopped):
    """Called only by an already-started controller in stable town.

    Uses the existing serialized game-thread queue, including native OR setters,
    and never starts a bot or saves a card. Interrupted/unknown batches are not
    retried on the same live process. A fresh launch requires new full proof.
    """
    with dispatcher_lock(ad):
        binding = _check(ad, reader, sid, game, stopped)
        journal = getattr(ad, ATTRIBUTE, None)
        if not (isinstance(journal, Journal) and journal.seal is _SEAL
                and journal.adapter is ad and journal.process is getattr(ad, 'proc', None)):
            journal = Journal(_SEAL, ad, getattr(ad, 'proc', None), [])
            setattr(ad, ATTRIBUTE, journal)
        environment, players, difficulty, episode = binding
        # A partly acknowledged native batch poisons automatic retry for this
        # process, even if a later Start selects another episode or difficulty.
        blocked = next((r for r in journal.receipts if r.status != 'applied_readback_verified'), None)
        if blocked is not None:
            return dict(blocked.details, status=blocked.status, repeated=True,
                        blocked_by_prior_outcome=True)
        previous = next((r for r in journal.receipts if
                         (r.environment, r.difficulty, r.episode) == (environment, difficulty, episode)), None)
        before = ad.read_memory(BITMAP, 0x200)
        if len(before) != 0x200:
            raise ValueError('Short native quest bitmap')
        visited_before = _u32(ad, VISITED)
        floors = DESTINATIONS[episode]
        wanted = sum(1 << (floor - 1) for floor in floors)
        missing_flags = [flag for flag in FLAGS if not flag_set(before, difficulty, flag)]
        missing_floors = [floor for floor in floors if not visited_before & (1 << (floor - 1))]
        if previous is not None and not missing_flags and not missing_floors:
            # The old actor pointers grant no authority. _check just proved the
            # current two actors, and the current native bitmap/mask was reread.
            if _check(ad, reader, sid, game, stopped) != binding:
                raise ValueError('Native state changed during access-policy revalidation')
            previous.players = players
            return dict(previous.details, status=previous.status, repeated=True,
                        fresh_access_readback_verified=True)
        if previous is None and len(journal.receipts) >= 16:
            raise ValueError('Access-policy environment history exceeded its process bound')
        calls = [(SET_FLAG, difficulty, flag) for flag in missing_flags]
        calls += [(SET_DESTINATION, floor) for floor in missing_floors]
        details = dict(episode=episode, difficulty=difficulty, requested_flags=list(FLAGS),
                       requested_destinations=list(floors), native_calls=len(calls),
                       before_bitmap_sha256=hashlib.sha256(before).hexdigest(),
                       before_visited=visited_before, completion_credit_awarded=False,
                       completion_verified=False, native_menu_acceptance_verified=False,
                       principal_lab_conversation_flags_verified=False,
                       all_missions_available_in_offline_multi_verified=False,
                       shared_runtime_bitmap=True, card_saved=False)
        receipt = Receipt(_SEAL, ad, getattr(ad, 'proc', None), environment, players,
                          difficulty, episode, 'pending', details)
        if previous is not None:
            journal.receipts.remove(previous)
        journal.receipts.append(receipt)
        try:
            native = GC(ad, 0, pin_player=True)
            for start in range(0, len(calls), 20):
                if _check(ad, reader, sid, game, stopped) != binding:
                    raise ValueError('Native access-policy state changed during application')
                # The native function itself ORs each bit; no host read/modify/write race.
                native.call(calls[start:start + 20])
            if _check(ad, reader, sid, game, stopped) != binding:
                raise ValueError('Native access-policy state changed before readback')
            after = ad.read_memory(BITMAP, 0x200)
            visited_after = _u32(ad, VISITED)
            if any(not flag_set(after, difficulty, flag) for flag in FLAGS) or visited_after & wanted != wanted:
                raise RuntimeError('Native access-policy readback incomplete')
            # Existing bits may be added by the game; no preexisting bit may disappear.
            if any(old & new != old for old, new in zip(before, after)) or visited_before & visited_after != visited_before:
                raise RuntimeError('Native progress changed unexpectedly during access policy')
            receipt.status = 'applied_readback_verified'
            receipt.details.update(after_bitmap_sha256=hashlib.sha256(after).hexdigest(),
                                   after_visited=visited_after)
        except Exception as error:
            receipt.status = 'interrupted' if isinstance(error, InterruptedError) else 'outcome_unknown'
            receipt.details['error'] = type(error).__name__ + ': ' + str(error)[:250]
            raise
        return dict(receipt.details, status=receipt.status, repeated=False)
