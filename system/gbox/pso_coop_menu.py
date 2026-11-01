"""Bounded menu attempts with independent evidence for the PSO license screen.

Model labels remain advisory. Unknown menu confirmations fail closed; native
in-game actions retain their existing path. Each allowed menu input is singular.
"""
from __future__ import annotations

from .pso_license_menu import observe
from .pso_menu_observer import observe as observe_boot, next_key


class MenuProgress:
    LIMIT = 6

    def __init__(self, players=1):
        if type(players) is not int or players not in (1, 2):
            raise ValueError('Menu setup supports one or two players')
        self.players = players
        self.previous = {}
        self.key = None
        self.repeats = 0
        self._license_up = None

    def review(self, plan, commands, identity, *, frame=None, fresh_frame=None, native_gameplay=False):
        observed = observe(frame)
        current = observe(fresh_frame)
        known = observed['recognized']
        boot = observe_boot(frame) if not known and not current['recognized'] else {}
        fresh_boot = observe_boot(fresh_frame) if boot else {}
        boot_known = bool(boot.get('recognized') or fresh_boot.get('recognized'))
        menu_screen = plan.get('screen') in ('menu', 'unknown', None)
        if not known and not current['recognized'] and not boot_known and not menu_screen and native_gameplay:
            self.key, self.repeats, self.previous = None, 0, {}
            self._license_up = None
            return commands, ''
        labels = {k: str(plan.get(k) or '').strip()[:180] for k in
                  ('menu_title', 'selected_option', 'intended_option', 'selection_evidence')}
        chosen = commands[:1]
        reason = ''
        if known or current['recognized']:
            if not known or not current['recognized'] or observed['selected'] != current['selected']:
                reason = 'License selection changed or became unreadable; plan again from a fresh frame'
            elif not chosen:
                reason = 'No menu action returned; reobserve the visible selection'
            elif chosen[0][0] != 1 or len(chosen[0][1]) != 1:
                reason = 'License navigation and confirmation must be separate player-one actions'
            elif current['selected'] == 'Disagree':
                if chosen[0][1][0] not in ('up', 'a', 'start'):
                    reason = 'License Disagree is selected; only one UP toward Agree is permitted'
                elif self._license_up is not None and self._license_up[0] == identity:
                    reason = 'One license UP was already attempted; require a new frame proving Agree'
                else:
                    chosen = [(1, ['up'], .08)]
                    self._license_up = (identity, current['frame_sha256'])
            elif chosen[0][1] != ['a']:
                reason = 'License Agree is independently selected; only a separate A confirmation is permitted'
            elif self._license_up is not None and self._license_up[0] == identity and (
                    current['frame_sha256'] == self._license_up[1] or
                    observed['frame_sha256'] == self._license_up[1]):
                reason = 'Require a fresh changed selection frame after the license UP'
            else:
                chosen = [(1, ['a'], .08)]
        elif boot_known:
            signature = lambda value: (value.get('menu'), value.get('selected'), value.get('option_index'))
            current = fresh_boot
            if not boot.get('recognized') or not current.get('recognized') or signature(boot) != signature(current):
                reason = 'Boot menu or selection changed; plan again from a fresh frame'
            elif not chosen:
                reason = 'No menu action returned; reobserve the visible selection'
            elif chosen[0][0] != 1 or len(chosen[0][1]) != 1:
                reason = 'Boot menu navigation and confirmation must be separate player-one actions'
            else:
                safe = next_key(current, self.players)
                proposed = chosen[0][1][0]
                if safe is None or (proposed != safe and proposed not in ('a', 'start')):
                    reason = 'Proposed menu action does not match the independently observed offline setup step'
                else:
                    chosen = [(1, [safe], .08)]
                    self._license_up = None  # Independently proven departure from the license dialog.
        elif self._license_up is not None and self._license_up[0] == identity:
            reason = 'License selection is unreadable after UP; withhold input until independently observed'
        elif chosen:
            reason = 'Menu input withheld: independent visible selection is unavailable'
        else:
            reason = 'No menu action returned; reobserve the visible selection'
        key = (identity, current.get('menu'), current.get('selected'),
               tuple((p, tuple(keys)) for p, keys, _ in chosen))
        self.repeats = self.repeats + 1 if key == self.key else 1
        self.key = key
        if self.repeats >= self.LIMIT:
            reason = 'Six unchanged menu attempts; inspect the visible selection and input delivery'
        self.previous = {**labels, 'independent_selection': current,
            'attempted_actions': [{'player':p,'keys':list(keys),'secs':secs} for p,keys,secs in chosen],
            'repeated_attempts':self.repeats, 'withheld_reason':reason, 'input_delivery_verified':False}
        return ([] if reason else chosen), reason

    @property
    def stalled(self):
        return self.repeats >= self.LIMIT
