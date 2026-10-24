// clients/web/viz/tactical-map.js: the Sessions view's "Tactical map" - a live top-down view of a Mercenaries round
// drawn from the frames gbox/mercs/tactical.py posts (docs/tactical_map.md). Server side: tests/test_tactical_map.py.
// The pure parts run here; the section itself runs in a real browser on a real RE5 stage and frame (Public Assembly,
// read from the Spark's RPCS3: tests/fixtures/tactical_map). GBOX_TACTICAL_EVIDENCE=<dir> keeps screenshots.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const T = require('../clients/web/viz/tactical-map.js');

const tick = () => new Promise(r => setImmediate(r));
async function until(cond, n = 400) { for (let i = 0; i < n && !cond(); i++) await tick(); assert.ok(cond(), 'condition never became true'); }

// a street 20 m x 20 m (two triangles) at y 0 and a roof (one triangle) 3 m up; units cm
const STAGE = { v: 1, key: 'BLUS30491.nav3.00000001', kind: 'mesh', units: 'cm', view: { x: -1, z: 1 },
  bounds: [-1000, -1000, 1000, 1000], y: [0, 300],
  points: [-1000, 0, -1000, 1000, 0, -1000, 1000, 0, 1000, -1000, 0, 1000, 0, 300, 0, 500, 300, 0, 0, 300, 500],
  tris: [0, 1, 2, 0, 2, 3, 4, 5, 6], walls: [0, 1, 1, 2, 2, 3, 3, 0, 4, 5], cross: [5, 6] };
const FRAME = { v: 1, seq: 7, t: 1000, title: 'BLUS30491', stage: STAGE.key, units: 'cm', screen: 'playing', live: true, age_s: 0.1,
  clock: { left: 92.4, start: 120, combo: 7, combo_left: 3.14, score: 12345, kills: 20 },
  player: { pos: [0, 0, 0], facing: 0, hp: 900, hp_max: 1000, state: 'aim', aim: true },
  enemies: [{ id: 3, pos: [0, 0, 800], hp: 800, hp_max: 800, flags: ['attacking', 'target'] },
            { id: 4, pos: [300, 300, 300], hp: 700, hp_max: 700, flags: ['no_los'] }],
  bonuses: [{ id: 11, pos: [-600, 13, 0], kind: 'time', taken: false }, { id: 12, pos: [600, 13, 600], kind: 'combo', taken: false },
            { id: 13, pos: [0, 13, -600], kind: 'time', taken: true }],
  plan: { phase: 'gather_time', target: { kind: 'enemy', id: 3, pos: [0, 0, 800] }, route: [[-300, 0, 0], [-600, 13, 0]],
          stand: { pos: [500, 0, -500], r: 300 }, nearest_bonus: { id: 11, kind: 'time', pos: [-600, 13, 0], dist: 612, eta_s: 1.36, est: true } } };

test('the words: phases, the clock, distances', () => {
  assert.deepEqual(['gather_time', 'combo_bonus', 'stand', 'break_for_time', 'break-for-time', 'hunt_crows', ''].map(T.phaseLabel),
    ['Gather time', 'Combo bonus', 'Stand', 'Break for time', 'Break for time', 'Hunt crows', '']);
  assert.deepEqual([92.4, 61, 9.44, 0, -3, null].map(T.clockText), ['1:32', '1:01', '9.4', '0.0', '0.0', '–']);
  assert.deepEqual([T.metres(612, 'cm'), T.metres(2867, 'cm'), T.metres(4500, 'mm'), T.metres(null, 'cm')], ['6.1 m', '29 m', '4.5 m', '']);
});

test('the lines above the map: clock, combo, phase, the nearest bonus and its ETA, the target', () => {
  const h = T.hud(FRAME);
  assert.equal(h.state, 'round');
  assert.equal(h.clock, '1:32');
  assert.equal(h.combo, '×7 · 3.1 s');
  assert.equal(h.phase, 'Gather time');
  assert.equal(h.score, '12,345 pts · 20 kills');
  assert.equal(h.nearest, 'Time bonus · 6.1 m · ~1.4 s');          // ~ : an estimate (no plan from the bot)
  assert.equal(h.target, 'Majini 3 · 8.0 m');
  assert.equal(h.status, '');
  assert.equal(T.hud({ ...FRAME, player: undefined, screen: 'results' }).status, 'Between rounds · results');
  assert.equal(T.hud({ ...FRAME, player: undefined, screen: 'select_stage' }).status, 'Between rounds · select stage');
  assert.equal(T.hud({ ...FRAME, live: false, age_s: 12.4 }).status, 'No new frame for 12 s');
  assert.equal(T.hud({ ...FRAME, screen: 'stopped' }).status, 'Autoplay stopped');
  assert.equal(T.hud(null).state, 'none');
  const exact = T.hud({ ...FRAME, plan: { ...FRAME.plan, nearest_bonus: { id: 12, kind: 'combo', dist: 2000, eta_s: 4 } } });
  assert.equal(exact.nearest, 'Combo bonus · 20 m · 4.0 s');           // the bot's own ETA: no ~
});

test('the view: the player in the middle, +z up and +x to his left, the map turning with him when asked', () => {
  const size = { w: 400, h: 400 };
  const v = T.viewOf(T.want(FRAME, STAGE, { mode: 'follow' }), size);
  assert.deepEqual(T.project(v, 0, 0), [200, 200]);
  const [ux, uy] = T.project(v, 0, 500), [lx, ly] = T.project(v, 500, 0);
  assert.ok(Math.abs(ux - 200) < 1e-9 && uy < 200, '+z is up');
  assert.ok(lx < 200 && Math.abs(ly - 200) < 1e-9, '+x is on the left (the right-handed world seen from above)');
  // follow fits what the bot is going for: the target 8 m ahead, the stand 7 m off
  const r = T.want(FRAME, STAGE, { mode: 'follow' }).radius;
  assert.ok(r >= 800 * 1.15 - 1e-6 && r <= 4500, `radius ${r}`);
  // the whole stage
  const s = T.want(FRAME, STAGE, { mode: 'stage' });
  assert.deepEqual([s.cx, s.cz, Math.round(s.radius)], [0, 0, 1040]);
  // heading up: facing +x (pi / 2) - a point ahead of him is straight above him on the map
  const turned = { ...FRAME, player: { ...FRAME.player, facing: Math.PI / 2 } };
  const hv = T.viewOf(T.want(turned, STAGE, { mode: 'follow', headingUp: true }), size);
  const [ax, ay] = T.project(hv, 500, 0);
  assert.ok(Math.abs(ax - 200) < 1e-6 && ay < 200, `ahead is up: ${ax}, ${ay}`);
  const [dx, dy] = T.screenDir(hv, Math.PI / 2);
  assert.ok(Math.abs(dx) < 1e-9 && Math.abs(dy + 1) < 1e-9);
  // without heading up the same facing points left on the map
  const [nx, ny] = T.screenDir(T.viewOf(T.want(turned, STAGE, { mode: 'follow' }), size), Math.PI / 2);
  assert.ok(Math.abs(nx + 1) < 1e-9 && Math.abs(ny) < 1e-9);
});

test('the marks: who is where, their flags and levels, the route from the player, the nearest bonus labelled', () => {
  const v = T.viewOf(T.want(FRAME, STAGE, { mode: 'follow' }), { w: 400, h: 400 });
  const ms = T.marks(FRAME, v), by = k => ms.filter(m => m.kind === k);
  assert.deepEqual(by('enemy').map(m => [m.id, m.flags, m.level]), [[3, ['attacking', 'target'], 'same'], [4, ['no_los'], 'above']]);
  assert.match(by('enemy')[0].tip, /^Majini 3 · 800\/800 health · 8\.0 m · attacking · the bot's target$/);
  assert.match(by('enemy')[1].tip, /above · out of sight/);
  const bonuses = by('bonus');
  assert.deepEqual(bonuses.map(b => [b.id, b.type, b.taken, b.near]), [[11, 'time', false, true], [12, 'combo', false, false], [13, 'time', true, false]]);
  assert.equal(bonuses[0].label, '6.1 m · ~1.4 s');
  const route = by('route')[0];
  assert.deepEqual(route.pts[0], [200, 200]);                       // from the player
  assert.equal(route.pts.length, 3);
  assert.equal(by('nearest').length, 0, 'the route already goes to the nearest bonus: no second line');
  assert.equal(by('player')[0].aim, true);
  assert.equal(by('stand').length, 1);
  // the nearest bonus far away: a dotted line and an arrow at the map's edge
  const far = { ...FRAME, plan: { ...FRAME.plan, route: [], nearest_bonus: { id: 99, kind: 'time', pos: [0, 0, -9000], dist: 9100, eta_s: 20 } } };
  const fv = T.viewOf(T.want(far, STAGE, { mode: 'follow' }), { w: 400, h: 400 }), fm = T.marks(far, fv);
  const arrow = fm.find(m => m.kind === 'offscreen');
  assert.ok(arrow && arrow.y > 370 && Math.abs(arrow.x - 200) < 1e-6, 'an arrow at the bottom edge, below the player');
  assert.equal(arrow.label, '91 m');
  assert.ok(fm.some(m => m.kind === 'nearest'));
});

test('rotation-aware zoom anchors the cursor and pan moves the map with the drag',()=>{
  const size={w:400,h:300},camera={cx:300,cz:-500,rot:1.1,radius:2000};
  const v=T.viewOf(camera,size),world=T.unproject(v,81,239);
  assert.ok(Math.hypot(...T.project(v,...world).map((n,i)=>n-[81,239][i]))<1e-8);
  const zoom=T.zoomView(camera,size,81,239,.5,'cm');
  assert.equal(zoom.radius,1000);
  assert.ok(Math.hypot(...T.project(T.viewOf(zoom,size),...world).map((n,i)=>n-[81,239][i]))<1e-8);
  const pan=T.panView(camera,size,60,-40);
  const a=T.project(v,...world),b=T.project(T.viewOf(pan,size),...world);
  assert.ok(Math.abs(b[0]-a[0]-60)<1e-8&&Math.abs(b[1]-a[1]+40)<1e-8);
});

// a 2D context that records what was drawn
function recorder() {
  const calls = [];
  const ctx = new Proxy({ calls }, {
    get(o, k) { if (k in o) return o[k]; if (k === 'measureText') return s => ({ width: String(s).length * 6 }); return (...a) => calls.push([k, ...a]); },
    set(o, k, v) { calls.push(['set', k, v]); return true; } });
  return { ctx, calls };
}

test('drawing: the floor by level, the walls and crossings, every mark, the scale', () => {
  const { ctx, calls } = recorder();
  const theme = T.themeOf(null);
  const v = T.viewOf(T.want(FRAME, STAGE, { mode: 'stage' }), { w: 300, h: 300 });
  const ms = T.draw(ctx, { frame: FRAME, stage: STAGE, view: v, theme });
  assert.ok(ms.length >= 8);
  const fills = calls.filter(c => c[0] === 'set' && c[1] === 'fillStyle').map(c => c[2]);
  assert.ok(fills.includes(theme.floor) && fills.includes(theme.floorOther), 'his level and the roof above in their own fills');
  assert.ok(fills.includes(theme.enemy) && fills.includes(theme.bonus) && fills.includes(theme.player));
  assert.ok(calls.some(c => c[0] === 'setLineDash' && c[1].length), 'the route and the crossing are dashed');
  assert.ok(calls.some(c => c[0] === 'fillText' && c[1] === '5 m'), 'a scale bar');
  assert.equal(calls.filter(c => c[0] === 'save').length, calls.filter(c => c[0] === 'restore').length);
  // no frame yet: the stage alone, nothing breaks
  const r2 = recorder();
  assert.deepEqual(T.draw(r2.ctx, { frame: null, stage: STAGE, view: v, theme }), []);
});

// the feed: a fake server with frames to hand out
function fakeApi(frames, stage = STAGE) {
  const calls = [];
  let i = 0, fail = 0;
  const api = async path => {
    calls.push(path);
    if (fail > 0) { fail--; throw new Error('gBox server unreachable'); }
    if (path.startsWith('/api/autoplay/tactical/stage/')) return stage;
    const f = frames[Math.min(i++, frames.length - 1)];
    if (f && path.includes(`after=${f.seq}`)) return { seq: f.seq, same: true, age_s: (f.age_s || 0) + 1, live: true };
    return f;
  };
  return { api, calls, failNext: n => { fail = n; } };
}

test('the feed: frames after the newest seen, "same" when nothing moved, the stage once, the frames going', async () => {
  T._stages.clear();
  const f2 = { ...FRAME, seq: 8 };
  const { api, calls } = fakeApi([FRAME, FRAME, f2, {}]);
  const got = [], stagesGot = [], timers = [];
  const feed = T.create({ sid: 'w1-j9', api, onFrame: f => got.push(f && f.seq), onStage: s => stagesGot.push(s.key),
                          onStatus: f => got.push(f ? `same ${f.age_s}` : 'error'), setTimer: (fn, ms) => { timers.push(ms); return setImmediate(fn); },
                          clearTimer: clearImmediate });
  await until(() => got.includes(null));
  feed.stop();
  assert.deepEqual(got.slice(0, 4), [7, 'same 1.1', 8, null]);
  assert.deepEqual(calls.filter(p => !p.includes('/stage/')),
    ['/api/autoplay/tactical/w1-j9', '/api/autoplay/tactical/w1-j9?after=7', '/api/autoplay/tactical/w1-j9?after=7',
     '/api/autoplay/tactical/w1-j9?after=8']);
  assert.deepEqual(stagesGot, [STAGE.key]);
  assert.equal(calls.filter(p => p.includes('/stage/')).length, 1, 'a stage is read once');
  assert.equal(timers[1], 125, 'fast while it shows a round');
  assert.equal(timers.at(-1), 3000, 'slow once the frames are gone');
  // another mount of the same stage: from the page's cache
  const again = fakeApi([FRAME]), seen = [];
  const feed2 = T.create({ sid: 'w1-j9', api: again.api, onStage: s => seen.push(s.key), setTimer: (fn) => setImmediate(fn), clearTimer: clearImmediate });
  await until(() => seen.length === 1);
  feed2.stop();
  assert.equal(again.calls.filter(p => p.includes('/stage/')).length, 0);
});

test('the feed backs off while the server is away and polls slowly while the map is not on screen', async () => {
  T._stages.clear();
  const { api, failNext } = fakeApi([FRAME]);
  failNext(3);
  const timers = [], errors = [];
  let shown = false;
  const feed = T.create({ sid: 'w1-j9', api, visible: () => shown, onStatus: (f, err) => err && errors.push(err),
                          setTimer: (fn, ms) => { timers.push(ms); return timers.length < 6 ? setImmediate(fn) : null; }, clearTimer: () => {} });
  await until(() => timers.length >= 6);
  feed.stop();
  assert.equal(errors.length, 3);
  assert.deepEqual(timers.slice(1, 4), [250, 500, 1000], 'doubling while away');
  assert.equal(timers[4], 3000, 'back, but not on screen: slow');
});

test('the section: hidden until frames come, the dock handle, the legend', () => {
  const h = T.html('w1-"j9"');
  assert.match(h, /<details data-dock="tactical" class="sect" data-tmap="w1-&#34;j9&#34;" open hidden>/);
  assert.match(h, /<summary draggable="true">Tactical map/);
  for (const word of ['Player', 'Majini', 'out of sight', 'attacking', 'time bonus', 'combo bonus', 'route', 'stand spot', 'Follow', 'Stage', 'Heading up'])
    assert.ok(h.includes(word), word);
});

// ---- in a real browser, on a real stage ----
const FIX = path.join(__dirname, 'fixtures', 'tactical_map');
const REAL_STAGE = JSON.parse(fs.readFileSync(path.join(FIX, 'BLUS30491-public-assembly.stage.json'), 'utf8'));
const REAL_FRAMES = fs.readFileSync(path.join(FIX, 'BLUS30491-public-assembly.frames.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);

async function page(fn) {
  const { withPage } = require('../scripts/browser_lifecycle.cjs');
  const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
  const server = http.createServer((req, res) => { res.setHeader('Content-Type', 'text/html'); res.end('<!doctype html><body></body>'); });
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  try {
    return await withPage(async (evaluate, send) => {
      await send('Page.navigate', { url: `http://127.0.0.1:${server.address().port}/` });
      for (let n = 0; n < 100; n++) { if (await evaluate(`document.readyState==='complete'`)) break; await new Promise(r => setTimeout(r, 10)); }
      await evaluate(`document.documentElement.dataset.embedded='true';document.head.innerHTML='<meta name="viewport" content="width=device-width,initial-scale=1">'+${JSON.stringify(web.match(/<style>([\s\S]*?)<\/style>/)[0])};`);
      await evaluate(fs.readFileSync(path.join(__dirname, '../clients/web/viz/tactical-map.js'), 'utf8'));
      return fn(evaluate, send);
    });
  } finally { await new Promise(r => server.close(r)); }
}

test('in the browser: the section shows itself with the round, draws the stage crisp, fits a phone', async () => {
  const frame = { ...REAL_FRAMES.at(-1), seq: 1, live: true, age_s: 0.1 };
  await page(async (evaluate, send) => {
    await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 2, mobile: false });
    await evaluate(`document.body.innerHTML='<div class="play"><div style="background:#000;aspect-ratio:16/9"></div><div class="sidecol"><div id="dock-top" class="dock">'+GBoxTacticalMap.html('w1-j9')+'</div></div></div>';
      window.frame=${JSON.stringify(frame)};window.stage=${JSON.stringify(REAL_STAGE)};window.asked=[];
      window.api=async p=>{asked.push(p);if(p.includes('/stage/'))return stage;if(!window.on)return {};return p.includes('after='+frame.seq)?{seq:frame.seq,same:true,age_s:0.2,live:true}:frame;};
      window.ctl=GBoxTacticalMap.mount(document,{sid:'w1-j9',api});`);
    await new Promise(r => setTimeout(r, 300));
    assert.equal(await evaluate(`document.querySelector('[data-dock=tactical]').hidden`), true, 'no frames: no section');
    await evaluate(`window.on=true;document.querySelector('[data-dock=tactical]').dispatchEvent(new Event('toggle'));`);
    for (let n = 0; n < 100 && await evaluate(`document.querySelector('[data-dock=tactical]').hidden`); n++) await new Promise(r => setTimeout(r, 30));
    await new Promise(r => setTimeout(r, 400));
    const s = await evaluate(`(()=>{const c=document.querySelector('.tmap canvas'),g=c.getContext('2d'),d=g.getImageData(0,0,c.width,c.height).data;
      const cols=new Set();for(let i=0;i<d.length;i+=4*97)cols.add(d[i]<<16|d[i+1]<<8|d[i+2]);
      return {hidden:document.querySelector('[data-dock=tactical]').hidden,clock:document.querySelector('[data-tm=clock]').textContent,
        nearest:document.querySelector('[data-tm=nearest]').textContent,w:c.width,cw:c.clientWidth,colors:cols.size,
        stageReads:asked.filter(p=>p.includes('/stage/')).length,afters:asked.filter(p=>p.includes('after=')).length};})()`);
    assert.equal(s.hidden, false);
    assert.equal(s.clock, (await evaluate(`GBoxTacticalMap.clockText(${frame.clock.left})`)));
    assert.match(s.nearest, /^Nearest: Time bonus · \d+(\.\d)? m · ~\d+\.\d s$/);
    assert.equal(s.w, s.cw * 2, 'drawn at the screen\'s pixel density');
    assert.ok(s.colors > 6, `the stage and the marks are drawn (${s.colors} colours)`);
    assert.equal(s.stageReads, 1);
    assert.ok(s.afters >= 1, 'polls for newer frames');
    const shoot = async name => {
      if (!process.env.GBOX_TACTICAL_EVIDENCE) return;
      fs.mkdirSync(process.env.GBOX_TACTICAL_EVIDENCE, { recursive: true });
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(path.join(process.env.GBOX_TACTICAL_EVIDENCE, name), Buffer.from(shot.result.data, 'base64'));
    };
    await shoot('tactical-map-desktop.png');
    await evaluate(`document.querySelector('[data-tm-mode=stage]').click()`);
    assert.equal(await evaluate(`document.querySelector('[data-tm-mode=stage]').getAttribute('aria-pressed')`), 'true');
    await shoot('tactical-map-stage.png');
    // a phone: the side column under the game, the map its full width, nothing wider than the screen
    await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 3, mobile: true });
    await new Promise(r => setTimeout(r, 300));
    const phone = await evaluate(`(()=>{const c=document.querySelector('.tmap canvas').getBoundingClientRect();
      return {right:c.right,width:c.width,scroll:document.documentElement.scrollWidth,inner:innerWidth};})()`);
    assert.ok(phone.right <= phone.inner && phone.scroll <= phone.inner, JSON.stringify(phone));
    assert.ok(phone.width > 300, 'the map takes the phone\'s width: ' + JSON.stringify(phone));
    await shoot('tactical-map-phone.png');
    await evaluate(`ctl.stop()`);
  });
});

test('browser map holds rotation on hover, zooms and pans, clicks a bonus without turning a drag into a command',async()=>{
  await page(async(evaluate)=>{
    const run=code=>evaluate('(async()=>{'+code+'})()');
    await run(`document.body.innerHTML=GBoxTacticalMap.html('w1-j9');
      window.frame=${JSON.stringify({...FRAME,goal_round:'a'.repeat(32),goal_capabilities:['bonus','item']})};
      window.stage=${JSON.stringify(STAGE)};window.commands=[];
      window.api=async(p,body)=>{if(p.endsWith('/goal')){commands.push(body);return {state:'queued',label:'Time bonus'};}return p.includes('/stage/')?stage:frame;};
      window.ctl=GBoxTacticalMap.mount(document,{sid:'w1-j9',api,setTimer:fn=>{window.nextMapPoll=fn;return 1;},clearTimer:()=>{}});
      await nextMapPoll();await Promise.resolve();
      document.querySelector('[data-tm-heading]').click();
      window.c=document.querySelector('.tmap canvas');window.r=c.getBoundingClientRect();
      c.dispatchEvent(new PointerEvent('pointerenter',{clientX:r.left+30,clientY:r.top+30}));
      window.held=ctl.view;frame={...frame,seq:8,player:{...frame.player,facing:1.8,pos:[300,0,300]}};await nextMapPoll();`);
    const held=await evaluate(`JSON.stringify(ctl.view)===JSON.stringify(held)`);assert.equal(held,true);
    const zoom=await evaluate(`(()=>{const before=ctl.view.radius;c.dispatchEvent(new WheelEvent('wheel',{deltaY:-160,clientX:r.left+100,clientY:r.top+100,cancelable:true}));return ctl.view.radius<before;})()`);
    assert.equal(zoom,true);
    await evaluate(`window.beforePan=ctl.view;
      c.dispatchEvent(new PointerEvent('pointerdown',{button:0,pointerId:1,clientX:r.left+100,clientY:r.top+100}));
      c.dispatchEvent(new PointerEvent('pointermove',{pointerId:1,clientX:r.left+160,clientY:r.top+140}));
      c.dispatchEvent(new PointerEvent('pointerup',{pointerId:1,clientX:r.left+160,clientY:r.top+140}));`);
    assert.equal(await evaluate(`commands.length`),0);
    assert.equal(await evaluate(`ctl.view.cx!==beforePan.cx||ctl.view.cz!==beforePan.cz`),true);
    await run(`document.querySelector('[data-tm-mode=stage]').click();
      window.v=GBoxTacticalMap.viewOf(ctl.view,{w:c.clientWidth,h:parseFloat(c.style.height)});
      window.mark=GBoxTacticalMap.marks(frame,v).find(m=>m.kind==='bonus'&&m.id===11);
      c.dispatchEvent(new PointerEvent('pointerdown',{button:0,pointerId:2,clientX:r.left+mark.x,clientY:r.top+mark.y}));
      c.dispatchEvent(new PointerEvent('pointerup',{pointerId:2,clientX:r.left+mark.x,clientY:r.top+mark.y}));await Promise.resolve();`);
    assert.deepEqual(await evaluate(`commands`),[{round:'a'.repeat(32),stage:STAGE.key,kind:'bonus',id:11,seq:8}]);
    await run(`document.querySelector('[data-tm=cancel-goal]').click();await Promise.resolve();`);
    assert.deepEqual(await evaluate(`commands.at(-1)`),{cancel:true});
    await run(`c.dispatchEvent(new PointerEvent('pointerleave'));document.querySelector('[data-tm-mode=follow]').click();frame={...frame,seq:9,player:{...frame.player,facing:2.1}};await nextMapPoll();`);
    assert.ok(Math.abs((await evaluate(`ctl.view.rot`))+2.1)<.001);
    await evaluate(`ctl.stop()`);
  });
});
