// Bot demos on any PC (clients/web/viz/bot-demo.js and its wiring in both shells): "🤖 Bot demo on <PC>" for every
// online PC, this one included, in the library cards, the right-click menu, the Sessions header, and in the desktop app
// the docked game's right-click menu and a conversation's game chip. The Sessions header says "🤖 Bot demo" and keeps
// Stop and the coach box; a coach note sent on this PC hands the game the keyboard back.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const BD = require('../clients/web/viz/bot-demo.js');

const ROOT = path.join(__dirname, '..', 'clients');
const read = p => fs.readFileSync(path.join(ROOT, p), 'utf8');
const WORKERS = [{ name: 'i9-NUC', os: 'windows', online: true }, { name: 'lilspark', os: 'linux', online: true },
                 { name: 'JAYBUILTFINALE', os: 'windows', online: true }, { name: 'gone', os: 'windows', online: false }];

test('every online PC, this one first, then the Spark', () => {
  const pcs = BD.pcs(WORKERS, 'JAYBUILTFINALE');
  assert.deepEqual(pcs.map(p => p.name), ['JAYBUILTFINALE', 'lilspark', 'i9-NUC']);
  assert.deepEqual(pcs.map(p => p.label), ['🤖 Bot demo on JAYBUILTFINALE (this PC)', '🤖 Bot demo on lilspark (the Spark)',
                                           '🤖 Bot demo on i9-NUC']);
  assert.deepEqual(BD.pcs(WORKERS, '').map(p => p.name), ['lilspark', 'i9-NUC', 'JAYBUILTFINALE']);   // a browser
  assert.deepEqual(BD.pcs(null, 'x'), []);
  const html = BD.itemsHTML(BD.pcs(WORKERS, 'JAYBUILTFINALE'));
  assert.deepEqual([...html.matchAll(/data-bot-demo="([^"]+)"/g)].map(m => m[1]), ['JAYBUILTFINALE', 'lilspark', 'i9-NUC']);
  assert.match(html, /the bot waits while you type/);
  assert.match(BD.itemsHTML([]), /No PC is online/);
  assert.equal(BD.launchPath('re4 x', 'i9-NUC'), '/api/games/re4%20x/launch?node=i9-NUC&autoplay=true');
});

test('the header chip: only for a bot demo', () => {
  assert.equal(BD.badgeHTML({ session_id: 's' }), '');
  assert.match(BD.badgeHTML({ bot_demo: true }), /🤖 Bot demo/);
  assert.match(BD.badgeHTML({}, { demo: true, running: true, mission: 'playbook: re4_merc_bot' }), /playbook: re4_merc_bot/);
});

test('the menu picks a PC and launches there', () => {
  const nodes = [];
  const el = { style: {}, innerHTML: '', id: '', contains: () => true, setAttribute() {} };
  const doc = { body: { append: n => nodes.push(n) }, getElementById: () => nodes[0] || null, createElement: () => el,
                addEventListener() {}, removeEventListener() {} };
  const launched = [];
  const m = BD.open(doc, { x: 5, y: 6, gid: 're4', title: 'RE4', pcs: BD.pcs(WORKERS, 'i9-NUC'), launch: (g, pc) => launched.push([g, pc]) });
  assert.equal(m.el.style.display, 'flex');
  assert.match(m.el.innerHTML, /RE4: bot demo on/);
  m.el.onclick({ target: { closest: () => ({ dataset: { botDemo: 'i9-NUC' } }) } });
  assert.deepEqual(launched, [['re4', 'i9-NUC']]);
  assert.equal(m.el.style.display, 'none');
});

test('web shell: the card, the right-click menu and the Sessions header offer it; the header says Bot demo', () => {
  const web = read('web/index.html');
  assert.match(web, /<script src="\/viz\/bot-demo\.js"><\/script>/);
  assert.match(web, /onclick='botDemoMenu\(event, \$\{JSON\.stringify\(g\.game_id\)\}, \$\{JSON\.stringify\(g\.title\)\}\)'>🤖<\/button>/);
  assert.match(web, /GBoxBotDemo\.badgeHTML\(s\)/);
  assert.match(web, /id="session-bot-demo"[^>]*botDemoMenu\(event/);
  assert.match(web, /aria-label="Stop" onclick='hardStop/);                       // Stop stays
  assert.match(web, /GBoxBotDemo\.pcs\(TRAY\.ws, window\.GBOX_LOCAL\?\.worker\)/);
  // a coach note sent while the game runs on this PC: the game gets the keyboard back (desktop: gamefocus)
  assert.match(web, /onSent: \(\) => \{[\s\S]{0,300}console\.log\("GBOX:" \+ JSON\.stringify\(\{ ev: "gamefocus", sid \}\)\)/);
});

test('desktop shell: the docked game\'s right-click menu and the game chip offer it, launched through the view', () => {
  const desk = read('desktop/index.html');
  assert.match(desk, /<script src="\.\.\/web\/viz\/bot-demo\.js"><\/script>/);
  assert.match(desk, /botDemoItems\(\)\.map\(p => \[`bot:\$\{p\.name\}`, esc\(p\.label\)\]\)/);
  assert.match(desk, /if \(a\.startsWith\("bot:"\)\) return botDemoInView\(EMB\.game, a\.slice\(4\)\);/);
  assert.match(desk, /GBoxBotDemo\.itemsHTML\(botDemoItems\(\)\)/);
  assert.match(desk, /else if \(b\.dataset\.botDemo\) botDemoInView\(chip\.dataset\.g, b\.dataset\.botDemo\);/);
  assert.match(desk, /botDemoLaunch\(\$\{JSON\.stringify\(gid\)\}, \$\{JSON\.stringify\(pc\)\}\)/);
  assert.match(desk, /else if \(m\.ev === "gamefocus"\) gameFocus\(\);/);
  assert.match(desk, /GBoxBotDemo\.pcs\(BOTPCS\.list, S\?\.workerName\)/);       // S may not be loaded yet
});

test('the coach box tells its host when a note went in', async () => {
  const C = require('../clients/web/viz/autoplay-coach.js');
  const listeners = {};
  const input = { value: 'aim higher', addEventListener: (ev, fn) => { listeners[ev] = fn; }, blur() {} };
  const status = { dataset: {} };
  const box = { querySelector: s => s === 'input' ? input : status };
  const host = { ownerDocument: null, matches: () => true, querySelector: () => box };
  Object.assign(host, box);
  const sent = [];
  const ctl = C.mount(host, { sid: 's1', api: async () => ({ note: 1, number: 7, message_id: 'm', captures: {} }),
                              onSent: out => sent.push(out.note), sleep: async () => {}, hold: 0 });
  assert.ok(ctl);
  listeners.keydown({ key: 'Enter', stopPropagation() {}, preventDefault() {} });
  await new Promise(r => setTimeout(r, 10));
  assert.deepEqual(sent, [1]);
});
