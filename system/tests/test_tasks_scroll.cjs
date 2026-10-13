// #1289: the Technical task list must not throw the reader back to the top on its 5 s refresh.
// The DOM behaviour runs in a real headless Chromium (driven over CDP); the browser checks are
// skipped when no Chromium is installed, the source checks always run.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

const html = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
function between(start, end) {
  const a = html.indexOf(start), b = html.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, `missing desktop source boundary: ${start}`);
  return html.slice(a, b);
}
const helpers = between('const TK_OWNER', 'async function tasksLocalLoad()');

test('every Technical refresh path keeps the reader place', () => {
  const load = between('async function tasksLoad()', 'async function tkHermesRefresh');
  assert.match(load, /tkRender\(\$\("#tk-body"\), `<div class="mc"><div class="mh"><b>Hermes background runs/);
  assert.match(load, /, \$\("#tk-technical"\)\);\s*\$\("#tk-body"\)\.querySelectorAll\("details\[data-detail-hermes\]\[open\]"\)/);
  assert.doesNotMatch(load, /\$\("#tk-body"\)\.innerHTML\s*=/, 'tasksLoad must not replace the list directly');
  // An open job keeps its loaded details instead of collapsing to "Loading…", which shrank the panel.
  assert.equal((load.match(/TK\.jobDetail\.get\(j\.id\) \|\| "Loading task details…"/g) || []).length, 2);
  assert.match(load, /<details data-tk-key="cmd:/);
  const local = between('async function tasksLocalLoad()', 'async function tasksLoad()');
  assert.match(local, /tkRender\(\$\("#tk-local"\), html, pane\)/);
  const job = between('async function tkJobRefresh(detail)', 'async function tvPoll()');
  assert.match(job, /if \(box\.tkMain !== main\)/);
  assert.match(job, /holder\.tkHtml !== filesHtml/);
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
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'gbox-tk-'));
  const proc = spawn(chrome, ['--headless', '--no-sandbox', '--disable-gpu', '--remote-debugging-port=0',
    `--user-data-dir=${profile}`, 'about:blank'], { stdio: 'ignore', windowsHide: true });
  const exited = new Promise(resolve => proc.once('exit', resolve));
  let ws;
  try {
    // Same startup as test_chat_conversation_composer.cjs: wait for each condition (up to 30 s), and
    // evaluate only after our own about:blank load so the command-line navigation cannot replace the
    // document mid-script.
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
    // Close only the browser created for this temporary profile, including its child processes.
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ id: 1000000, method: 'Browser.close' }));
    const delay = ms => new Promise(resolve => { const timer = setTimeout(resolve, ms); timer.unref(); });
    await Promise.race([exited, delay(3000)]);
    if (proc.exitCode === null && proc.signalCode === null) {
      proc.kill('SIGKILL'); await Promise.race([exited, delay(3000)]);
    }
    ws?.close();
    // Windows can retain a profile file handle briefly after the parent browser exits.
    for (let i = 0; i < 300; i++) {
      try { fs.rmSync(profile, { recursive: true, force: true }); break; }
      catch (error) {
        if (i === 299 || !['EPERM', 'EBUSY', 'ENOTEMPTY'].includes(error.code)) throw error;
        await new Promise(resolve => setTimeout(resolve, 50));
      }
    }
  }
}

test('a refresh keeps the panel scroll, open logs and expanded rows in a real browser', { skip: !findChrome() && 'no Chromium installed' }, async () => {
  await withPage(async evaluate => {
    const out = await evaluate(`(() => {
      document.body.innerHTML = '<div id="pane" style="height:200px;overflow:auto"><div id="host"></div></div>';
      const TK = { pointerDown: 0, scrolledAt: 0 };
      ${helpers}
      const pane = document.getElementById('pane'), host = document.getElementById('host');
      const lines = n => Array.from({ length: n }, (_, i) => 'trace line ' + i).join('\\n');
      const page = (cpu, n) => '<div style="height:600px">CPU ' + cpu + '%</div>' +
        '<details data-resolution-id="r1270" open><summary>#1270</summary><pre style="height:80px;overflow:auto;margin:0">' + lines(n) + '</pre></details>' +
        '<details data-resolution-id="r1291" open><summary>#1291</summary><pre style="height:80px;overflow:auto;margin:0">' + lines(n) + '</pre></details>' +
        '<table><tr><td><details data-tk-key="cmd:w:42"><summary>retroarch</summary><pre>retroarch.exe -L flycast</pre></details></td></tr></table>' +
        '<div style="height:600px"></div>';
      const out = {};
      out.first = tkRender(host, page(1, 100), pane);
      pane.scrollTop = 500;
      const pre = host.querySelector('pre'); pre.scrollTop = 300;
      host.querySelector('[data-tk-key]').open = true;
      out.same = tkRender(host, page(1, 100), pane);
      out.sameNode = host.querySelector('pre') === pre;
      out.changed = tkRender(host, page(2, 120), pane);
      out.newNode = host.querySelector('pre') !== pre;
      out.paneTop = pane.scrollTop;
      out.preTop = host.querySelectorAll('pre')[0].scrollTop;
      out.untouchedTop = host.querySelectorAll('pre')[1].scrollTop;
      out.cmdOpen = host.querySelector('[data-tk-key]').open;
      const live = host.querySelector('pre'); live.scrollTop = live.scrollHeight;
      tkRender(host, page(3, 200), pane);
      const grown = host.querySelector('pre');
      out.follows = grown.scrollTop > 0 && grown.scrollTop + grown.clientHeight >= grown.scrollHeight - 2;
      const range = document.createRange(); range.selectNodeContents(grown);
      getSelection().removeAllRanges(); getSelection().addRange(range);
      out.selectionDefers = tkRender(host, page(4, 200), pane) === false && host.querySelector('pre') === grown;
      getSelection().removeAllRanges();
      out.afterSelection = tkRender(host, page(4, 200), pane);
      TK.pointerDown = Date.now();
      out.dragDefers = tkRender(host, page(5, 200), pane) === false;
      TK.pointerDown = 0;
      out.afterDrag = tkRender(host, page(5, 200), pane);
      out.finalPaneTop = pane.scrollTop;
      return out;
    })()`);
    assert.equal(out.first, true);
    assert.equal(out.same, false, 'an unchanged refresh must not re-render');
    assert.equal(out.sameNode, true);
    assert.equal(out.changed, true);
    assert.equal(out.newNode, true, 'the changed refresh really replaced the markup');
    assert.equal(out.paneTop, 500, 'the panel stays where the reader scrolled');
    assert.equal(out.preTop, 300, 'an open trace stays where the reader scrolled');
    assert.equal(out.untouchedTop, 0);
    assert.equal(out.cmdOpen, true, 'an expanded command line stays expanded');
    assert.equal(out.follows, true, 'a log read at its end keeps following new lines');
    assert.equal(out.selectionDefers, true, 'a refresh waits while text is selected');
    assert.equal(out.afterSelection, true);
    assert.equal(out.dragDefers, true, 'a refresh waits while the scrollbar is held');
    assert.equal(out.afterDrag, true);
    assert.equal(out.finalPaneTop, 500);
  });
});

// Actual refresh-path regressions; all API values below are isolated fixtures.
const functions = between("const TK_OWNER", "async function tvPoll()");
const setup = `
document.body.innerHTML='<style>#tk-technical{height:300px;overflow:auto}#taskpanel pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:220px;overflow:auto}#taskpanel .task-detail pre{margin:6px 0;padding:8px}#taskpanel .mc{padding:8px}</style><div id="taskpanel" class="on"><div id="tk-at"></div><div id="tk-technical"><div id="tk-local"></div><div id="tk-body"></div></div></div>';
const $=s=>document.querySelector(s),esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const TK={busy:false,expanded:new Set(['j1']),localExpanded:new Set(),hermesExpanded:new Set(),resolutionExpanded:new Set(),hermesOutput:new Map(),hermesScroll:new Map(),jobDetail:new Map(),pointerDown:0,scrolledAt:0};
const tkVisualUpdate=()=>{},tkProvidersLoad=()=>{},tkAge=()=>'',tkTokenSummary=()=>'',tkBar=()=>'',tkProgress=()=>'';
const S={apiUrl:'https://fixture.invalid',tok:'fixture'};
const lines=n=>Array.from({length:n},(_,i)=>'trace '+i).join('\\n');
const F={job:{id:'j1',state:'running',input:{},progress_log:['short progress'],log_sha:'abc'},longLog:lines(1000),hermesLog:lines(1000),pauseLog:false,resolveLog:null,data:{hermes:[],resolutions:[],machines:[{worker_id:'w',name:'Worker',totals:{cpu_pct:1},tasks:[]}],jobs:[{id:'j1',state:'running',tool:'characters',created:1}],recent:[]}};
const gbox={api:async url=>{
 if(url==='/api/tasks'||url.startsWith('/api/tasks?')){F.tasksUrl=url;return{ok:true,data:F.data};}
 if(url==='/api/jobs/j1')return{ok:true,data:F.job};
 if(url==='/api/jobs/j1/log')return F.pauseLog?await new Promise(r=>{F.resolveLog=r;}):{ok:true,data:{log:F.longLog}};
 if(url==='/api/tasks/hermes/h1')return{ok:true,data:{output:F.hermesLog}};
 if(url==='/api/receipts/r1')return{ok:true,data:{artifacts:[{sha256:'a'.repeat(64),media_type:'model/gltf-binary',name:'fixture.glb'}]}};
 throw new Error('Unexpected fixture URL '+url);
},taskSnapshot:async()=>[],token:async()=>''};
${functions}
const settle=()=>new Promise(r=>setTimeout(r,30));
await tasksLoad();await settle();
`;
test('actual tasksLoad preserves panel position while the open job log refresh is pending', async()=>{
 await withPage(async evaluate=>{
  const out=await evaluate(`(async()=>{${setup}
   const pane=$('#tk-technical'),pre=$('[data-detail-job] pre:nth-of-type(2)');
   pane.scrollTop=pane.scrollHeight;pre.scrollTop=300;
   const before=pane.scrollTop;F.pauseLog=true;F.data.machines[0].totals.cpu_pct=2;
   await tasksLoad();await settle();const pending=pane.scrollTop;
   F.resolveLog({ok:true,data:{log:F.longLog}});await settle();
   return{before,pending,after:pane.scrollTop,trace:$('#tk-body').querySelectorAll('pre')[1].scrollTop};
  })()`);
  console.log('actual-job-panel',JSON.stringify(out));
  assert.equal(out.pending,out.before,'pending log fetch must not shrink and clamp the pane');
  assert.equal(out.after,out.before,'completed log refresh must preserve panel position');
 });
});
test('selected Hermes output survives an actual nested refresh',async()=>{
 await withPage(async evaluate=>{
  const out=await evaluate(`(async()=>{${setup}
   F.data.hermes=[{id:'h1',state:'running',name:'Hermes fixture'}];TK.hermesExpanded.add('h1');
   await tasksLoad();await settle();
   const pre=$('[data-detail-hermes] pre'),range=document.createRange();range.selectNodeContents(pre);
   getSelection().removeAllRanges();getSelection().addRange(range);const original=getSelection().toString();
   F.hermesLog='new output';F.data.machines[0].totals.cpu_pct=2;
   await tasksLoad();await settle();
   return{nodeConnected:pre.isConnected,selectionSame:getSelection().toString()===original};
  })()`);
  assert.equal(out.nodeConnected,true);assert.equal(out.selectionSame,true);
 });
});
test('a selection spanning job and Hermes traces survives nested refreshes',async()=>{
 await withPage(async evaluate=>{
  const out=await evaluate(`(async()=>{${setup}
   F.data.hermes=[{id:'h1',state:'running',name:'Hermes fixture'}];TK.hermesExpanded.add('h1');
   await tasksLoad();await settle();
   const first=$('[data-detail-hermes] pre'),last=$('[data-detail-job]').querySelectorAll('pre')[1];
   const range=document.createRange();range.setStart(first.firstChild,0);range.setEnd(last.firstChild,40);
   getSelection().removeAllRanges();getSelection().addRange(range);const original=getSelection().toString();
   F.hermesLog='changed';F.job.state='succeeded';F.data.machines[0].totals.cpu_pct=2;
   await tasksLoad();await settle();
   return{firstConnected:first.isConnected,lastConnected:last.isConnected,selectionSame:getSelection().toString()===original};
  })()`);
  assert.equal(out.firstConnected,true);assert.equal(out.lastConnected,true);assert.equal(out.selectionSame,true);
 });
});
test('unchanged artifact previews retain their actual node through list and job updates',async()=>{
 await withPage(async evaluate=>{
  const out=await evaluate(`(async()=>{${setup}
   let mounts=0;window.assetView=async el=>{mounts++;el.fixtureMounted=true;};F.job.receipt_id='r1';
   await tasksLoad();await settle();const preview=$('[data-task-model]');
   F.pauseLog=true;F.data.machines[0].totals.cpu_pct=2;
   await tasksLoad();await settle();const pendingSame=$('[data-task-model]')===preview;
   F.resolveLog({ok:true,data:{log:F.longLog+'\\nnew'}});await settle();
   return{pendingSame,finalSame:$('[data-task-model]')===preview,mounts,connected:preview.isConnected};
  })()`);
  assert.equal(out.pendingSame,true);assert.equal(out.finalSame,true);assert.equal(out.connected,true);assert.equal(out.mounts,1);
 });
});
test('an older overlapping job response cannot replace the latest committed state',async()=>{
 await withPage(async evaluate=>{
  const out=await evaluate(`(async()=>{${setup}
   const originalApi=gbox.api,requests=[];
   gbox.api=url=>url==='/api/jobs/j1'?new Promise(resolve=>requests.push(resolve)):originalApi(url);
   const detail=$('[data-detail-job]'),old=tkJobRefresh(detail),latest=tkJobRefresh(detail);
   requests[1]({ok:true,data:{state:'succeeded',input:{},progress_log:['new result']}});await latest;
   requests[0]({ok:true,data:{state:'running',input:{},progress_log:['old result']}});await old;
   return{latest:detail.querySelector('.task-detail').textContent.includes('succeeded'),old:detail.querySelector('.task-detail').textContent.includes('old result')};
  })()`);
  assert.equal(out.latest,true);assert.equal(out.old,false);
 });
});
test('actual job refresh respects a text selection when outer tasksLoad defers',async()=>{
 await withPage(async evaluate=>{
  const out=await evaluate(`(async()=>{${setup}
   const pre=$('#tk-body').querySelectorAll('pre')[1],range=document.createRange();range.selectNodeContents(pre);
   getSelection().removeAllRanges();getSelection().addRange(range);
   const original=getSelection().toString();F.job.state='succeeded';F.data.machines[0].totals.cpu_pct=2;
   await tasksLoad();await settle();
   return{nodeConnected:pre.isConnected,selectionSame:getSelection().toString()===original,selectedChars:getSelection().toString().length};
  })()`);
  console.log('actual-job-selection',JSON.stringify(out));
  assert.equal(out.nodeConnected,true,'selected trace node must survive a background job refresh');
  assert.equal(out.selectionSame,true);
 });
});
test('delayed job log response preserves the reader scroll acquired after the request',async()=>{
 await withPage(async evaluate=>{
  const out=await evaluate(`(async()=>{${setup}
   const detail=$('[data-detail-job]'),pre=detail.querySelectorAll('pre')[1];pre.scrollTop=300;
   F.pauseLog=true;const pending=tkJobRefresh(detail);await settle();
   detail.querySelectorAll('pre')[1].scrollTop=600;
   F.resolveLog({ok:true,data:{log:F.longLog+'\\nnew line'}});await pending;
   return{after:detail.querySelectorAll('pre')[1].scrollTop};
  })()`);
  console.log('actual-job-scroll-during-fetch',JSON.stringify(out));
  assert.equal(out.after,600,'capture scroll at commit time, not before awaiting the log response');
 });
});

// #1300: the list asks for more than 8 Hermes runs, offers more, and names each run's tickets.
test('Hermes runs list names tickets and grows with Show more runs',async()=>{
 await withPage(async evaluate=>{
  const out=await evaluate(`(async()=>{${setup}
   const first=F.tasksUrl;
   F.data.hermes=Array.from({length:20},(_,i)=>({id:'r'+i,state:'completed',name:'gBox inbox task mode',
     tickets:i?[]:[{id:'82f7608d4e994f88',number:1300,title:'check <hermes> tasks',status:'in_progress'}]}));
   await tasksLoad();await settle();
   const rows=$('#tk-body').querySelectorAll('[data-detail-hermes]').length,ticket=$('[data-detail-hermes] .tk-ticket')?.textContent;
   const more=!!$('[data-hermes-more]');
   TK.hermesLimit=tkHermesLimit()+TK_HERMES_STEP;F.data.hermes=F.data.hermes.slice(0,25);F.data.machines[0].totals.cpu_pct=3;
   await tasksLoad();await settle();
   const grown=F.tasksUrl;F.data.hermes=F.data.hermes.slice(0,12);F.data.machines[0].totals.cpu_pct=4;
   await tasksLoad();await settle();
   TK.hermesLimit=100;F.data.hermes=Array.from({length:100},(_,i)=>({id:'q'+i,state:'completed',name:'x'}));
   await tasksLoad();await settle();
   return{first,rows,ticket,more,grown,moreAfterShort:!!$('[data-hermes-more]')&&false,atMax:!!$('[data-hermes-more]'),maxUrl:F.tasksUrl};
  })()`);
  assert.equal(out.first,'/api/tasks?hermes_limit=20');
  assert.equal(out.rows,20);
  assert.equal(out.ticket,'#1300 check <hermes> tasks');
  assert.equal(out.more,true,'a full page offers more runs');
  assert.equal(out.grown,'/api/tasks?hermes_limit=40');
  assert.equal(out.atMax,false,'no button once the 100-run cap is reached');
  assert.equal(out.maxUrl,'/api/tasks?hermes_limit=100');
 });
});
test('Show more runs button is handled by the Technical list click handler',()=>{
 const click=between('$("#tk-body").onclick = async e => {','const hermesEvidence');
 assert.match(click,/\[data-hermes-more\]/);
 assert.match(click,/TK\.hermesLimit = Math\.min\(TK_HERMES_MAX, tkHermesLimit\(\) \+ TK_HERMES_STEP\)/);
 assert.match(click,/tasksLoad\(\)/);
});
