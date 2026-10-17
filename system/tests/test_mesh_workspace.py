import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from gbox import attachments as A, blender_roundtrip as RT, mesh_workspace as M
from tests import blender_rt_fixtures as fx


def donor(tmp_path):
    src=fx.humanoid(tmp_path/'source.glb',fx.ROLE_NAMES)
    gl,blob=A.pack(src)
    RT.tag(gl,{'slug':'donor','name':'Donor','rig':{'roles':fx.ROLE_NAMES}})
    return A.glb_bytes(gl,blob)


def test_workspace_uses_exact_job_pair_and_matching_donor(tmp_path,monkeypatch):
    raw=donor(tmp_path)
    row={'key':'one','donor':'donor','game_id':'1'*16,'slot':'player',
         'comparison':{'before':'/api/jobs/job/fitting/files/a.glb','after':'/api/jobs/job/fitting/files/b.glb'}}
    calls=[]
    def fetch(ctx,path,limit):
        calls.append(path)
        return json.dumps({'models':[row]}).encode() if path.endswith('/review') else raw
    monkeypatch.setattr(M,'fetch',fetch)
    info=M.prepare(None,M.WorkspaceIn(source_job='job',model='one'),tmp_path)
    assert info['tags']['armature']['gbox_slug']=='donor'
    assert (tmp_path/'before.glb').read_bytes()==raw
    assert info['context']['slot']=='player'
    assert not any('sessions' in path or 'launch' in path for path in calls)
    with pytest.raises(ValueError,match='does not match'):
        M.prepare(None,M.WorkspaceIn(character='other',source_job='job',model='one'),tmp_path)
    row['comparison']['before']='/api/jobs/other/fitting/files/a.glb'
    with pytest.raises(ValueError,match='another fitting job'):
        M.prepare(None,M.WorkspaceIn(source_job='job',model='one'),tmp_path)


@pytest.mark.parametrize('path',['https://example.com/a','//example.com/a','/api/../token','/api/jobs/a?token=bad'])
def test_workspace_cannot_fetch_arbitrary_urls(path):
    with pytest.raises(ValueError,match='asset route'):
        M.fetch(SimpleNamespace(server='http://invalid',headers={}),path,10)


def test_blend_contains_editable_donor_and_disabled_reduction(tmp_path,monkeypatch):
    exe=os.environ.get('GBOX_TEST_BLENDER')
    if not exe:pytest.skip('Set GBOX_TEST_BLENDER for the actual .blend round trip')
    raw=donor(tmp_path)
    monkeypatch.setattr(M,'fetch',lambda *args:raw)
    info=M.prepare(None,M.WorkspaceIn(character='donor'),tmp_path)
    # The fit pair is a separate hidden reference, never the editable source.
    (tmp_path/'before.glb').write_bytes(raw);(tmp_path/'after.glb').write_bytes(raw)
    script=tmp_path/'workspace.py';script.write_text(M.SCRIPT)
    output=tmp_path/'review.blend'
    run=subprocess.run([exe,'-b','--factory-startup','--python',str(script),'--',str(tmp_path),str(output)],capture_output=True,text=True,timeout=90)
    assert run.returncode==0 and output.is_file(),run.stdout+run.stderr
    check=tmp_path/'verify.py'
    check.write_text('''import bpy, json
meshes=[o for o in bpy.data.objects if o.get('gbox_workspace_edit')]
assert meshes
for obj in meshes:
    mod=next(mod for mod in obj.modifiers if mod.type=='DECIMATE')
    assert mod.type=='DECIMATE' and mod.ratio==1 and not mod.show_viewport and not mod.show_render
    assert obj.vertex_groups.get('gbox_protect_detail') and obj.vertex_groups.get('gbox_reduce_allowed')
assert len([c for c in bpy.data.collections if c.name.startswith('REFERENCE') and c.hide_viewport])==3
assert any(o.get('gbox_slug')=='donor' for o in bpy.context.selected_objects)
assert len([o for o in bpy.data.objects if o.name.startswith('GROUND')])==1
assert bpy.data.texts.get('START HERE - geometry review')
print('VERIFIED_WORKSPACE')
''')
    check_result=subprocess.run([exe,'-b','--factory-startup',str(output),'--python-exit-code','1','--python',str(check)],capture_output=True,text=True,timeout=90)
    assert check_result.returncode==0 and 'VERIFIED_WORKSPACE' in check_result.stdout,check_result.stdout+check_result.stderr
    assert (tmp_path/'donor.glb').read_bytes()==raw
