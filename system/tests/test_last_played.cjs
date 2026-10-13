// "Reload the game you had up" pop-up (clients/web/viz/last-played.js over /api/last_played): shown when the operator's
// game ended (and on the next start), Reload / Reload with your last moment / Dismiss, don't ask again, crash wording.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const LPop = require('../clients/web/viz/last-played.js');

const NOW = 1_800_000_000;
const ENTRY = { session_id: 'w-a', game_id: 'ts', title: 'MGS: The Twin Snakes', mod: 'tts_sonic_full_cast', node: 'JAYBUILTFINALE',
  node_online: true, ended: NOW - 120, reason: { kind: 'stopped', crash: false, text: 'You stopped it.' },
  moment: { artifact: 'a'.repeat(64), ts: NOW - 130, frame_url: '/api/artifacts/' + 'f'.repeat(64) }, report: null };

function fakeHost() {
  let parts = [], muted = false;
  const host = {
    get html() { return parts.join(''); },
    insertAdjacentHTML: (_w, h) => parts.push(h),
    querySelector: sel => {
      if (sel === '#lp-css') return parts.some(p => p.includes('id="lp-css"')) ? {} : null;
      if (sel === '.lp-back') {
        const i = parts.findIndex(p => p.includes('class="lp-back"'));
        return i < 0 ? null : { remove: () => parts.splice(i, 1), querySelector: s => (s === '[data-lp="mute"]' ? { checked: muted } : null) };
      }
      return null;
    },
    addEventListener: (t, fn) => { host.click = fn; }, removeEventListener() {},
    mute: v => { muted = v; },
  };
  return host;
}
const click = (host, lp, extra = {}) => host.click({ target: { closest: () => ({ dataset: { lp, ...extra } }) }, preventDefault() {} });

function env(entry, extra = {}) {
  const calls = [], host = fakeHost(), reloaded = [];
  let current = entry;
  const e = {
    host, calls, reloaded, wait: async () => {}, now: () => NOW, poll: 3600000, url: u => u + '?token=t',
    setEntry: x => { current = x; },
    onReloaded: (sid, out) => reloaded.push([sid, out]),
    api: async (p, body) => {
      calls.push([p, body]);
      if (p === '/api/last_played') return { entry: current };
      if (p === '/api/last_played/dismiss') return { ok: true };
      if (p === '/api/last_played/reload') return { id: 'j1', state: 'running' };
      if (p === '/api/jobs/j1') return extra.job || { id: 'j1', state: 'succeeded', output: { session_id: 'w-new', moment_loaded: !!body?.moment } };
      throw new Error('unexpected ' + p);
    },
    ...extra,
  };
  return e;
}

test('render: title, why it ended, build, PC, the moment with its picture and age, the three choices', () => {
  const html = LPop.html(ENTRY, { url: u => u + '?token=t', now: NOW });
  assert.match(html, /role="dialog"/);
  assert.match(html, /MGS: The Twin Snakes ended/);
  assert.match(html, /You stopped it\./);
  assert.match(html, /Build tts_sonic_full_cast · on JAYBUILTFINALE · ended 2 min ago/);
  assert.match(html, /<img alt="Your last moment" src="\/api\/artifacts\/f{64}\?token=t">/);
  assert.match(html, /data-lp="reload"[^>]*>Reload MGS: The Twin Snakes \(tts_sonic_full_cast\)</);
  assert.match(html, /data-lp="moment"[^>]*>Reload with your last moment \(2 min ago\)</);
  assert.match(html, /data-lp="dismiss"[^>]*>Dismiss</);
  assert.match(html, /Don't ask again for this game/);
  const plain = LPop.html({ ...ENTRY, moment: null, mod: '' }, { now: NOW });
  assert.ok(!plain.includes('data-lp="moment"'), 'no saved moment: no moment button');
  assert.match(plain, /Original game · on JAYBUILTFINALE/);
});

test('a crash or a failed relaunch says so, and links its report when one exists', () => {
  const html = LPop.html({ ...ENTRY, reason: { kind: 'relaunch_failed', crash: true, text: 'Its relaunch failed: Dolphin exited 1.' },
    report: { id: 'r9', number: 1642, status: 'in_progress' } }, { now: NOW });
  assert.match(html, /class="lp-box lp-bad"/);
  assert.match(html, /⚠ MGS: The Twin Snakes ended/);
  assert.match(html, /class="lp-why lp-bad">Its relaunch failed: Dolphin exited 1\./);
  assert.match(html, /data-lp="report" data-id="r9">Report #1642 · in progress</);
  const offline = LPop.html({ ...ENTRY, node_online: false }, { now: NOW });
  assert.match(offline, /JAYBUILTFINALE \(offline right now\)/);
  assert.match(offline, /data-lp="reload" disabled/);
});

test('controller: shows the entry, Reload with the moment runs the reload job and hands over the new session', async () => {
  const e = env(ENTRY), ctl = LPop.mount(e);
  await ctl.ready;
  assert.match(e.host.html, /class="lp-back"/);
  await click(e.host, 'moment');
  assert.deepEqual(e.calls.find(c => c[0] === '/api/last_played/reload')[1], { session_id: 'w-a', moment: true });
  assert.deepEqual(e.reloaded.map(r => r[0]), ['w-new']);
  assert.ok(!e.host.html.includes('class="lp-back"'), 'closed once the game is back');
  ctl.stop();
});

test('controller: a failed reload stays open and says why; Dismiss and "don\'t ask again" go to the server', async () => {
  let e = env(ENTRY, { job: { id: 'j1', state: 'failed', error: 'PSO is running on JAYBUILTFINALE; it was not stopped.' } });
  let ctl = LPop.mount(e); await ctl.ready;
  await click(e.host, 'reload');
  assert.match(e.host.html, /role="alert">⚠ Reload failed: PSO is running on JAYBUILTFINALE; it was not stopped\./);
  assert.deepEqual(e.reloaded, []);
  ctl.stop();
  e = env(ENTRY); ctl = LPop.mount(e); await ctl.ready;
  e.host.mute(true);
  await click(e.host, 'dismiss');
  assert.deepEqual(e.calls.at(-1), ['/api/last_played/dismiss', { session_id: 'w-a', never_for_game: true }]);
  assert.ok(!e.host.html.includes('class="lp-back"'));
  await ctl.check();                                         // the same entry is not shown again in this window
  assert.ok(!e.host.html.includes('class="lp-back"'));
  e.setEntry({ ...ENTRY, session_id: 'w-b' });               // another game ends: it is offered
  await ctl.check();
  assert.match(e.host.html, /data-lp-sid="w-b"/);
  ctl.stop();
});

test('nothing to offer (a game runs): no pop-up; the web shell mounts it and loads the script', async () => {
  const e = env(null), ctl = LPop.mount(e); await ctl.ready;
  assert.equal(e.host.html, '');
  ctl.stop();
  const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  assert.match(web, /<script src="\/viz\/last-played\.js"><\/script>/);
  assert.match(web, /const LASTPLAYED = GBoxLastPlayed\.mount\(\{ api, host: document\.body,/);
  const main = fs.readFileSync(path.join(__dirname, '../clients/desktop/main.js'), 'utf8');
  assert.match(main, /\/api\/sessions\/\$\{encodeURIComponent\(x\.session_id\)\}\/moment\?wait=5/, 'the app keeps the moment before it quits');
  assert.ok(main.indexOf('await keepMoments();') < main.indexOf('taskkill", ["/T", "/F", "/PID", String(worker.pid)]); worker = null;'));
});
