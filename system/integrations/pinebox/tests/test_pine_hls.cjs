const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const player = require('../frontend/pine-hls.js');

function fixture(native = false) {
  const engines = [], messages = [], timers = [];
  class Hls {
    static Events = {MANIFEST_PARSED:'manifest', ERROR:'error', FRAG_BUFFERED:'buffered'};
    static ErrorTypes = {MEDIA_ERROR:'mediaError',NETWORK_ERROR:'networkError'};
    static isSupported() { return !native; }
    constructor(config) { this.config=config; this.events={}; engines.push(this); }
    on(event, fn) { this.events[event]=fn; }
    attachMedia(media) { this.media=media; }
    loadSource(source) { this.source=source; }
    recoverMediaError() { this.recovered=(this.recovered||0)+1; }
    destroy() { this.destroyed=true; }
  }
  const video = {muted:false,volume:1,plays:0, pauses:0, loads:0,readyState:4,currentTime:1,
    buffered:{length:1,start:()=>0,end:()=>12},
    play() { this.plays++; this.paused=false; return Promise.resolve(); },
    pause() { this.pauses++; this.paused=true; }, load() { this.loads++; },
    removeAttribute(k) { delete this[k]; }, canPlayType() { return native ? 'maybe' : ''; }};
  const holds=[];let holding=false;
  const hold={capture(){holds.push('capture');},show(){holding=true;holds.push('show');},hide(){holding=false;holds.push('hide');},
    reset(){holding=false;holds.push('reset');},held(){return holding;}};
  const options = {loadHls:async()=>Hls, holdFrame:hold, onStatus:s=>messages.push(s),
    setTimeout(fn,ms) { const row={fn,ms}; timers.push(row); return row; },
    clearTimeout(row) { row.cancelled=true; }};
  const p = player.create(video, options);
  return {p,video,Hls,engines,messages,timers,options,holds,hold};
}
const flush = ()=>new Promise(resolve=>setImmediate(resolve));

test('LAN media bypasses the station loop while public HTTPS stays on the isolated same-origin door',()=>{
  const page=new URL('http://10.89.1.246:8096/radio');
  assert.equal(player.mediaUrl('/api/gbox/hls?k=program&t=listener',page),
    'http://10.89.1.246:18098/api/gbox/hls?k=program&t=listener');
  assert.equal(player.mediaUrl('/gbox-hls/hls-1.7.3.min.js',page),
    'http://10.89.1.246:18098/gbox-hls/hls-1.7.3.min.js');
  assert.equal(player.mediaUrl('',page),'');
  for(const value of ['/api/dj/state','https://other.example/api/gbox/hls','/api/gbox/hls-other'])
    assert.equal(player.mediaUrl(value,page),value);
  assert.equal(player.mediaUrl('/api/gbox/hls?k=program',new URL('https://lilspark.tail1fec29.ts.net/radio')),
    '/api/gbox/hls?k=program');
});

test('compressed live main video uses a bounded buffer without periodic healthy reconnects', async()=>{
  const f=fixture();
  f.p.source('/api/gbox/hls?k=pc-spark1&t=listener'); await flush();
  assert.equal(f.engines.length,1);
  const e=f.engines[0];
  assert.equal(e.source,'/api/gbox/hls?k=pc-spark1&t=listener');
  assert.equal(e.config.initialLiveManifestSize,8);
  assert.equal(e.config.liveSyncMode,'buffered');
  assert.equal(e.config.liveSyncDurationCount,8);
  assert.equal(e.config.liveMaxLatencyDurationCount,24);
  assert.equal(e.config.maxMaxBufferLength,24);
  assert.equal(e.config.backBufferLength,10);
  e.events.manifest();
  for(let i=0;i<20;i++) f.p.source(e.source);
  assert.equal(f.engines.length,1); assert.equal(f.timers.length,0);
  assert.equal(f.video.muted,true);
});

test('startup and rebuffer wait for decoded cushion without replacing the decoder',async()=>{
  const f=fixture();let end=3;f.video.buffered.end=()=>end;
  f.p.source('/hls');await flush();const e=f.engines[0];
  e.events.manifest();f.video.oncanplay();e.events.buffered();
  assert.equal(f.video.plays,0,'a manifest and one playable fragment are not a startup cushion');
  end=8;e.events.buffered();assert.equal(f.video.plays,0);
  end=9;e.events.buffered();assert.equal(f.video.plays,1);
  f.video.onplaying();end=2;f.video.onwaiting();
  f.video.onwaiting();e.events.error(null,{details:'bufferStalledError',fatal:false});
  assert.equal(f.p.state().stalls,1,'one interrupted playback episode counts once across native and HLS events');
  f.video.onplaying();assert.equal(f.p.state().waitingForBuffer,true,'a stale playing event cannot clear a paused buffer gate');
  const paused=f.video.pauses;f.video.oncanplay();e.events.buffered();
  assert.equal(f.video.plays,1);assert.ok(paused>0);assert.equal(f.p.state().waitingForBuffer,true);
  end=9;e.events.buffered();assert.equal(f.video.plays,2);assert.equal(f.engines.length,1);
  assert.equal(f.timers.length,0);assert.equal(f.p.state().bufferAheadSeconds,8);
});

test('gameplay volume is independent and sound requires explicit listener interaction', async()=>{
  const f=fixture();
  f.p.volume(0.23); f.p.source('/hls'); await flush();
  f.engines[0].events.manifest();
  assert.equal(f.video.volume,0.23); assert.equal(f.video.muted,true);
  assert.match(f.messages.at(-1).message,/Click Enable gameplay audio/);
  f.p.enableAudio(); assert.equal(f.video.muted,false);
  f.p.volume(0); assert.equal(f.video.muted,true);
  assert.equal(f.messages.at(-1).enabled,true);
  f.p.volume(2); assert.equal(f.video.volume,1); assert.equal(f.video.muted,false);
  f.p.volume(NaN); assert.equal(f.video.volume,1);
  f.p.enableAudio(); assert.equal(f.video.muted,true);
  assert.deepEqual(Object.keys(f.video).filter(k=>/dj|sfx|context/i.test(k)),[]);
});

test('source replacement destroys old decoder and pending old loads cannot take over', async()=>{
  const f=fixture(); let resolveOld;
  f.options.loadHls=()=>new Promise(resolve=>{resolveOld=resolve;});
  const p=player.create(f.video,f.options);
  p.source('/old'); p.stop(); resolveOld(f.Hls); await flush();
  assert.equal(f.engines.length,0);
  f.p.source('/one'); await flush(); const first=f.engines[0];
  f.p.source('/two'); await flush();
  assert.equal(first.destroyed,true); assert.equal(f.engines[1].source,'/two');
  first.events.error(null,{fatal:true}); assert.equal(f.timers.length,0);
});

test('fatal failures alone schedule bounded retries; stopping cancels pending work', async()=>{
  const f=fixture(); f.p.source('/hls'); await flush();
  f.engines[0].events.error(null,{fatal:false}); assert.equal(f.timers.length,0);
  f.engines[0].events.error(null,{fatal:true});
  f.engines[0].events.error(null,{fatal:true});
  assert.equal(f.timers.length,1); assert.equal(f.timers[0].ms,1000);
  f.timers[0].fn(); await flush(); assert.equal(f.engines[0].destroyed,true);
  f.engines[1].events.error(null,{fatal:true}); assert.equal(f.timers[1].ms,2000);
  f.p.stop(); assert.equal(f.timers[1].cancelled,true);
  f.timers[1].fn(); await flush(); assert.equal(f.engines.length,2);
});

test('native HLS uses the same relay when the browser lacks MSE support',async()=>{
  const f=fixture(true); f.p.source('/native-hls');await flush();
  assert.equal(f.video.src,'/native-hls'); assert.equal(f.engines.length,0);
  assert.equal(f.video.muted,true); f.p.enableAudio(); assert.equal(f.video.muted,false);
});

test('browser autoplay rejection reports an actionable click and never pretends sound is on',async()=>{
  const f=fixture(); f.video.play=()=>Promise.reject(new Error('NotAllowedError'));
  f.p.source('/hls'); await flush(); f.p.enableAudio(); await flush();
  assert.equal(f.video.muted,true); assert.equal(f.p.state().audio,false);
  assert.match(f.messages.at(-1).message,/Click Enable gameplay audio/);
});

test('real playback clears stale reconnecting status and cancels a pending native retry',async()=>{
  const f=fixture(true);f.p.source('/hls');await flush();
  f.video.error={code:3,message:'PipelineStatus::DEMUXER_ERROR_COULD_NOT_PARSE'};
  f.video.onerror();assert.equal(f.p.state().phase,'recovering');assert.equal(f.p.state().holding,true);
  f.video.error=null;f.video.currentTime=2;f.video.ontimeupdate();
  assert.equal(f.p.state().phase,'playing');assert.equal(f.p.state().holding,false);
  assert.equal(f.timers[0].cancelled,true);
  assert.doesNotMatch(f.messages.at(-1).message,/reconnect/);
  assert.equal(f.p.state().errors[0].type,'native-media-error');
});

test('a real native HLS failure falls back to pinned MSE player and preserves the picture during reattach',async()=>{
  const f=fixture(true);f.p.source('/hls');await flush();
  f.video.error={code:3,message:'DEMUXER_ERROR_COULD_NOT_PARSE'};f.video.onerror();
  f.Hls.isSupported=()=>true;
  f.timers[0].fn();await flush();
  assert.equal(f.engines.length,1);assert.equal(f.p.state().transport,'hls.js');
  assert.equal(f.p.state().holding,true,'do not expose the cleared video while the decoder restarts');
  f.video.error=null;f.video.paused=false;f.video.onplaying();
  assert.equal(f.p.state().holding,false);assert.equal(f.p.state().phase,'playing');
  assert.equal(f.p.state().errors[0].transport,'native-hls');
});

test('MSE support wins even when Chromium also advertises native HLS',async()=>{
  const f=fixture();f.video.canPlayType=()=>'maybe';f.p.source('/hls');await flush();
  assert.equal(f.engines.length,1);assert.equal(f.p.state().transport,'hls.js');
});

test('fatal media errors attempt supported recovery before full decoder destruction',async()=>{
  const f=fixture();f.p.source('/hls');await flush();const e=f.engines[0];
  f.video.error={code:3,message:'decode error'};
  e.events.error(null,{type:'mediaError',details:'bufferAppendError',fatal:true});
  assert.equal(e.recovered,1);assert.equal(e.destroyed,undefined);assert.equal(f.timers[0].ms,5000);
  assert.equal(f.p.state().holding,true);
  f.video.error=null;f.video.paused=false;f.video.onplaying();
  assert.equal(f.timers[0].cancelled,true);assert.equal(f.p.state().phase,'playing');
  for(let i=0;i<20;i++)e.events.error(null,{type:'networkError',details:'fragLoadError',fatal:false});
  assert.equal(f.p.state().errors.length,12);
  f.p.stop();assert.equal(f.p.state().holding,false);
});

test('official vendored runtime is exact 1.7.3 with checked-in provenance',()=>{
  const vendor=path.join(__dirname,'../frontend/vendor/hls-1.7.3.min.js');
  const box={module:{exports:{}},exports:{},self:{},console};
  vm.runInNewContext(fs.readFileSync(vendor,'utf8'),box);
  assert.equal(box.module.exports.version,'1.7.3');
  assert.equal(player.VERSION,'1.7.3');
});

test('all network roads select HLS for main while only thumbnails use JPEG snapshots',()=>{
  const source=fs.readFileSync(path.join(__dirname,'../frontend/gbox-tune.js'),'utf8');
  const draw=source.slice(source.indexOf('  function draw()'),source.indexOf('  function drawLoop()'));
  assert.match(draw,/if \(m && m\.hls\)/);
  assert.doesNotMatch(draw,/onRoad\(/);
  assert.match(draw,/p\.source\(requested\)/);
  assert.match(draw,/feed\(\{frame:t\.frame\}, v\.img, v\)/);
  assert.match(source,/Gameplay volume/);
  assert.match(source,/document\.hidden\) stopAll\(\)/);
  assert.match(source,/player\.stop\(\)/);
  assert.doesNotMatch(source,/api_token|getUserMedia|AudioContext/);
});

test('browser: a decoded frame remains visible after video cleanup and never crosses source selections',async()=>{
  const {withPage}=require('../../../scripts/browser_lifecycle.cjs');
  await withPage(async evaluate=>{
    await evaluate(`document.body.innerHTML='<div style="position:relative;width:640px;height:360px"><video muted playsinline style="width:100%;height:100%"></video></div>';`);
    await evaluate(fs.readFileSync(path.join(__dirname,'../frontend/pine-hls.js'),'utf8'));
    await evaluate(`window.engines=[];window.timers=[];
      window.FakeHls=class {static Events={MANIFEST_PARSED:'manifest',ERROR:'error'};static isSupported(){return true;}
        constructor(){this.events={};engines.push(this)}on(k,f){this.events[k]=f}attachMedia(){}loadSource(){}destroy(){this.dead=true}};
      const video=document.querySelector('video');video.canPlayType=()=>'';
      window.player=PineGBoxHls.create(video,{loadHls:async()=>FakeHls,setTimeout:(fn,ms)=>{const t={fn,ms};timers.push(t);return t},clearTimeout:t=>t.cancelled=true});
      player.source('/first');`);
    await new Promise(r=>setTimeout(r,30));
    await evaluate(`window.sourceCanvas=document.createElement('canvas');sourceCanvas.width=640;sourceCanvas.height=360;
      sourceCanvas.getContext('2d').fillStyle='#ee1414';sourceCanvas.getContext('2d').fillRect(0,0,640,360);
      window.fixtureStream=sourceCanvas.captureStream(10);document.querySelector('video').srcObject=fixtureStream;document.querySelector('video').play();`);
    for(let i=0;i<100&&!await evaluate(`document.querySelector('video').readyState>=2&&player.state().phase==='playing'`);i++)await new Promise(r=>setTimeout(r,20));
    assert.equal(await evaluate(`player.state().phase`),'playing');
    await evaluate(`engines[0].events.error(null,{type:'networkError',details:'fragLoadError',fatal:true});
      fixtureStream.getTracks().forEach(t=>t.stop());document.querySelector('video').srcObject=null;timers[0].fn();`);
    await new Promise(r=>setTimeout(r,30));
    const held=await evaluate(`(()=>{const c=document.querySelector('.gbox-hold');return {held:player.state().holding,hidden:c.hidden,ready:document.querySelector('video').readyState,pixel:[...c.getContext('2d').getImageData(20,20,1,1).data]}})()`);
    assert.equal(held.held,true);assert.equal(held.hidden,false);assert.equal(held.ready,0);
    assert.ok(held.pixel[0]>180&&held.pixel[1]<50&&held.pixel[2]<50,JSON.stringify(held));
    await evaluate(`player.source('/second')`);
    assert.equal(await evaluate(`document.querySelector('.gbox-hold').hidden`),true,'old source picture cannot leak onto another selected feed');
    await evaluate(`player.stop()`);
  },{timeoutMs:30000});
});

test('browser: station metadata changes and failed polls retain a healthy decoder; explicit off stops it',async()=>{
  const {withPage}=require('../../../scripts/browser_lifecycle.cjs');
  await withPage(async evaluate=>{
    await evaluate(`window.pendingTimers=[];window.realNow=Date.now;window.offset=0;
      Date.now=()=>realNow()+offset;
      window.setTimeout=(fn,ms)=>{const row={fn,ms};pendingTimers.push(row);return row};
      window.clearTimeout=row=>{if(row)row.cancelled=true};
      window.calls={sources:[],stops:0};
      window.PineGBoxHls={create:()=>({volume(){},source(url){calls.sources.push(url)},
        stop(){calls.stops++},state(){return{phase:'playing'}}})};
      window.api=async()=>{throw Error('temporary metadata outage')};`);
    await evaluate(fs.readFileSync(path.join(__dirname,'../frontend/gbox-tune.js'),'utf8'));
    await evaluate(`window.tile={key:'program',device:'spark1',title:'RE5',hls:'/hls?k=program',frame:'/frame?revision=1'};
      GBoxTune.news({show:true,state:'live',tiles:[tile]});Promise.resolve();`);
    assert.deepEqual(await evaluate(`calls.sources`),['/hls?k=program']);
    await evaluate(`GBoxTune.news({show:true,state:'live',tiles:[{...tile,title:'next round',frame:'/frame?revision=2'}]});Promise.resolve();`);
    assert.equal(await evaluate(`calls.stops`),0,'thumbnail metadata must not reset gameplay');
    assert.deepEqual(await evaluate(`calls.sources`),['/hls?k=program']);
    await evaluate(`offset=13000;pendingTimers.find(t=>t.ms===15000).fn();(async()=>{for(let i=0;i<5;i++)await Promise.resolve()})()`);
    const state=await evaluate(`GBoxTune.state()`);
    assert.equal(state.on,true);assert.equal(state.metadataDelayed,true);
    assert.equal(await evaluate(`calls.stops`),0,'failed metadata poll must not stop a working feed');
    await evaluate(`GBoxTune.news({show:false,state:'off',tiles:[]})`);
    assert.equal(await evaluate(`GBoxTune.state().on`),false);
    assert.equal(await evaluate(`calls.stops`),1,'the station still owns its explicit off switch');
  },{timeoutMs:30000});
});
