/* One transparent, never-focused text surface above the native or GPU game picture. */
const path=require('node:path');
const {shapeMinusHoles}=require('./embed-geometry');
module.exports=function({BrowserWindow,getWin}) {
  let overlay=null,state=null,ready=false,hooked=null;
  function close(){const old=overlay;overlay=null;ready=false;if(old&&!old.isDestroyed())old.destroy();}
  function draw(){
    const win=getWin();
    if(!overlay||overlay.isDestroyed()||!win||!state)return;
    if(!state.visible||!state.rect||win.isMinimized()||!win.isVisible()){overlay.hide();return;}
    const z=win.webContents.getZoomFactor()||1,b=win.getContentBounds(),r=state.rect;
    const w=Math.max(1,Math.round(r.w*z)),h=Math.max(1,Math.round(r.h*z));
    overlay.setBounds({x:Math.round(b.x+r.x*z),y:Math.round(b.y+r.y*z),width:w,height:h});
    try{overlay.setShape(shapeMinusHoles(w,h,state.holes||[],z));}catch{}
    if(ready){overlay.webContents.executeJavaScript(`window.operationFrame(${JSON.stringify(state.frame)})`).catch(()=>{});overlay.showInactive();}
  }
  function update(next){
    state=next;
    if(!next?.frame?.rows?.length){close();return;}
    const win=getWin();if(!win||win.isDestroyed())return;
    if(!overlay||overlay.isDestroyed()){
      ready=false;
      const current=overlay=new BrowserWindow({parent:win,frame:false,transparent:true,show:false,focusable:false,skipTaskbar:true,
        resizable:false,movable:false,hasShadow:false,webPreferences:{contextIsolation:true,sandbox:true,backgroundThrottling:false}});
      current.setIgnoreMouseEvents(true);
      current.on('closed',()=>{if(overlay===current){overlay=null;ready=false;}});
      current.loadFile(path.join(__dirname,'operation-output.html')).then(()=>{if(overlay===current){ready=true;draw();}}).catch(()=>{if(overlay===current)close();});
      if(hooked!==win){hooked=win;for(const ev of ['move','resize','restore','show'])win.on(ev,draw);
        for(const ev of ['hide','minimize'])win.on(ev,()=>overlay&&!overlay.isDestroyed()&&overlay.hide());
        win.on('closed',close);}
    }
    draw();
  }
  return {update,close};
};
