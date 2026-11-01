"""Merge a remote connection's pad lease with the local adapter's input.

The lease never releases a key held by another caller. Analog directions share
an axis: local input takes priority and its release cannot centre a remote axis
unless that remote lease actually ends. Unknown remote event shapes fail closed.
"""
from __future__ import annotations

import threading
from functools import wraps

MARKER='_gbox_desktop_input_lease'


class InputLease:
    def __init__(self,send,secret,*,normalize=lambda player,key:(player,key),axis=lambda identity:None):
        self.send,self.secret,self.normalize,self.axis=send,secret,normalize,axis
        self.__wrapped__=send  # expose the existing polite keyword through inspect.signature
        self.local={};self.remote={};self.lock=threading.RLock()

    def identity(self,event):
        player=event.get('player',1)
        if type(player) is not int or player not in (1,2,3,4):return None
        key=event.get('key')
        return self.normalize(player,key) if isinstance(key,str) and key else None

    def _effective(self,identity):
        group=self.axis(identity)
        if group:
            local=[key for key in self.local if self.axis(key)==group]
            return identity in (self.local if local else self.remote)
        return identity in self.local or identity in self.remote

    def __call__(self,events,*args,**kwargs):
        with self.lock:
            output=[]
            for incoming in events:
                if not isinstance(incoming,dict):continue
                remote=incoming.get(MARKER)==self.secret
                event={key:value for key,value in incoming.items() if key!=MARKER}
                identity=self.identity(event)
                if identity is None:
                    if not remote:output.append(event)
                    continue
                before={key:self._effective(key) for key in set(self.local)|set(self.remote)|{identity}}
                held=self.remote if remote else self.local
                if event.get('down',True):held[identity]=event
                else:held.pop(identity,None)
                after={key:self._effective(key) for key in set(before)|set(self.local)|set(self.remote)}
                # Centre a displaced analog direction before asserting the new
                # owner. Reassert its remaining direction after any key-up.
                group=self.axis(identity)
                for key,was in before.items():
                    if key!=identity and was and not after.get(key):
                        template=self.local.get(key) or self.remote.get(key)
                        if template:output.append({**template,'down':False})
                effective=after.get(identity,False)
                output.append({**event,'down':effective})
                if group:
                    for key,active in after.items():
                        if key!=identity and active and self.axis(key)==group:
                            template=self.local.get(key) or self.remote.get(key)
                            output.append({**template,'down':True})
            return self.send(output,*args,**kwargs)

    def release(self):
        with self.lock:
            events=[{**event,'down':False,MARKER:self.secret} for event in self.remote.values()]
            return self(events) if events else None

    def expired(self,event):
        """An expired remote event can only clear this lease's existing hold."""
        with self.lock:
            identity=self.identity(event)
            owned=self.remote.get(identity)
            return self([{**owned,'down':False,MARKER:self.secret}]) if owned else None


def attach(adapter,secret,*,initial_local=()):
    """Wrap only the actual local worker's adapter; no native process adoption."""
    existing=getattr(adapter,'_desktop_input_lease',None)
    if existing:
        if existing.secret!=secret:raise RuntimeError('Adapter already has another remote input owner')
        return existing
    from . import adapters as A
    name=str(getattr(adapter,'name','')).lower()
    rpcs3='rpcs3' in name
    def normalize(player,key):
        if rpcs3:
            key=A.RPCS3_PAD_ALIASES.get(key,key)
            return player,A.RPCS3_KEYPAD.get(key,key)
        if key in A.STICK:return player,('axis',)+A.STICK[key]
        if getattr(adapter,'remote_port',None) and player==1 and key in A.RETROPAD_ID:
            return player,('pad',A.RETROPAD_ID[key])
        dolphin={'z':'e','cup':'k','cdown':'i','cleft':'j','cright':'l',
                 'dup':'t','ddown':'g','dleft':'f','dright':'h'} if 'dolphin' in name else {}
        key=dolphin.get(key,key)
        return player,A.PAD_KEYS.get(player,A.PAD_KEYS[1]).get(key,key)
    def axis(identity):
        player,key=identity
        return (player,key[:3]) if isinstance(key,tuple) and key[0]=='axis' else None
    lease=InputLease(adapter.send_input,secret,normalize=normalize,axis=axis)
    for event in initial_local:
        identity=lease.identity(event)
        if identity is not None:lease.local[identity]=event
    adapter.send_input=lease
    # Scoped P2 adapters have a distinct entry point. Share the same ledger,
    # retaining the actual player number and original per-port method.
    scoped=getattr(adapter,'send_input_player',None)
    if callable(scoped):
        @wraps(scoped)
        def send_player(events,player=2,*args,**kwargs):
            with lease.lock:
                original=lease.send
                emitted=None
                def forward(rows,*a,**k):
                    nonlocal emitted
                    emitted=len(rows)
                    if 'dolphin' in name and player==1:
                        # The scoped P1 method delegates to this lease now. Use
                        # the captured emitter after the normal P1 transform.
                        from .pso_coop_setup import input_rows
                        return original(input_rows(rows,1),*a,**k)
                    return scoped(rows,player,*a,**k)
                lease.send=forward
                try:
                    rows=[{**row,'player':player} for row in events]
                    result=lease(rows,*args,**kwargs)
                    # Axis ownership can expand one request into multiple key
                    # events. Confirm the logical count only after all emitted
                    # events were acknowledged; retain the physical sent count.
                    if ('dolphin' in name and isinstance(result,dict)
                            and type(result.get('sent')) is int and result['sent']==emitted):
                        result={**result,'logical_sent':len(rows)}
                    return result
                finally:lease.send=original
        adapter.send_input_player=send_player
    adapter._desktop_input_lease=lease
    return lease
