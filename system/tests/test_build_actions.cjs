// #1656 build actions (clients/web/viz/build-actions.js) and where they show: "What this changes" with its badges and
// "Where to look in game", the 🗑 Delete dialog (everywhere / only this PC) and the ⚑ Report dialog (quick reasons + text)
// on the Mods cards, the Builds rows and the game menu's Special builds options.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const BA = require('../clients/web/viz/build-actions.js');
const MG = require('../clients/web/viz/mods-gallery.js');
const BV = require('../clients/web/viz/builds.js');
const GM = require('../clients/web/viz/game-menu.js');

const RECORDED = { lines: ['Replaces the game\'s cast with Wrestlers: 2 characters swapped (kane → neo, rock → smith)'], where: 'slots: neo, smith',
                   status: 'recorded', badge: '', inferred: false, sources: ['marker cast'] };
const NONE = { lines: ['Inferred from the name: 007 Agent Under Fire: multiplayer map dm1; characters Bond (combat)'],
               where: 'Multiplayer > map dm1 > play as Bond (combat)', where_inferred: true, status: 'no_changes',
               badge: 'No changes from the original game found: this looks like a test build', inferred: false };
const UNKNOWN = { lines: [], where: '', status: 'unknown', badge: 'Changes not recorded', inferred: false };
const GUESS = { lines: ['Inferred from the name: 007 Agent Under Fire'], where: '', status: 'inferred', badge: '', inferred: true };
const BUILD = { key: 'auf/auf_dm1_bondcombat_uwbthug', name: 'auf_dm1_bondcombat_uwbthug', game_id: 'auf', game_title: '007 Agent Under Fire',
                mod_title: 'auf_dm1_bondcombat_uwbthug', writer: 'auf', size: 1459978240, own_size: 2048, what: NONE,
                where: [{ where: 'spark', label: 'Spark collection' }, { where: 'pc', node: 'MYPC', online: true, label: 'MYPC (staged copy)' }] };

test('What this changes: recorded lines + where, the no-changes and not-recorded badges, inferred tags, the compact line', () => {
  const rec = BA.whatHTML(RECORDED);
  assert.match(rec, /<div class="ba-what ba-recorded"><div class="ba-h">What this changes<\/div><ul class="ba-lines"><li>Replaces the game&#39;s cast/);
  assert.match(rec, /<b>Where to look in game:<\/b> slots: neo, smith/);
  const none = BA.whatHTML(NONE);
  assert.match(none, /class="ba-what ba-no_changes"/);
  assert.match(none, /<span class="ba-badge ba-none">No changes from the original game found: this looks like a test build<\/span>/);
  assert.match(none, /Multiplayer &#62; map dm1 &#62; play as Bond \(combat\) <span class="ba-tag">inferred<\/span>/);
  assert.match(BA.whatHTML(UNKNOWN), /<span class="ba-badge ba-unknown">Changes not recorded<\/span>/);
  assert.match(BA.whatHTML(GUESS), /What this changes <span class="ba-tag"[^>]*>inferred<\/span>/);
  const compact = BA.whatHTML(RECORDED, { compact: true });
  assert.match(compact, /class="ba-what ba-compact" title="Replaces the game&#39;s cast[^"]*Where to look: slots: neo, smith">/);
  assert.ok(compact.includes('<span class="ba-line">Replaces the game&#39;s cast'));
  assert.equal(BA.whatHTML(null), '');
  assert.equal(BA.reportedHTML({ number: 41, id: 'r' }), '<span class="ba-rep" title="A report was filed on this build: request #41">Reported #41</span>');
  assert.equal(BA.reportedHTML(null), '');
});

test('the delete dialog: name, folder, game, size, where it lives; everywhere by default, only this PC when it has a copy', () => {
  const html = BA.deleteDialogHTML(BUILD, { here: 'MYPC' });
  assert.match(html, /🗑 Delete “auf_dm1_bondcombat_uwbthug”\?/);
  assert.match(html, /<tr><th>Size<\/th><td>2 KB \(1\.36 GB with files shared with the base game\)<\/td><\/tr>/);
  assert.match(html, /<tr><th>Lives on<\/th><td>Spark collection<br>MYPC \(staged copy\)<\/td><\/tr>/);
  assert.match(html, /<input type="radio" name="ba-scope" value="all" checked> Delete everywhere \(Spark collection \+ every PC's copy\)/);
  assert.match(html, /<input type="radio" name="ba-scope" value="node"> Only this PC \(MYPC\)/);
  assert.match(html, /The base game and other builds are never touched/);
  const elsewhere = BA.deleteDialogHTML(BUILD, { here: 'OTHER' });
  assert.match(elsewhere, /value="node" disabled> Only this PC \(OTHER\) \(no copy here\)/);
  assert.deepEqual(BA.deleteCall(BUILD, 'node', 'MYPC'), { path: '/api/builds/auf/auf_dm1_bondcombat_uwbthug/delete', body: { scope: 'node', node: 'MYPC' } });
  assert.deepEqual(BA.deleteCall(BUILD, 'all', 'MYPC').body, { scope: 'all', node: '' });
  assert.equal(BA.deleteResultText(BUILD, { scope: 'all', spark: { removed: ['x'] }, jobs: [{ node: 'MYPC' }], skipped: [{ node: 'LAB', reason: 'offline' }] }),
               'Deleted auf_dm1_bondcombat_uwbthug (Spark collection removed); deleting the copy on MYPC; not deleted: LAB: offline');
});

test('the report dialog: quick reasons including detail loss, a labelled note field, what gets sent', () => {
  const html = BA.reportDialogHTML({ ...BUILD, what: RECORDED });
  assert.match(html, /⚑ Report a problem with “auf_dm1_bondcombat_uwbthug”/);
  for (const [k, l] of [['no_change', "Doesn't show the expected change"], ['broken', 'Character looks broken or garbled'],
                        ['crash', 'Game crashes or freezes'], ['other', 'Other']])
    assert.ok(html.includes(`value="${k}"`) && html.includes(l.replace("'", '&#39;')), k);
  assert.match(html, /name="ba-reason" value="no_change" checked/);
  assert.match(html, /<textarea id="ba-report-note" class="ba-text" data-ba-note[^>]*maxlength="4000"[^>]*data-nomic><\/textarea>/);
  assert.match(html, /value="detail_loss"/);
  assert.match(html, /Note for the ticket/);
  assert.match(html, /newest in-game frame and its fit previews\. It goes to the investigation queue/);
  assert.deepEqual(BA.reportCall(BUILD, 'broken', '  unrecognizable  '), { path: '/api/builds/auf/auf_dm1_bondcombat_uwbthug/report', body: { reason: 'broken', note: 'unrecognizable' } });
});

test('workbench reports link only the selected build and preserve the exact running copy', () => {
  const card = { title: 'Play as Leon', calls: [{ tool: '@launch', input: { mod: 'sa2_re6_leon' } }] };
  const session = { session_id: 'worker-session', game_id: 'sa2', title: 'Sonic Adventure 2', mod: 'sa2_re6_leon~abc123', detail: { worker_name: 'JAYBUILTFINALE' } };
  const b = BA.sessionBuild(card, 'sa2', session);
  assert.equal(b.name, 'sa2_re6_leon'); assert.equal(b.runtime_mod, session.mod);
  assert.equal(b.session_id, session.session_id);
  assert.match(BA.reportDialogHTML(b), /Linked to the game session on JAYBUILTFINALE/);
  assert.deepEqual(BA.reportCall(b, 'detail_loss', '  Decimation removed Leon’s detail.  '), {
    path: '/api/builds/sa2/sa2_re6_leon/report', body: { reason: 'detail_loss', note: 'Decimation removed Leon’s detail.', session_id: 'worker-session' }
  });
  for (const other of [{ ...session, game_id: 'other' }, { ...session, mod: 'metal_sonic' }, undefined])
    assert.equal(BA.sessionBuild(card, 'sa2', other).session_id, undefined);
  assert.equal(BA.sessionBuild({ calls: [] }, 'sa2', session), null);
  const shell = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  assert.match(shell, /data-report-mod[^>]*>Report problem<\/button>/);
  assert.match(shell, /GBoxBuildActions\.sessionBuild\(m, gid, session\)/);
});

// a document just big enough for open(): one modal element whose controls answer what the dialog reads
function fakeDoc(state = {}) {
  const made = [];
  const doc = { body: { appendChild(el) { el.attached = true; } }, made,
    createElement() {
      const el = { className: '', innerHTML: '', listeners: {}, removed: false, status: { textContent: '' }, btn: { disabled: false },
        addEventListener(t, f) { this.listeners[t] = f; }, remove() { this.removed = true; },
        querySelector(sel) {
          if (sel === '[data-ba-status]') return this.status;
          if (sel === '[data-ba="go"]') return this.btn;
          if (sel.includes('ba-scope')) return { value: state.scope || 'all' };
          if (sel.includes('ba-reason')) return { value: state.reason || 'no_change' };
          if (sel === '[data-ba-note]') return { value: state.note || '' };
          return null;
        } };
      made.push(el); return el;
    } };
  return doc;
}
const press = (el, act) => el.listeners.click({ target: { closest: s => s === '[data-ba]' ? { dataset: { ba: act } } : null } });
const tick = () => new Promise(r => setTimeout(r, 0));

test('open(): delete posts the chosen scope, a failure says why and stays open, cancel answers null', async () => {
  const calls = [];
  let fail = true;
  const api = async (p, body, method) => { calls.push([method, p, body]); if (fail) throw new Error('409 in use by a running game'); return { key: BUILD.key, jobs: [] }; };
  const doc = fakeDoc({ scope: 'node' });
  const p = BA.open('delete', BUILD, { document: doc, api, here: 'MYPC' });
  const el = doc.made[0];
  assert.ok(el.attached && el.innerHTML.includes('ba-scope'));
  await press(el, 'go');
  assert.equal(el.status.textContent, '⚠ 409 in use by a running game'); assert.equal(el.removed, false); assert.equal(el.btn.disabled, false);
  fail = false;
  await press(el, 'go');
  assert.deepEqual(await p, { key: BUILD.key, jobs: [], scope: 'node' });
  assert.deepEqual(calls.at(-1), ['POST', '/api/builds/auf/auf_dm1_bondcombat_uwbthug/delete', { scope: 'node', node: 'MYPC' }]);
  assert.ok(el.removed);
  const doc2 = fakeDoc();
  const p2 = BA.open('report', BUILD, { document: doc2, api });
  await press(doc2.made[0], 'cancel');
  assert.equal(await p2, null);
  const doc3 = fakeDoc({ reason: 'broken', note: 'HUcast is unrecognizable' });
  const p3 = BA.open('report', BUILD, { document: doc3, api: async (pth, body) => { calls.push(['POST', pth, body]); return { number: 77, id: 'r77' }; } });
  await press(doc3.made[0], 'go');
  assert.deepEqual(await p3, { number: 77, id: 'r77' });
  assert.deepEqual(calls.at(-1)[2], { reason: 'broken', note: 'HUcast is unrecognizable' });
});

// ------------------------------------------------------------------ on the Mods cards
const CARD = { key: 'auf/auf_dm1_bondcombat_uwbthug', name: 'auf_dm1_bondcombat_uwbthug', game_id: 'auf', title: '007 Agent Under Fire',
               mod_title: 'auf_dm1_bondcombat_uwbthug', writer: 'auf', built: 1000, size: 10, own_size: 10, verified: false, changes: [],
               images: [], donor_previews: [], shots: [], card_id: 'c1', state_slot: null, tickets: [], last_launch: null, what: NONE };

test('Broken-build dialog explains temporary preservation and submits the note and PC', async () => {
  const calls = [], doc = fakeDoc({note:'Character destroyed, no crash'});
  const done = BA.open('broken', BUILD, {document:doc, here:'MYPC', api:async (...args)=>{calls.push(args);return {number:7};}});
  assert.match(doc.made[0].innerHTML, /broken files are deleted from Spark too/);
  await press(doc.made[0], 'go');
  assert.deepEqual(await done, {number:7});
  assert.deepEqual(calls[0], ['/api/builds/auf/auf_dm1_bondcombat_uwbthug/broken', {node:'MYPC',note:'Character destroyed, no crash'}, 'POST']);
});

test('Broken mod card has accessible top-left action, static overlay and disabled Play', () => {
  const html = MG.cardHTML({...CARD,broken:{state:'preserved',number:7}});
  assert.match(html, /mg-broken-toggle/);
  assert.match(html, /aria-pressed="true"/);
  assert.match(html, /removed from PC/);
  assert.match(html, /data-mg="play" disabled/);
});

test('Mods card: What this changes under the title, ⚑ Report and 🗑 bottom right, both in the options, Reported #N', () => {
  const html = MG.cardHTML(CARD, {});
  assert.ok(html.indexOf('class="ba-what ba-no_changes"') > html.indexOf('mg-title') && html.indexOf('ba-what') < html.indexOf('mg-btns'));
  assert.match(html, /No changes from the original game found: this looks like a test build/);
  assert.match(html, /<span class="mg-acts"><button class="act" type="button" data-mg="report"[^>]*>⚑ Report<\/button><button class="act mg-del" type="button" data-mg="delete"[^>]*>🗑<\/button><\/span><\/div><\/div><\/article>$/);
  const menu = MG.cardHTML(CARD, { menu: true });
  assert.match(menu, /data-mg="report"[^>]*>⚑ Report a problem…<\/button><button[^>]*data-mg="delete"[^>]*>🗑 Delete…</);
  // the ⚑ build report mark: its own badge in the report row (opens the request)
  const rep = MG.cardHTML({ ...CARD, reported: { number: 9, id: 'r9' } }, {});
  assert.match(rep, /<div class="mg-lfr"><button class="act mg-lf mg-br" type="button" data-mg="request" data-n="9"[^>]*>⚑ Build report #9<\/button><\/div>/);
  // with #318's launch failure ticket too: both badges side by side in one row, the ticket buttons not repeated
  const both = MG.cardHTML({ ...CARD, reported: { number: 9, id: 'r9' }, launch_report: { number: 7, status: 'in_progress', label: 'boot hang' },
                             tickets: [{ number: 7 }, { number: 9 }, { number: 5, title: 'other' }] }, {});
  assert.match(both, /<div class="mg-lfr"><button class="act mg-lf mg-lf-bad" type="button" data-mg="request" data-n="7"[\s\S]*?>⚠ Reported as #7, being investigated<\/button><button class="act mg-lf mg-br" type="button" data-mg="request" data-n="9"[\s\S]*?>⚑ Build report #9<\/button><\/div>/);
  assert.equal((both.match(/class="mg-lfr"/g) || []).length, 1, 'one badge row');
  assert.ok(!/class="act mg-req"[^>]*data-n="(7|9)"/.test(both) && /class="act mg-req"[^>]*data-n="5"/.test(both));
  assert.equal(MG.reportsHTML(null, null), '');
  assert.equal(MG.reportsHTML({ number: 3, verified: true }, null), MG.reportHTML({ number: 3, verified: true }));
});

function mgHost() {
  const el = () => ({ innerHTML: '', textContent: '', dataset: {}, querySelector: () => null });
  const parts = { '[data-mg-grid]': el(), '[data-mg-sum]': el(), '[data-mg-more]': el() };
  let html = '';
  const listeners = {};
  return { parts, listeners, host: { get innerHTML() { return html; }, set innerHTML(v) { html = v; }, querySelector: s => parts[s] || null,
    contains: () => false, addEventListener: (t, f) => (listeners[t] ||= []).push(f), removeEventListener() {} } };
}
const mgTarget = (key, mg) => ({ closest: s => s === '.mg-card' ? { dataset: { key } } : s === '[data-mg]' ? { dataset: { mg } } : null });

test('Mods controller: 🗑 asks where it lives, deletes everywhere (the card goes) or keeps it; ⚑ marks the card Reported #N', async () => {
  const h = mgHost(), seen = [];
  const other = { ...CARD, key: 'auf/keep', name: 'keep', mod_title: 'Keep me', what: RECORDED };
  let answer = { scope: 'all', spark: { removed: ['auf_dm1_bondcombat_uwbthug'] }, jobs: [{ node: 'MYPC' }], skipped: [] };
  const env = { here: 'MYPC', wait: async () => {}, toast: t => seen.push(['toast', t]),
    api: async p => {
      if (p.startsWith('/api/mods/built')) return { items: [CARD, other], cache_dir: '/c' };
      if (p === '/api/workers') return [];
      if (p.startsWith('/api/builds?')) return { items: [{ key: CARD.key, where: BUILD.where, size: 5, own_size: 1 }] };
      throw new Error('unexpected ' + p);
    },
    buildActions: { ...BA, open: async (kind, b) => { seen.push([kind, b.key, (b.where || []).length]); return kind === 'report' ? { number: 12, id: 'r12' } : answer; } } };
  const ctl = MG.mount(h.host, env); await ctl.ready;
  try {
    await ctl.onClick({ target: mgTarget(CARD.key, 'report'), preventDefault() {} });
    assert.deepEqual(seen[0], ['report', CARD.key, 0]);
    assert.match(h.parts['[data-mg-grid]'].innerHTML, /⚑ Build report #12/);
    assert.match(h.parts['[data-mg-grid]'].innerHTML, /⚑ Reported: request #12/);
    answer = { scope: 'node', node: 'MYPC', spark: { removed: [] }, jobs: [{ node: 'MYPC' }], skipped: [] };
    await ctl.onClick({ target: mgTarget(CARD.key, 'delete'), preventDefault() {} });
    assert.deepEqual(seen.find(x => x[0] === 'delete'), ['delete', CARD.key, 2], 'the dialog knows where it lives');
    assert.match(h.parts['[data-mg-grid]'].innerHTML, /data-key="auf\/auf_dm1_bondcombat_uwbthug"/, 'only this PC: the card stays');
    answer = { scope: 'all', spark: { removed: ['x'] }, jobs: [], skipped: [] };
    await ctl.onClick({ target: mgTarget(CARD.key, 'delete'), preventDefault() {} });
    assert.ok(!h.parts['[data-mg-grid]'].innerHTML.includes('data-key="auf/auf_dm1_bondcombat_uwbthug"'), 'deleted everywhere: the card goes');
    assert.match(h.parts['[data-mg-grid]'].innerHTML, /data-key="auf\/keep"/);
    assert.match(seen.at(-1)[1], /^Deleted auf_dm1_bondcombat_uwbthug \(Spark collection removed\)/);
  } finally { ctl.stop(); }
});

// ------------------------------------------------------------------ on the Builds rows
test('Builds row: the compact What this changes line, ⚑ and 🗑 next to Launch, Report… / Delete… in ▾, Reported #N', () => {
  const row = { ...BUILD, label: BUILD.mod_title, kinds: ['file'], kind: 'file', launch_options: [], reported: { number: 3 } };
  const html = BV.rowHTML(row, { opts: row.key }, { here: 'MYPC' });
  assert.match(html, /<div class="bv-nm">[\s\S]*?<\/div><div class="ba-what ba-compact"[^>]*><span class="ba-badge ba-none">No changes from the original game found/);
  assert.match(html, /data-bv="report"[^>]*aria-label="Report">⚑<\/button><button class="act bv-act bv-del" type="button" data-bv="delete"/);
  assert.match(html, /data-bv="report" data-key="auf\/auf_dm1_bondcombat_uwbthug">⚑ Report a problem…<\/button><button[^>]*data-bv="delete" data-key="auf\/auf_dm1_bondcombat_uwbthug">🗑 Delete…/);
  assert.match(html, /<span class="bv-chip ba-rep"[^>]*>Reported #3<\/span>/);
  assert.match(BV.detailsHTML({ key: row.key, name: row.name, what: RECORDED, modifications: {} }), /^<div class="ba-what ba-recorded">/);
});

// ------------------------------------------------------------------ in Special builds
test('Special builds: the build line says what it changes; ⚑ Report… and 🗑 Delete… in the options run the shared dialogs', async () => {
  GM._reset();
  const b = { key: 'auf/auf_dm1_bondcombat_uwbthug', name: 'auf_dm1_bondcombat_uwbthug', mod_title: 'auf_dm1_bondcombat_uwbthug', kind: 'other',
              tickets: [], launch_options: [], rebuild_recipe: null, what: NONE, reported: { number: 4 } };
  const special = () => ({ game_id: 'auf', total: 1, groups: [{ key: 'other', label: 'Other', count: 1, builds: [JSON.parse(JSON.stringify(b))] }] });
  const opened = [];
  const io = { worker: 'MYPC', storage: { getItem: () => '1', setItem() {} },
    api: async p => p.endsWith('/special_builds') ? special() : p.startsWith('/api/builds?') ? { items: [{ key: b.key, where: BUILD.where, size: 9 }] } : [],
    buildActions: { ...BA, open: async (kind, x) => { opened.push([kind, x.game_id, (x.where || []).length]); return kind === 'report' ? { number: 5, id: 'r5' } : { scope: 'all', spark: { removed: ['a'] }, jobs: [], skipped: [] }; } } };
  const host = { innerHTML: '' };
  const s = GM.mountSpecial(io, host, { gid: 'auf', title: 'AUF' });
  await s.settled;
  assert.match(host.innerHTML, /class="gm-what"[^>]*><b style="color:#e88">No changes from the original game found: this looks like a test build<\/b> Inferred from the name/);
  assert.match(host.innerHTML, /Reported #4/);
  assert.match(host.innerHTML, /Where to look: Multiplayer &#62; map dm1 &#62; play as Bond \(combat\)/);
  const click = (act, extra = {}) => host.onclick({ target: { closest: q => q === '[data-gm-sb]' ? { dataset: { gmSb: act, key: b.key, ...extra } } : null }, stopPropagation() {} });
  click('opts');
  assert.match(host.innerHTML, /data-gm-sb="report" data-key="auf\/auf_dm1_bondcombat_uwbthug"[^>]*>⚑ Report a problem…/);
  assert.match(host.innerHTML, /data-gm-sb="delete" data-key="auf\/auf_dm1_bondcombat_uwbthug"[^>]*>🗑 Delete…/);
  click('report'); await tick(); await tick();
  assert.deepEqual(opened[0], ['report', 'auf', 0]);
  assert.match(host.innerHTML, /report filed as request #5/);
  click('delete'); for (let i = 0; i < 6; i++) await tick();
  assert.deepEqual(opened[1], ['delete', 'auf', 2], 'the delete dialog knows where it lives');
  assert.match(host.innerHTML, /🗑 Deleted auf_dm1_bondcombat_uwbthug \(Spark collection removed\)/);
});

test('both shells load build-actions.js before the views that use it; CRLF kept', () => {
  const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  const desk = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
  assert.ok(web.indexOf('/viz/build-actions.js') > 0 && web.indexOf('/viz/build-actions.js') < web.indexOf('/viz/mods-gallery.js'));
  assert.ok(web.indexOf('/viz/build-actions.js') < web.indexOf('/viz/builds.js'));
  assert.ok(desk.indexOf('../web/viz/build-actions.js') > 0 && desk.indexOf('../web/viz/build-actions.js') < desk.indexOf('../web/viz/mods-gallery.js'));
  const src = fs.readFileSync(path.join(__dirname, '../clients/web/viz/build-actions.js'), 'utf8');
  for (const f of [src, web, desk]) assert.ok(!/[^\r]\n/.test(f), 'CRLF line endings kept');
});
