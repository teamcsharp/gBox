// The blueprint look switch (clients/web/viz/blueprint-look.js): the PC's MercMode setting read from GET /api/mercmode
// and set through POST /api/mercmode {host, blueprint_look}, confirmed from the route's fresh status; the shells load it
// before the panels that use it.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const B = require('../clients/web/viz/blueprint-look.js');

const DATA = { hosts: [
  { name: 'lilspark', id: 'w123', settings: { blueprint_look: false }, desired_settings: { blueprint_look: true },
    current_run: { session_id: 'w123-re5' } },
  { name: 'i9-NUC', id: 'w9', settings: { enabled: true }, desired_settings: { enabled: true } },
  { name: 'OldPC', id: 'w7', settings: null, desired_settings: null }] };

test('the host row is found by the run, the worker id or the PC name, and the setting is read from it', () => {
  assert.equal(B.hostFor(DATA, { sid: 'w123-re5' }).name, 'lilspark');
  assert.equal(B.hostFor(DATA, { sid: 'w123-other' }).name, 'lilspark');           // the session id's worker prefix
  assert.equal(B.hostFor(DATA, { pc: 'LILSPARK' }).name, 'lilspark');
  assert.equal(B.hostFor(DATA, { sid: 'nobody-x', pc: 'elsewhere' }), null);
  assert.deepEqual(B.read(DATA, { sid: 'w123-re5' }), { host: 'lilspark', on: false, reason: '' });  // the applied setting, not the desired one
  assert.equal(B.read(DATA, { pc: 'i9-NUC' }).on, null);                              // an older gBox there
  assert.match(B.read(DATA, { pc: 'i9-NUC' }).reason, /older gBox/);
  assert.equal(B.read(DATA, { pc: 'OldPC' }).on, null);
  assert.match(B.read({ hosts: [] }, { sid: 'w123-re5' }).reason, /No gBox PC owns/);
  assert.equal(B.read(undefined, {}).host, null);
});

test('set posts the PC and the flag to the MercMode route and confirms from the fresh status', async () => {
  const calls = [];
  const api = async (url, body, method) => {
    calls.push({ url, body, method });
    if (method === 'GET') return DATA;
    return { hosts: [{ name: 'lilspark', id: 'w123', settings: { blueprint_look: body.blueprint_look } }] };
  };
  assert.deepEqual(await B.fetch(api, { sid: 'w123-re5' }), { host: 'lilspark', on: false, reason: '' });
  assert.deepEqual(calls.at(-1), { url: '/api/mercmode', body: undefined, method: 'GET' });
  assert.deepEqual(await B.set(api, 'lilspark', true), { host: 'lilspark', on: true, reason: '' });
  assert.deepEqual(calls.at(-1), { url: '/api/mercmode', body: { host: 'lilspark', blueprint_look: true }, method: 'POST' });
  await assert.rejects(B.set(api, '', true), /needs the PC/);
  await assert.rejects(B.set(api, 'lilspark', 'yes'), /needs the PC/);
  // a status that does not show the new value is not a success
  const stubborn = async (url, body, method) => method === 'GET' ? DATA : { hosts: [{ name: 'lilspark', settings: { blueprint_look: false } }] };
  await assert.rejects(B.set(stubborn, 'lilspark', true), /did not confirm/);
  assert.match(B.message(true), /grid textures.*next round/);
  assert.match(B.message(false), /own textures.*next round/);
});

test('the switch says what it does, when it applies, and is disabled until the setting is known', () => {
  const on = B.html({ host: 'lilspark', on: true, attr: 'data-bl-scope="3"' });
  assert.match(on, /Blueprint look \(grid textures on the level\)/);
  assert.match(on, /applies at the next round · MercMode on lilspark/);
  assert.match(on, /<input type="checkbox" data-blueprint-look data-bl-scope="3"[^>]*aria-checked="true" checked>/);
  const off = B.html({ host: 'lilspark', on: false });
  assert.match(off, /aria-checked="false">/);
  assert.doesNotMatch(off, /checked>/);
  const unknown = B.html({ host: null, on: null, reason: 'No gBox PC owns <this> game' });
  assert.match(unknown, /aria-checked="mixed" disabled>/);
  assert.match(unknown, /No gBox PC owns &#60;this&#62; game/);
  assert.doesNotMatch(unknown, /<this>/);
  assert.match(B.html({ host: 'lilspark', on: true, disabled: true }), /checked disabled>/);
  assert.match(B.html({ cls: 'bl-row' }), /class="bl-row"/);
});

test('every shell loads the module before the panels that use it, and it never names a token or a RAM address', () => {
  const root = path.join(__dirname, '..', 'clients');
  const web = fs.readFileSync(path.join(root, 'web', 'index.html'), 'utf8');
  const desktop = fs.readFileSync(path.join(root, 'desktop', 'index.html'), 'utf8');
  const mini = fs.readFileSync(path.join(root, 'desktop', 'mini.html'), 'utf8');
  const live = fs.readFileSync(path.join(root, 'web', 'mercs-live.html'), 'utf8');
  assert.match(web, /<script src="\/viz\/blueprint-look\.js"><\/script>\s*<script src="\/viz\/mercs-clock\.js"><\/script>\s*<script src="\/viz\/re5-modifiers\.js"><\/script>/);
  assert.match(desktop, /<script src="\.\.\/web\/viz\/blueprint-look\.js"><\/script>\s*<script src="\.\.\/web\/viz\/mercs-clock\.js"><\/script>/);
  assert.match(mini, /<script src="\.\.\/web\/viz\/blueprint-look\.js"><\/script>\s*<script src="\.\.\/web\/viz\/mercs-clock\.js"><\/script>/);
  assert.match(live, /<script src="\/viz\/blueprint-look\.js"><\/script><script src="\/viz\/re5-modifiers\.js"><\/script>/);
  const source = fs.readFileSync(path.join(root, 'web', 'viz', 'blueprint-look.js'), 'utf8');
  assert.doesNotMatch(source, /api_token|Bearer|0x[0-9a-f]{6,}/i);
  assert.match(source, /\/api\/mercmode/);                       // the existing settings route, no new one
  assert.doesNotMatch(source, /\/api\/(blueprint|jobs|switch_mods)/);
});
