// #1639 builds on this PC (clients/web/viz/build-local.js): the download icon's states (on this PC / not on this PC /
// downloading / no PC), its menu (Download to this PC, Export…, Open folder, Delete from this PC), the calls, the
// download flow with progress, the Export dialog (formats with "same as the original" first, the folder picker, progress,
// the final path and Show in folder) and where the icon shows: the Mods card's picture corner and the Builds row's end.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const BL = require('../clients/web/viz/build-local.js');
const BA = require('../clients/web/viz/build-actions.js');
const MG = require('../clients/web/viz/mods-gallery.js');
const BV = require('../clients/web/viz/builds.js');

const B = { key: 'zelda/link_sonic', name: 'link_sonic', game_id: 'zelda', mod_title: 'Link as Sonic', game_title: 'Zelda (USA)',
            where: [{ where: 'spark', label: 'Spark collection' }] };
const HERE = { ...B, key: 'zelda/here_build', name: 'here_build', where: [{ where: 'spark' }, { where: 'pc', node: 'MYPC', label: 'MYPC (local copy)' }] };
const FORMATS = { source: 'Zelda (USA).gcz', image: 'Zelda (USA).iso', game_title: 'Zelda (USA)', folder: false, formats: [
  { id: 'same', label: 'Same format as the original (.gcz: Dolphin GCZ (compressed))', ext: '.gcz', kind: 'gcz', default: true },
  { id: 'plain', label: 'Plain image (.iso)', ext: '.iso', kind: 'copy' },
  { id: 'patch', label: 'Patch only (BPS, + IPS / xdelta)', ext: '.bps', kind: 'patch', note: 'needs your original game file on this PC' },
  { id: 'zip', label: 'Zip of the .iso files', ext: '.zip', kind: 'zip' }] };

test('icon states: no PC, not on this PC, on this PC (heartbeat list, the row\'s where, what this view just did), downloading', () => {
  assert.equal(BL.stateOf(B, {}).state, 'none');
  assert.equal(BL.stateOf(B, { here: 'MYPC' }).state, 'off');
  assert.equal(BL.stateOf(HERE, { here: 'MYPC' }).state, 'here', 'a Builds row: its where list names this PC');
  assert.equal(BL.stateOf(HERE, { here: 'MYPC', local: {} }).state, 'off', 'the heartbeat list wins over a stale row');
  assert.deepEqual(BL.stateOf(B, { here: 'MYPC', local: { [B.key]: { staged: true } } }), { state: 'here', staged: true, exporting: null });
  assert.equal(BL.stateOf(B, { here: 'MYPC', local: {}, over: new Map([[B.key, true]]) }).state, 'here', 'just downloaded');
  assert.equal(BL.stateOf(HERE, { here: 'MYPC', over: new Map([[HERE.key, false]]) }).state, 'off', 'just deleted here');
  assert.deepEqual(BL.stateOf(B, { here: 'MYPC', job: { op: 'download', pct: 41.6, msg: 'Fetching 10/24 MB' } }), { state: 'busy', pct: 42, msg: 'Fetching 10/24 MB' });
  assert.equal(BL.hereOf({ here: 'auto' }), '', 'a plain browser has no PC behind it');
});

test('the icon: a filled check / an arrow / a ring with the percent, a ▾ for the menu, greyed out without a PC', () => {
  const off = BL.iconHTML({ state: 'off' }, { here: 'MYPC' });
  assert.match(off, /<span class="bl" data-bl-state="off"><button class="bl-main bl-off" type="button" data-bl="main" title="Not on this PC: click to download it here/);
  assert.match(off, /aria-label="Download to this PC"><svg[^>]*><path d="M12 3v11/);
  assert.match(off, /data-bl="menu" aria-haspopup="menu" aria-expanded="false"/);
  const here = BL.iconHTML({ state: 'here' }, { open: true, here: 'MYPC' });
  assert.match(here, /bl-main bl-here[^>]*title="On this PC: it plays at once, offline\.[^"]*this PC: MYPC"[^>]*aria-label="On this PC"><svg[^>]*><circle cx="12" cy="12" r="10" fill="currentColor"\/>/);
  assert.match(here, /aria-expanded="true"/);
  const busy = BL.iconHTML({ state: 'busy', pct: 42, msg: 'Fetching 10/24 MB' });
  assert.match(busy, /aria-label="Downloading 42%"/);
  assert.match(busy, /stroke-dasharray="23\.75 56\.55"/);
  assert.match(busy, /<span class="bl-pct">42%<\/span>/);
  assert.match(busy, /title="Downloading to this PC: 42% · Fetching 10\/24 MB"/);
  const none = BL.iconHTML({ state: 'none' });
  assert.equal((none.match(/ disabled>/g) || []).length, 2, 'both buttons disabled');
  assert.match(none, /Open gBox on your PC to download builds to it/);
});

test('the menu: Download / Export… / Open folder / Delete from this PC by state', () => {
  const off = BL.menuHTML(B, { state: 'off' }, 'MYPC');
  assert.match(off, /<div class="bl-mh">Not on this PC \(MYPC\)<\/div>/);
  assert.match(off, /data-bl="download"[^>]*>⬇ Download to this PC</);
  assert.match(off, /data-bl="export" title="[^"]*\(downloads it first\)">⇪ Export…</);
  assert.match(off, /data-bl="open"[^>]*disabled>📂 Open folder</);
  assert.match(off, /data-bl="delete"[^>]*disabled>🗑 Delete from this PC</);
  const here = BL.menuHTML(B, { state: 'here', staged: true }, 'MYPC');
  assert.match(here, /On this PC \(MYPC\) · staged copy/);
  assert.ok(!here.includes('data-bl="download"'), 'nothing to download');
  assert.match(here, /data-bl="open" title="Show this build&#39;s folder[^"]*">📂 Open folder</);
  assert.match(here, /data-bl="delete" title="Remove only this PC&#39;s copy: the Spark collection and other PCs keep theirs">🗑 Delete from this PC</);
  assert.match(BL.menuHTML(B, { state: 'busy', pct: 7 }), /data-bl="download"[^>]*disabled>⬇ Downloading 7%…</);
});

test('the calls: download / locate / export queue build_local on this PC; formats', () => {
  assert.deepEqual(BL.downloadCall(B, 'MYPC'), { path: '/api/builds/zelda/link_sonic/local', body: { op: 'download', node: 'MYPC' } });
  assert.deepEqual(BL.locateCall(B, 'MYPC').body, { op: 'locate', node: 'MYPC' });
  assert.deepEqual(BL.exportCall(B, 'MYPC', '  D:\\Exports ', 'same'),
    { path: '/api/builds/zelda/link_sonic/local', body: { op: 'export', node: 'MYPC', dest: 'D:\\Exports', format: 'same', label: 'Link as Sonic' } });
  assert.equal(BL.formatsPath(B), '/api/builds/zelda/link_sonic/formats');
});

test('the export dialog: same format as the original first and checked, notes, the picker only in the app', () => {
  const html = BL.exportDialogHTML(B, FORMATS, { dest: 'D:\\Exports', canPick: true, here: 'MYPC' });
  assert.match(html, /⇪ Export “Link as Sonic”/);
  assert.match(html, /<tr><th>Original<\/th><td><code>Zelda \(USA\)\.gcz<\/code><\/td><\/tr>/);
  assert.match(html, /<input type="radio" name="bx-format" value="same" checked> <span><span class="bx-t">Same format as the original \(\.gcz: Dolphin GCZ \(compressed\)\) <span class="bx-def">default<\/span><\/span>/);
  const order = ['same', 'plain', 'patch', 'zip'].map(v => html.indexOf(`value="${v}"`));
  assert.deepEqual([...order].sort((a, b) => a - b), order);
  assert.match(html, /<small class="bx-note">needs your original game file on this PC<\/small>/);
  assert.match(html, /value="D:\\Exports"/);
  assert.match(html, /data-bx="pick">Choose…<\/button>/);
  const typed = BL.exportDialogHTML(B, null, { canPick: false });
  assert.ok(!typed.includes('data-bx="pick"') && typed.includes('placeholder="e.g. D:\\Games\\Exports"'));
  assert.match(typed, /value="same" checked> <span><span class="bx-t">Same format as the original/, 'formats not loaded yet: same is still the default');
  const dis = BL.exportDialogHTML(B, { formats: [FORMATS.formats[0], { id: 'patch', label: 'Patch', disabled: 'a patch needs a single-image build' }] });
  assert.match(dis, /value="patch" disabled> <span><span class="bx-t">Patch<\/span><small class="bx-note">a patch needs a single-image build<\/small>/);
  const res = BL.resultHTML({ label: 'Same format as the original (.chd)', main: 'D:\\Exports\\Crazy Taxi - Sonic\\Crazy Taxi (USA).gdi', dir: 'D:\\Exports\\Crazy Taxi - Sonic',
                              notice: "chdman isn't installed on this PC", files: [{ path: 'Crazy Taxi (USA).gdi', size: 100 }, { path: 'track01.bin', size: 2 * 2 ** 20 }] }, { canShow: true });
  assert.match(res, /✓ Exported · Same format as the original \(\.chd\)/);
  assert.match(res, /<code data-bx-path>D:\\Exports\\Crazy Taxi - Sonic\\Crazy Taxi \(USA\)\.gdi<\/code>/);
  assert.match(res, /⚠ chdman isn&#39;t installed on this PC/);
  assert.match(res, /<li><code>track01\.bin<\/code> <span class="mut">2\.0 MB<\/span><\/li>/);
  assert.match(res, /data-bx="show">📂 Show in folder</);
  assert.ok(!BL.resultHTML({ dir: 'x' }).includes('data-bx="show"'));
});

// a job API: each job answers queued -> running (progress) -> succeeded with `out`
function jobsApi(extra = {}) {
  const calls = [], jobs = new Map();
  let n = 0;
  const api = async (p, body, method) => {
    calls.push([method || 'GET', p, body]);
    if (p.startsWith('/api/builds/local?')) return { node: 'MYPC', builds: extra.local || {} };
    if (p.endsWith('/formats')) return FORMATS;
    if (p.endsWith('/local')) {
      if (extra.reject) throw new Error(extra.reject);
      const id = 'j' + (++n);
      jobs.set(id, { op: body.op, step: 0 });
      return { job_id: id, state: 'queued', node: body.node };
    }
    const m = p.match(/^\/api\/jobs\/(.+)$/);
    if (m) {
      const j = jobs.get(m[1]); j.step++;
      if (j.step === 1) return { id: m[1], state: 'queued' };
      if (j.step === 2) return { id: m[1], state: 'running', progress: { pct: 55, msg: 'Fetching mod link_sonic: 50/91 MB' } };
      if (extra.fail) return { id: m[1], state: 'failed', error: extra.fail };
      const out = j.op === 'download' ? { here: true, folder: 'link_sonic', size: 95420416, files: 1 }
        : j.op === 'locate' ? { here: true, dir: 'C:\\gbox\\cache\\mods\\zelda\\link_sonic' }
        : { dir: 'D:\\Exports\\Zelda - Link as Sonic', main: 'D:\\Exports\\Zelda - Link as Sonic\\Zelda (USA).gcz', kind: 'gcz', label: 'Same format as the original (.gcz)', files: [{ path: 'Zelda (USA).gcz', size: 1000 }] };
      return { id: m[1], state: 'succeeded', progress: { pct: 100, msg: 'done' }, output: { result: out } };
    }
    if (p.endsWith('/delete')) return { scope: body.scope, node: body.node, jobs: [{ node: 'MYPC' }], spark: { removed: [] } };
    throw new Error('unexpected ' + p);
  };
  return { api, calls };
}

test('follow(): progress while the job runs, its error when it fails', async () => {
  const { api } = jobsApi();
  const seen = [];
  const r = await api('/api/builds/zelda/link_sonic/local', { op: 'download', node: 'MYPC' }, 'POST');
  const j = await BL.follow({ api }, r.job_id, (p, m) => seen.push([p, m]), { wait: async () => {} });
  assert.equal(j.state, 'succeeded');
  assert.deepEqual(seen, [[0, 'Waiting for this PC\'s worker…'], [55, 'Fetching mod link_sonic: 50/91 MB'], [100, 'done']]);
  const bad = jobsApi({ fail: 'build link_sonic is neither on this PC nor in the central collection' });
  const r2 = await bad.api('/api/builds/zelda/link_sonic/local', { op: 'download' }, 'POST');
  await assert.rejects(BL.follow({ api: bad.api }, r2.job_id, null, { wait: async () => {} }), /neither on this PC nor in the central collection/);
});

test('download: a click on the arrow queues it on this PC, the ring shows the percent, then the check; a toast and a note', async () => {
  const { api, calls } = jobsApi();
  const draws = [], notes = [], toasts = [];
  let L;
  L = BL.create({ api, here: 'MYPC', wait: async () => {} }, { redraw: () => draws.push(L.iconHTML(B)), note: (b, t) => notes.push(t), toast: t => toasts.push(t) });
  await L.refresh();
  assert.equal(L.state(B).state, 'off');
  const handled = await L.onClick({ target: { closest: s => s === '[data-bl]' ? { dataset: { bl: 'main' } } : null } }, B);
  assert.ok(handled);
  assert.deepEqual(calls.filter(c => c[0] === 'POST'), [['POST', '/api/builds/zelda/link_sonic/local', { op: 'download', node: 'MYPC' }]]);
  assert.ok(draws.some(h => h.includes('bl-busy') && h.includes('55%')), 'the ring with the percent while it downloads');
  assert.match(draws.at(-1), /bl-main bl-here/);
  assert.equal(L.state(B).state, 'here');
  assert.deepEqual(toasts, ['Downloading Link as Sonic to this PC…', 'Link as Sonic is on this PC (91.0 MB): it plays instantly, offline']);
  assert.deepEqual(notes, ['⬇ On this PC (91.0 MB): it plays instantly, offline']);
  // the heartbeat catches up: the override goes, the list says the same
  const later = jobsApi({ local: { [B.key]: { built: 1 } } });
  const L2 = BL.create({ api: later.api, here: 'MYPC' }); L2.over.set(B.key, true);
  await L2.refresh();
  assert.equal(L2.over.size, 0); assert.equal(L2.state(B).state, 'here');
});

test('a failed download says why; a click on the check opens the menu; right-click on the icon only', async () => {
  const bad = jobsApi({ fail: 'mod checksum mismatch' });
  const notes = [];
  const L = BL.create({ api: bad.api, here: 'MYPC', wait: async () => {} }, { note: (b, t) => notes.push(t) });
  await L.download(B);
  assert.deepEqual(notes, ['⚠ Download failed: mod checksum mismatch']);
  assert.equal(L.state(B).state, 'off');
  const Lh = BL.create({ api: jobsApi({ local: { [HERE.key]: {} } }).api, here: 'MYPC' });
  await Lh.refresh();
  await Lh.onClick({ target: { closest: s => s === '[data-bl]' ? { dataset: { bl: 'main' } } : null } }, HERE);
  assert.equal(Lh.menu, HERE.key);
  assert.match(Lh.menuHTML(HERE), /data-bl-menu="zelda\/here_build"/);
  Lh.menu = null;
  assert.equal(Lh.onContext({ target: { closest: () => null } }, HERE), false, 'right-click elsewhere: the card\'s own menu');
  let prevented = false;
  assert.equal(Lh.onContext({ target: { closest: s => s.includes('.bl') ? {} : null }, preventDefault() { prevented = true; } }, HERE), true);
  assert.ok(prevented && Lh.menu === HERE.key);
  const none = BL.create({ api: bad.api, here: 'auto' });
  assert.equal(none.onContext({ target: { closest: () => ({}) }, preventDefault() {}, stopPropagation() {} }, B), true);
  assert.equal(none.menu, null, 'no PC: no menu');
});

test('Open folder locates this PC\'s copy and opens it; Delete from this PC is the delete dialog limited to this PC', async () => {
  const { api, calls } = jobsApi({ local: { [HERE.key]: {} } });
  const opened = [], dialogs = [];
  const fakeBA = { open: async (kind, b, env) => { dialogs.push([kind, b, env]); return { scope: 'node', node: 'MYPC', jobs: [{ node: 'MYPC' }], spark: { removed: [] } }; },
                   deleteResultText: BA.deleteResultText };
  const notes = [];
  const L = BL.create({ api, here: 'MYPC', wait: async () => {}, openPath: p => opened.push(p), buildActions: fakeBA }, { note: (b, t) => notes.push(t) });
  await L.refresh();
  assert.equal(await L.open(HERE), 'C:\\gbox\\cache\\mods\\zelda\\link_sonic');
  assert.deepEqual(opened, ['C:\\gbox\\cache\\mods\\zelda\\link_sonic']);
  assert.deepEqual(calls.find(c => c[0] === 'POST')[2], { op: 'locate', node: 'MYPC' });
  await L.remove(HERE);
  assert.equal(dialogs[0][0], 'delete');
  assert.equal(dialogs[0][2].onlyHere, true);
  assert.equal(dialogs[0][2].here, 'MYPC');
  assert.equal(L.state(HERE).state, 'off');
  assert.equal(notes.at(-1), 'Deleted Link as Sonic from MYPC; deleting the copy on MYPC');
  // the real dialog with onlyHere: only this PC's copy, checked, no "everywhere"
  const html = BA.deleteDialogHTML(HERE, { here: 'MYPC', onlyHere: true });
  assert.match(html, /🗑 Delete “Link as Sonic” from this PC\?/);
  assert.ok(!html.includes('value="all"'));
  assert.match(html, /value="node" checked> Only this PC \(MYPC\)/);
  assert.match(html, /the Spark collection and other PCs keep theirs/);
  assert.match(BA.deleteDialogHTML(HERE, { here: 'MYPC' }), /value="all" checked/, 'the 🗑 Delete… dialog itself is unchanged');
});

// a document just big enough for openExport(): the modal's fields answer what the dialog reads
function fakeDoc() {
  const parts = { dest: { value: '' }, status: { textContent: '' }, run: { innerHTML: '' }, go: { disabled: false, textContent: '' }, fmt: { value: 'same' } };
  const wrap = { className: '', html: '', listeners: {}, removed: false,
    set innerHTML(v) { this.html = v; const m = v.match(/data-bx-dest type="text" value="([^"]*)"/); if (m && !parts.dest.touched) parts.dest.value = m[1].replace(/&#92;/g, '\\'); },
    get innerHTML() { return this.html; },
    addEventListener(t, f) { this.listeners[t] = f; }, remove() { this.removed = true; },
    querySelector(sel) {
      if (sel === '[data-bx-dest]') return parts.dest;
      if (sel === '[data-bx-status]') return parts.status;
      if (sel === '[data-bx-run]') return parts.run;
      if (sel === '[data-bx="go"]') return parts.go;
      if (sel.startsWith('input[name="bx-format"]')) return parts.fmt;
      return null;
    } };
  return { doc: { body: { appendChild() {} }, createElement: () => wrap }, wrap, parts,
           click: bx => wrap.listeners.click({ target: { closest: s => s === '[data-bx]' ? { dataset: { bx } } : null } }) };
}
const tick = () => new Promise(r => setTimeout(r, 0));

test('Export…: formats load, Choose… fills the folder, Export runs on this PC with progress, then the path and Show in folder', async () => {
  const { api, calls } = jobsApi();
  const d = fakeDoc(), shown = [], remembered = [];
  const done = BL.openExport(B, { document: d.doc, api, here: 'MYPC', wait: async () => {}, pickFolder: async o => { assert.match(o.title, /Export “Link as Sonic” to…/); return 'E:\\Backups'; },
                                  showInFolder: p => shown.push(p), lastDest: () => 'D:\\Exports', rememberDest: p => remembered.push(p) });
  await tick();
  assert.match(d.wrap.html, /Same format as the original \(\.gcz: Dolphin GCZ \(compressed\)\)/);
  assert.match(d.wrap.html, /data-bx="pick">Choose…/);
  assert.equal(d.parts.dest.value, 'D:\\Exports', 'the last folder used');
  await d.click('pick');
  assert.equal(d.parts.dest.value, 'E:\\Backups');
  d.parts.dest.touched = true;
  await d.click('go');
  assert.deepEqual(calls.filter(c => c[0] === 'POST').map(c => c[2]), [{ op: 'export', node: 'MYPC', dest: 'E:\\Backups', format: 'same', label: 'Link as Sonic' }]);
  assert.deepEqual(remembered, ['E:\\Backups']);
  assert.match(d.parts.run.innerHTML, /✓ Exported · Same format as the original \(\.gcz\)/);
  assert.match(d.parts.run.innerHTML, /Zelda - Link as Sonic\\Zelda \(USA\)\.gcz/);
  assert.equal(d.parts.go.textContent, '⇪ Export again');
  await d.click('show');
  assert.deepEqual(shown, ['D:\\Exports\\Zelda - Link as Sonic\\Zelda (USA).gcz']);
  await d.click('cancel');
  const r = await done;
  assert.equal(r.kind, 'gcz');
  assert.ok(d.wrap.removed);
});

test('Export… refuses an empty folder, says a failed export\'s reason, and needs a PC', async () => {
  const bad = jobsApi({ fail: 'a patch is made against your original game file, and it isn\'t on this PC' });
  const d = fakeDoc();
  const done = BL.openExport(B, { document: d.doc, api: bad.api, here: 'MYPC', wait: async () => {}, lastDest: () => '' });
  await tick();
  await d.click('go');
  assert.equal(d.parts.status.textContent, '⚠ Choose the folder on this PC to export to');
  d.parts.dest.value = 'D:\\x'; d.parts.dest.touched = true; d.parts.fmt.value = 'patch';
  await d.click('go');
  assert.equal(bad.calls.find(c => c[0] === 'POST')[2].format, 'patch');
  assert.match(d.parts.status.textContent, /^⚠ a patch is made against your original game file/);
  assert.equal(d.parts.go.disabled, false, 'the operator can pick another format and try again');
  await d.click('cancel'); assert.equal(await done, null);
  const d2 = fakeDoc();
  const p2 = BL.openExport(B, { document: d2.doc, api: bad.api, here: '', lastDest: () => 'D:\\x' });
  await tick(); await d2.click('go');
  assert.match(d2.parts.status.textContent, /No PC behind this view/);
  await d2.click('cancel'); await p2;
});

test('the Mods card: the icon sits in the picture\'s top-right corner, the menu under it; the Builds row: at its right end', () => {
  const m = { key: 'zelda/link_sonic', name: 'link_sonic', game_id: 'zelda', title: 'Zelda', mod_title: 'Link as Sonic', writer: 'w', built: 1, size: 10,
              images: [{ url: '/x.png', name: 'p' }] };
  const icon = BL.iconHTML({ state: 'off' }), menu = BL.menuHTML(m, { state: 'off' }, 'MYPC');
  const card = MG.cardHTML(m, { dl: icon, dlMenu: menu });
  assert.match(card, /<div class="mg-pic">[\s\S]*<div class="mg-dl"><span class="bl" data-bl-state="off">[\s\S]*<\/div><\/div>\s*<div class="mg-body">/);
  assert.match(card, /<div class="mg-dlm"><div class="bl-menu" role="menu" data-bl-menu="zelda\/link_sonic">/);
  assert.ok(!MG.cardHTML(m).includes('mg-dl'), 'no icon without a view state');
  const nopic = MG.cardHTML({ ...m, images: [] }, { dl: icon });
  assert.match(nopic, /No pictures yet[^<]*<\/div><div class="mg-dl">/);
  const L = BL.create({ api: async () => ({}), here: 'MYPC' });
  L.menu = HERE.key;
  const row = BV.rowHTML(HERE, { local: L, open: new Set() }, { here: 'MYPC' });
  assert.match(row, /data-bv="delete"[^>]*>🗑<\/button><span class="bv-dl"><span class="bl" data-bl-state="here">/);
  assert.match(row, /<div class="bv-dlm"><div class="bl-menu" role="menu" data-bl-menu="zelda\/here_build">/);
});

// the Mods gallery on a fake host (as tests/test_mods_gallery.cjs): the icon's state from this PC's list, a click downloads
function host() {
  const parts = { '[data-mg-grid]': { innerHTML: '' }, '[data-mg-sum]': { textContent: '' }, '[data-mg-more]': { innerHTML: '' } };
  const listeners = {};
  return { parts, listeners, host: { innerHTML: '', querySelector: s => parts[s] || null, contains: () => false,
    addEventListener: (t, fn) => (listeners[t] ||= []).push(fn), removeEventListener() {} } };
}

test('the Mods page: on this PC / not on this PC per card; a click on the arrow downloads; right-click on it opens its menu', async () => {
  const items = [{ ...B, title: 'Zelda', writer: 'w', built: 2, size: 10 }, { ...HERE, title: 'Zelda', writer: 'w', built: 1, size: 10 }];
  const j = jobsApi({ local: { [HERE.key]: { built: 1 } } });
  const api = async (p, body, method) => p.startsWith('/api/mods/built') ? { items } : p === '/api/workers' ? [] : j.api(p, body, method);
  const h = host();
  const ctl = MG.mount(h.host, { api, here: 'MYPC', wait: async () => {}, poll: null, toast: () => {} });
  await ctl.ready;
  try {
    const grid = () => h.parts['[data-mg-grid]'].innerHTML;
    assert.match(grid(), /data-key="zelda\/link_sonic">[\s\S]*?data-bl-state="off"/);
    assert.match(grid(), /data-key="zelda\/here_build">[\s\S]*?data-bl-state="here"/);
    const card = { dataset: { key: B.key }, querySelector: () => null };
    const t = { closest: s => s === '.mg-card' ? card : s === '[data-bl]' ? { dataset: { bl: 'main' } } : null };
    for (const fn of h.listeners.click) await fn({ target: t, preventDefault() {}, stopPropagation() {} });
    assert.deepEqual(j.calls.filter(c => c[0] === 'POST').map(c => c[2]), [{ op: 'download', node: 'MYPC' }]);
    assert.match(grid(), /data-key="zelda\/link_sonic">[\s\S]*?data-bl-state="here"/);
    assert.match(grid(), /⬇ On this PC \(91\.0 MB\): it plays instantly, offline/);
    const rc = { closest: s => s === '.mg-card' ? { dataset: { key: HERE.key } } : s.includes('.bl') ? {} : null, matches: () => false };
    ctl.onContext({ target: rc, preventDefault() {}, stopPropagation() {} });
    assert.equal(ctl.st.menu, null, 'not the card\'s own options');
    assert.match(grid(), /data-bl-menu="zelda\/here_build"/);
  } finally { ctl.stop(); }
});
