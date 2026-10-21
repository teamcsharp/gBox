// Sessions view header: the build a session runs, named and renamed in place (clients/web/viz/session-build.js, mounted
// by clients/web/index.html; the desktop app shows that shell in its Play webview and hears renames over GBOX:).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const SB = require('../clients/web/viz/session-build.js');
const LBF = require('../clients/web/viz/launch-bar.js');

const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
const desk = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

const GID = '65b7187589166b26', FOLDER = 'auf_dm1_bondcombat_uwbthug';
const MOD = { session_id: 'w1-s7', game_id: GID, title: '007 - Agent Under Fire (USA)', state: 'running', adapter: 'dolphin',
  mod: FOLDER, collection_mod: FOLDER, mod_build: FOLDER };
const STOCK = { session_id: 'w1-s8', game_id: GID, title: '007 - Agent Under Fire (USA)', state: 'running', adapter: 'dolphin' };

// ---------- a header just big enough for the controller: #session-title, #session-build (innerHTML), the field ----------
function header(session) {
  const html = SB.titleHTML(session);
  const title = { attrs: {}, setAttribute(k, v) { this.attrs[k] = v; } };
  const build = { innerHTML: (html.match(/<span class="sb-build"[^>]*>([\s\S]*)<\/span>$/) || [])[1] || null, focused: false };
  let input = null;
  build.querySelector = sel => {
    if (sel !== '[data-sb-input]' || !/data-sb-input/.test(build.innerHTML || '')) return null;
    const value = (build.innerHTML.match(/ value="([^"]*)"/) || [])[1] || '';
    if (!input || input.html !== build.innerHTML) input = { html: build.innerHTML, value: value.replace(/&#(\d+);/g, (_, n) => String.fromCharCode(+n)),
      focus() { build.focused = true; }, select() { this.selected = true; } };
    return input;
  };
  const listeners = {};
  const head = { html, title, build, listeners,
    querySelector: sel => sel === '#session-build' ? (build.innerHTML === null ? null : build) : sel === '#session-title' ? title : null,
    contains: () => true,
    addEventListener(t, fn) { (listeners[t] ||= []).push(fn); }, removeEventListener(t, fn) { listeners[t] = (listeners[t] || []).filter(f => f !== fn); } };
  return head;
}
function apiStub(answer = (p, b) => ({ key: `${GID}/${FOLDER}`, display_name: (b && b.display_name) || '', label: (b && b.display_name) || FOLDER })) {
  const calls = [];
  const api = async (p, body, method) => { calls.push({ path: p, body, method }); const r = answer(p, body, method); if (r instanceof Error) throw r; return r; };
  return { api, calls };
}
// an event whose target sits in the header: closest(sel) answers the element the selector names
function ev(kind, extra = {}) {
  const stops = { prevented: 0, stopped: 0 };
  const target = { closest: sel => {
    if (kind === 'name' && sel === '[data-sb]') return { getAttribute: () => 'rename' };
    if (kind === 'name' && sel === '.sb-name[data-sb]') return {};
    if (kind === 'fav' && sel === '[data-sb]') return { getAttribute: () => 'favorite' };
    if (kind === 'title' && sel === '[data-sb]') return extra.stock ? null : { getAttribute: () => 'rename' };
    if (kind === 'field' && sel === '[data-sb-input]') return { value: extra.value };
    return null;
  } };
  return { target, key: extra.key, preventDefault() { stops.prevented++; }, stopPropagation() { stops.stopped++; }, stops };
}
const mountOn = (session, api, more = {}) => { const head = header(session); const ctl = SB.mount(head, { session, api, document: null, ...more }); return { head, ctl }; };

test('the header shows the game, then the build it runs: its display name, else its folder name; ✎ "Rename this build"', () => {
  const named = SB.titleHTML({ ...MOD, mod_title: 'Bond vs. the UWB thug' });
  assert.match(named, /<b class="sb-game" id="session-title" data-sb="rename" title="Rename this build: Bond vs. the UWB thug">007 - Agent Under Fire \(USA\)<\/b>/);
  assert.match(named, /<span class="sb-build" id="session-build" data-key="65b7187589166b26\/auf_dm1_bondcombat_uwbthug">/);
  assert.match(named, /<span class="sb-sep" aria-hidden="true">·<\/span><b class="sb-name" data-sb="rename" role="button" tabindex="0" title="Rename this build: Bond vs. the UWB thug \(folder auf_dm1_bondcombat_uwbthug\)">Bond vs. the UWB thug<\/b>/);
  assert.match(named, /<button class="sb-ico" type="button" data-sb="rename" title="Rename this build" aria-label="Rename this build">✎<\/button>/);
  const plain = SB.titleHTML(MOD);
  assert.match(plain, /<b class="sb-name"[^>]*title="Rename this build \(folder auf_dm1_bondcombat_uwbthug, no name of its own yet\)">auf_dm1_bondcombat_uwbthug<\/b>/);
  // a staged alias (<mod>~<build>) is still that build; collection_mod names it; a favorite shows its ★
  assert.equal(SB.buildOf({ game_id: GID, mod: `${FOLDER}~1a2b` }).name, FOLDER);
  assert.equal(SB.buildOf({ game_id: GID, mod: `${FOLDER}~1a2b`, collection_mod: FOLDER }).key, `${GID}/${FOLDER}`);
  assert.match(SB.titleHTML({ ...MOD, mod_favorite: true }), /<span class="sb-star" title="A favorite build: listed first and kept">★<\/span>/);
  assert.match(SB.titleHTML({ ...MOD, title: '<Bond> & "Q"', mod_title: '<b>x</b>' }), /&#60;Bond&#62; &#38; &#34;Q&#34;[\s\S]*&#60;b&#62;x&#60;\/b&#62;/);
});

test('the stock game: no build to rename, a tooltip says so, and nothing renames its title', async () => {
  const html = SB.titleHTML(STOCK);
  assert.equal(html, '<b class="sb-game" id="session-title" data-stock="1" title="Stock game, no build to rename">007 - Agent Under Fire (USA)</b>');
  assert.doesNotMatch(html, /data-sb|✎|<input/);
  for (const s of [STOCK, { ...STOCK, mod: '' }, { ...STOCK, mod: '~' }, { ...STOCK, mod: FOLDER, game_id: '' }]) assert.equal(SB.buildOf(s), null);
  const { api, calls } = apiStub();
  const { head, ctl } = mountOn(STOCK, api);
  assert.deepEqual(Object.keys(head.listeners), [], 'no click / key handlers on a stock header');
  assert.equal(ctl.start(), false);
  ctl.onClick(ev('title', { stock: true }));
  assert.equal(await ctl.save('Renamed stock game'), null);
  await ctl.favorite();
  assert.equal(calls.length, 0, 'nothing is ever sent for the stock game');
  assert.match(SB.titleHTML(STOCK), /title="Stock game, no build to rename"/);
});

test('click the build name: an inline field; Enter saves through PATCH /api/builds/{game}/{folder}; ★ Favorite this build after', async () => {
  const { api, calls } = apiStub((p, b, m) => m === 'PUT' ? { key: `${GID}/${FOLDER}`, favorite: true }
    : { key: `${GID}/${FOLDER}`, display_name: b.display_name, label: b.display_name || FOLDER });
  const renamed = [], starred = [];
  const { head, ctl } = mountOn(MOD, api, { onRenamed: i => renamed.push(i), onFavorite: i => starred.push(i) });
  assert.deepEqual(Object.keys(head.listeners).sort(), ['click', 'focusout', 'input', 'keydown']);
  ctl.onClick(ev('name'));
  assert.equal(ctl.st.editing, true);
  assert.match(head.build.innerHTML, /<input class="sb-input" data-sb-input type="text" value="auf_dm1_bondcombat_uwbthug" size="28" maxlength="120" aria-label="Build name" placeholder="auf_dm1_bondcombat_uwbthug" title="Enter saves · Esc cancels · empty restores the original name \(auf_dm1_bondcombat_uwbthug\)" spellcheck="false" autocomplete="off" data-nomic>/);
  assert.equal(head.build.focused, true, 'the field takes the focus');
  const typing = { size: 28, value: 'Bond (combat) vs UWB thug - it works in dm1' };
  ctl.onInput({ target: { closest: s => s === '[data-sb-input]' ? typing : null } });
  assert.equal(typing.size, 45, 'the field grows with the name');
  const enter = ev('field', { key: 'Enter', value: '  Bond (combat) vs UWB thug  ' });
  ctl.onKey(enter); await tick(); await tick();
  assert.equal(enter.stops.stopped, 1, 'the key never reaches the game or the shell');
  assert.deepEqual(calls[0], { path: `/api/builds/${GID}/${FOLDER}`, body: { display_name: 'Bond (combat) vs UWB thug' }, method: 'PATCH' });
  assert.match(head.build.innerHTML, /<b class="sb-name"[^>]*>Bond \(combat\) vs UWB thug<\/b>/);
  assert.doesNotMatch(head.build.innerHTML, /<input/);
  assert.equal(head.title.attrs.title, 'Rename this build: Bond (combat) vs UWB thug');
  assert.match(head.build.innerHTML, /<span class="sb-note" role="status" title="Shown on the Mods page, in Builds, Special builds, the launch bar and notifications; the folder stays auf_dm1_bondcombat_uwbthug">✓ Renamed<\/span>/);
  assert.deepEqual(renamed, [{ game_id: GID, name: FOLDER, key: `${GID}/${FOLDER}`, display_name: 'Bond (combat) vs UWB thug', label: 'Bond (combat) vs UWB thug' }]);
  // ★ Favorite this build: the favorites endpoint (#1656)
  assert.match(head.build.innerHTML, /<button class="act sb-fav" type="button" data-sb="favorite" title="Keep this build:[^"]*">★ Favorite this build<\/button>/);
  ctl.onClick(ev('fav')); await tick(); await tick();
  assert.deepEqual(calls[1], { path: `/api/builds/${GID}/${FOLDER}/favorite`, body: { favorite: true }, method: 'PUT' });
  assert.doesNotMatch(head.build.innerHTML, /★ Favorite this build/);
  assert.match(head.build.innerHTML, /<span class="sb-star" title="A favorite build: listed first and kept">★<\/span>/);
  assert.match(head.build.innerHTML, />✓ Favorite<\/span>/);
  assert.deepEqual(starred, [{ game_id: GID, name: FOLDER, key: `${GID}/${FOLDER}`, favorite: true }]);
  // the ✎, the game title and F2 / Enter on the name open the field too
  ctl.onClick(ev('title')); assert.equal(ctl.st.editing, true); ctl.cancel();
  ctl.onKey(ev('name', { key: 'F2' })); assert.equal(ctl.st.editing, true); ctl.cancel();
  // a starred build is not offered again
  ctl.start(); ctl.onKey(ev('field', { key: 'Enter', value: 'Bond v3' })); await tick(); await tick();
  assert.doesNotMatch(head.build.innerHTML, /★ Favorite this build/);
});

test('Esc cancels: no request, the name stays, the field closes (and a later blur does not save)', async () => {
  const { api, calls } = apiStub();
  const { head, ctl } = mountOn({ ...MOD, mod_title: 'Bond combat' }, api);
  ctl.onClick(ev('name'));
  assert.match(head.build.innerHTML, /value="Bond combat"/);
  const esc = ev('field', { key: 'Escape', value: 'Something else' });
  ctl.onKey(esc);
  assert.equal(esc.stops.prevented, 1); assert.equal(esc.stops.stopped, 1);
  assert.equal(ctl.st.editing, false);
  assert.match(head.build.innerHTML, /<b class="sb-name"[^>]*>Bond combat<\/b>/);
  ctl.onFocusOut(ev('field', { value: 'Something else' })); await tick();
  assert.equal(calls.length, 0);
  // unchanged Enter sends nothing either
  ctl.start(); ctl.onKey(ev('field', { key: 'Enter', value: ' Bond combat ' })); await tick();
  assert.equal(calls.length, 0);
  // leaving the field keeps what was typed (as the Mods cards do)
  ctl.start(); ctl.onFocusOut(ev('field', { value: 'Bond combat 2' })); await tick(); await tick();
  assert.deepEqual(calls.map(c => c.body), [{ display_name: 'Bond combat 2' }]);
});

test('an empty name restores the original (the folder name); a failed save says so and keeps the name', async () => {
  const { api, calls } = apiStub();
  const { head, ctl } = mountOn({ ...MOD, mod_title: 'Bond combat' }, api);
  ctl.start(); ctl.onKey(ev('field', { key: 'Enter', value: '   ' })); await tick(); await tick();
  assert.deepEqual(calls[0].body, { display_name: '' });
  assert.match(head.build.innerHTML, /<b class="sb-name"[^>]*>auf_dm1_bondcombat_uwbthug<\/b>/);
  assert.match(head.build.innerHTML, /Original name restored/);
  assert.doesNotMatch(head.build.innerHTML, /★ Favorite this build/, 'no ★ offer for a restored name');
  const bad = apiStub(() => new Error('404 no build'));
  const x = mountOn({ ...MOD, mod_title: 'Bond combat' }, bad.api);
  x.ctl.start(); x.ctl.onKey(ev('field', { key: 'Enter', value: 'New' })); await tick(); await tick();
  assert.match(x.head.build.innerHTML, /<b class="sb-name"[^>]*>Bond combat<\/b>/);
  assert.match(x.head.build.innerHTML, /<span class="sb-note" role="status" title="404 no build">⚠ rename failed<\/span>/);
});

test('a rename made elsewhere (Mods, Builds, the desktop app) reaches the header on the tray poll, never under typing', () => {
  const { api } = apiStub();
  const { head, ctl } = mountOn(MOD, api);
  assert.equal(ctl.sync({ ...MOD, mod_title: 'From the Mods page' }), true);
  assert.match(head.build.innerHTML, />From the Mods page<\/b>/);
  assert.equal(ctl.sync({ ...MOD, mod_title: 'From the Mods page' }), false, 'unchanged: no redraw');
  assert.equal(ctl.sync({ ...MOD, game_id: 'other' }), false, 'another build is not this one');
  ctl.start();
  assert.equal(ctl.sync({ ...MOD, mod_title: 'Later' }), false);
  assert.match(head.build.innerHTML, /<input/);
});

test('a tray poll that left before the save cannot put the old name back for a few seconds', async () => {
  let clock = 1000;
  const { api } = apiStub();
  const { head, ctl } = mountOn(MOD, api, { now: () => clock });
  ctl.start(); ctl.onKey(ev('field', { key: 'Enter', value: 'Bond combat' })); await tick(); await tick();
  assert.equal(ctl.sync(MOD), false, 'the stale row (no mod_title yet) is ignored');
  assert.match(head.build.innerHTML, />Bond combat<\/b>/);
  clock += 9000;
  assert.equal(ctl.sync({ ...MOD, mod_title: 'Renamed again elsewhere' }), true);
  assert.match(head.build.innerHTML, />Renamed again elsewhere<\/b>/);
});

test('the dictation wrapper leaves the field alone (data-nomic, as #1656 did for the Mods cards)', () => {
  const m = web.match(/const skip = (el => [^\n]*?);\r?\n/);
  assert.ok(m, 'the shell\'s dictation wrapper skip() is present');
  const skip = vm.runInNewContext(m[1]);
  const html = SB.buildHTML(SB.buildOf(MOD), { editing: true });
  const field = { type: 'text', closest: () => null, offsetParent: {}, dataset: /\sdata-nomic[\s>]/.test(html) ? { nomic: '' } : {} };
  assert.equal(skip(field), true, 'the rename field is never wrapped');
  assert.equal(skip({ type: 'text', closest: () => null, offsetParent: {}, dataset: {} }), false, 'a plain field would be');
});

test('the web shell wires it: the module, the header title, the mount after render, the tray poll, the desktop bridge', () => {
  assert.match(web, /<script src="\/viz\/session-build\.js"><\/script>/);
  assert.match(web, /GBoxSessionBuild\.titleHTML\(s\)/);
  assert.match(web, /SESSIONBUILD\.session = s;/);
  // (no session: the view follows a game that plays unless the operator chose the list, viz/session-follow.js)
  assert.match(web, /sessionsView\.after = \(sid, mode\) => \{\r?\n  if \(!sid\) \{ if \(!FOLLOW\.list\) followWatch\(null\); return; \}[^\n]*\r?\n  syncSessionFav\(\);\r?\n  const head = \$\("#session-head"\);\r?\n  sessionBuildMount\(head\);/);
  assert.match(web, /SESSIONBUILD\.ctl\.sync\(ss\.find\(x => x\.session_id === SESSIONBUILD\.ctl\.sid\)\)/);
  assert.match(web, /onRenamed: info => sessionBuildChanged\("buildrenamed", info\)/);
  assert.match(web, /function sessionBuildChanged\(ev, info\) \{\r?\n  trayTick\(\);/);
  assert.ok(web.indexOf('const SESSIONBUILD') < web.indexOf('async function trayTick'), 'declared before the first tray poll');
  assert.match(desk, /m\.ev === "buildrenamed" \|\| m\.ev === "buildfavorite"\) buildRenamedMsg\(m\)/);
  assert.match(desk, /GBOX_LAUNCH_BAR\?\.rename\?\.\(/);
});

test('the launch bar names a build renamed while it launches', () => {
  const LB = LBF({ document: undefined });
  const m = LB.createModel();
  m.remote([{ id: 'L', tool: 'launch_game', state: 'running', created: 100,
    input: { game: { game_id: GID, title: '007 - Agent Under Fire (USA)' }, mod: `${FOLDER}~ab12` } }]);
  assert.equal(m.view().title, `Launching 007 - Agent Under Fire (USA) · ${FOLDER}~ab12`);
  assert.equal(m.rename(GID, FOLDER, 'Bond combat'), true);
  assert.equal(m.view().title, 'Launching 007 - Agent Under Fire (USA) · Bond combat');
  m.rename('other', FOLDER, 'Nope');
  assert.equal(m.view().title, 'Launching 007 - Agent Under Fire (USA) · Bond combat');
});
