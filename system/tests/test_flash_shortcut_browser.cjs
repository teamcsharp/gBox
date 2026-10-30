'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {withPage}=require('../scripts/browser_lifecycle.cjs');

test('flash taps, F, remapping and quick commands act without action popups or game-key leakage',async()=>{
  const files=['stream-interventions.js','autoplay-coach.js'];
  const server=http.createServer((req,res)=>{
    if(files.some(f=>req.url==='/'+f)){
      res.setHeader('Content-Type','application/javascript');res.end(fs.readFileSync(path.join(__dirname,'../clients/web/viz',req.url.slice(1))));return;
    }
    res.end(`<body><img id="stream" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="><div id="actions"></div><div id="coach"></div><textarea id="text"></textarea>${files.map(f=>`<script src="/${f}"></script>`).join('')}</body>`);
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  try{await withPage(async(evaluate,send)=>{
    await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}`});
    await evaluate(`new Promise(r=>{const wait=()=>window.GBoxAutoplayCoach?r():setTimeout(wait,10);wait();})`);
    await evaluate(`window.posts=[];window.notes=[];window.keys=[];window.fail=false;window.delayed=true;window.releases=[];window.current='re6';
      window.alert=window.confirm=window.prompt=()=>{throw Error('No action dialog allowed')};
      document.addEventListener('keydown',e=>keys.push(e.code));document.addEventListener('keyup',e=>keys.push(e.code+'Up'));
      window.api=async(p,b)=>{
        if(p.endsWith('/directive')){posts.push({p,b});return {directive:{label:b.command}};}
        if(b){posts.push({p,b});if(fail)throw Error('native temporarily unavailable');if(delayed)await new Promise(r=>releases.push(r));return {request:{id:b.request_id,state:'queued'}};}
        return {requests:posts.filter(x=>x.b.op).map(x=>({id:x.b.request_id,op:x.b.op,state:'confirmed'}))};
      };
      window.install=()=>{window.mount=GBoxStreamInterventions.mount(document.querySelector('#actions'),{sid:()=>current,api,notify:t=>notes.push(t)});
        window.flash=document.querySelector('#actions button');flash.setAttribute('data-flash','');};install();
      window.press=(key,code,opts={})=>{const target=document.activeElement;target.dispatchEvent(new KeyboardEvent('keydown',{key,code,bubbles:true,cancelable:true,...opts}));target.dispatchEvent(new KeyboardEvent('keyup',{key,code,bubbles:true,cancelable:true,...opts}));};
      window.menu=()=>flash.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true}));
      for(let i=0;i<20;i++)flash.click();`);
    const desktop=fs.readFileSync(path.join(__dirname,'../clients/desktop/index.html'),'utf8');
    const contextHandler=desktop.match(/document\.addEventListener\('contextmenu', event => \{[\s\S]*?\}, true\);/)[0];
    await evaluate(`window.COMPACT={on:true};window.pipMenu=()=>{throw Error('PiP menu intercepted flash shortcut menu')};${contextHandler}`);
    assert.equal(await evaluate('posts.length'),20,'all clicks post while previous requests are unresolved');
    assert.equal(await evaluate('new Set(posts.map(x=>x.b.request_id)).size'),20);
    await evaluate(`delayed=false;releases.forEach(r=>r());new Promise(r=>setTimeout(r,10))`);
    await evaluate(`mount.client.poll()`);
    assert.deepEqual(await evaluate('notes'),[]);
    assert.equal(await evaluate(`document.querySelector('#actions [role=status]').textContent`),'');
    await evaluate(`flash.focus();press('f','KeyF');press('f','KeyF',{repeat:true});`);
    assert.equal(await evaluate('posts.length'),21);
    assert.deepEqual(await evaluate('keys'),[],'shortcut down/up do not reach controller listeners');
    await evaluate(`document.querySelector('#text').focus();press('f','KeyF');`);
    assert.equal(await evaluate('posts.length'),21,'typing F is untouched');
    await evaluate(`flash.focus();press('f','KeyF',{ctrlKey:true});menu();document.querySelector('.flash-shortcut-menu button').click();press('g','KeyG');`);
    assert.equal(await evaluate('posts.length'),21,'capturing a binding never detonates');
    assert.equal(await evaluate(`flash.getAttribute('aria-keyshortcuts')`),'G');
    await evaluate(`flash.focus();press('f','KeyF');press('g','KeyG');`);
    assert.equal(await evaluate('posts.length'),22);
    await evaluate(`mount.dispose();install();flash.focus();press('g','KeyG');`);
    assert.equal(await evaluate('posts.length'),23,'binding survives mount/reload');
    await evaluate(`menu();document.querySelectorAll('.flash-shortcut-menu button')[1].click();flash.focus();press('g','KeyG');press('f','KeyF');flash.click();`);
    assert.equal(await evaluate('posts.length'),24,'unmapped button remains clickable');
    assert.equal(await evaluate(`flash.hasAttribute('aria-keyshortcuts')`),false);
    await evaluate(`menu();document.querySelectorAll('.flash-shortcut-menu button')[2].click();fail=true;flash.focus();press('f','KeyF');new Promise(r=>setTimeout(r,10))`);
    assert.match(await evaluate('flash.title'),/native temporarily unavailable/);
    assert.equal(await evaluate('flash.dataset.flashState'),'unavailable');
    assert.deepEqual(await evaluate('notes'),[],'errors stay on button, no popup');
    await evaluate(`fail=false;current='re5';press('f','KeyF');`);
    assert.equal(await evaluate('posts.at(-1).p'),'/api/sessions/re5/interventions','shortcut follows current title');
    await evaluate(`document.querySelector('#coach').innerHTML=GBoxAutoplayCoach.html('re5');window.coach=GBoxAutoplayCoach.mount(document.querySelector('#coach'),{sid:'re5',api});
      for(const id of ['fight','next_area','explore','hunt','score','repetitive','mine','mine_trail','missing']){
        document.querySelector('[data-coach-cmds]').click();document.querySelector('[data-cmd="'+id+'"]').click();
      }`);
    assert.deepEqual(await evaluate(`posts.filter(x=>x.p.endsWith('/directive')).map(x=>x.b.command)`),
      ['fight','next_area','explore','hunt','score','repetitive','mine','mine_trail','missing']);
    assert.equal(await evaluate(`document.querySelectorAll('.coach-menu,.coach-sub,.flash-shortcut-menu,[role=dialog]').length`),0);
    await evaluate(`mount.dispose();coach.dispose();flash.focus();press('f','KeyF')`);
    assert.equal(await evaluate('posts.filter(x=>x.b.op).length'),26,'disposed shortcut cannot post');
  },{timeoutMs:30000});}finally{server.closeAllConnections();await new Promise(r=>server.close(r));}
});
