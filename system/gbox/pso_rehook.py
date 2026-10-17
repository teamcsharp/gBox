"""Reconnect PSO controls to the same live emulator; never restart or reload its game."""
import struct


def reconnect_memory(ad,game,steps):
    from .adapters import DolphinWinAdapter,DolphinAdapter
    from .debug import DolphinProcMem,GdbDebugger,Unavailable
    from .pso_mods_tool import SIGNATURE
    proc=getattr(ad,'proc',None)
    if proc is not None and proc.poll() is not None:raise RuntimeError('The emulator has exited; select a running PSO session')
    address,length=(0x80000000,8) if game.get('platform')=='gamecube' else (SIGNATURE[0],len(SIGNATURE[1]))
    expected=b'GPOE8P\0\x02' if game.get('platform')=='gamecube' else SIGNATURE[1]
    def probe(data):
        if data!=expected:raise RuntimeError('The running ROM does not match a verified PSO revision, or is still booting')
    old=getattr(ad,'dbg',None)
    if isinstance(ad,DolphinWinAdapter):
        # A fresh process handle discards stale MEM1 mapping caches. Never reattach
        # Windows GDB: Dolphin cannot reliably accept it after the boot detach.
        if proc is None:raise RuntimeError('The Dolphin process is unavailable')
        new=DolphinProcMem(proc.pid)
        try:probe(new.read(address,length))
        except Exception:
            new.close();raise
        ad.dbg=new
        if old is not None:
            try:old.close()
            except Exception:pass
        steps.append({'stage':'memory','state':'ok','message':f'Reconnected Dolphin memory to the same process ({proc.pid}).'})
    else:
        if isinstance(ad,DolphinAdapter) and old is not None:
            if getattr(old,'running',True) is False:
                raise RuntimeError('The game is paused. Resume gameplay before reconnecting its debugger')
            try:halted=old.info().get('halted')
            except (OSError,Unavailable):
                if getattr(old,'running',None) is not True:raise
                halted=False
            if halted:raise RuntimeError('The game is paused. Resume gameplay before reconnecting its debugger')
        try:data=ad.read_memory(address,length)
        except Exception:
            if not isinstance(ad,DolphinAdapter):raise
            # Linux uses the already-configured localhost stub, with a short
            # reconnect budget rather than the sixty-second boot attach loop.
            if old is not None:old.close()
            ad.dbg=None
            new=GdbDebugger('127.0.0.1',ad.port,'ppc',connect_timeout=.5)
            try:data=new.read(address,length);probe(data)
            except Exception:
                new.close();raise
            ad.dbg=new
        probe(data)
        steps.append({'stage':'memory','state':'ok','message':'Verified the current emulator memory connection.'})


def recover(sid,ad,game,ctx):
    from . import pso_controls as controls
    from .pso_live import deadline
    steps=[];cap=None
    def result(ready,message):
        return {'supported':bool(cap and cap.get('supported')),'ready':ready,'verified':ready,
                'capabilities':cap,'steps':steps,'message':message,'session_id':sid}
    try:
        reconnect_memory(ad,game,steps)
        cap=controls.capabilities(game,ad.read_memory)
        if not cap['supported']:
            steps.append({'stage':'revision','state':'blocked','message':cap['reason']})
            return result(False,cap['reason'])
        steps.append({'stage':'revision','state':'ok','message':'Verified the executable and initialized offline player.'})
        if getattr(ad,'paused_tids',None) or (getattr(ad,'dbg',None) and ad.dbg.info().get('halted')):
            raise RuntimeError('The game is paused. Resume gameplay, then click Reconnect PSO controls again')
        if game.get('platform')=='gamecube':
            from .pso_gc_live import GC,QUEUE,QMAX,QSZ,VT_UPDATE,CAVE,CODE
            native=GC(ad)
            if any(native.u32(QUEUE+i*QSZ) for i in range(QMAX)):
                raise RuntimeError('A previous native command is still pending. Resume gameplay and let it finish; it was not cleared or replayed')
            def verified():return native.u32(VT_UPDATE)==CAVE and native.read(CAVE,len(CODE))==CODE
        else:
            from .pso_mods_tool import PSO,QUEUE,VT_UPDATE,CAVE,stub_code
            native=PSO(ad.read_memory,ad.write_memory)
            if native.u32(QUEUE):raise RuntimeError('A previous native command is still pending. Resume gameplay and let it finish; it was not cleared or replayed')
            def verified():return native.u32(VT_UPDATE)==CAVE and native.read(CAVE,len(stub_code()))==stub_code()
        prefs=controls.preferences(ctx)
        ad._pso_preferences_dirty=False
        deadline(ctx);native.hook()
        steps.append({'stage':'hook','state':'ok','message':'Installed or verified the native game-thread dispatcher.'})
        deadline(ctx)
        applied=controls.apply_defaults(sid,ad,game,ctx,prefs)
        if not applied or applied.get('state')!='applied':raise RuntimeError((applied or {}).get('reason') or 'Saved PSO defaults could not be verified')
        if not verified():raise RuntimeError('The native dispatcher did not pass read-back verification')
        steps.append({'stage':'defaults','state':'ok','message':'Refreshed saved mod defaults and verified the installed hook.'})
        return result(True,'PSO controls reconnected. Item and character sheets are ready.')
    except Exception as error:
        steps.append({'stage':'recovery','state':'blocked','message':str(error)[:500]})
        return result(False,str(error)[:500])
