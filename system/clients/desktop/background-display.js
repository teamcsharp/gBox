/* Idle operations can be scrolled for inspection. Clicks and keys return to the
   app without consuming input; native games and operator sessions retain control. */
(function(root){
  let frame=null,timer=null,disposed=false,lastInput=Date.now(),busy=false,inspecting=false;
  function hide(){inspecting=false;if(frame){frame.remove();frame=null;}}
  function wake(){lastInput=Date.now();hide();}
  function scroll(){if(frame)inspecting=true;}
  for(const name of ['pointerdown','keydown'])addEventListener(name,wake,{capture:true,passive:true});
  addEventListener('wheel',scroll,{capture:true,passive:true});
  addEventListener('message',event=>{
    if(!frame||event.source!==frame.contentWindow)return;
    if(event.data?.gboxBackgroundScroll)scroll();
    else if(event.data?.gboxBackgroundClosed||event.data?.gboxBackgroundInput)wake();
  });
  async function poll(){
    if(disposed||busy)return;
    busy=true;
    try{
      const settings=await gbox.settings();
      const result=await gbox.api('/api/background/workers/'+encodeURIComponent(settings.workerName)+'/status');
      if(!result.ok)throw Error(result.error||'Worker status unavailable');
      const state=result.data;
      const operator=state.sessions.some(s=>!s.agent_owned);
      const idle=state.worker.os!=='windows'||state.worker.idle_seconds>=300;
      // Scrolling resets Windows' idle timer too. Keep the inspected panel until a click/key dismisses it.
      if(disposed||document.hidden||Date.now()-lastInput<300000||!idle&&!inspecting||!state.online||!state.background_testing||operator){hide();return;}
      const game=state.sessions.find(s=>s.agent_owned && s.local_window &&
        !['no_window','covered','stopped'].includes(s.gameplay_state) && !s.presentation?.persistent);
      if(game && !inspecting && root.GBoxBackgroundGameplay){
        hide();
        if(await root.GBoxBackgroundGameplay(game,()=>!disposed && Date.now()-lastInput>=300000))return;
      }
      if(!frame){
        const token=await gbox.token();
        if(disposed||Date.now()-lastInput<300000)return;
        const url=new URL('/viz/background-operations.html',settings.apiUrl);
        url.hash=new URLSearchParams({worker:settings.workerName,token}).toString();
        frame=document.createElement('iframe');frame.title='Live background operations';frame.src=url.href;
        frame.style.cssText='position:fixed;left:0;right:0;top:80px;bottom:30px;width:100%;height:calc(100% - 110px);border:0;z-index:59;background:#070b18';
        document.body.append(frame);
      }
    }catch{/* The child panel marks stale data and retries. Keep it visible on a transient API failure. */}
    finally{busy=false;if(!disposed)timer=setTimeout(poll,10000);}
  }
  addEventListener('pagehide',()=>{disposed=true;clearTimeout(timer);hide();});
  root.GBoxBackgroundDisplay={poll,hide};
  timer=setTimeout(poll,10000);
})(globalThis);
