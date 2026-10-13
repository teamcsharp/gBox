// #72: the conversation (chat panel) must end in a talk section — a text composer with a
// send button and a microphone icon that switches gBox into hands-free voice mode. The DOM
// behaviour runs in a real headless Chromium (driven over CDP); the browser checks are
// skipped when no Chromium is installed, the source and vm checks always run.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const { spawn } = require('node:child_process');

const html = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
function between(start, end) {
  const a = html.indexOf(start), b = html.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, `missing desktop source boundary: ${start}`);
  return html.slice(a, b);
}
const composer = between('// conversation composer + clickable options + voice-mode mic', 'chatModels();');
const talkStart = between('async function talkStart()', 'const STT');
const voice = between('// ---------------- voice conversation: listen', '// ---------------- dictation:');

test('the conversation ends in a composer with a microphone icon', () => {
  const panel = between('id="chatlog"></div><div id="chatimgs">', '<div class="pickhint"');
  assert.match(panel, /id="chatcomp">\s*<textarea id="chatin2"/, 'the composer section follows the conversation log');
  assert.match(panel, /id="chatsend"/, 'the composer has a send button');
  const mic = between('id="chatvoice"', '</button>');
  assert.match(mic, /<rect x="9" y="2" width="6" height="12" rx="3"/, 'the voice button shows a microphone glyph');
  assert.match(mic, /<path d="M5 10a7 7 0 0 0 14 0M12 17v5"/, 'the microphone glyph includes the stand and cable');
  assert.doesNotMatch(mic, /M3 10v4/, 'the old volume-bars glyph is gone');
});

function nodes() {
  const map = new Map();
  const node = id => {
    if (!map.has(id)) map.set(id, { id, value: '', innerHTML: '', textContent: '', scrollTop: 0, scrollHeight: 20,
      style: {}, dataset: {}, options: [], selectedOptions: [], classes: new Set(), attrs: {},
      setAttribute(k, v) { this.attrs[k] = v; },
      classList: { add: (...c) => c.forEach(x => map.get(id).classes.add(x)),
        remove: (...c) => c.forEach(x => map.get(id).classes.delete(x)),
        toggle: (c, on) => on === undefined ? (map.get(id).classes.has(c) ? map.get(id).classes.delete(c) : map.get(id).classes.add(c)) : (on ? map.get(id).classes.add(c) : map.get(id).classes.delete(c)),
        contains: c => map.get(id).classes.has(c) },
      addEventListener() {}, insertAdjacentHTML() {}, querySelectorAll: () => [], querySelector: () => null });
    return map.get(id);
  };
  return { map, node };
}

test('the composer sends on Enter, the send button and clears itself', () => {
  const { node } = nodes();
  const sent = [];
  const context = vm.createContext({ $: node, esc: String, chatSend: v => sent.push(v),
    TALK: { on: false }, talkStart: () => {}, talkStop: () => {}, compFit() {},
    MutationObserver: function () { this.observe = () => {}; }, setInterval: () => 0,
    addEventListener() {}, window: {}, alert() {} });
  vm.runInContext(composer, context);
  const run = code => vm.runInContext(code, context);
  const box = node('#chatin2');
  box.value = 'give me infinite lives';
  run('compSend()');
  assert.deepEqual(sent, ['give me infinite lives'], 'compSend hands the text to the chat');
  assert.equal(box.value, '', 'compSend clears the composer');
  box.value = 'second line';
  box.onkeydown({ key: 'Enter', shiftKey: false, isComposing: false, preventDefault() {} });
  assert.deepEqual(sent, ['give me infinite lives', 'second line'], 'Enter sends');
  assert.equal(box.value, '', 'Enter clears the composer too');
  box.value = 'keep me';
  box.onkeydown({ key: 'Enter', shiftKey: true, isComposing: false, preventDefault() {} });
  assert.equal(box.value, 'keep me', 'Shift+Enter inserts a new line instead of sending');
  box.value = 'composing';
  box.onkeydown({ key: 'Enter', shiftKey: false, isComposing: true, preventDefault() {} });
  assert.equal(box.value, 'composing', 'Enter while an IME is composing does not send');
  box.value = 'via button';
  node('#chatsend').onclick();
  assert.equal(sent.at(-1), 'via button', 'the send button sends the composer text');
});

test('the microphone icon switches the conversation into voice mode', () => {
  const { node } = nodes();
  const calls = { start: 0, stop: 0, menu: [] };
  const TALK = { on: false };
  const context = vm.createContext({ $: node, esc: String, chatSend() {},
    TALK, talkStart: () => { calls.start++; TALK.on = true; }, talkStop: () => { calls.stop++; TALK.on = false; },
    MutationObserver: function () { this.observe = () => {}; }, setInterval: () => 0, addEventListener() {},
    window: { gboxMicMenu: (anchor, ev) => calls.menu.push([anchor, ev]) }, alert() {} });
  vm.runInContext(composer, context);
  const mic = node('#chatvoice');
  mic.onclick();
  assert.equal(calls.start, 1, 'the mic icon starts voice mode');
  assert.equal(TALK.on, true);
  mic.onclick();
  assert.equal(calls.stop, 1, 'clicking again ends voice mode');
  assert.equal(TALK.on, false);
  const ev = {};
  mic.oncontextmenu(ev);
  assert.equal(calls.menu.length, 1, 'right-click opens the default-microphone menu');
  assert.equal(calls.menu[0][0], mic, 'the menu is anchored on the mic icon');
  assert.equal(calls.menu[0][1], ev);
});

test('voice mode opens the microphone and the live sidebar, and stops cleanly', async () => {
  const { node } = nodes();
  const stopped = [], alerts = [], ctxs = [];
  const TALK = { on: false, stream: null, ctx: null, audio: null };
  const stream = { getTracks: () => [{ stop: () => stopped.push(1) }] };
  const context = vm.createContext({ $: node, esc: String, TALK,
    live: () => {}, liveStatus() {}, liveVoices: async () => {}, liveCard: async () => {},
    instantCommand: async () => null, chatContext: async () => ({}), CH: { cid: 'c1' },
    S: { apiUrl: 'https://fixture.invalid' }, EMB: { last: '' },
    gbox: { api: async () => ({ ok: false }), stt: async () => 'spoken', tts: async () => new ArrayBuffer(0) },
    navigator: { mediaDevices: { getUserMedia: async () => stream } },
    MediaRecorder: function () { this.start = () => {}; this.stop = () => {}; },
    AudioContext: function () { ctxs.push(this); this.close = () => { this.closed = true; }; this.createMediaStreamSource = () => ({ connect() {} });
      this.createAnalyser = () => ({ fftSize: 1024, getFloatTimeDomainData: a => a.fill(0) }); },
    Audio: function () { this.play = () => Promise.resolve(); }, URL: { createObjectURL: () => 'blob:' },
    Blob, JSON, requestAnimationFrame: () => 0, localStorage: { getItem: () => '', setItem() {} },
    document: { body: node('body'), querySelectorAll: () => [] },
    window: { gboxMicMenu() {}, gboxMicAudio: o => o }, alert: m => alerts.push(m), talkLoop: async () => {} });
  vm.runInContext(talkStart + '\n' + 'async function talkLoop() {}', context);
  node('#livevoice').options = [{ text: 'Adam' }];
  await context.talkStart();
  assert.equal(TALK.on, true, 'voice mode is on');
  assert.equal(stopped.length, 0);
  assert.ok(node('#live').classes.has('on'), 'the live voice sidebar opens');
  assert.ok(node('#talkbtn').classes.has('on'), 'the talk button lights up');
  assert.ok(node('body').classes.has('talking'));
  context.talkStop();
  assert.equal(TALK.on, false, 'voice mode is off');
  assert.equal(stopped.length, 1, 'the microphone track is released');
  assert.equal(ctxs.length, 1, 'an AudioContext was opened for the mic');
  assert.equal(ctxs[0].closed, true, 'the AudioContext is closed with voice mode');
  assert.ok(!node('#live').classes.has('on'));
  assert.ok(!node('body').classes.has('talking'));
});

test('voice mode reports an unavailable microphone instead of half-starting', async () => {
  const { node } = nodes();
  const alerts = [];
  const context = vm.createContext({ $: node, esc: String, TALK: { on: false, stream: null, ctx: null, audio: null },
    live: () => {}, liveStatus() {}, liveVoices: async () => {}, liveCard: async () => {},
    instantCommand: async () => null, chatContext: async () => ({}), CH: { cid: 'c1' },
    S: { apiUrl: 'https://fixture.invalid' }, EMB: { last: '' },
    gbox: { api: async () => ({ ok: false }), stt: async () => '', tts: async () => new ArrayBuffer(0) },
    navigator: { mediaDevices: { getUserMedia: async () => { throw new Error('denied'); } } },
    MediaRecorder: function () {}, AudioContext: function () { this.close = () => {}; },
    Audio: function () {}, URL: { createObjectURL: () => 'blob:' }, Blob, JSON,
    requestAnimationFrame: () => 0, localStorage: { getItem: () => '', setItem() {} },
    document: { body: node('body'), querySelectorAll: () => [] },
    window: { gboxMicMenu() {}, gboxMicAudio: o => o }, alert: m => alerts.push(m), talkLoop: async () => {} });
  vm.runInContext(talkStart + '\n' + 'async function talkLoop() {}', context);
  await context.talkStart();
  assert.equal(context.TALK.on, false, 'voice mode must not start without a microphone');
  assert.equal(alerts.length, 1);
  assert.match(alerts[0], /Microphone unavailable/);
});

function findChrome() {
  if (process.env.GBOX_CHROME && fs.existsSync(process.env.GBOX_CHROME)) return process.env.GBOX_CHROME;
  if (process.platform === 'win32') {
    for (const p of [path.join(process.env['PROGRAMFILES(X86)'] || '', 'Microsoft/Edge/Application/msedge.exe'),
      path.join(process.env.PROGRAMFILES || '', 'Google/Chrome/Application/chrome.exe')]) {
      if (fs.existsSync(p)) return p;
    }
  }
  const root = path.join(os.homedir(), '.cache/ms-playwright');
  if (!fs.existsSync(root)) return null;
  for (const dir of fs.readdirSync(root).sort().reverse()) {
    for (const rel of ['chrome-linux/headless_shell', 'headless_shell', 'chrome-linux/chrome', 'chrome-linux64/chrome']) {
      const p = path.join(root, dir, rel);
      if (/^chromium/.test(dir) && fs.existsSync(p)) return p;
    }
  }
  return null;
}

async function withPage(fn) {
  const chrome = findChrome();
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'gbox-72-'));
  const proc = spawn(chrome, ['--headless', '--no-sandbox', '--disable-gpu', '--remote-debugging-port=0',
    `--user-data-dir=${profile}`, 'about:blank'], { stdio: 'ignore', windowsHide: true });
  const exited = new Promise(resolve => proc.once('exit', resolve));
  let ws;
  try {
    // Every step waits for its condition (up to 30 s) instead of a fixed number of polls: a loaded
    // machine starts the browser slowly, the port file can exist before its port line is written, and
    // /json/list can briefly have no page target.
    const until = async (what, probe) => {
      for (const end = Date.now() + 30000; ;) {
        const value = await probe().catch(() => null);
        if (value) return value;
        if (Date.now() > end || proc.exitCode !== null) throw new Error(`headless browser: no ${what}`);
        await new Promise(r => setTimeout(r, 50));
      }
    };
    const portFile = path.join(profile, 'DevToolsActivePort');
    const port = await until('DevToolsActivePort', async () => {
      const line = fs.readFileSync(portFile, 'utf8').split('\n')[0].trim();
      return /^\d+$/.test(line) && line;
    });
    const page = await until('page target', async () =>
      (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t => t.type === 'page' && t.webSocketDebuggerUrl));
    ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((ok, no) => { ws.onopen = ok; ws.onerror = no; });
    let seq = 0; const waiting = new Map(), events = [];
    ws.onmessage = e => {
      const m = JSON.parse(e.data);
      if (m.id === undefined) { events.push(m.method); return; }
      waiting.get(m.id)?.(m); waiting.delete(m.id);
    };
    const send = (method, params) => new Promise(ok => { const id = ++seq; waiting.set(id, ok); ws.send(JSON.stringify({ id, method, params })); });
    // The command-line about:blank may still be committing; a script evaluated before that loses its
    // document mid-run. Navigate once ourselves and evaluate only after that load has fired.
    await send('Page.enable', {});
    events.length = 0;
    await send('Page.navigate', { url: 'about:blank' });
    await until('page load', async () => events.includes('Page.loadEventFired'));
    const evaluate = async expression => {
      const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      if (r.error) throw new Error('Runtime.evaluate: ' + JSON.stringify(r.error));
      if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails));
      return r.result.result.value;
    };
    await fn(evaluate);
  } finally {
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ id: 1000000, method: 'Browser.close' }));
    const delay = ms => new Promise(resolve => { const timer = setTimeout(resolve, ms); timer.unref(); });
    await Promise.race([exited, delay(3000)]);
    if (proc.exitCode === null && proc.signalCode === null) {
      proc.kill('SIGKILL'); await Promise.race([exited, delay(3000)]);
    }
    ws?.close();
    // Windows keeps profile handles open until the browser's child processes exit, which takes longer
    // on a loaded machine: retry for up to 15 s.
    for (let i = 0; i < 300; i++) {
      try { fs.rmSync(profile, { recursive: true, force: true }); break; }
      catch (error) {
        if (i === 299 || !['EPERM', 'EBUSY', 'ENOTEMPTY'].includes(error.code)) throw error;
        await new Promise(resolve => setTimeout(resolve, 50));
      }
    }
  }
}

test('the composer and the voice-mode mic work in a real browser', { skip: !findChrome() && 'no Chromium installed' }, async () => {
  await withPage(async evaluate => {
    const out = await evaluate(`(async () => {
      document.body.innerHTML = '<div id="chatpanel" class="on"><div id="chatmain">' +
        '<div id="chatlog" style="height:60px;overflow:auto">older turns…</div><div id="chatimgs"></div>' +
        '<div id="chatcomp"><textarea id="chatin2" rows="1"></textarea>' +
        '<button id="chatvoice" title="Voice mode"></button><button id="chatsend"></button></div></div></div>' +
        '<aside id="live"><div id="livestatus"></div><div id="livemeter"><i></i></div>' +
        '<div id="livefeed"></div><select id="livevoice"><option selected>XTTS · Adam</option></select>' +
        '<button id="livestop"></button></aside><button id="talkbtn"></button><div id="report"></div>';
      const $ = sel => document.querySelector(sel);
      const esc = s => String(s ?? '');
      const instantCommand = async () => null;
      const chatContext = async () => ({});
      const CH = { cid: 'c1' }; const S = { apiUrl: 'https://fixture.invalid' };
      const EMB = { last: '' };
      const sent = []; const chatSend = v => sent.push(v);
      class MediaRecorder { constructor(s) { this.state = 'inactive'; } start() {} stop() { this.state = 'inactive'; this.onstop && this.onstop(); } }
      class AudioContext { close() {} createMediaStreamSource() { return { connect() {} }; }
        createAnalyser() { return { fftSize: 1024, getFloatTimeDomainData: a => a.fill(0) }; } }
      class Audio { constructor() { this.paused = false; } play() { return Promise.resolve(); } pause() { this.paused = true; } }
      const gbox = { api: async () => ({ ok: false }), stt: async () => 'spoken words', tts: async () => new ArrayBuffer(0), token: async () => 'tok' };
      const released = [];
      navigator.mediaDevices = { getUserMedia: async () => ({ getTracks: () => [{ stop: () => released.push(1) }] }) };
      window.gboxMicMenu = (...args) => { window.__micMenu = args; };
      window.gboxMicAudio = o => o;
      ${voice}
      ${composer}
      const r = {};
      // talkStart is async (it awaits the microphone): wait for its last step, not a fixed delay that a
      // loaded machine can outlast. The checks below still read every condition themselves.
      const settled = async done => { for (const end = Date.now() + 10000; !done() && Date.now() < end;) await new Promise(ok => setTimeout(ok, 20)); };
      r.composerBelowLog = $('#chatcomp').getBoundingClientRect().top >= $('#chatlog').getBoundingClientRect().top;
      r.mic = !!$('#chatvoice');
      $('#chatvoice').click();
      await settled(() => document.body.classList.contains('talking'));
      r.voiceOn = TALK.on && $('#live').classList.contains('on') && $('#talkbtn').classList.contains('on');
      r.bodyTalking = document.body.classList.contains('talking');
      $('#chatvoice').click();
      await settled(() => !document.body.classList.contains('talking'));
      r.voiceOff = !TALK.on && !$('#live').classList.contains('on') && released.length > 0;
      $('#chatvoice').dispatchEvent(new MouseEvent('contextmenu', { bubbles: true }));
      r.micMenu = Array.isArray(window.__micMenu) && window.__micMenu[0] === $('#chatvoice');
      const box = $('#chatin2'); box.value = 'hi from the composer';
      box.onkeydown({ key: 'Enter', shiftKey: false, isComposing: false, preventDefault() {} });
      r.sent = sent;
      r.cleared = box.value === '';
      return r;
    })()`);
    assert.equal(out.composerBelowLog, true, 'the composer section sits at the bottom of the conversation');
    assert.equal(out.mic, true, 'the microphone icon is rendered');
    assert.equal(out.voiceOn, true, 'the mic icon switches the conversation into voice mode');
    assert.equal(out.bodyTalking, true);
    assert.equal(out.voiceOff, true, 'a second click ends voice mode and releases the microphone');
    assert.equal(out.micMenu, true, 'right-click on the mic icon opens the default-microphone menu');
    assert.deepEqual(out.sent, ['hi from the composer'], 'Enter sends the composed text');
    assert.equal(out.cleared, true, 'the composer clears after sending');
  });
});
