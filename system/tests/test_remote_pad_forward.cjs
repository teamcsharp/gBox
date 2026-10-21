// Run with node system/tests/test_remote_pad_forward.cjs. #1532: a pad on the PC viewing a Spark-hosted session drives it.
// Drives the web client's real controller loop with a fake navigator.getGamepads and the desktop's XInput pushes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../clients/web/index.html'), 'utf8');
const source = html.slice(html.indexOf('const RETRO ='), html.indexOf('async function snap(sid)'));
const SID = '13e9fba6ff024e99-9ec23b6f5cfc4726';
const HID = 'HID-compliant game controller (STANDARD GAMEPAD Vendor: 045e Product: 0b20)';

function client() {
  const storage = new Map(), sent = [], nodes = new Map();
  let frames = 0;
  const ctx = vm.createContext({
    navigator: { getGamepads: () => ctx.devices }, devices: [], console,
    localStorage: { getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v) },
    api: async (url, body, method, timeoutMs) => sent.push({ url, timeoutMs, ...body }),
    requestAnimationFrame() { frames++; }, addEventListener() {}, setInterval() {},
    $: key => nodes.get(key), cur: 'Sessions', show() {},
    esc: v => String(v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
  });
  ctx.window = ctx;
  vm.runInContext(source, ctx);
  const run = code => vm.runInContext(code, ctx);
  run(`active = ${JSON.stringify({ sid: SID, title: 'Dead or Alive 2', local: false })}`);
  const events = () => sent.flatMap(s => s.events.map(e => ({ url: s.url, ...e })));
  const flush = () => run('Promise.all([...padQueues.values()])');
  // the desktop host's push, as clients/desktop/index.html sends it
  const push = pads => run(`window.gboxNativePad(${JSON.stringify(pads)})`);
  return { ctx, run, sent, events, flush, push, nodes, storage, frames: () => frames };
}
const gamepad = (id, index, mapping = 'standard') => ({ id, index, mapping, connected: true, axes: [0, 0, 0, 0],
  buttons: Array.from({ length: 17 }, () => ({ pressed: false, value: 0 })) });
const xi = (buttons = 0, more = {}) => [{ slot: 0, buttons, lt: 0, rt: 0, lx: 0, ly: 0, rx: 0, ry: 0, ...more }];
const START = 0x0010, A = 0x1000;
const url = `/api/sessions/${SID}/input`;

async function test() {
  // 1. The ticket: the HID Xbox pad is Player 1, but the view's Gamepad API reports no presses (unfocused/hidden
  //    view). Before the fix nothing reached the session; the desktop's XInput reading now drives Player 1.
  {
    const c = client(), hid = gamepad(HID, 0); c.ctx.devices = [hid];
    c.run('padLoop()'); await c.flush();
    assert.equal(c.sent.length, 0);
    c.push(xi(START)); await c.flush();
    assert.deepEqual(c.events(), [{ url, key: 'start', down: true, player: 1 }], 'Start reaches the remote session');
    assert.equal(c.sent[0].timeoutMs, 5000, 'a stalled request cannot hold later presses forever');
    // never double-sent: the animation-frame pass and Chromium's own copy of the same pad add nothing
    hid.buttons[9] = { pressed: true, value: 1 };
    c.run('padLoop(); padLoop()'); c.push(xi(START)); await c.flush();
    assert.equal(c.events().length, 1, 'one press, one event');
    c.push(xi(0)); await c.flush();
    assert.deepEqual(c.events().at(-1), { url, key: 'start', down: false, player: 1 });
    c.run('padLoop()'); await c.flush();
    assert.equal(c.events().length, 2, "the browser's stale copy of the pad sends nothing");
    // positional RetroPad layout and the left stick as d-pad, like the browser path
    c.push(xi(A, { lx: -30000 })); await c.flush();
    assert.deepEqual(c.events().slice(-2).map(e => e.key).sort(), ['b', 'left']);
    c.push(xi(0)); await c.flush();
    // the controller status names the selected pad as Player 1
    const stat = { setAttribute() {} }; c.nodes.set('#padstat', stat); c.run('padStatus()');
    assert.match(stat.textContent, /HID-compliant game controller .* → Player 1/);
  }
  // 2. Local (native window) sessions are unchanged: the emulator reads the pad itself, nothing is forwarded.
  {
    const c = client(); c.ctx.devices = [gamepad(HID, 0)];
    c.run(`active = { sid: 'JAY-1', title: 'x', local: true }`);
    c.push(xi(START)); c.run('padLoop()'); await c.flush();
    assert.equal(c.sent.length, 0, 'no forwarding to a local native game');
  }
  // 3. A plain browser (no desktop pushes) or a stale native reading keeps the Gamepad API path.
  {
    const c = client(), hid = gamepad(HID, 0); c.ctx.devices = [hid];
    hid.buttons[9] = { pressed: true, value: 1 };
    c.run('padLoop()'); await c.flush();
    assert.deepEqual(c.events(), [{ url, key: 'start', down: true, player: 1 }], 'browser path unchanged');
    c.push(xi(0)); await c.flush();                            // native takes over: the browser copy is released once
    assert.deepEqual(c.events().at(-1), { url, key: 'start', down: false, player: 1 });
    c.run('window.GBOX_NATIVE_PAD_STATE.at = Date.now() - 5000; padLoop()'); await c.flush();
    assert.deepEqual(c.events().at(-1), { url, key: 'start', down: true, player: 1 }, 'stale native: browser again');
    assert.equal(c.events().length, 3);
  }
  // 4. Chromium has not exposed the pad at all (no button pressed in the view since it loaded): native is Player 1.
  {
    const c = client();
    c.push(xi(START)); await c.flush();
    assert.deepEqual(c.events(), [{ url, key: 'start', down: true, player: 1 }]);
    const stat = { setAttribute() {} }; c.nodes.set('#padstat', stat); c.run('padStatus()');
    assert.match(stat.textContent, /Xbox controller \(XInput slot 0\) → Player 1/);
  }
  // 5. "Off" stays off; an explicitly chosen non-Xbox pad stays Player 1 and the Xbox reading is not forwarded.
  {
    const c = client(), ds = gamepad('DualSense Wireless Controller', 1); c.ctx.devices = [gamepad(HID, 0), ds];
    c.run('selectPrimaryPad("none")'); c.push(xi(START)); await c.flush();
    assert.equal(c.sent.length, 0, 'forwarding off');
    c.run(`selectPrimaryPad(${JSON.stringify(JSON.stringify({ id: ds.id, index: 1 }))})`);
    c.push(xi(START)); await c.flush();
    assert.equal(c.sent.length, 0, 'the Xbox pad is not Player 1');
    ds.buttons[0] = { pressed: true, value: 1 }; c.run('padLoop()'); await c.flush();
    assert.deepEqual(c.events(), [{ url, key: 'b', down: true, player: 1 }]);
  }
  // 6. Mini window: the main view is hidden (no animation frames); presses go to the session the mini window shows.
  {
    const c = client(); c.run('active = null');
    c.run(`window.gboxPadTarget('spark-mini')`);
    c.push(xi(START)); await c.flush();
    assert.deepEqual(c.events(), [{ url: '/api/sessions/spark-mini/input', key: 'start', down: true, player: 1 }]);
    c.run('window.gboxPadTarget(null)'); await c.flush();
    assert.deepEqual(c.events().at(-1), { url: '/api/sessions/spark-mini/input', key: 'start', down: false, player: 1 },
      'closing mini releases what it held');
    c.push(xi(0)); await c.flush();
    assert.equal(c.events().length, 2, 'nothing goes anywhere with no streamed game open');
  }
  // 7. One failing pass must not end controller input for the page's life.
  {
    const c = client(), before = c.frames();
    c.ctx.navigator.getGamepads = () => { throw new Error('boom'); };
    c.ctx.console = { warn() {} };
    c.run('padLoop()');
    assert.equal(c.frames(), before + 1, 'next frame still scheduled');
  }
  // 8. The desktop host hands every XInput change to the view's gboxNativePad, and mini open/close sets the target.
  {
    const host = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
    const at = host.indexOf('gbox.onPadState?.('), end = host.indexOf('setInterval(', at);
    const calls = [], handlers = {};
    const wv = { executeJavaScript: code => { calls.push(code); return Promise.resolve(); } };
    const ctx = vm.createContext({ document: { querySelector: () => wv },
      gbox: { onPadState: fn => { handlers.pad = fn; }, onMiniClosed: fn => { handlers.mini = fn; } } });
    vm.runInContext(host.slice(at, end) + ';globalThis.miniPadTarget = miniPadTarget;', ctx);
    handlers.pad(xi(START));
    const c = client(); c.run(calls[0]); await c.flush();
    assert.deepEqual(c.events(), [{ url, key: 'start', down: true, player: 1 }], 'host push reaches the forwarder');
    ctx.miniPadTarget('spark-mini'); handlers.mini();
    assert.deepEqual(calls.slice(1), ['window.gboxPadTarget?.("spark-mini")', 'window.gboxPadTarget?.(null)']);
    const mini = host.slice(host.indexOf('$("#tb-mini").onclick'), host.indexOf('// ---------------- Tools:'));
    assert.match(mini, /compactEnter\(\)/);
    assert.match(host, /pad: sid => miniPadTarget\(sid\)/);
    // an older view without gboxNativePad still gets the glyph state
    const old = vm.createContext({ window: {}, Date }); vm.runInContext(calls[0], old);
    assert.equal(old.window.GBOX_NATIVE_PAD_STATE.pads[0].buttons, START);
    const main = fs.readFileSync(path.join(__dirname, '../clients/desktop/main.js'), 'utf8');
    assert.match(main, /mini\.on\("closed"[^\n]*webContents\.send\("mini:closed"\)/);
    const preload = fs.readFileSync(path.join(__dirname, '../clients/desktop/preload.js'), 'utf8');
    assert.match(preload, /onMiniClosed: fn => ipcRenderer\.on\("mini:closed"/);
  }
  // 9. A disconnected compact view releases the original session and blocks subsequent held presses.
  {
    const c = client(); c.run(`window.gboxPadTarget('spark-mini')`); c.push(xi(START)); await c.flush();
    c.run(`window.gboxPadStreamState('spark-mini', false)`); await c.flush();
    assert.deepEqual(c.events().at(-1), { url: '/api/sessions/spark-mini/input', key: 'start', down: false, player: 1 });
    const count = c.events().length; c.push(xi(START)); await c.flush(); assert.equal(c.events().length, count);
    c.run(`window.gboxPadStreamState('another-session', true)`); await c.flush(); assert.equal(c.events().length, count);
    c.run(`window.gboxPadStreamState('spark-mini', true)`); await c.flush(); assert.equal(c.events().at(-1).down, true);
  }
  // 10. The main picture's connection state gates the same real controller loop.
  {
    const c = client(); c.ctx.gboxStreamWatchdog = require('../clients/web/viz/stream-watchdog.js');
    const attrs = { src: '/api/sessions/' + SID + '/mjpeg', 'data-stream-state': 'connected' };
    c.nodes.set('#scr', { tagName: 'IMG', getAttribute: k => attrs[k] }); c.push(xi(START)); await c.flush();
    attrs['data-stream-state'] = 'reconnecting'; c.run('padLoop()'); await c.flush();
    assert.deepEqual(c.events().at(-1), { url, key: 'start', down: false, player: 1 });
    const count = c.events().length; c.push(xi(START)); await c.flush(); assert.equal(c.events().length, count);
  }
  // 11. Typing in the compact coach must gate input, not clear its target and fall back to active.
  {
    const c = client(); c.run(`window.gboxPadTarget('spark-mini')`); c.push(xi(START)); await c.flush();
    c.run('window.gboxPadTextCapture(true)'); await c.flush();
    assert.deepEqual(c.events().at(-1), { url: '/api/sessions/spark-mini/input', key: 'start', down: false, player: 1 });
    const count = c.events().length; c.push(xi(START)); await c.flush(); assert.equal(c.events().length, count);
    c.run('window.gboxPadTextCapture(false)'); await c.flush();
    assert.deepEqual(c.events().at(-1), { url: '/api/sessions/spark-mini/input', key: 'start', down: true, player: 1 });
  }
  console.log('Remote pad forwarding checks passed (11 groups)');
}
test().catch(e => { console.error(e); process.exitCode = 1; });
