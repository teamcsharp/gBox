"""Apply the authorized access policy from an existing isolated co-op controller."""
from .pso_coop_unlock import apply_once
from .registry import Unsupported


class AccessPolicy:
    def __init__(self, ad, reader, inputs, sid, game, stopped, invalidate, stats):
        self.ad, self.reader, self.inputs = ad, reader, inputs
        self.sid, self.game, self.stopped = sid, game, stopped
        self.invalidate, self.stats = invalidate, stats
        self.checked = None
        authorization = getattr(ad, '_pso_coop_new_card', {}) or {}
        self.enabled = authorization.get('isolated') is True and bool(authorization.get('path'))

    def step(self, state, *, mapped, menu_paused, waiting):
        """True means reobserve before any next controller/model input.

        Called after the ordinary two-controller mapping proof and menu guard.
        The native helper independently revalidates process, card, pad config,
        both actors and all code guards. It owns the no-retry queue journal.
        """
        if not self.enabled:
            return False
        players = state.get('players') or {}
        town = (state.get('verified') is True and state.get('phase') == 14 and
                not state.get('travelling') and state.get('floor') == 0 and set(players) == {1, 2})
        if not town:
            self.checked = None
            self.stats['access_policy_state'] = 'waiting_for_verified_town'
            return False
        if not mapped or menu_paused or waiting:
            return False
        key = (state.get('episode'), state.get('difficulty'),
               tuple((slot, players[slot].get('ptr')) for slot in (1, 2)))
        if key == self.checked:
            return False
        self.invalidate()
        self.inputs.release()
        if self.stopped():
            raise InterruptedError('Access policy stopped before application')
        self.stats.update(action='applying_verified_area_access', access_policy_state='checking')
        try:
            receipt = apply_once(self.ad, self.reader, self.sid, self.game, self.stopped)
        except Exception as error:
            if isinstance(error, InterruptedError) and self.stopped():
                raise
            self.stats.update(access_policy_state='needs_operator', access_policy_error=str(error),
                              campaign_state='needs_operator', ok=False)
            # A native timeout is not a planner/network failure and may not enter
            # the controller's automatic transient retry path.
            raise Unsupported('PSO area-access policy stopped: ' + str(error)) from error
        self.stats['access_policy'] = receipt
        self.stats['access_policy_state'] = receipt.get('status', 'unknown')
        if receipt.get('status') != 'applied_readback_verified':
            self.stats.update(campaign_state='needs_operator', ok=False)
            raise Unsupported('PSO area-access native outcome requires inspection; no automatic retry')
        self.checked = key
        self.stats.update(access_native_readback_verified=True,
                          access_destination_menu_verified=False,
                          principal_lab_conversation_flags_verified=False,
                          all_missions_available_in_offline_multi_verified=False)
        return True
