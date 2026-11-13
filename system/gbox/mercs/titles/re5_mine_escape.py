"""One manual click: native flash cover, armed mines, then observed hazard escape."""
import time


def execute(ctl, count, *, ring, allow_unverified, allowed, stats, request_id, round_id):
    from .re5_switch_native import Unavailable
    owner = ctl.ready()

    def current():
        return allowed() and ctl.ready() == owner

    if not current():
        raise Unavailable('mine escape request changed before execution')
    flash = None
    if ring:
        flash = ctl.grenade_ring('flash', count=5, radius_cm=600, inner_cm=400,
                                 expand=False, ripple_ms=0, expected=owner, allowed=current)
        if flash.get('state') != 'confirmed' or flash.get('verified') is not True:
            return {'op': 'proximity_mine_ring', 'state': 'uncertain', 'verified': False,
                    'reason': 'Flash cover was not confirmed; mines were not deployed.',
                    'requested': count, 'placed': 0, 'armed': 0, 'flash': flash}
        if stats is not None:
            stats['native_flash_confirmed_at'] = time.time()
    if not current():
        return {'op': 'proximity_mine_ring' if ring else 'proximity_mine_drop',
                'state': 'uncertain', 'verified': False, 'requested': count, 'placed': 0, 'armed': 0,
                'reason': 'Player or round changed after flash cover; mines were not deployed.', 'flash': flash}
    result = ctl.proximity_mines(count, allow_unverified=allow_unverified, allowed=current, expected=owner)
    if flash is not None:
        result.update(flash=flash, flash_detonated=flash.get('detonated', 0))
    # The native arming lifecycle (or a witnessed trigger) is mandatory, not just
    # a successful factory call. Preserve partial results and never replay.
    if result.get('state') == 'confirmed' and (
            result.get('placed') != count or result.get('armed', 0) + result.get('triggered', 0) < count):
        result.update(state='uncertain', verified=False, reason='Not every mine was observed armed or triggered.')
    if stats is not None:
        stats['proximity_mines_last'] = result
        stats['proximity_mines_placed'] = stats.get('proximity_mines_placed', 0) + int(result.get('placed') or 0)
        if current() and result.get('mines'):
            # Combat thread alone chooses a mesh-valid escape direction. No
            # neutral input or equipment handover in this background worker.
            queue = stats.setdefault('native_mine_force_receipts', [])
            queue.append({'id': request_id, 'owner': [round_id, *owner], 'receipt': result})
            del queue[:-8]
    return result
