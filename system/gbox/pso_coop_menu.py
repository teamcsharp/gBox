"""Bounded menu attempts based on the planner's visible-selection evidence.

These labels are visual model observations, never native cursor proof. Rejecting
an ungrounded confirmation is safer than silently treating intent as selection.
"""
from __future__ import annotations


class MenuProgress:
    LIMIT = 6

    def __init__(self):
        self.previous = {}
        self.key = None
        self.repeats = 0

    def review(self, plan, commands, identity):
        if plan.get('screen') not in ('menu', 'unknown', None):
            self.key, self.repeats, self.previous = None, 0, {}
            return commands[:1], ''
        labels = {k: str(plan.get(k) or '').strip()[:180] for k in
                  ('menu_title', 'selected_option', 'intended_option', 'selection_evidence')}
        chosen = commands[:1]
        reason = ''
        if chosen:
            keys = chosen[0][1]
            if 'a' in keys or 'start' in keys:
                if len(keys) != 1:
                    reason = 'Menu navigation and confirmation must be separate observed actions'
                elif not all(labels.values()):
                    reason = 'Confirmation needs the visible menu, selected option, intended option, and highlight evidence'
                elif labels['selected_option'].casefold() != labels['intended_option'].casefold():
                    reason = 'Move the highlight to the intended option and reobserve before confirming'
        else:
            reason = 'No menu action returned; reobserve the visible selection'
        key = (identity, *(labels[k].casefold() for k in ('menu_title', 'selected_option', 'intended_option')),
               tuple((p, tuple(keys)) for p, keys, _ in chosen))
        self.repeats = self.repeats + 1 if key == self.key else 1
        self.key = key
        if self.repeats >= self.LIMIT:
            reason = 'Six unchanged menu attempts; inspect the visible selection and input delivery'
        self.previous = {**labels, 'attempted_actions': [{'player':p,'keys':list(keys),'secs':secs}
            for p,keys,secs in chosen], 'repeated_attempts':self.repeats, 'withheld_reason':reason,
            'input_delivery_verified':False}
        return ([] if reason else chosen), reason

    @property
    def stalled(self):
        return self.repeats >= self.LIMIT
