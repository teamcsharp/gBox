// #1788: automated inbox tickets collapse into one entry per kind; operator requests and build reports stay top level.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { groupKey, group, LABELS } = require('../clients/desktop/inbox-groups.js');

const CASES = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'inbox_groups_cases.json'), 'utf8')).cases;
const DESKTOP = path.join(__dirname, '..', 'clients', 'desktop');
let n = 0;
const req = (title, extra = {}) => ({ id: `r${++n}`, number: n, title, status: 'done', created: 1000 - n, source: 'chat', author: 'operator', ...extra });
const launch = (extra = {}) => req('Launch failed: Dead or Alive 2 on i9-NUC', { source: 'automation', author: 'system', automated: true, context: { launch_failure: true, auto_report: true }, ...extra });

test('every shared case lands in its group (the same table gbox/inbox.py is tested against)', () => {
  for (const c of CASES) assert.equal(groupKey(c.request), c.key, c.request.title);
  for (const c of CASES) if (c.key) assert.ok(LABELS[c.key], `label for ${c.key}`);
});

test('a group takes the place of its newest member with count, pending and newest time; operator requests stay put', () => {
  const list = [req('newest operator ask'), launch({ status: 'in_progress', created: 990 }), req('Build report: x (y): broken', { source: 'app' }),
    launch({ created: 980 }), req('older operator ask'), launch({ status: 'open', created: 970 })];
  const out = group(list);
  assert.deepEqual(out.map(e => e.type === 'group' ? `group:${e.key}` : e.request.title),
    ['newest operator ask', 'group:launch_failure', 'Build report: x (y): broken', 'older operator ask']);
  const g = out[1];
  assert.equal(g.label, 'Launch failures');
  assert.equal(g.count, 3); assert.equal(g.pending, 2); assert.equal(g.newest, 990);
  assert.equal(g.latest, list[1]);
  assert.deepEqual(g.items, [list[1], list[3], list[5]], 'every ticket is kept, newest first');
});

test('nothing is dropped: the entries hold exactly the input requests', () => {
  const list = CASES.map((c, i) => ({ id: `c${i}`, number: i, status: 'open', created: 100 - i, ...c.request }))
    .concat(CASES.map((c, i) => ({ id: `d${i}`, number: 100 + i, status: 'done', created: 50 - i, ...c.request })));
  const ids = group(list).flatMap(e => e.type === 'group' ? e.items.map(r => r.id) : [e.request.id]);
  assert.deepEqual([...ids].sort(), list.map(r => r.id).sort());
});

test('a kind with a single ticket stays a plain entry; min and pending are configurable', () => {
  const lone = [req('ask'), launch()];
  assert.deepEqual(group(lone).map(e => e.type), ['request', 'request']);
  assert.deepEqual(group(lone, { min: 1 }).map(e => e.type), ['request', 'group']);
  const g = group([launch(), launch()], { pending: () => true })[0];
  assert.equal(g.pending, 2);
  assert.deepEqual(group([]), []); assert.deepEqual(group(undefined), []);
});

test('the desktop Requests view loads the grouping and renders groups at top level, unlinked entries and sub-requests', () => {
  const html = fs.readFileSync(path.join(DESKTOP, 'index.html'), 'utf8');
  assert.match(html, /<script src="inbox-groups\.js"><\/script>/);
  assert.match(html, /GBoxInboxGroups\.group\(visibleRoots/);
  assert.match(html, /GBoxInboxGroups\.group\(visibleUnresolved/);
  assert.match(html, /GBoxInboxGroups\.group\(children\.get\(x\.id\)/);
  assert.match(html, /class="req-group" data-group-key=/);
});

test('an open group stays open when its count changes (keyed by kind, not by summary text)', () => {
  const src = fs.readFileSync(path.join(DESKTOP, 'inbox-view.js'), 'utf8');
  assert.match(src, /detail\.dataset\.groupKey \? "group:" \+ detail\.dataset\.groupKey/);
});

// #2801: standing per-game background work leaves the inbox for the Background work view
const { standingKey, standing, STANDING_LABELS } = require('../clients/desktop/inbox-groups.js');
const STANDING = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'inbox_standing_cases.json'), 'utf8')).cases;

test('standing background work is recognised by its context, the same table gbox/inbox.py is tested against', () => {
  for (const c of STANDING) assert.equal(standingKey(c.request), c.key, c.request.title);
  for (const c of STANDING) if (c.key) assert.ok(STANDING_LABELS[c.key], `label for ${c.key}`);
  assert.equal(standing(STANDING.find(c => c.key).request), true);
  assert.equal(standing({ title: 'JSRF not playing', source: 'app', author: 'operator' }), false);
});

test('the Background work view groups by standing kind and keeps every request', () => {
  const list = STANDING.filter(c => c.key).map((c, i) => ({ id: `s${i}`, number: i, status: 'open', created: 100 - i, ...c.request }));
  const out = group(list, { min: 1, key: standingKey, labels: STANDING_LABELS });
  assert.ok(out.every(e => e.type === 'group'));
  assert.deepEqual(out.flatMap(e => e.items.map(r => r.id)).sort(), list.map(r => r.id).sort());
  assert.ok(out.every(e => e.label === STANDING_LABELS[e.key]));
});

test('the desktop inbox, Pending and the badge leave standing work out and list it under Background work', () => {
  const html = fs.readFileSync(path.join(DESKTOP, 'index.html'), 'utf8');
  assert.match(html, /data-request-filter="background"/);
  assert.ok(html.includes('background = r.data.filter(GBoxInboxGroups.standing), all = r.data.filter(x => !GBoxInboxGroups.standing(x))'));
  assert.ok(html.includes('"all", "pending", "completed", "background"'));
});
