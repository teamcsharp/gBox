"""Editable Blender geometry workspaces, with immutable references and no automatic reduction."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import httpx
from pydantic import BaseModel, Field, model_validator

from .models import Permission as P
from .registry import tool


class WorkspaceIn(BaseModel):
    character: str = Field(default='', pattern=r'^[A-Za-z0-9_-]{0,128}$')
    source_job: str = Field(default='', pattern=r'^[A-Za-z0-9_-]{0,64}$')
    model: str = Field(default='', max_length=160)

    @model_validator(mode='after')
    def source(self):
        if not self.character and not (self.source_job and self.model):
            raise ValueError('Choose a library character or an exact fitting job and model')
        return self


class WorkspaceOut(BaseModel):
    result: dict


SCRIPT = r'''
import bpy, sys, json
from mathutils import Vector
from pathlib import Path
directory, output = map(Path, sys.argv[sys.argv.index('--')+1:])
info = json.loads((directory/'workspace.json').read_text())
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
for collection in list(bpy.data.collections):
    if collection.users == 0: bpy.data.collections.remove(collection)

def load(name, filename, reference=False):
    collection = bpy.data.collections.new(name); bpy.context.scene.collection.children.link(collection)
    old = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(directory/filename))
    objects = set(bpy.data.objects)-old
    for obj in objects:
        for c in list(obj.users_collection): c.objects.unlink(obj)
        collection.objects.link(obj)
        if reference:
            obj['gbox_reference'] = True; obj.hide_select = True
        obj.hide_render = reference
    collection.hide_viewport = reference
    return collection, objects

working, objects = load('EDIT - source donor (return this as a variant)', 'donor.glb')
tags = info.get('tags', {})
for obj in objects:
    if obj.type == 'ARMATURE':
        for key, value in tags.get('armature', {}).items(): obj[key] = value
        for bone in obj.data.bones:
            if bone.name in tags.get('bones', {}): bone['gbox_role'] = tags['bones'][bone.name]
    for key,value in tags.get('objects', {}).get(obj.name, {}).items(): obj[key] = value
    if obj.type != 'MESH': continue
    obj['gbox_workspace_edit'] = True
    protected = {name for name,role in tags.get('bones',{}).items() if role in ('head','l_hand','r_hand','l_foot','r_foot')}
    indices = {group.index for group in obj.vertex_groups if group.name in protected}
    protect = obj.vertex_groups.new(name='gbox_protect_detail')
    reduce = obj.vertex_groups.new(name='gbox_reduce_allowed')
    for vertex in obj.data.vertices:
        keep = any(g.group in indices and g.weight >= .3 for g in vertex.groups)
        (protect if keep else reduce).add([vertex.index], 1.0, 'REPLACE')
    modifier = obj.modifiers.new('REVIEW ONLY - enable and adjust reduction', 'DECIMATE')
    modifier.decimate_type = 'COLLAPSE'; modifier.ratio = 1.0
    modifier.vertex_group = reduce.name
    modifier.show_viewport = False; modifier.show_render = False
load('REFERENCE - untouched source (hidden)', 'donor.glb', True)
for side in ('before','after'):
    if (directory/(side+'.glb')).exists(): load('REFERENCE - fitted '+side+' reduction (hidden)', side+'.glb', True)
points = [obj.matrix_world @ vertex.co for obj in objects if obj.type == 'MESH' for vertex in obj.data.vertices]
low = min((v.z for v in points),default=0)
height = max((v.z for v in points),default=1)-low
guides = bpy.data.collections.new('GUIDES - set ground and shoe landmarks'); bpy.context.scene.collection.children.link(guides)
for name,z in [('GROUND - move to intended sole contact',low),('LEFT_SHOE_TOP - set ankle boundary',low+.15*height),('RIGHT_SHOE_TOP - set ankle boundary',low+.15*height)]:
    obj=bpy.data.objects.new(name,None);guides.objects.link(obj);obj.empty_display_type='CIRCLE'
    obj.empty_display_size=max(height*.4,.1);obj.location.z=z;obj['gbox_reference']=True
    obj['notice']='Guide only. Save matching shoe/ground controls in gBox before a rebuild.'
text=bpy.data.texts.new('START HERE - geometry review')
text.write(info['instructions']+'\n\nSource and measured fit context:\n'+json.dumps(info.get('context',{}),indent=2))
bpy.context.scene['gbox_workspace']=json.dumps(info.get('context',{}))
bpy.context.scene['gbox_review_notes']=''
bpy.ops.object.select_all(action='DESELECT')
for obj in objects: obj.select_set(True)
active=next((obj for obj in objects if obj.type=='ARMATURE'),next(iter(objects),None))
if active:bpy.context.view_layer.objects.active=active
for image in bpy.data.images:
    if image.has_data and image.source in ('FILE','GENERATED') and not image.packed_file:image.pack()
bpy.ops.wm.save_as_mainfile(filepath=str(output))
print('GBOX_WORKSPACE '+json.dumps({'objects':len(objects),'mesh_triangles':sum(sum(len(p.vertices)-2 for p in obj.data.polygons) for obj in objects if obj.type=='MESH'),'ground_guide':low,'height':height}))
'''

INSTRUCTIONS = '''The EDIT collection is the original rigged donor, not an automatically decimated mesh.
Keep the hidden REFERENCE source untouched. The optional fitted before/after collections use
target-game coordinates and are geometry-only: do not export those as a donor or as gameplay proof.
Reduction modifiers start DISABLED at ratio 1. Paint gbox_reduce_allowed / gbox_protect_detail,
adjust topology, and inspect the face, fingers, shoe silhouettes and joints in several poses.
The vertex mask guides Blender's collapse modifier; it is not an absolute topology guarantee.
Use Hard Ops DICE on an editable duplicate if installed, or Blender's Knife/Bisect/loop cuts.
Dicing adds geometry; inspect UVs, weights, silhouette, volume and the native budget afterwards.
Move the ground and shoe-top guides to identify the sole contact and ankle/leg boundary.
These guides are explanatory: set the matching per-donor/game shoe and ground controls in gBox.
Write recommendations in Scene > Custom Properties > gbox_review_notes or the mesh-review report.
Return only the EDIT character using the gBox add-on's Send to gBox, or export its selected
mesh and armature as a GLB with custom properties and import it as a new donor variant.
Save the no-auto-reduction option for the target game to stop writers reducing that variant again.
The original donor and ROM stay unchanged. A .blend is a workspace, never approval of a game build.
'''


def fetch(ctx, path, limit):
    """Only same-server relative routes; bound downloads before passing bytes to Blender."""
    if not re.fullmatch(r'/api/[A-Za-z0-9_./%-]+', path) or '..' in path or '//' in path:
        raise ValueError('Invalid workspace asset route')
    payload=bytearray()
    with httpx.stream('GET',ctx.server+path,headers=ctx.headers,timeout=120,follow_redirects=False) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            payload.extend(chunk)
            if len(payload)>limit:raise ValueError('Workspace asset exceeds its download limit')
    return bytes(payload)


def prepare(ctx, inp, directory):
    from .blender_copy import gbox_tags
    context={'source_job':inp.source_job,'model':inp.model}
    donor=inp.character
    if inp.source_job:
        data=json.loads(fetch(ctx,f'/api/jobs/{inp.source_job}/fitting/review',2<<20))
        row=next((r for r in data.get('models',[]) if r['key']==inp.model),None)
        if not row:raise ValueError('Fitted model not found')
        if donor and donor!=row.get('donor'):raise ValueError('Donor does not match the fitting job')
        donor=row.get('donor') or ''
        context.update({k:row.get(k) for k in ('donor','game_id','slot','comparison','stages')})
        pair=row.get('comparison')
        if pair:
            prefix=f'/api/jobs/{inp.source_job}/fitting/files/'
            for side in ('before','after'):
                path=pair.get(side,'')
                if not path.startswith(prefix):raise ValueError('Comparison belongs to another fitting job')
                (directory/(side+'.glb')).write_bytes(fetch(ctx,path,8<<20))
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',donor):raise ValueError('The fit has no editable library donor')
    source=fetch(ctx,f'/api/characters/{donor}/blender',128<<20)
    (directory/'donor.glb').write_bytes(source)
    context.update(donor=donor,donor_sha256=hashlib.sha256(source).hexdigest())
    info={'tags':gbox_tags(directory/'donor.glb'),'context':context,'instructions':INSTRUCTIONS}
    (directory/'workspace.json').write_text(json.dumps(info,indent=2))
    return info


@tool('mesh_workspace','1.0',WorkspaceIn,WorkspaceOut,capabilities=['assets'],permissions=[P.READ,P.EXECUTE],
      timeout_s=420,artifacts=['geometry-review.blend','workspace.json'])
def mesh_workspace(inp:WorkspaceIn,ctx):
    """Export an editable .blend donor with preserved references, optional exact fit pair and disabled reduction controls. No build or game input."""
    from .blender_copy import find_blender
    exe=find_blender()
    with tempfile.TemporaryDirectory(prefix='gbox-mesh-workspace-') as temp:
        directory=Path(temp);ctx.progress(5,'Collecting the rigged donor and exact saved fitting geometry')
        info=prepare(ctx,inp,directory)
        script=directory/'workspace.py';script.write_text(SCRIPT)
        output=directory/'geometry-review.blend'
        ctx.progress(35,'Creating the editable Blender workspace (original geometry preserved)')
        result=subprocess.run([exe,'-b','--factory-startup','--python-exit-code','1','--python',str(script),'--',str(directory),str(output)],
                              capture_output=True,text=True,timeout=300,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        line=next((s for s in result.stdout.splitlines() if s.startswith('GBOX_WORKSPACE ')),None)
        if result.returncode or not line or not output.is_file():
            raise RuntimeError('Blender workspace failed: '+(result.stdout+result.stderr)[-1000:])
        if output.stat().st_size>256<<20:raise ValueError('Workspace exceeds 256 MB')
        ctx.artifact('geometry-review.blend',output.read_bytes(),'application/x-blender',**info['context'])
        ctx.artifact('workspace.json',json.dumps(info,indent=2).encode(),'application/json')
        ctx.progress(100,'Editable .blend ready; no donor or ROM was changed')
        return {'result':{'workspace':'geometry-review.blend','sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'context':info['context'],
                          'blender':json.loads(line[len('GBOX_WORKSPACE '):]),'notice':'Edit the source donor, return a variant, and review native budgets before building.'}}
