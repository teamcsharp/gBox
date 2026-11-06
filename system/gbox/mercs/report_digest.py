"""A digest of the Mercenaries incident reports: what the evidence says, computed rather than narrated.

The operator's rule is that reports exist only for a death, lost health or a missed shot, and that they must drive
improvement. This turns the stored `mercs_round_report` documents into the few numbers that answer "what is going
wrong" without anyone reading 1,800 reports:

* how the rounds ended (died / completed) per title;
* behaviour rates per minute for each outcome, because absolute counts are confounded by how long a round lasted (a died
  round in the sample averaged 233 s against 46 s for a completed one, so only rates compare);
* why reports were or were not opened (the eligibility reasons);
* the enemies the reports have learned about, with the danger each one carries.

Everything is computed from the documents; nothing is asserted that the rows do not support.
"""
from __future__ import annotations

import collections
import json

KIND = 'mercs_round_report'

# Rates are computed from these metric leaves: (group, field, label).
RATE_FIELDS = (
    ('aim', 'shots', 'shots'),
    ('aim', 'hits', 'hits'),
    ('aim', 'misses', 'missed shots'),
    ('aim', 'round_melee', 'melee attacks'),
    ('engagement', 'kills', 'kills'),
    ('survival', 'round_escapes', 'escapes'),
    ('survival', 'round_tablet_misses', 'tablet misses'),
    ('qte', 'qte_presses', 'QTE presses'),
    ('qte', 'resuscitate_presses', 'resuscitations'),
)


def _leaf(data, group, field):
    sub = data.get(group)
    if not isinstance(sub, dict):
        return None
    value = sub.get(field)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def digest(store) -> dict:
    """The numbers behind the incident reports, grouped so a change can be judged against them."""
    rows = store.db.execute('SELECT body FROM docs WHERE kind=?', (KIND,)).fetchall()
    states = collections.Counter()
    outcomes = collections.Counter()
    categories = collections.Counter()
    reasons = collections.Counter()
    titles = collections.defaultdict(lambda: collections.Counter())
    rates = collections.defaultdict(lambda: collections.Counter())        # outcome -> label -> total
    minutes = collections.Counter()                                        # outcome -> summed minutes
    enemies = collections.Counter()
    usable = 0
    for (body,) in rows:
        try:
            doc = json.loads(body)
        except (TypeError, ValueError):
            continue
        state = str(doc.get('state'))
        states[state] += 1
        report = doc.get('report') if isinstance(doc.get('report'), dict) else {}
        title = str(doc.get('title') or report.get('title') or '?')
        if state != 'analysed':
            if doc.get('reason'):
                reasons[str(doc['reason'])[:120]] += 1
            continue
        usable += 1
        outcome = str(report.get('outcome') or '?')
        outcomes[outcome] += 1
        categories[str(report.get('category') or '?')] += 1
        titles[title][outcome] += 1
        metrics = report.get('metrics') if isinstance(report.get('metrics'), dict) else {}
        timer = _leaf(metrics, 'survival', 'timer') or 0.0
        for group, field, label in RATE_FIELDS:
            value = _leaf(metrics, group, field)
            if value is not None:
                rates[outcome][label] += value
        minutes[outcome] += timer / 60.0
        knowledge = report.get('enemy_knowledge')
        if isinstance(knowledge, str):
            for part in knowledge.split(';'):
                name = part.split('(')[0].strip()
                if name and len(name) < 24:
                    enemies[name] += 1
    per_minute = {}
    labels = [label for _, _, label in RATE_FIELDS]
    for outcome in outcomes:                       # every outcome present gets a row, even with no metrics at all
        span = minutes.get(outcome) or 0.0
        totals = rates.get(outcome) or {}
        per_minute[outcome] = {label: (round(totals[label] / span, 2) if span and label in totals else None)
                               for label in labels}
    return {
        'reports': sum(states.values()),
        'analysed': usable,
        'states': dict(states.most_common()),
        'outcomes': dict(outcomes.most_common()),
        'categories': dict(categories.most_common()),
        'titles': {title: dict(counts.most_common()) for title, counts in titles.items()},
        'minutes_analysed': {outcome: round(value, 1) for outcome, value in minutes.items()},
        'per_minute': per_minute,
        'why_no_report': dict(reasons.most_common(8)),
        'enemies_seen': dict(enemies.most_common(12)),
    }
