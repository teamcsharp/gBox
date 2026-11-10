// The live map's enemy identities (operator 2026-11-10: "profile pictures of the enemies with names in the live map
// showing them reflected on the map by name and identity and a sidebar with listings and details on each and every
// enemy type"): clients/web/viz/tactical-map.js names each mark, sizes and rings it by tier, shows bosses' portraits,
// and lists the types on the stage (portrait, name, tier, live count, health, what it does, how to kill it) from
// GET /api/mercs/enemies/{title} (gbox/tactical_map.py, gbox/mercs/enemy_identity.py). GBOX_TACTICAL_EVIDENCE=<dir>
// keeps the browser screenshot.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const T = require('../clients/web/viz/tactical-map.js');
const W = require('../clients/desktop/mercs-window.cjs');

const FIX = path.join(__dirname, 'fixtures', 'tactical_map');
const INFO = JSON.parse(fs.readFileSync(path.join(FIX, 'enemy-identities-RE5.json'), 'utf8'));
const RE5 = '010018100CD46000';
const FRAME = { v: 1, seq: 3, title: RE5, units: 'cm', screen: 'playing', live: true, clock: { kills: 17 },
  player: { pos: [0, 0, 0], facing: 0, hp: 1000, hp_max: 1000 },
  enemies: [{ id: 1, pos: [0, 0, 600], hp: 6100, hp_max: 8000, cls: 'uEm20', name: 'Executioner Majini', tier: 'boss', level: 'verified' },
            { id: 2, pos: [40, 0, 640], hp: 800, hp_max: 800, cls: 'uEm10', name: 'Majini', tier: 'normal', level: 'verified' },
            { id: 3, pos: [-400, 0, 200], hp: 700, hp_max: 700, cls: 'uEm11', name: 'Majini (female)', tier: 'normal', level: 'verified' }],
  kinds: { uEm10: { name: 'Majini', count: 1, tier: 'normal', level: 'verified', threat: 'low' },
           uEm20: { name: 'Executioner Majini', count: 1, tier: 'boss', level: 'verified', threat: 'high' },
           uEm11: { name: 'Majini (female)', count: 1, tier: 'normal', level: 'verified', threat: 'low' } } };

function recorder() {
  const calls = [];
  const ctx = new Proxy({}, { get(o, k) { if (k in o) return o[k]; if (k === 'measureText') return s => ({ width: String(s).length * 6 });
    return (...a) => calls.push([k, ...a]); }, set(o, k, v) { o[k] = v; return true; } });
  return { ctx, calls };
}

test('the legend names each type with its tier, bosses first - no class codes, no "low threat"', () => {
  const html = T.kindsHtml(FRAME, (t, c) => `/p/${c}.png`);
  const order = [...html.matchAll(/title="(uEm\d+)"/g)].map(m => m[1]);
  assert.deepEqual(order, ['uEm20', 'uEm10', 'uEm11']);
  assert.match(html, /Executioner Majini ×1 <small class="tm-tier"[^>]*>boss<\/small>/);
  assert.match(html, /Majini \(female\) ×1/);
  assert.doesNotMatch(html, /threat|>uEm20</);
  assert.match(html, /src="\/p\/uEm20\.png"/);
  // a frame from a worker without identities keeps its old wording
  assert.match(T.kindsHtml({ title: RE5, kinds: { uEm10: { name: 'Majini', count: 2, threat: 'low' } } }), /low threat/);
});

test('marks: bosses larger, every one named, the tier in the hover text', () => {
  const v = T.viewOf({ cx: 0, cz: 0, radius: 1500, rot: 0 }, { w: 400, h: 400 });
  const ms = T.marks(FRAME, v).filter(m => m.kind === 'enemy'), by = id => ms.find(m => m.id === id);
  assert.ok(by(1).r > by(2).r * 1.5, 'a boss is drawn larger');
  assert.equal(by(1).name, 'Executioner Majini');
  assert.equal(by(1).tier, 'boss');
  assert.match(by(1).tip, /^Executioner Majini 1 · boss · 6100\/8000 health/);
  const { ctx } = recorder();
  const faces = [];
  const placed = T.enemyLabels(ctx, ms, v, { halo: '#fff', ink: '#000' }, cls => (faces.push(cls), null));
  assert.equal(placed[0].text, 'Executioner Majini', 'the boss is labelled first');
  assert.deepEqual(faces, ['uEm20'], 'portraits are asked only for bosses and dangerous ones');
  assert.ok(placed.some(p => p.text === 'Majini (female)'));
  assert.ok(!placed.some(p => p.id === 2), 'a label that would cover the boss\'s is skipped');
});

test('the sidebar: next heavy, the types on the map with live health, every type with how to kill it', () => {
  const html = T.rosterHtml(FRAME, INFO, (t, c) => `/p/${c}.png`, 'Public Assembly', new Set(['uEm20']));
  assert.match(html, /<b>Next heavy:<\/b> Executioner Majini at kill 20 \(in 3\) · SW fence/);
  const here = html.split('<h4>On the map now</h4>')[1].split('class="tm-all"')[0];
  assert.deepEqual([...here.matchAll(/data-cls="(uEm\d+)"/g)].map(m => m[1]), ['uEm20', 'uEm10', 'uEm11']);
  assert.match(here, /<details class="tm-card" data-cls="uEm20"[^>]* open>/, 'the reader\'s open card stays open');
  assert.match(here, /Executioner Majini ×1/);
  assert.match(here, /HP 6100\/8000/);
  assert.match(here, /<b>Weak point:<\/b>/);
  assert.match(here, /<b>How to kill it:<\/b><ul><li>/);
  assert.match(here, /href="https:\/\/www\.evilresource\.com\/resident-evil-5\/enemies\/executioner" target="_blank" rel="noopener noreferrer"/);
  assert.match(here, /seen and named live/);
  const all = html.split('class="tm-all"')[1];
  assert.equal([...all.matchAll(/class="tm-card"/g)].length, INFO.enemies.length, 'every type of the title');
  assert.match(all, /Chainsaw Majini/);
  assert.equal(T.nextHeavy(INFO, 'Public_Assembly', 71), null);
  assert.equal(T.nextHeavy(INFO, 's406', 0).cls, 'uEm22');
  assert.equal(T.rosterHtml(null, INFO), '');
  assert.doesNotMatch(T.rosterHtml({ ...FRAME, enemies: [{ id: 9, pos: [0, 0, 0], cls: '<x>', name: '<img onerror=1>' }],
                                     kinds: {} }, null), /<img onerror/, 'names are escaped');
});

test('the desktop viewer may read the listing and only portrait images', () => {
  assert.equal(W.request({ path: `/api/mercs/enemies/${RE5}` }, new Set()).method, 'GET');
  assert.throws(() => W.request({ path: `/api/mercs/enemies/${RE5}/uEm20.png` }, new Set()), /Unsupported/);
  assert.equal(W.imagePath(`/api/mercs/enemies/${RE5}/uEm20.png`), `/api/mercs/enemies/${RE5}/uEm20.png`);
  for (const bad of ['/api/sessions', `/api/mercs/enemies/${RE5}/../x.png`, `/api/mercs/enemies/${RE5}/uEm20.jpg`, 42])
    assert.throws(() => W.imagePath(bad), /Unsupported/);
});

// ---- in a real browser: the recorded Public Assembly stage and frame, with identities ----
const REAL_STAGE = JSON.parse(fs.readFileSync(path.join(FIX, 'BLUS30491-public-assembly.stage.json'), 'utf8'));
const REAL_FRAMES = fs.readFileSync(path.join(FIX, 'BLUS30491-public-assembly.frames.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
const PORTRAITS = path.join(__dirname, '..', 'gbox-data', 'mercs', 'enemy_portraits', RE5);

function identities(frame) {
  // the recorded frame predates the identities: its nearest enemy made the Executioner, the rest the town Majini
  const by = new Map(INFO.enemies.map(e => [e.cls, e]));
  const near = frame.enemies.map(e => [Math.hypot(e.pos[0] - frame.player.pos[0], e.pos[2] - frame.player.pos[2]), e]).sort((a, b) => a[0] - b[0]);
  const enemies = near.map(([, e], i) => {
    const cls = i === 0 ? 'uEm20' : i % 3 ? 'uEm10' : 'uEm11', who = by.get(cls);
    return { ...e, cls, name: who.name, kind: who.name, tier: who.tier, level: who.level, ...(cls === 'uEm20' ? { hp: 6100, hp_max: 8000 } : {}) };
  });
  const kinds = {};
  for (const e of enemies) (kinds[e.cls] ||= { name: e.name, count: 0, tier: e.tier, level: e.level }).count++;
  return { ...frame, title: RE5, enemies, kinds, seq: 1, live: true, age_s: 0.1 };
}

test('in the browser: names on the map, the boss ringed with its portrait, the sidebar beside it', async () => {
  const { withPage } = require('../scripts/browser_lifecycle.cjs');
  const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  const png = cls => { const p = path.join(PORTRAITS, cls + '.png');
    return fs.existsSync(p) ? 'data:image/png;base64,' + fs.readFileSync(p).toString('base64') : null; };
  const faces = Object.fromEntries(['uEm20', 'uEm10', 'uEm11', 'uEm22'].map(c => [c, png(c)]).filter(([, v]) => v));
  const frame = identities(REAL_FRAMES.at(-1));
  const server = http.createServer((req, res) => { res.setHeader('Content-Type', 'text/html'); res.end('<!doctype html><body></body>'); });
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  try {
    await withPage(async (evaluate, send) => {
      await send('Page.navigate', { url: `http://127.0.0.1:${server.address().port}/` });
      for (let n = 0; n < 100; n++) { if (await evaluate(`document.readyState==='complete'`)) break; await new Promise(r => setTimeout(r, 10)); }
      await send('Emulation.setDeviceMetricsOverride', { width: 1180, height: 1000, deviceScaleFactor: 1, mobile: false });
      await evaluate(`document.documentElement.dataset.embedded='true';document.head.innerHTML='<meta name="viewport" content="width=device-width,initial-scale=1">'+${JSON.stringify(web.match(/<style>([\s\S]*?)<\/style>/)[0])};`);
      await evaluate(fs.readFileSync(path.join(__dirname, '../clients/web/viz/tactical-map.js'), 'utf8'));
      await evaluate(`document.body.style.background='#16161c';document.body.innerHTML='<div style="max-width:1150px;margin:8px">'+GBoxTacticalMap.html('w1-j9')+'</div>';
        window.frame=${JSON.stringify(frame)};window.stage=${JSON.stringify({ ...REAL_STAGE, name: 'Public Assembly' })};
        window.info=${JSON.stringify(INFO)};window.faces=${JSON.stringify(faces)};window.asked=[];
        window.api=async p=>{asked.push(p);if(p.includes('/stage/'))return stage;if(p.startsWith('/api/mercs/enemies/'))return info;
          return p.includes('after='+frame.seq)?{seq:frame.seq,same:true,age_s:0.2,live:true}:frame;};
        window.image=async p=>faces[p.split('/').pop().replace('.png','')]||null;
        window.ctl=GBoxTacticalMap.mount(document,{sid:'w1-j9',api,image});`);
      for (let n = 0; n < 150 && !(await evaluate(`!!document.querySelector('.tm-card')`)); n++) await new Promise(r => setTimeout(r, 30));
      await new Promise(r => setTimeout(r, 600));
      await evaluate(`document.querySelector('.tm-card[data-cls=uEm20]').open=true;document.querySelector('.tm-card[data-cls=uEm20]').dispatchEvent(new Event('toggle'));`);
      await new Promise(r => setTimeout(r, 400));
      const s = await evaluate(`(()=>({kinds:document.querySelector('[data-tm=kinds]').textContent,
        next:document.querySelector('.tm-next')?.textContent,cards:[...document.querySelectorAll('.tm-roster > .tm-card b')].map(b=>b.textContent),
        open:document.querySelector('.tm-card[data-cls=uEm20]').open,imgs:document.querySelectorAll('.tm-roster img').length,
        listing:asked.filter(p=>p.startsWith('/api/mercs/enemies/')).length,
        side:(()=>{const a=document.querySelector('.tm-roster').getBoundingClientRect(),c=document.querySelector('.tmap canvas').getBoundingClientRect();return a.left>=c.right-1;})()}))()`);
      assert.match(s.kinds, /^Executioner Majini ×1 boss/);
      assert.match(s.kinds, /Majini \(female\) ×\d/);
      assert.doesNotMatch(s.kinds, /uEm\d|threat/);
      assert.equal(s.next, 'Next heavy: Executioner Majini at kill 20 (in 13) · SW fence');
      assert.equal(s.cards[0], 'Executioner Majini ×1');
      assert.equal(s.open, true, 'an opened card stays open across frames');
      assert.equal(s.listing, 1, 'the listing is read once');
      assert.ok(s.side, 'the sidebar sits beside the map on a wide screen');
      if (Object.keys(faces).length) assert.ok(s.imgs >= 1, 'portraits in the sidebar');
      if (process.env.GBOX_TACTICAL_EVIDENCE) {
        fs.mkdirSync(process.env.GBOX_TACTICAL_EVIDENCE, { recursive: true });
        const shot = await send('Page.captureScreenshot', { format: 'png' });
        fs.writeFileSync(path.join(process.env.GBOX_TACTICAL_EVIDENCE, 'enemy-identity-map.png'), Buffer.from(shot.result.data, 'base64'));
      }
      await evaluate(`ctl.stop()`);
    });
  } finally { await new Promise(r => server.close(r)); }
});
