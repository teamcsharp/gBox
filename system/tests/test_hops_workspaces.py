import json,os,subprocess
from pathlib import Path
import pytest
from gbox import hops_workspace as H,mesh_workspace as M


def test_hops_workspaces_validate_explicit_controls():
    assert H.HopsIn(character='amy',mode='3d',cuts=4).cuts==4
    with pytest.raises(ValueError):H.HopsIn(character='amy',mode='destructive')
    with pytest.raises(ValueError):H.HopsIn(character='amy',cuts=1000)
    with pytest.raises(ValueError):H.HopsIn(character='amy',voxel_resolution=4096)


def test_actual_local_node_knife_is_dynamic_and_restores_new_vertex_weights(tmp_path):
    exe=os.environ.get('GBOX_TEST_HOPS_BLENDER');provider=os.environ.get('GBOX_TEST_HOPS_ROOT')
    if not exe or not provider:pytest.skip('Requires the operator-provided local HOps asset and Blender 4.5+')
    script=tmp_path/'probe.py'
    helper=Path(H.__file__).with_name('hops_workspace_blender.py')
    script.write_text('''import bpy,bmesh,json,importlib.util
spec=importlib.util.spec_from_file_location('helper',HELPER)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_cube_add(size=2);cube=bpy.context.object
group=cube.vertex_groups.new(name='test_weight');group.add(list(range(8)),1,'REPLACE')
report=module.attach([cube],{'provider':PROVIDER,'mode':'2d','cuts':2,'voxel_resolution':64})
def measure():
    bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();evaluated=cube.evaluated_get(dg)
    mesh=evaluated.to_mesh(preserve_all_data_layers=True,depsgraph=dg);mesh.calc_loop_triangles()
    bm=bmesh.new();bm.from_mesh(mesh)
    result={'triangles':len(mesh.loop_triangles),'volume':bm.calc_volume(),'vertices':len(mesh.vertices),
            'weighted':sum(any(g.group==group.index and g.weight>.99 for g in v.groups) for v in mesh.vertices),'uv_layers':len(mesh.uv_layers)}
    bm.free();evaluated.to_mesh_clear();return result
two=measure();assert two['triangles']>12 and abs(two['volume']-8)<1e-5 and two['weighted']==two['vertices'],two
grid=bpy.data.objects[report['grid']]
grid['Cuts Y']=2;grid.update_tag();cube.update_tag();three=measure()
assert three['triangles']>two['triangles'] and abs(three['volume']-8)<1e-5 and three['weighted']==three['vertices'],three
for axis in 'XYZ':grid['Cuts '+axis]=0
grid.update_tag();cube.update_tag();off=measure();assert off['triangles']==12,off
assert len(cube.data.vertices)==8,'Non-destructive source mesh must not change'
print('NODE_DICE_VERIFIED '+json.dumps({'2d':two,'3d':three,'off':off}))
'''.replace('HELPER',repr(str(helper))).replace('PROVIDER',repr(provider)))
    run=subprocess.run([exe,'-b','--factory-startup','--python-exit-code','1','--python',str(script)],capture_output=True,text=True,timeout=120)
    assert run.returncode==0 and 'NODE_DICE_VERIFIED ' in run.stdout,(run.stdout+run.stderr)[-2500:]
