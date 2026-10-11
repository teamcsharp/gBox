const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
const start = html.indexOf('function paintSessionFav(btn, on)');
const end = html.indexOf('async function toggleFav(id, btn)', start);
assert.ok(start >= 0 && end > start, 'session favorite helpers must be present');
const source = html.slice(start, end);
const tick = () => new Promise(resolve => setImmediate(resolve));

function button(gid) {
  const attrs = { 'aria-pressed': 'false' };
  return { dataset: { gid }, attrs, disabled: true, title: 'Checking favorites', textContent: '☆',
    setAttribute(key, value) { attrs[key] = value; }, getAttribute(key) { return attrs[key] ?? null; } };
}
function setup() {
  let current = button('game-one');
  const calls = [];
  const context = vm.createContext({ console, encodeURIComponent,
    $: selector => selector === '#session-fav' ? current : null,
    api(url, body) {
      let resolve, reject;
      const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
      calls.push({ url, body, resolve, reject });
      return promise;
    } });
  vm.runInContext(source, context);
  return { context, calls, get current() { return current; },
    replace(gid) { current = gid ? button(gid) : null; return current; },
    sync: () => context.syncSessionFav(), toggle: btn => context.toggleSessionFav(btn || current) };
}
async function load(x, favorite) {
  const pending = x.sync(); x.calls.at(-1).resolve({ favorite }); await pending;
}

test('initial state comes from the server and keeps the control disabled until confirmed', async () => {
  for (const favorite of [false, true]) {
    const x = setup(), pending = x.sync();
    assert.equal(x.current.disabled, true);
    assert.equal(x.calls[0].url, '/api/catalog/game-one');
    x.calls[0].resolve({ favorite }); await pending;
    assert.equal(x.current.getAttribute('aria-pressed'), String(favorite));
    assert.equal(x.current.textContent, favorite ? '★' : '☆');
    assert.equal(x.current.disabled, false);
  }
});

test('initial lookup failure can retry without guessing or posting a favorite', async () => {
  const x = setup(), pending = x.sync();
  x.calls[0].reject(Error('503 temporary outage')); await pending;
  assert.equal(x.current.disabled, false);
  assert.match(x.current.title, /retry|reload/i);
  const retry = x.toggle(); await tick();
  assert.equal(x.calls.length, 2);
  assert.equal(x.calls[1].url, '/api/catalog/game-one');
  assert.equal(x.calls[1].body, undefined);
  x.calls[1].resolve({ favorite: true }); await retry;
  assert.equal(x.current.getAttribute('aria-pressed'), 'true');
  assert.equal(x.calls.length, 2);
  const remove = x.toggle();
  assert.equal(x.calls[2].url, '/api/catalog/game-one/favorite?on=false');
  x.calls[2].resolve({ favorite: false }); await remove;
});

test('repeated syncs and clicks cannot overlap the pending initial lookup', async () => {
  const x = setup(), first = x.sync();
  const second = x.sync(), click = x.toggle(); await tick();
  assert.equal(x.calls.length, 1);
  x.calls[0].resolve({ favorite: false }); await Promise.all([first, second, click]);
  assert.equal(x.current.disabled, false);
  assert.equal(x.current.getAttribute('aria-pressed'), 'false');
});

test('duplicate clicks while a save is pending send one mutation and keep the button disabled', async () => {
  const x = setup(); await load(x, false);
  const first = x.toggle(), second = x.toggle(); await tick();
  assert.equal(x.calls.length, 2);
  assert.equal(x.current.disabled, true);
  assert.equal(x.current.getAttribute('aria-pressed'), 'false');
  x.calls[1].resolve({ favorite: true }); await Promise.all([first, second]);
  assert.equal(x.current.disabled, false);
  assert.equal(x.current.getAttribute('aria-pressed'), 'true');
});

test('background sync cannot issue an older read during an in-flight save', async () => {
  const x = setup(); await load(x, false);
  const saving = x.toggle(), refresh = x.sync(); await tick();
  assert.equal(x.calls.length, 2);
  x.calls[1].resolve({ favorite: true }); await Promise.all([saving, refresh]);
  assert.equal(x.current.getAttribute('aria-pressed'), 'true');
  assert.equal(x.current.disabled, false);
});

test('save paints the confirmed server value rather than the requested optimistic state', async () => {
  const x = setup(); await load(x, false);
  const saving = x.toggle();
  assert.equal(x.calls[1].url, '/api/catalog/game-one/favorite?on=true');
  assert.equal(x.current.getAttribute('aria-pressed'), 'false');
  x.calls[1].resolve({ favorite: false }); await saving;
  assert.equal(x.current.getAttribute('aria-pressed'), 'false');
  assert.equal(x.current.textContent, '☆');
  assert.equal(x.current.disabled, false);
});

test('a lost save response reloads server truth on retry instead of repeating the write', async () => {
  const x = setup(); await load(x, false);
  const saving = x.toggle();
  x.calls[1].reject(Error('connection lost after write')); await saving;
  assert.equal(x.current.getAttribute('aria-pressed'), 'false');
  assert.equal(x.current.disabled, false);
  const retry = x.toggle(); await tick();
  assert.equal(x.calls[2].url, '/api/catalog/game-one');
  assert.equal(x.calls[2].body, undefined);
  x.calls[2].resolve({ favorite: true }); await retry;
  assert.equal(x.current.getAttribute('aria-pressed'), 'true');
  assert.equal(x.calls.length, 3);
  const confirmedClick = x.toggle();
  assert.equal(x.calls[3].url, '/api/catalog/game-one/favorite?on=false');
  x.calls[3].resolve({ favorite: false }); await confirmedClick;
});

test('failed save and failed reload remain retryable without changing the last confirmed star', async () => {
  const x = setup(); await load(x, true);
  const saving = x.toggle(); x.calls[1].reject(Error('write failed')); await saving;
  const retry = x.toggle(); await tick(); x.calls[2].reject(Error('lookup failed')); await retry;
  assert.equal(x.current.getAttribute('aria-pressed'), 'true');
  assert.equal(x.current.disabled, false);
  const again = x.toggle(); await tick();
  assert.equal(x.calls[3].url, '/api/catalog/game-one');
  x.calls[3].resolve({ favorite: false }); await again;
  assert.equal(x.current.getAttribute('aria-pressed'), 'false');
});

test('malformed lookup payloads do not turn a truthy string into a confirmed star', async () => {
  for (const response of [{ favorite: 'false' }, { favorite: 0 }, null, []]) {
    const x = setup(), pending = x.sync(); x.calls[0].resolve(response); await pending;
    assert.equal(x.current.getAttribute('aria-pressed'), 'false');
    assert.equal(x.current.disabled, false);
    assert.match(x.current.title, /confirm|unavailable/i);
    const retry = x.toggle(); await tick();
    assert.equal(x.calls[1].url, '/api/catalog/game-one');
    x.calls[1].resolve({ favorite: false }); await retry;
  }
});

test('legacy missing and null favorite fields confirm an unfavorited game', async () => {
  for (const response of [{}, { favorite: null }]) {
    const x = setup(), pending = x.sync(); x.calls[0].resolve(response); await pending;
    assert.equal(x.current.getAttribute('aria-pressed'), 'false');
    assert.equal(x.current.textContent, '\u2606');
    assert.equal(x.current.disabled, false);
    const saving = x.toggle();
    assert.equal(x.calls[1].url, '/api/catalog/game-one/favorite?on=true');
    x.calls[1].resolve({ favorite: true }); await saving;
    assert.equal(x.current.getAttribute('aria-pressed'), 'true');
  }
});

test('nonboolean mutation payloads cannot claim a successful favorite and recover by reading', async () => {
  for (const response of [{ favorite: 'true' }, { favorite: 'false' }, { favorite: null }, {}, null]) {
    const x = setup(); await load(x, false);
    const saving = x.toggle(); x.calls[1].resolve(response); await saving;
    assert.equal(x.current.getAttribute('aria-pressed'), 'false');
    const retry = x.toggle(); await tick();
    assert.equal(x.calls[2].url, '/api/catalog/game-one');
    x.calls[2].resolve({ favorite: true }); await retry;
  }
});

test('duplicate retry clicks reconcile once without posting even if the first write took effect', async () => {
  const x = setup(); await load(x, false);
  const saving = x.toggle(); x.calls[1].reject(Error('lost acknowledgement')); await saving;
  const first = x.toggle(), second = x.toggle(); await tick();
  assert.equal(x.calls.length, 3);
  assert.equal(x.calls[2].body, undefined);
  assert.equal(x.current.disabled, true);
  x.calls[2].resolve({ favorite: true }); await Promise.all([first, second]);
  assert.equal(x.calls.length, 3);
  assert.equal(x.current.getAttribute('aria-pressed'), 'true');
});

test('navigation discards a late initial result and leaves the next game disabled while it loads', async () => {
  const x = setup(), old = x.current, first = x.sync();
  const fresh = x.replace('game-two'), second = x.sync();
  x.calls[0].resolve({ favorite: true }); await first;
  assert.equal(fresh.disabled, true);
  assert.equal(fresh.getAttribute('aria-pressed'), 'false');
  assert.equal(old.getAttribute('aria-pressed'), 'false');
  x.calls[1].resolve({ favorite: false }); await second;
  assert.equal(fresh.disabled, false);
});

test('navigation discards an old lookup error without changing either header title', async () => {
  const x = setup(), old = x.current, pending = x.sync();
  const fresh = x.replace('game-two');
  x.calls[0].reject(Error('old game unavailable')); await pending;
  assert.equal(old.title, 'Checking favorites');
  assert.equal(fresh.title, 'Checking favorites');
  assert.equal(fresh.disabled, true);
});

test('a reused button cannot apply a reply captured for a different game id', async () => {
  for (const mutation of [false, true]) {
    const x = setup();
    if (mutation) await load(x, false);
    const previousTitle = x.current.title;
    const pending = mutation ? x.toggle() : x.sync();
    x.current.dataset.gid = 'game-two';
    x.calls.at(-1).resolve({ favorite: true }); await pending;
    assert.equal(x.current.getAttribute('aria-pressed'), 'false');
    assert.equal(x.current.title, previousTitle);
    assert.equal(x.current.disabled, true);
  }
});

test('navigation discards late save success and error without altering the detached header', async () => {
  for (const failed of [false, true]) {
    const x = setup(); await load(x, false);
    const old = x.current, previousTitle = old.title, saving = x.toggle();
    const fresh = x.replace('game-two');
    if (failed) x.calls[1].reject(Error('old game failed')); else x.calls[1].resolve({ favorite: true });
    await saving;
    assert.equal(fresh.disabled, true);
    assert.equal(fresh.title, 'Checking favorites');
    assert.equal(old.getAttribute('aria-pressed'), 'false');
    assert.equal(old.title, previousTitle);
  }
});

test('stale detached clicks and absent controls perform no requests', async () => {
  const x = setup(), stale = x.current; x.replace('game-two');
  const detached = x.toggle(stale); await tick();
  assert.equal(x.calls.length, 0);
  await detached;
  x.replace(null); await x.sync();
  assert.equal(x.calls.length, 0);
});
