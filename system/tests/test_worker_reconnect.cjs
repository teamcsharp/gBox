// #1296: the desktop app says why this PC's worker is offline and the ↻ icon reconnects it.
// Extracts the real functions from clients/desktop/main.js and index.html (no Electron needed).
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const mainJs = fs.readFileSync(path.join(root, "clients/desktop/main.js"), "utf8");
const page = fs.readFileSync(path.join(root, "clients/desktop/index.html"), "utf8");

function grab(src, name) {
  const start = src.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} not found`);
  let i = src.indexOf("{", start), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}" && --depth === 0) break;
  }
  return src.slice(start, i + 1);
}

const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const ago = t => `${Math.round(Date.now() / 1000 - t)} s ago`;
const ctx = vm.createContext({ esc, ago });
vm.runInContext(grab(mainJs, "workerExitReason") + "\n" + grab(page, "workerReconnectNote"), ctx);

// The exact console the operator attached to #1296 (i9-NUC worker crash loop).
const tail = `20:22:04.201 [win-worker] Traceback (most recent call last):\r
  File "C:\\_tools\\gBox\\system\\gbox\\worker.py", line 210, in run\r
    raise RuntimeError('Worker activation held: finished results still await verified delivery')\r
RuntimeError: Worker activation held: finished results still await verified delivery\r
20:22:04.909 [win-worker] \n`;

test("exit reason is the final exception line, not the traceback frame", () => {
  assert.strictEqual(ctx.workerExitReason(tail),
    "RuntimeError: Worker activation held: finished results still await verified delivery");
  assert.strictEqual(ctx.workerExitReason("connecting\nplain last line\n"), "plain last line");
  assert.strictEqual(ctx.workerExitReason(""), "");
});

test("offline own worker: panel names the cause and offers reconnect", () => {
  const html = ctx.workerReconnectNote({ name: "i9-NUC", online: false },
    { running: false, lastExit: { code: 1, at: Date.now() - 5000, reason: ctx.workerExitReason(tail) } });
  assert.match(html, /This PC's worker isn't running\./);
  assert.match(html, /↻ refreshes this panel/);
  assert.match(html, /Last worker exit \(code 1, \d+ s ago\): RuntimeError: Worker activation held/);
  assert.match(html, /data-reconnect-worker="1"/);
});

test("running but not checked in, and online, read differently", () => {
  assert.match(ctx.workerReconnectNote({ name: "i9-NUC", online: false }, { running: true }),
    /running but hasn't checked in/);
  const ok = ctx.workerReconnectNote({ name: "i9-NUC", online: true }, { running: true, lastExit: null });
  assert.match(ok, /connected\. ↻ refreshes this panel/);
  assert.doesNotMatch(ok, /Last worker exit/);
  assert.doesNotMatch(ok, /data-reconnect-worker/);
  assert.doesNotMatch(ctx.workerReconnectNote({ online: false }, { running: true }), /data-reconnect-worker/);
});

test("reason text is escaped", () => {
  const html = ctx.workerReconnectNote({ online: false }, { lastExit: { code: 1, at: Date.now(), reason: "Error: <img src=x>" } });
  assert.doesNotMatch(html, /<img/);
});

test("refresh never initiates reconciliation; a separate explicit button is offered", () => {
  const refresh = page.slice(page.indexOf('$("#svc-refresh").onclick'), page.indexOf('floating($("#svcpanel")'));
  assert.match(refresh, /SVC_KEY && svcShow\(SVC_KEY\)/);
  assert.doesNotMatch(refresh, /svcReconnect/);
  assert.match(mainJs, /if \(op === "restart"\) return restartWorker\(\);/);
  assert.match(mainJs, /return \{ running: !!worker, lastExit: workerLastExit \};/);
  assert.match(mainJs, /workerLastExit = \{ code, at: Date\.now\(\), reason: workerExitReason\(workerTail\) \};/);
});

const start = mainJs.indexOf('let workerTail = ');
const end = mainJs.indexOf('ipcMain.handle("win:worker"', start);
assert.ok(start >= 0 && end > start);
function workerHarness({ running = false, standalone = false, deferredToken = null } = {}) {
  const calls = [], scheduled = [];
  const children = [];
  const context = vm.createContext({
    fs: { existsSync: () => true }, STANDALONE: standalone,
    settings: () => ({ repoLocal: '/owned/system', apiUrl: 'http://owned', workerName: 'TestPC', autoStartWorker: false }),
    venvPython: () => '/owned/python', token: () => deferredToken || Promise.resolve('private-test-token'),
    path, os: { homedir: () => '/owned/home' }, process: { env: {} },
    spawn: (_binary, args, options) => {
      calls.push({ args, windowsHide: options.windowsHide });
      const child = { pid: 123, stdout: { on() {} }, stderr: { on() {} }, on() {} };
      children.push(child); return child;
    },
    worker: running ? { pid: 123 } : null, workerStopRequested: false,
    send() {}, setTimeout: (...args) => { scheduled.push(args); },
    execFile: () => assert.fail('reconnect must never terminate a worker or its children'),
  });
  vm.runInContext(mainJs.slice(start, end), context);
  return { context, calls, scheduled, children };
}

test('running worker reconnect is refused without kill, spawn or claimed restart', async () => {
  const h = workerHarness({ running: true });
  const result = await h.context.restartWorker();
  assert.equal(result.running, true);
  assert.equal(result.started, false);
  assert.match(result.error, /still running.*held/);
  assert.equal(h.calls.length, 0);
});

test('stopped worker explicitly starts with bounded result reconciliation and no kill', async () => {
  const h = workerHarness();
  const result = await h.context.restartWorker();
  assert.equal(result.started, true); assert.equal(result.restarted, true);
  assert.equal(h.calls.length, 1);
  assert.ok(h.calls[0].args.includes('--reconcile-results'));
  assert.equal(h.calls[0].windowsHide, true);
});

test('watchdog start does not reconcile refused results', async () => {
  const h = workerHarness();
  await h.context.startWorker();
  assert.equal(h.calls.length, 1);
  assert.ok(!h.calls[0].args.includes('--reconcile-results'));
});

test('concurrent starts are serialized and cannot spawn duplicate workers', async () => {
  let release;
  const h = workerHarness({ deferredToken: new Promise(resolve => { release = resolve; }) });
  const first = h.context.startWorker();
  const second = h.context.startWorker();
  const rejected = await h.context.restartWorker();
  assert.equal(rejected.started, false);
  assert.match(rejected.error, /already starting/);
  release('private-test-token');
  await Promise.all([first, second]);
  assert.equal(h.calls.length, 1);
});

test('standalone reconnect does not implicitly restart its control plane', async () => {
  const h = workerHarness({ standalone: true });
  const result = await h.context.restartWorker();
  assert.equal(result.started, false);
  assert.match(result.error, /maintenance review/);
  assert.equal(h.calls.length, 0);
});

test('missing start confirmation is shown as an error without claiming connection', async () => {
  const begin = page.indexOf('async function svcReconnect(key)');
  const finish = page.indexOf('$("#svc-refresh").onclick', begin);
  const messages = [];
  const element = { insertAdjacentHTML: (_where, text) => messages.push(text), remove() {} };
  const context = vm.createContext({
    $: () => element, esc, SVC_KEY: 'worker:old-worker', S: { workerName: 'TestPC' },
    gbox: { winWorker: async () => ({ running: true }), api: async () => assert.fail('missing start confirmation must not poll') },
    setTimeout: callback => callback(), svcShow: async () => {},
  });
  vm.runInContext(page.slice(begin, finish), context);
  await context.svcReconnect('worker:old-worker');
  assert.match(messages.join('\n'), /did not start.*not confirmed/);
});

test('a fresh worker ID reconnects by this configured PC identity, not the stale ID', async () => {
  const begin = page.indexOf('async function svcReconnect(key)');
  const finish = page.indexOf('$("#svc-refresh").onclick', begin);
  const messages = [], polled = [];
  const element = { insertAdjacentHTML: (_where, text) => messages.push(text), remove() {} };
  const context = vm.createContext({
    $: () => element, esc, SVC_KEY: 'worker:old-worker', S: { workerName: 'TestPC' },
    gbox: { winWorker: async () => ({ started: true }), api: async path => {
      polled.push(path); return { data: [{ id: 'new-worker', name: 'TestPC', online: true }] };
    } },
    setTimeout: callback => callback(), svcShow: async () => {},
  });
  vm.runInContext(page.slice(begin, finish), context);
  await context.svcReconnect('worker:old-worker');
  assert.equal(polled.length, 1);
  assert.doesNotMatch(messages.join('\n'), /connection is not confirmed/);
});
