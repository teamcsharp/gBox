"""Bounded menu attempts with independent evidence for the PSO license screen.

Menu presses are ~0.3 s HELD deflections (2026-11-04, verified live on lilspark: the main menu ignores brief
taps; a clear held press registers). Model labels remain advisory. Unknown menu confirmations fail closed; native
in-game actions retain their existing path. Each allowed menu input is singular.
"""
from __future__ import annotations

from .pso_license_menu import observe
from .pso_menu_observer import observe as observe_boot, next_key


def known_menu_command(observation, players=2, *, finish_save=False):
    """Propose one deterministic action only for independently observed menus.

    This proposal grants no authority: MenuProgress.review still requires two
    matching fresh proofs, saved-buddy ordering, requested episode/difficulty,
    native transport/finish state, and the unchanged-menu attempt bound.
    """
    if not observation.get('recognized') or players != 2:
        return None
    menu = observation.get('menu')
    if menu == 'ingame_p2_cancel' and not finish_save:
        return 2, ['b'], .3
    if menu in ('press_start', 'main', 'mode', 'ingame_start', 'quit_confirm', 'after_save'):
        key = next_key(observation, players, finish_save=finish_save is True)
        return (1, [key], .4 if menu == 'press_start' else .3) if key else None
    if menu in ('saved_p1', 'saved_p2', 'verify_saved', 'game_options', 'transporter_forest'):
        player = observation.get('player')
        if type(player) is int and player in (1, 2):
            return player, ['a'], .3
    return None


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
        self._controls_paused = False
        self._pause_identity = None
        self._cancel_frame = None
        self._exit_samples = 0
        self._exit_frame = None
        self._field_clear = 0        # consecutive RAM-field-gameplay frames with NO menu visible (freeze-resume)
        self._field_frame = None
        self._saved_selected = set()
        self.observation = {}

    @property
    def controls_paused(self):
        return self._controls_paused

    def observe_frame(self, frame, *, native_gameplay=False, identity=None):
        """Pause native pad control before probing/moving under a visible menu.

        Phase 14 alone does not prove the menu closed. After a permitted B,
        require two observations of both demonstrated gameplay HUDs, or a
        verified native phase/area transition. Unknown transitions stay paused.
        """
        observed = observe_boot(frame)
        license_menu = observe(frame)
        self.observation = license_menu if license_menu.get('recognized') else observed
        area = tuple(identity[:3]) if isinstance(identity, (tuple, list)) and len(identity) >= 3 else None
        recognized_menu = bool(license_menu.get('recognized') or observed.get('recognized'))
        field_now = bool(native_gameplay and area and area[0] == 14 and area[2] not in (None, 0))
        visible = bool(recognized_menu or observed.get('menu_visible'))
        # OPERATOR FREEZE FIX (2026-11-03): on a RAM-confirmed FIELD floor (phase 14,
        # floor > 0), a weak HUD-only "menu_visible" with NO recognized menu layout must
        # NOT freeze play - a boot/title/license layout cannot legitimately be on a real
        # field floor, so trust RAM and keep navigating/fighting. A genuinely recognized
        # in-game menu still pauses (handled by the menu path + the warp backstop).
        if visible and field_now and not recognized_menu:
            visible = False
        if visible:
            if not self._controls_paused:
                self._pause_identity = area
            self._controls_paused = True
            self._exit_samples = 0
            self._exit_frame = None
        elif self._controls_paused:
            changed_area = bool(native_gameplay and area and area[0] == 14 and
                self._pause_identity and area != self._pause_identity and
                all(value is not None for value in area))
            exit_visible = bool(native_gameplay and self._cancel_frame and
                observed.get('gameplay_visible') and observed.get('frame_sha256') != self._cancel_frame)
            if not exit_visible:
                self._exit_samples, self._exit_frame = 0, None
            elif observed.get('frame_sha256') != self._exit_frame:
                self._exit_samples += 1
                self._exit_frame = observed['frame_sha256']
            # OPERATOR FREEZE FIX (2026-11-03): PSO field play is RAM-driven. If RAM now
            # confirms verified FIELD gameplay (phase 14, a real floor > 0) and the frame
            # shows the gameplay HUD with NO menu visible, the pause latch was a transient
            # or now-closed menu (there was no B-cancel, so _cancel_frame is None and the
            # exit-sample path can never fire). Resume nav/combat after two stable gameplay
            # frames instead of standing frozen until the floor changes - that latch was
            # the "characters standing still for ~85s until the warp" the operator saw.
            field_resume = bool(native_gameplay and area and area[0] == 14 and
                area[2] not in (None, 0) and not visible and observed.get('gameplay_visible'))
            if not field_resume:
                self._field_clear, self._field_frame = 0, None
            elif observed.get('frame_sha256') != self._field_frame:
                self._field_clear += 1
                self._field_frame = observed.get('frame_sha256')
            if changed_area or self._exit_samples >= 2 or self._field_clear >= 2:
                self._controls_paused = False
                self._pause_identity = self._cancel_frame = None
                self._exit_samples = self._field_clear = 0
                self._exit_frame = self._field_frame = None
        return self._controls_paused

    def review(self, plan, commands, identity, *, frame=None, fresh_frame=None, native_gameplay=False,
               finish_save=False, target_episode=None, target_difficulty=None):
        observed = observe(frame)
        current = observe(fresh_frame)
        known = observed['recognized']
        boot = observe_boot(frame) if not known and not current['recognized'] else {}
        fresh_boot = observe_boot(fresh_frame) if boot else {}
        boot_known = bool(boot.get('recognized') or fresh_boot.get('recognized'))
        menu_visible = bool(boot.get('menu_visible') or fresh_boot.get('menu_visible'))
        menu_screen = plan.get('screen') in ('menu', 'unknown', None)
        if known or current['recognized'] or boot_known or menu_visible or plan.get('screen') == 'menu':
            if not self._controls_paused:
                self._pause_identity = tuple(identity[:3]) if isinstance(identity, (tuple, list)) and len(identity) >= 3 else None
            self._controls_paused = True
        if not known and not current['recognized'] and not boot_known and not menu_visible and not menu_screen and native_gameplay and not self.controls_paused:
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
                    chosen = [(1, ['up'], .3)]
                    self._license_up = (identity, current['frame_sha256'])
            elif chosen[0][1] != ['a']:
                reason = 'License Agree is independently selected; only a separate A confirmation is permitted'
            elif self._license_up is not None and self._license_up[0] == identity and (
                    current['frame_sha256'] == self._license_up[1] or
                    observed['frame_sha256'] == self._license_up[1]):
                reason = 'Require a fresh changed selection frame after the license UP'
            else:
                chosen = [(1, ['a'], .3)]
        elif boot_known:
            signature = lambda value: (value.get('menu'), value.get('selected'), value.get('option_index'),
                                       value.get('player'), value.get('observed_episode'), value.get('observed_difficulty'))
            current = fresh_boot
            if not boot.get('recognized') or not current.get('recognized') or signature(boot) != signature(current):
                reason = 'Boot menu or selection changed; plan again from a fresh frame'
            elif current.get('menu') == 'press_start':
                if chosen and (chosen[0][0] != 1 or chosen[0][1] not in (['start'], ['a'])):
                    reason = 'Observed title prompt requires one separate player-one Start'
                else:
                    chosen = [(1, [next_key(current, self.players)], .4)]
                    self._saved_selected.clear()
                    self._license_up = None
            elif current.get('menu') in ('saved_p1', 'saved_p2', 'verify_saved', 'game_options'):
                owner = current.get('player')
                if chosen and (chosen[0][0] != owner or len(chosen[0][1]) != 1):
                    reason = 'Saved campaign menu requires one action from its independently observed player'
                elif current['menu'] == 'saved_p2' and 1 not in self._saved_selected:
                    reason = 'Verify the saved player-one selection before selecting player two'
                elif current['menu'] == 'verify_saved' and self._saved_selected != {1, 2}:
                    reason = 'Both saved buddy identities must be independently selected before ready confirmation'
                elif current['menu'] == 'game_options' and not (
                        type(target_episode) is int and target_episode in (1, 2) and
                        type(target_difficulty) is int and target_difficulty in range(4) and
                        current.get('observed_episode') == target_episode and
                        current.get('observed_difficulty') == target_difficulty):
                    reason = 'Observed episode and difficulty must match the trusted requested campaign settings'
                else:
                    chosen = [(owner, ['a'], .3)]
                    if current['menu'] == 'saved_p1':
                        self._saved_selected = {1}
                    elif current['menu'] == 'saved_p2':
                        self._saved_selected.add(2)
            elif current.get('menu') == 'transporter_forest':
                area = tuple(identity[:3]) if isinstance(identity, (tuple, list)) and len(identity) >= 3 else None
                if (self.players != 2 or not native_gameplay or area != (14, 1, 0) or
                        type(target_episode) is not int or target_episode != 1 or finish_save is True):
                    reason = 'Forest entry requires verified two-player Episode I town play and the trusted Episode I goal'
                elif chosen and (chosen[0][0] != 2 or chosen[0][1] != ['a']):
                    reason = 'Observed Forest destination requires a separate player-two A confirmation'
                else:
                    chosen = [(2, ['a'], .3)]
            elif current.get('menu') == 'ingame_p2_cancel':
                if self.players != 2 or not native_gameplay or finish_save is True:
                    reason = 'Observed player-two field panel only permits normal cancellation'
                elif chosen and (chosen[0][0] != 2 or chosen[0][1] != ['b']):
                    reason = 'Observed lower-view panel requires one separate player-two B'
                else:
                    chosen = [(2, ['b'], .3)]
                    self._cancel_frame = current.get('frame_sha256')
                    self._exit_samples = 0
                    self._exit_frame = None
            elif current.get('menu') in ('ingame_start', 'quit_confirm', 'after_save'):
                safe = next_key(current, self.players, finish_save=finish_save is True)
                if chosen and (chosen[0][0] != current.get('player') or len(chosen[0][1]) != 1):
                    reason = 'Observed split-screen menu requires a separate player-one action'
                elif safe is None:
                    reason = 'After-save navigation requires the native campaign completion state'
                else:
                    chosen = [(1, [safe], .3)]
                    if current['menu'] == 'after_save':
                        self._saved_selected.clear()
                    if safe == 'b':
                        self._cancel_frame = current.get('frame_sha256')
                        self._exit_samples = 0
                        self._exit_frame = None
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
                    chosen = [(1, [safe], .3)]
                    if current.get('menu') in ('main', 'mode'):
                        self._saved_selected.clear()
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
