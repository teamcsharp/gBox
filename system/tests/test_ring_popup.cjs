// Replay ring pop-up (#1084): right-click the record icon -> the running game's background gameplay ring: the bar of
// what it holds, In / Out, the size goal, Export through the `recording` worker tool, then open / attach the clip.
// The desktop shell's #ringpop and the web client's mirror, driven on a tiny fake DOM.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const desktop = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
const web = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
const START = '// ---------------- replay ring pop-up (#1084)', END = '// ---------------- end replay ring pop-up';

function node(tag) {
  const n = { tagName: String(tag).toUpperCase(), style: {}, dataset: {}, listeners: {}, classes: new Set(), attrs: {}, sub: {},
    value: '', textContent: '', innerHTML: '', disabled: false, max: '' };
  n.classList = { add: (...c) => c.forEach(x => n.classes.add(x)), remove: (...c) => c.forEach(x => n.classes.delete(x)),
    toggle: (c, f) => { (f === undefined ? !n.classes.has(c) : f) ? n.classes.add(c) : n.classes.delete(c); }, contains: c => n.classes.has(c) };
  n.setAttribute = (k, v) => { n.attrs[k] = v; };
  n.querySelector = sel => (n.sub[sel] ||= node('x'));
  n.addEventListener = (t, fn) => (n.listeners[t] ||= []).push(fn);
  n.fire = (t, ev) => (n.listeners[t] || []).forEach(fn => fn(ev));
  n.append = (...k) => { n.children = (n.children || []).concat(k); };
  return n;
}
const button = data => ({ closest: sel => (sel === 'button' ? { dataset: data } : null) });
const flush = () => new Promise(r => setImmediate(r));
const plain = x => JSON.parse(JSON.stringify(x));

function fixture(src, extra = {}) {
  const jobs = [], fits = [], drags = [], toasts = [], posts = [], opened = [], saved = [], recmenu = node('div');
  const status = { state: 'recording', span_s: 95.5, segments: [[5, 0], [10, 5], [95.5, 10]], encoder_note: 'h264_nvenc (NVIDIA GPU)',
    bitrate_kbps: 8000, stops_in_s: 14.2, game_id: 'g1', title: 'Crazy Taxi' };
  const ctx = {
    document: { body: node('body'), createElement: node,
      querySelector: sel => (sel === '#sopres' ? { set textContent(t) { toasts.push(t); } } : null) }, $: sel => (sel === '#recmenu' ? recmenu : null), esc: String,
    fitMenu: (el, x, y, pad, top) => fits.push([x, y, pad, top]), dragAnywhere: el => { drags.push(el); return el; },
    toast: t => toasts.push(t), S: { apiUrl: 'http://spark:8765' }, window: { open: u => opened.push(u) },
    openRecMenu: () => { ctx.recOpened = true; }, setImmediate, setTimeout, clearTimeout, tq: () => 'token=t0k', bnEmbedded: () => false,
    recordingPrefsReady: Promise.resolve(), recordingPrefsSave: Promise.resolve(),
    runJob: async body => {                                    // web: the job queue answers with the job
      try { return { state: 'succeeded', output: await ctx.gameJob(body.tool, Object.fromEntries(Object.entries(body.input).filter(([k]) => k !== 'session_id'))) }; }
      catch (e) { return { state: 'failed', error: e.message }; }
    },
    api: async (url, body) => { const r = await ctx.gbox.api(url, body); if (!r.ok) throw new Error(r.error); return r.data; },
    gameJob: async (tool, input) => {
      jobs.push([tool, plain(input)]);
      if (input.op === 'export') return { session_id: 'w-1', op: 'export', status, clip: { name: 'replay-g1.mp4', sha256: 'ab'.repeat(32),
        bytes: 9.5 * 1048576, seconds: input.in_s - input.out_s, height: 720, encoder: 'h264_nvenc', fits: true } };
      return { session_id: 'w-1', op: 'status', status };
    },
    gbox: { token: async () => 't0k', recSaveClip: async clip => { saved.push(plain(clip));return {file:'configured-folder/replay-g1.mp4'}; },
      recOpen: async file => opened.push(file), api: async (url, body) => {
      posts.push([url, body && plain(body)]);
      if (url.startsWith('/api/requests?')) return { ok: true, data: [{ id: 'r9', number: 1084, title: 'auto capture' }] };
      if (url === '/api/mods' && !body) return { ok: true, data: [{ id: 'm1', title: 'Fast taxi', game_id: 'g1', calls: [{ tool: 'poke', input: {} }] },
                                                                 { id: 'm2', title: 'Other game', game_id: 'zz', calls: [] }] };
      return { ok: true, data: {} };
    } },
    ...extra,
  };
  vm.createContext(ctx);
  vm.runInContext(src.slice(src.indexOf(START), src.indexOf(END)), ctx);
  Object.assign(ctx, vm.runInContext('({ RING, ringClamp, ringKbps, ringFmt, ringTimelineHTML, ringPopOpen, ringRender, ringStateText })', ctx));
  ctx.open = (e, sid) => ctx.ringPopOpen(e, sid);
  return { ctx, jobs, fits, drags, toasts, posts, opened, saved, recmenu, status };
}

for (const [name, src] of [['desktop', desktop], ['web', web]]) {
  test(`${name}: the range and size math match the worker`, () => {
    const { ctx } = fixture(src);
    assert.deepEqual(plain(ctx.ringClamp(30, 0, 95.5)), { inS: 30, outS: 0, seconds: 30 });
    assert.deepEqual(plain(ctx.ringClamp(5, 200, 95.5)), { inS: 95.5, outS: 5, seconds: 90.5 });   // swapped and clamped
    assert.deepEqual(plain(ctx.ringClamp(-3, -1, 0)), { inS: 0, outS: 0, seconds: 0 });
    assert.equal(ctx.ringKbps(20, 60), 2712);                       // ring_record.video_kbps(20, 60)
    assert.equal(ctx.ringKbps(2, 20), 813);
    assert.equal(ctx.ringKbps(1, 600), 150);
    assert.equal(ctx.ringFmt(95.5), '1:36'); assert.equal(ctx.ringFmt(0), '0:00');
  });

  test(`${name}: the bar puts the oldest on the left and marks the selection`, () => {
    const { ctx, status } = fixture(src);
    assert.match(ctx.ringTimelineHTML({ span_s: 0, segments: [] }, 0, 0), /Nothing recorded yet/);
    const html = ctx.ringTimelineHTML({ span_s: 120, segments: [[120, 60], [60, 0]] }, 30, 0);
    assert.match(html, /<i style="left:0\.00%;width:50\.00%"><\/i><i style="left:50\.00%;width:50\.00%"><\/i>/);
    assert.match(html, /class="rg-sel" style="left:75\.00%;width:25\.00%"/);
    assert.match(html, /−2:00/);
    assert.match(ctx.ringStateText(status), /recording · stops 14\.2 s/);
    assert.match(ctx.ringStateText({ state: 'waiting' }), /waiting for the controller/);
    assert.match(ctx.ringStateText({ state: 'ended' }), /can still be exported/);
  });

  test(`${name}: right-click opens the pop-up next to the icon and loads the ring`, async () => {
    const f = fixture(src), { ctx } = f;
    if (name === 'desktop') f.recmenu.classList.add('on');
    await ctx.ringPopOpen({ clientX: 500, clientY: 20 }, name === 'web' ? 'w-1' : undefined);
    const m = ctx.RING.el;
    assert.ok(m.classes.has('on')) ; assert.equal(f.drags.length, 1, 'movable like every gBox pop-up (dragAnywhere)');
    assert.deepEqual(f.fits[0], [480, 34, 8, 40], 'kept inside the window (fitMenu)');
    assert.deepEqual(f.jobs, [['recording', { op: 'status' }]]);
    if (name === 'desktop') assert.ok(!f.recmenu.classes.has('on'), 'the app recording menu gives way');
    assert.equal(ctx.RING.inS, 30); assert.equal(ctx.RING.outS, 0);          // default: the last 30 s
    assert.equal(m.sub['#rg-in'].max, '95.5'); assert.equal(m.sub['#rg-in'].value, '65.5');
    assert.equal(m.sub['#rg-out'].value, '95.5'); assert.equal(m.sub['#rg-out-v'].value, 'newest');
    assert.equal(m.sub['#rg-in-v'].value, '−0:30');
    assert.match(m.sub['#rg-state'].textContent, /recording/);
    assert.match(m.sub['#rg-enc'].textContent, /NVIDIA GPU/);
    assert.match(m.sub['#rg-est'].textContent, /0:30 clip · about 5,424 kb\/s/);
    await ctx.ringPopOpen({ clientX: 10, clientY: 10 }, name === 'web' ? 'w-1' : undefined);
    assert.equal(f.drags.length, 1, 'one pop-up element, reused');
  });

  test(`${name}: In / Out / presets / size goal, then Export through the recording tool`, async () => {
    const f = fixture(src), { ctx } = f;
    await ctx.ringPopOpen({ clientX: 500, clientY: 20 }, name === 'web' ? 'w-1' : undefined);
    const m = ctx.RING.el;
    m.fire('input', { target: { id: 'rg-in', value: '5.5' } });               // slider position 5.5 of 95.5: 90 s back
    m.fire('input', { target: { id: 'rg-out', value: '85.5' } });             // 10 s back
    m.fire('input', { target: { id: 'rg-mb', value: '8' } });
    assert.equal(ctx.RING.inS, 90); assert.equal(ctx.RING.outS, 10); assert.equal(ctx.RING.mb, 8);
    m.fire('click', { target: button({ last: '60' }) });
    assert.equal(ctx.RING.inS, 60); assert.equal(ctx.RING.outS, 0);
    m.fire('click', { target: button({ last: '120' }) });
    assert.equal(ctx.RING.inS, 95.5, 'more than the ring holds: all of it');
    m.fire('click', { target: button({ rg: 'export' }) });
    await flush(); await flush(); await flush();
    assert.deepEqual(f.jobs.at(-1), ['recording', { op: 'export', in_s: 95.5, out_s: 0, target_mb: 8 }]);
    assert.equal(ctx.RING.clip.name, 'replay-g1.mp4');
    assert.match(m.sub['#rg-clip'].innerHTML, /replay-g1\.mp4 · 9\.5 MB · 1:36 · 720p h264_nvenc/);
    assert.match(m.sub['#rg-clip'].innerHTML, /Request #1084 · auto capture/);
    assert.match(m.sub['#rg-clip'].innerHTML, /Mod card · Fast taxi/);
    assert.doesNotMatch(m.sub['#rg-clip'].innerHTML, /Other game/, 'only this game\'s mod cards');
    assert.ok(f.toasts.some(t => (name === 'desktop' ? /Clip saved to configured-folder/ : /Clip ready: 9\.5 MB/).test(t)));
    if (name === 'desktop') { assert.equal(f.saved.length,1);assert.match(m.sub['#rg-clip'].innerHTML,/Saved to configured-folder/); }
  });

  test(`${name}: the clip opens, attaches to a request and becomes a mod card's video`, async () => {
    const f = fixture(src), { ctx } = f;
    await ctx.ringPopOpen({ clientX: 500, clientY: 20 }, name === 'web' ? 'w-1' : undefined);
    const m = ctx.RING.el;
    m.fire('click', { target: button({ rg: 'export' }) });
    await flush(); await flush(); await flush();
    m.fire('click', { target: button({ rg: 'open' }) });
    await flush();
    assert.ok(name === 'desktop' ? f.opened.at(-1)==='configured-folder/replay-g1.mp4' : f.opened.at(-1).endsWith(`/api/artifacts/${'ab'.repeat(32)}?token=t0k`), f.opened.at(-1));
    m.querySelector('#rg-target').value = 'req:r9';
    m.fire('click', { target: button({ rg: 'attach' }) });
    await flush(); await flush();
    const [url, body] = f.posts.at(-1);
    assert.equal(url, '/api/requests/r9/messages');
    assert.deepEqual(body.attachments, [{ sha256: 'ab'.repeat(32), name: 'replay-g1.mp4', type: 'video/mp4' }]);
    assert.equal(body.text, 'Replay clip: 0:30 of gameplay (9.5 MB)');
    m.querySelector('#rg-target').value = 'mod:m1';
    m.fire('click', { target: button({ rg: 'attach' }) });
    await flush(); await flush(); await flush();
    assert.deepEqual(f.posts.at(-1), ['/api/mods', { title: 'Fast taxi', calls: [{ tool: 'poke', input: {} }], game_id: 'g1', video: 'ab'.repeat(32) }]);
    assert.ok(f.toasts.some(t => /mod card's video/.test(t)));
  });

  test(`${name}: no game, no crash: the pop-up says so`, async () => {
    const f = fixture(src, { gameJob: async () => { throw new Error('no game running'); } });
    await f.ctx.ringPopOpen({ clientX: 1, clientY: 1 });
    const m = f.ctx.RING.el;
    assert.match(m.sub['#rg-state'].textContent, /Start a game first/);
    assert.match(m.sub['#rg-tl'].innerHTML, /Nothing recorded yet/);
    assert.equal(m.sub['[data-rg="export"]'].disabled, true);
  });
}

test('desktop: failed folder export keeps the clip attachable and retries saving without encoding again',async()=>{
  const f=fixture(desktop),{ctx}=f;let attempts=0;
  ctx.gbox.recSaveClip=async()=>{if(++attempts===1)throw Error('Network share unavailable');return {file:'new-preference/clip.mp4'};};
  await ctx.ringPopOpen({clientX:1,clientY:1});const m=ctx.RING.el;
  m.fire('click',{target:button({rg:'export'})});await flush();await flush();await flush();
  assert.equal(ctx.RING.clip.sha256,'ab'.repeat(32));assert.match(m.sub['#rg-clip'].innerHTML,/Network share unavailable.*Retry saving/s);
  assert.ok(!f.toasts.some(t=>/Clip saved/.test(t)));assert.equal(f.opened.length,0);
  m.fire('click',{target:button({rg:'save'})});await flush();await flush();await flush();
  assert.equal(attempts,2);assert.equal(f.jobs.filter(j=>j[1].op==='export').length,1);
  assert.equal(ctx.RING.clip.localFile,'new-preference/clip.mp4');assert.equal(ctx.RING.clip.exportError,undefined);
});

test('embedded web: clip saving crosses the desktop bridge and waits for confirmed destination',async()=>{
  const f=fixture(web,{bnEmbedded:()=>true}),{ctx}=f;const calls=[];
  ctx.console={log:message=>{const m=JSON.parse(message.slice(5));calls.push(m);
    setImmediate(()=>ctx.window.gboxReplaySaved(m.id,{file:'desktop-profile/clip.mp4'},''));}};
  ctx.deskFolders=()=>({showInFolder:file=>f.opened.push(file)});
  await ctx.ringPopOpen({clientX:1,clientY:1},'w-1');const m=ctx.RING.el;
  m.fire('click',{target:button({rg:'export'})});await flush();await flush();await flush();await flush();
  assert.equal(calls[0].ev,'savereplay');assert.equal(calls[0].clip.sha256,'ab'.repeat(32));
  assert.equal(ctx.RING.clip.localFile,'desktop-profile/clip.mp4');assert.match(m.sub['#rg-clip'].innerHTML,/Show in folder/);
  m.fire('click',{target:button({rg:'open'})});await flush();assert.deepEqual(f.opened,['desktop-profile/clip.mp4']);
});

test('desktop: right-click on the record icon opens the replay pop-up; clicking elsewhere closes it', () => {
  assert.match(desktop, /\$\("#tb-rec"\)\.oncontextmenu = e => \{ e\.preventDefault\(\); e\.stopPropagation\(\); ringPopOpen\(e\); \}/);
  assert.match(desktop, /\["#ringpop", "#tb-rec, #recmenu"\]\]/, 'closePops knows #ringpop and its opener');
  assert.match(desktop, /\$\("#tb-recopt"\)\.onclick = openRecMenu;/, 'the ▾ button keeps the app recording options');
  assert.match(desktop, /<button id="tb-rec" title="[^"]*Right-click: replay/);
});

test('web: the session panel offers the replay pop-up', () => {
  assert.match(web, /onclick='ringPopOpen\(event, \$\{JSON\.stringify\(sid\)\}\)'[^>]*>🎬 Replay/);
});
