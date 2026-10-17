// Build notifications in the bell tray (clients/web/viz/build-notes.js over GET /api/notify, gbox/build_notify.py):
// a build entry's thumbnail / title / summary / time / Play / ▾ options / Open in Mods, an error's reason / Open request /
// Retry build, a collect's Open models, a grouped entry's rows, the unread count, which entries are announced (toast +
// OS notification), and the Play wiring: the same launch the game menu's Special builds use (this PC's worker), in both
// clients.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const BN = require('../clients/web/viz/build-notes.js');

const GID = 'sadx';
const opt = (id, label, node, extra = {}) => ({ id, label, node, target: extra.target || node, moment: false, debug: false, default: false, ...extra,
  call: { method: 'POST', path: `/api/games/${GID}/launch?node=${node}&mod=cast_sadx` } });
const LAUNCH = [opt('here', 'This PC', 'auto', { target: 'here', default: true }), opt('pc:i9-NUC', 'Play on i9-NUC (windows)', 'i9-NUC'),
  opt('moment', 'Play from saved moment (slot 2)', 'auto', { target: 'here', moment: true, state_slot: 2 }),
  opt('debug', 'Play with the debugger (Spark)', 'linux', { debug: true })];
const BUILD = { kind: 'build', job_id: 'j1', game_id: GID, game_title: 'Sonic Adventure DX', mod: 'cast_sadx', mod_title: 'SADX <cast> as Heroes',
  summary: '4/4 slots built · Sonic, Knuckles, Amy, Gamma', launch: LAUNCH, state_slot: 2, card_id: 'c1',
  thumbnail: '/api/notify/n1/thumb?i=0&v=ab', thumbnail_source: 'capture' };
const ONE = { id: 'n1', auto: 'build', kind: 'build', count: 1, ts: 1760000000, read: false, title: 'SADX <cast> as Heroes is ready',
  text: 'Sonic Adventure DX · 4/4 slots built · Sonic, Knuckles, Amy, Gamma', items: [BUILD], launch: LAUNCH, mod: 'cast_sadx', game_id: GID };
const FAIL = { kind: 'error', job_id: 'j2', game_id: GID, game_title: 'Sonic Adventure DX', tool: 'characters', op: 'use', mod: '', mod_title: '',
  error: 'writer crashed: too many bones', summary: 'writer crashed: too many bones', request_id: 'r7', launch: [],
  retry: { tool: 'characters', input: { op: 'use', character: 'amy', game_id: GID, slot: 'player', launch: false, rebuild: true }, require_os: 'linux' },
  thumbnail: '/api/notify/n2/thumb?i=0&v=cd', thumbnail_source: 'boxart' };
const ERR = { id: 'n2', auto: 'build', kind: 'error', count: 1, ts: 1760000100, read: false, title: 'Build failed: characters use (Sonic Adventure DX)',
  text: 'writer crashed: too many bones', items: [FAIL] };
const COL = { id: 'n3', auto: 'build', kind: 'collect', count: 1, ts: 1760000200, read: true, title: '3 characters collected from Sonic Adventure DX',
  text: '3 collected · Sonic, Tails, Amy', items: [{ kind: 'collect', game_id: GID, game_title: 'Sonic Adventure DX', summary: '3 collected · Sonic, Tails, Amy',
    launch: [], thumbnail: '/api/notify/n3/thumb?i=0&v=ef', thumbnail_source: 'donor' }] };
const GROUP = { id: 'n4', auto: 'build', kind: 'build', count: 2, ts: 1760000300, read: false, title: '1 build ready, 1 failed',
  text: 'SADX <cast> as Heroes · characters use', items: [BUILD, FAIL] };
const LEGACY = { id: 'n5', title: 'Mario Mercenaries is ready on this PC', text: 'RE4 with Mario, running natively.', session_id: 'w1-s9', ts: 1760000400, read: false };
const url = u => `${u}${u.includes('?') ? '&' : '?'}token=t`;

test('a build entry: thumbnail, escaped title + summary, time, Play, ▾ other launch options, Open in Mods', () => {
  const html = BN.noteHTML(ONE, { url, here: 'i9-NUC' });
  assert.match(html, /class="tnote unread bnote bn-build" data-id="n1" data-sid="" data-auto="build"/);
  assert.match(html, /<img class="bn-thumb"[^>]*src="\/api\/notify\/n1\/thumb\?i=0&#38;v=ab&#38;token=t"[^>]*title="a frame of the build running"/);
  assert.ok(html.includes('SADX &#60;cast&#62; as Heroes is ready') && !html.includes('<cast>'));
  assert.ok(html.includes('4/4 slots built · Sonic, Knuckles, Amy, Gamma'));
  assert.match(html, /<time>[^<]+<\/time>/);
  assert.match(html, /data-bn="play" data-id="n1" data-i="0" title="Play on this PC \(i9-NUC\)">▶ Play</);
  assert.match(html, /data-bn="opts"[^>]*aria-expanded="false"/);
  assert.match(html, /data-bn="mods" data-id="n1" data-i="0">Open in Mods/);
  assert.ok(!html.includes('data-bn="launch"'), 'the ▾ list is closed');
  const open = BN.noteHTML(ONE, { url, here: 'i9-NUC', state: { open: 'n1:0' } });
  assert.match(open, /aria-expanded="true"/);
  assert.deepEqual([...open.matchAll(/data-opt="([^"]+)">▶ ([^<]+)</g)].map(m => [m[1], m[2]]),
    [['pc:i9-NUC', 'Play on i9-NUC (windows)'], ['moment', 'Play from saved moment (slot 2)'], ['debug', 'Play with the debugger (Spark)']]);
});

test('an error entry: the reason, Open request, Retry build, no Play; a collect: Open models; legacy notes as before', () => {
  const html = BN.noteHTML(ERR, { url });
  assert.match(html, /bn-error/);
  assert.match(html, /<span class="bn-sum bn-bad">writer crashed: too many bones<\/span>/);
  assert.match(html, /data-bn="request" data-id="n2" data-i="0">Open request/);
  assert.match(html, /data-bn="retry" data-id="n2" data-i="0"[^>]*>⟳ Retry build/);
  assert.ok(!html.includes('data-bn="play"'));
  const noRecipe = BN.noteHTML({ ...ERR, items: [{ ...FAIL, retry: null, request_id: '' }] }, { url });
  assert.ok(!noRecipe.includes('Retry build') && !noRecipe.includes('Open request'));
  const col = BN.noteHTML(COL, { url });
  assert.match(col, /class="tnote bnote bn-collect"/);
  assert.match(col, /3 characters collected from Sonic Adventure DX/);
  assert.match(col, /data-bn="models" data-id="n3" data-i="0">Open models/);
  const old = BN.noteHTML(LEGACY, { url });
  assert.match(old, /^<div class="tnote unread" data-id="n5" data-sid="w1-s9">/);
  assert.match(old, /<b>Mario Mercenaries is ready on this PC<\/b><span>RE4 with Mario, running natively.<\/span><time>/);
  assert.ok(!old.includes('data-auto'));
});

test('a grouped entry: the headline, then one row per build with its own thumbnail and buttons', () => {
  const html = BN.noteHTML(GROUP, { url });
  assert.match(html, /bnote bn-group bn-build/);
  assert.match(html, /<b>1 build ready, 1 failed<\/b>/);
  assert.equal((html.match(/class="bn-row bn-item"/g) || []).length, 2);
  assert.match(html, /data-bn="play" data-id="n4" data-i="0"/);
  assert.match(html, /data-bn="retry" data-id="n4" data-i="1"/);
  assert.match(html, /✗ characters use/);
});

test('the tray: unread count + Mark all read, newest entries, empty state', () => {
  const all = [GROUP, COL, ERR, ONE, LEGACY];
  assert.equal(BN.unread(all), 4);
  const html = BN.trayHTML(all, { url });
  assert.match(html, /^<div class="bn-top"><span class="mut">4 unread<\/span><button class="act" type="button" data-bn="readall">Mark all read/);
  assert.equal((html.match(/class="tnote/g) || []).length, 5);
  assert.match(BN.trayHTML([], {}), /No notifications yet/);
  assert.ok(!BN.trayHTML([COL], {}).includes('bn-top'), 'nothing unread: no header');
});

function io(notes, extra = {}) {               // the entries are copies: a click marks them read
  notes = notes.map(n => JSON.parse(JSON.stringify(n)));
  const calls = { api: [], launch: [], mods: [], req: [], models: [], repaint: 0, close: 0, dismiss: [] };
  return { calls, io: { notes: () => notes, state: {}, here: 'i9-NUC',
    api: async (p, b) => { calls.api.push([p, b]); return p === '/api/jobs' ? { id: 'j9', state: 'queued' } : { ok: true }; },
    launch: async (gid, x) => { calls.launch.push([gid, x]); return 'w1-s1'; },
    openMods: (gid, mod) => calls.mods.push([gid, mod]), openRequest: r => calls.req.push(r), openModels: (gid, t) => calls.models.push([gid, t]),
    repaint: () => calls.repaint++, close: () => calls.close++, dismiss: id => calls.dismiss.push(id), ...extra } };
}
const target = (attrs, button = true) => {
  const b = { dataset: attrs, tagName: 'BUTTON' };
  return { closest: s => (s === '[data-bn]' ? b : s === 'button' && button ? b : null) };
};

test('Play launches the build on this PC through the game menu launch (mod staged there), marks it read, closes the tray', async () => {
  const { calls, io: x } = io([ONE]), notes = x.notes();
  await BN.click(target({ bn: 'play', id: 'n1', i: '0' }), x);
  assert.equal(calls.launch.length, 1);
  const [gid, a] = calls.launch[0];
  assert.equal(gid, GID);
  assert.deepEqual({ mod: a.mod, node: a.node, debug: a.debug, slot: a.slot }, { mod: 'cast_sadx', node: 'i9-NUC', debug: false, slot: '' });
  assert.equal(a.option.id, 'here');
  assert.deepEqual(calls.api, [['/api/notify/n1/read', {}]]);
  assert.equal(notes[0].read, true);
  assert.equal(calls.close, 1);
  assert.deepEqual(calls.dismiss, ['n1'], 'the toast goes too');
  // no worker name known (a plain browser): node auto, the server picks the PC the operator plays on
  const { calls: c2, io: y } = io([ONE], { here: '' });
  await BN.click(target({ bn: 'play', id: 'n1', i: '0' }), y);
  assert.equal(c2.launch[0][1].node, 'auto');
});

test('▾ opens the other options: another PC, the saved moment (slot), the Spark debugger', async () => {
  const { calls, io: x } = io([ONE]);
  BN.click(target({ bn: 'opts', id: 'n1', i: '0' }), x);
  assert.equal(x.state.open, 'n1:0'); assert.equal(calls.repaint, 1);
  BN.click(target({ bn: 'opts', id: 'n1', i: '0' }), x);
  assert.equal(x.state.open, null, 'a second click closes it');
  await BN.click(target({ bn: 'launch', id: 'n1', i: '0', opt: 'pc:i9-NUC' }), x);
  await BN.click(target({ bn: 'launch', id: 'n1', i: '0', opt: 'moment' }), x);
  await BN.click(target({ bn: 'launch', id: 'n1', i: '0', opt: 'debug' }), x);
  assert.deepEqual(calls.launch.map(([, a]) => [a.node, a.debug, a.slot]), [['i9-NUC', false, ''], ['i9-NUC', false, 2], ['linux', true, '']]);
  assert.equal(BN.launchArgs(BUILD, LAUNCH[0], 'pc-x').x.node, 'pc-x');
});

test('Open in Mods, Open request, Retry build, Open models, Mark all read; a failed launch says why on the entry', async () => {
  const { calls, io: x } = io([ONE, ERR, COL, GROUP]);
  BN.click(target({ bn: 'mods', id: 'n1', i: '0' }), x);
  assert.deepEqual(calls.mods, [[GID, 'cast_sadx']]);
  BN.click(target({ bn: 'request', id: 'n2', i: '0' }), x);
  assert.deepEqual(calls.req, [{ id: 'r7' }]);
  BN.click(target({ bn: 'models', id: 'n3', i: '0' }), x);
  assert.deepEqual(calls.models, [[GID, 'Sonic Adventure DX']]);
  await BN.click(target({ bn: 'retry', id: 'n4', i: '1' }), x);
  const job = calls.api.find(([p]) => p === '/api/jobs');
  assert.deepEqual(job[1], { tool: 'characters', input: FAIL.retry.input, require_os: 'linux' });
  assert.match(x.state.msg['n4:1'], /rebuild queued \(job j9\)/);
  assert.match(BN.noteHTML(GROUP, { state: x.state }), /rebuild queued/);
  await BN.click(target({ bn: 'readall' }), x);
  assert.ok(calls.api.some(([p]) => p === '/api/notify/read_all'));
  const { io: bad } = io([ONE], { launch: async () => { throw new Error('PC offline'); } });
  await BN.click(target({ bn: 'play', id: 'n1', i: '0' }), bad);
  assert.equal(bad.state.msg['n1:0'], '✗ PC offline');
  assert.equal(BN.click({ closest: () => null }, x), false, 'not a tray button: the page handles it');
});

test('announcements: nothing old on page load; a new build entry or a grown group once; read ones never', () => {
  const seen = BN.seenOf([ONE, ERR]);
  assert.deepEqual(BN.fresh([ONE, ERR], seen), []);
  const next = { ...GROUP };
  assert.deepEqual(BN.fresh([next, ONE, ERR], seen).map(n => n.id), ['n4']);
  assert.deepEqual(BN.fresh([next, ONE, ERR], seen), [], 'once');
  const grown = { ...GROUP, count: 3, items: [BUILD, FAIL, BUILD] };
  assert.deepEqual(BN.fresh([grown], seen).map(n => n.id), ['n4']);
  assert.deepEqual(BN.fresh([{ ...COL, id: 'n9' }, LEGACY], seen), [], 'read entries and other notes are not announced');
  const toast = BN.toastHTML(ONE, { url });
  assert.match(toast, /class="bn-toast" data-id="n1" role="status"/);
  assert.match(toast, /data-bn="play" data-id="n1" data-i="0">▶ Play/);
  assert.match(toast, /data-bn="dismiss"/);
  assert.ok(!BN.toastHTML(ERR, { url }).includes('data-bn="play"'));
  assert.deepEqual(BN.osNote(ONE), { ev: 'buildnote', id: 'n1', title: ONE.title, body: ONE.text, kind: 'build', thumbnail: BUILD.thumbnail });
});

test('wiring: the web tray renders through build-notes, Play = the game menu launch; the desktop app shows OS notifications', () => {
  const web = fs.readFileSync(path.join(__dirname, '..', 'clients', 'web', 'index.html'), 'utf8');
  assert.match(web, /<script src="\/viz\/build-notes.js"><\/script>/);
  assert.match(web, /el\.innerHTML = GBoxBuildNotes\.trayHTML\(TRAY\.notes, \{ url: bnUrl/);
  assert.match(web, /GBoxBuildNotes\.click\(e\.target, buildNoteIO\(\)\)/);
  assert.match(web, /launch: \(gid, x\) => gameMenuIO\(\)\.launch\(gid, x\)/);
  // the game menu's launch: play() with the mod (the launch path that stages / fetches the mod on that PC)
  assert.match(web, /launch: \(gid, x\) => play\(gid, x\.node === "auto" \? undefined : x\.node, !!x\.debug, \{ disc: x\.mod/);
  assert.match(web, /GBoxBuildNotes\.fresh\(notes, TRAY\.seen\)[^\n]*bnAnnounce/);
  assert.match(web, /console\.log\("GBOX:" \+ JSON\.stringify\(os\)\)/);
  const desk = fs.readFileSync(path.join(__dirname, '..', 'clients', 'desktop', 'index.html'), 'utf8');
  assert.match(desk, /m\.ev === "buildnote"\) buildNoteMsg\(m\)/);
  assert.match(desk, /function buildNoteMsg\(m\) \{\s+gbox\.osNotify\?\.\(/);
  assert.match(desk, /m\.ev === "openrequest"\) modsGalleryRequest/);
  assert.match(desk, /EMB_GUEST_MENUS = "[^"]*#gbox-toasts/);              // the toast stack (viz/toast-stack.js)
  assert.match(desk, /gbox\.onNotifyClick\?\.\(/);
  const main = fs.readFileSync(path.join(__dirname, '..', 'clients', 'desktop', 'main.js'), 'utf8');
  assert.match(main, /ipcMain\.handle\("notify:os"/);
  assert.match(main, /new Notification\(\{ title:/);
  const pre = fs.readFileSync(path.join(__dirname, '..', 'clients', 'desktop', 'preload.js'), 'utf8');
  assert.match(pre, /osNotify: n => ipcRenderer\.invoke\("notify:os", n\)/);
});
