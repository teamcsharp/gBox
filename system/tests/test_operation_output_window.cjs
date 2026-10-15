const {test}=require('node:test'),assert=require('node:assert/strict');
const make=require('../clients/desktop/operation-output-window.cjs');
test('native output is one click-through child surface, follows zoom/holes, hides and is disposed after fading',async()=>{
  const windows=[],events={};let minimized=false;
  class Window {
    constructor(opts){this.opts=opts;this.events={};windows.push(this);this.webContents={executeJavaScript:async code=>this.code=code};}
    isDestroyed(){return !!this.dead;}destroy(){this.dead=true;this.events.closed?.();}on(e,fn){this.events[e]=fn;}
    loadFile(file){this.file=file;return Promise.resolve();}setIgnoreMouseEvents(x){this.ignored=x;}
    setBounds(x){this.bounds=x;}setShape(x){this.shape=x;}hide(){this.visible=false;}showInactive(){this.visible=true;}
  }
  const win={isDestroyed:()=>false,isMinimized:()=>minimized,isVisible:()=>true,getContentBounds:()=>({x:100,y:200}),
    webContents:{getZoomFactor:()=>1.5},on:(e,fn)=>events[e]=fn};
  const output=make({BrowserWindow:Window,getWin:()=>win});
  const frame={sid:'s',rows:[{label:'Native give',state:'running',lines:['Reported progress'],opacity:1}]};
  const state={frame,rect:{x:20,y:40,w:400,h:300},holes:[{x:0,y:0,w:40,h:20}],visible:true};
  output.update(state);await new Promise(r=>setImmediate(r));
  const w=windows[0];assert.equal(w.opts.transparent,true);assert.equal(w.opts.focusable,false);assert.equal(w.ignored,true);
  assert.deepEqual(w.bounds,{x:130,y:260,width:600,height:450});assert.equal(w.visible,true);
  assert.equal(w.shape.some(r=>r.x===0&&r.y===0),false,'native menu remains uncovered');
  assert.match(w.code,/Reported progress/);assert.equal(w.opts.webPreferences.sandbox,true);
  output.update(state);assert.equal(windows.length,1);minimized=true;events.minimize();assert.equal(w.visible,false);
  minimized=false;events.restore();assert.equal(w.visible,true);
  output.update({frame:{sid:'s',rows:[]}});assert.equal(w.dead,true);
});
