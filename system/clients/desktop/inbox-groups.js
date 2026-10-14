// #1788: the inbox shows automated tickets as one collapsible entry per kind (launch failures, readiness checks,
// session-observer and gap reports, agent-message mirrors, scheduled reviews, other automation) with a count and the
// newest time, so operator-written requests and build reports read as the list. Presentation only: nothing is closed,
// hidden or deleted, and expanding a group shows every ticket in it. gbox/inbox.py group_key() keeps the same rules.
(function (root) {
  const LABELS = {
    launch_failure: 'Launch failures',
    readiness: 'Character replacement readiness',
    observer: 'Session observer and gap reports',
    agent_message: 'Agent messages',
    review: 'Scheduled request reviews',
    automation: 'Other automated reports',
  };
  const OPERATOR_SOURCES = new Set(['chat', 'app', 'gbox-chat']);
  function groupKey(r) {
    if (!r) return null;
    const title = String(r.title || ''), body = String(r.body || r.title || '').trimStart(), ctx = r.context || {};
    if (/^build report\b/i.test(title)) return null;                     // build reports stay top level
    if (ctx.launch_failure || /^launch failed:/i.test(title)) return 'launch_failure';
    if (/^character replacement readiness\b/i.test(title)) return 'readiness';
    if (body.startsWith('<agent-message') || body.startsWith('<task-notification')) return 'agent_message';
    if (body.startsWith('gBox request review')) return 'review';
    if (r.source === 'gap' || /^session (observation|models)\b/i.test(title)) return 'observer';
    if (OPERATOR_SOURCES.has(r.source) && (r.author || 'operator') === 'operator' && !r.automated) return null;
    if (r.source === 'automation' || r.automated) return 'automation';
    return null;
  }
  // list: requests newest first. Returns entries in the same order: {type: 'request', request} or {type: 'group', key,
  // label, items (newest first), count, pending, newest (epoch s), latest (the newest request)}. A group takes the place
  // of its newest member; a kind with fewer than `min` members stays as plain requests.
  function group(list, { min = 2, pending = r => r.status !== 'done' } = {}) {
    const items = list || [], keys = items.map(groupKey), counts = new Map();
    keys.forEach(k => { if (k) counts.set(k, (counts.get(k) || 0) + 1); });
    const out = [], groups = new Map();
    items.forEach((r, i) => {
      const k = keys[i];
      if (!k || counts.get(k) < min) { out.push({ type: 'request', request: r }); return; }
      let g = groups.get(k);
      if (!g) { g = { type: 'group', key: k, label: LABELS[k], items: [] }; groups.set(k, g); out.push(g); }
      g.items.push(r);
    });
    for (const g of groups.values()) {
      g.count = g.items.length;
      g.pending = g.items.filter(pending).length;
      g.latest = g.items.reduce((a, r) => ((r.created || 0) > (a.created || 0) ? r : a), g.items[0]);
      g.newest = g.latest.created || 0;
    }
    return out;
  }
  const api = { LABELS, groupKey, group };
  root.GBoxInboxGroups = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(globalThis);
