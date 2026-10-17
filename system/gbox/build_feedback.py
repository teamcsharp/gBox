"""Durable operator feedback: reports and image references outlive deleted ROM payloads."""
import time
import re
from fastapi import HTTPException, Depends
KIND='build_feedback'

def record(store, report, gid, name, note='', reason='other', meta=None):
    with store.lock:
        return _record(store,report,gid,name,note,reason,meta)

def _record(store, report, gid, name, note='', reason='other', meta=None):
    rid=report['id'];request=store.get('request',rid) or report
    attachments=[]
    for message in request.get('messages',[]):
        for a in message.get('attachments',[]):
            if a.get('sha256') and not any(x['sha256']==a['sha256'] for x in attachments):
                attachments.append({k:a[k] for k in ('sha256','name','type','size') if k in a} | {'url':f"/api/artifacts/{a['sha256']}"})
    if request.get('image') and not any(a['sha256']==request['image'] for a in attachments):
        attachments.insert(0,{'sha256':request['image'],'name':'report-screenshot.png','type':'image/png','url':f"/api/artifacts/{request['image']}"})
    previous=store.get(KIND,rid) or {}
    row=previous | {'id':rid,'request_id':rid,'number':request.get('number'),'game_id':gid,'build':f'{gid}/{name}',
        'name':name,'request_url':f'/api/requests/{rid}','note':str(note)[:4000],'reason':reason,'attachments':attachments[:20],
        'updated':time.time(),'revision':int(previous.get('revision',0))+1}
    if previous.get('note') and previous['note'] != row['note']:
        row['previous_notes']=(previous.get('previous_notes',[])+[{'revision':previous.get('revision',1),'note':previous['note']}])[-20:]
    if meta:
        row['writer']=str(meta.get('writer') or '')
        row['recipe']=meta.get('recipe')
        slots=meta.get('slots') or meta.get('cast') or []
        row['slots']=slots[:100] if isinstance(slots,list) else []
    store.put(KIND,rid,row)
    return row

def rows(store,gid):
    return sorted((r for r in store.all(KIND) if r.get('game_id')==gid),key=lambda r:-(r.get('updated') or 0))

def check(store,req):
    tool=req.get('tool') if isinstance(req,dict) else req.tool
    if tool!='characters':return
    inp=(req.get('input') if isinstance(req,dict) else req.input) or {}
    if inp.get('op') not in ('use','live_use','match','cast_swap') or inp.get('plan_only'):return
    gid=inp.get('target_game') or inp.get('game_id')
    if not gid and inp.get('session_id'):gid=(store.get('session',inp['session_id']) or {}).get('game_id')
    all_feedback=store.all(KIND)
    if not all_feedback:return
    if not gid:gid=inp.get('game')
    if gid and not any(r.get('game_id')==gid for r in all_feedback) and not re.fullmatch(r'[0-9a-f]{16}',str(gid)) and not store.catalog_get(gid):
        _total,hits=store.search(str(gid),limit=10)
        exact=[h for h in hits if (h.get('title') or '').casefold()==str(gid).casefold()]
        if len(exact)==1:gid=exact[0]['game_id']
        else:raise HTTPException(409,{'code':'build_feedback_game_id_required','message':'Resolve the target game to game_id before building so its operator feedback can be checked.'})
    if not gid:
        raise HTTPException(409,{'code':'build_feedback_game_id_required','message':'Choose the target game_id before building so its operator feedback can be checked.'})
    feedback=rows(store,gid)
    if not feedback:return
    ack=inp.get('feedback_ack') or {}
    if not isinstance(ack,dict):ack={}
    pending=[r for r in feedback if ack.get(r['id'])!=r.get('revision',1)]
    if pending:
        raise HTTPException(409,{'code':'build_feedback_review_required','game_id':gid,
            'message':'Review the operator reports and images before building. Address their defects; acknowledge the exact revisions with feedback_ack {report_id: revision}. Acknowledgement is not proof of a fix.',
            'feedback':pending,'feedback_url':f'/api/build-feedback?game_id={gid}'})

def routes(app,store,auth):
    @app.get('/api/build-feedback')
    def get_feedback(game_id:str,actor=Depends(auth)):
        return {'game_id':game_id,'items':rows(store,game_id),'replacement_preference':'whole_cast',
            'required_contexts':['gameplay','in_engine_cutscenes','prerecorded_cinematics']}
    # Import existing report history once; keep artifact hashes, never the ROM payload or image base64.
    for request in store.all('request'):
        c=request.get('context') or {};build=c.get('build') or ''
        if c.get('build_report') and isinstance(build,str) and '/' in build and not store.get(KIND,request['id']):
            gid,name=build.split('/',1)
            text='\n'.join(m.get('text','') for m in request.get('messages',[]) if m.get('author')=='operator') or request.get('body','')
            record(store,request,gid,name,text,c.get('reason') or 'other')
