"""Game-pinned, durable build requests; a queued request is never presented as a finished build."""
import hashlib
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

KIND = 'game_build_request'


class BuildRequestIn(BaseModel):
    client_id: uuid.UUID
    session_id: str = Field(default='', max_length=128)
    kind: Literal['build', 'modification'] = 'build'
    description: str = Field(min_length=3, max_length=12000)
    recipe: Literal['agent','sonic2_player','photo_face'] = 'agent'
    photo: str = Field(default='',pattern='^(?:[a-f0-9]{64})?$')
    mapping: dict = Field(default_factory=dict)
    projection_scope:Literal['gameplay','boot','both']='gameplay'


def instructions(game, description, rid):
    return (f'Create the requested custom build of {game.get("title")}: {description}\n'
        f'Target game_id={game["game_id"]}; request_id={rid}. Keep the exact requested donor title and character. '
        'Read this request and prior build feedback before building. Use owned extracted assets and the native writer. '
        'If a reader/writer is missing, implement and test it rather than substituting an overlay or unrelated donor. '
        'Preserve the base game, operator session and personal saves. Build without automatically launching or swapping '
        'the operator game. Verify the exact output in a separate test session and retain actual screenshots and errors. '
        'Record the request number in the completed build marker. Publish the completed build with '
        f'POST /api/games/{game["game_id"]}/build-requests/{rid}/result, body {{"name":"<mod folder>"}}. '
        'Only a real completed launchable build may be published. Keep the request in progress if the build fails. '
        'The result must be available through the normal Builds play/download controls. Respect unlock-all and feedback policies.')


def routes(app, store, config, auth, create_request, investigate, submit):
    lock = threading.RLock()

    def game(gid):
        g = store.catalog_get(gid)
        if not g: raise HTTPException(404, 'Game is not in the owned catalog')
        return g

    def record(gid, rid):
        row = store.get(KIND, rid)
        if not row or row['game_id'] != gid: raise HTTPException(404, 'Build request not found for this game')
        return row

    def build(gid, name):
        from .filemods import mod_dir
        try:
            folder = mod_dir(config, gid, name)
            meta = json.loads((folder/'.gbox-mod.json').read_text())
            image = meta.get('image')
            path = (folder/image).resolve() if isinstance(image, str) else None
            if meta.get('game_id') != gid or meta.get('launchable') is False:
                raise ValueError('Wrong game or non-launchable files')
            if image:
                if not path or not path.is_relative_to(folder.resolve()) or not path.is_file():
                    raise ValueError('No completed image')
            elif not meta.get('files'):
                raise ValueError('No completed folder-game file manifest')
        except (ValueError, OSError, TypeError):
            raise HTTPException(409, 'A completed launchable build with its original marker is required')
        return {'name':name, 'title':meta.get('title') or meta.get('name') or name,
                'verified':bool(meta.get('verified_in_game') or meta.get('verified')),
                'download_url':f'/api/modfiles/{quote(gid,safe="")}/{quote(name,safe="")}/file/{quote(image,safe="/")}' if image else None}

    def view(row):
        report = store.get('request', row['request_id']) or {}
        result = dict(row, status=report.get('status','open'))
        result['jobs'] = [{'id':j['id'],'state':j['state'],'tool':j.get('tool'),'progress':j.get('progress'),
                           'error':j.get('error'),'admission_wait':j.get('admission_wait')} for j in store.all('job') if j.get('parent_request_id')==row['request_id']][-12:]
        # A completed recipe job can publish its exact output without an agent claiming success.
        for j in store.all('job'):
            if j.get('parent_request_id') != row['request_id'] or j.get('state') != 'succeeded': continue
            out = (j.get('output') or {}).get('result') or {}
            if out.get('game_id')==row['game_id'] and out.get('mod'):
                try: result['build'] = build(row['game_id'],out['mod'])
                except HTTPException: pass
        if row.get('build'):
            try: result['build'] = build(row['game_id'],row['build']['name'])
            except HTTPException: result.pop('build',None)
        return result

    @app.get('/api/games/{gid}/build-requests')
    def listing(gid: str, actor=Depends(auth)):
        g=game(gid)
        rows=sorted((r for r in store.all(KIND) if r['game_id']==gid),key=lambda r:r['created'],reverse=True)
        return {'game_id':gid,'title':g.get('title'),'items':[view(r) for r in rows[:30]]}

    @app.post('/api/games/{gid}/build-requests')
    def create(gid: str, body: BuildRequestIn, actor=Depends(auth)):
        g=game(gid); description=body.description.strip()
        if len(description)<3: raise HTTPException(422,'Describe the build you want')
        if len(json.dumps(body.mapping))>96000:raise HTTPException(422,'Sprite mapping exceeds its bounded profile size')
        session=store.get('session',body.session_id) if body.session_id else None
        if body.session_id and (not session or session.get('game_id')!=gid):
            raise HTTPException(409,'The session does not belong to this game')
        if body.recipe=='sonic2_player' and gid!='49b6a2f65aca26a2':raise HTTPException(422,'Sonic 2 player recipe requires Super Mario Bros.')
        if body.photo:
            artifact=store.get('artifact',body.photo) or {}
            if not (artifact.get('provenance') or {}).get('photo_skin_source'):raise HTTPException(422,'Upload the original photo first')
        if body.recipe=='photo_face':
            if gid in ('b7aecee966090bfa','66062703301f4969') and body.projection_scope!='gameplay':
                raise HTTPException(422,'Mario 64 boot-head projection needs a separate Goddard writer. Choose an engineering request for boot or both targets.')
            import re
            candidate=body.mapping.get('candidate','')
            if not re.fullmatch('[a-f0-9]{32}',candidate):raise HTTPException(422,'Preview and select the photo mapping first')
            try:preview=json.loads((config.data_dir/'sprite-face-candidates'/candidate/'candidate.json').read_text())
            except (OSError,ValueError):raise HTTPException(422,'Photo preview is missing')
            if preview['game_id']!=gid or preview['photo']!=body.photo:raise HTTPException(409,'Photo preview belongs to a different game or image')
        signature=hashlib.sha256(json.dumps([gid,body.kind,description,body.session_id,body.recipe,body.photo,body.mapping,body.projection_scope],sort_keys=True).encode()).hexdigest()
        with lock:
            old=next((r for r in store.all(KIND) if r.get('client_id')==str(body.client_id)),None)
            if old:
                if old['signature']!=signature: raise HTTPException(409,'Request ID already used for a different build')
                return view(old)
            report=create_request({'title':f'Custom {body.kind}: {g.get("title")} — {description}'[:180],
                'body':description,'source':'app','author':'operator',
                'attachments':[{'sha256':body.photo,'name':'sprite-source-photo.png'}] if body.photo else [],
                'context':{'game_id':gid,'game':g.get('title'),
                    'session_id':body.session_id,'base_mod':(session or {}).get('mod') or '',
                    'game_build_request':True,'replacement_requested':True,'photo':body.photo,'sprite_mapping':body.mapping,'projection_scope':body.projection_scope}})
            row={'id':report['id'],'request_id':report['id'],'number':report['number'],'game_id':gid,
                 'game_title':g.get('title'),'session_id':body.session_id,'base_mod':(session or {}).get('mod') or '',
                 'description':description,'kind':body.kind,'photo':body.photo,'mapping':body.mapping,
                 'projection_scope':body.projection_scope,
                 'client_id':str(body.client_id),'signature':signature,'created':time.time()}
            store.put(KIND,row['id'],row)
            try:
                # One verified local recipe; every other game/type goes through the existing engineering queue.
                if body.recipe=='sonic2_player':
                    job=submit({'tool':'smb1_sprite_build','input':{'game_id':gid,'request_id':row['id'],
                                'request_number':row['number']},'require_os':'linux','parent_request_id':row['id'],'agent_use':True},actor)
                    row['dispatch']={'mode':'native_recipe','job_id':getattr(job,'id',None) or job.get('id')}
                elif body.recipe=='photo_face':
                    job=submit({'tool':'photo_sprite_build','input':{'game_id':gid,'candidate':body.mapping['candidate'],
                        'request_id':row['id'],'request_number':row['number']},'require_os':'linux','parent_request_id':row['id'],'agent_use':True},actor)
                    row['dispatch']={'mode':'native_photo_recipe','job_id':getattr(job,'id',None) or job.get('id')}
                else:
                    details=description+f'\nProjection scope: {body.projection_scope}. Photo artifact: {body.photo or "none"}. Mapping: {json.dumps(body.mapping)}'
                    row['dispatch']=investigate(row['id'],row['number'],instructions(g,details,row['id']),name=f'Custom game build #{row["number"]}')
            except Exception as error:
                row['dispatch_error']=str(error)[:500]  # durable request remains available to the normal queue
            store.put(KIND,row['id'],row)
            return view(row)

    class ResultIn(BaseModel):
        name: str = Field(min_length=1,max_length=160)

    @app.post('/api/games/{gid}/build-requests/{rid}/result')
    def publish(gid: str, rid: str, body: ResultIn, actor=Depends(auth)):
        with lock:
            row=record(gid,rid); row['build']=build(gid,body.name)
            store.put(KIND,rid,row);store.audit(actor,'game_build_request.result',rid,{'name':body.name})
            return view(row)
