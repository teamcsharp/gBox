"""Runs inside Blender 4.5+. Import the operator's local node wrapper without loading GPU/UI add-ons."""
import importlib
import sys
import types
from pathlib import Path


def node_grid(bpy,collection,low,high,mode,cuts):
    obj=bpy.data.objects.new('DICE GRID - select Custom Properties for live cut counts',None)
    collection.objects.link(obj);obj.empty_display_type='CUBE'
    extent=[max(high[i]-low[i],1e-5) for i in range(3)]
    obj.location=[(high[i]+low[i])/2 for i in range(3)];obj.empty_display_size=max(extent)/2
    cutters=[]
    for axis in 'XYZ':
        key='Cuts '+axis;obj[key]=0 if mode=='2d' and axis=='Y' else cuts
        obj.id_properties_ui(key).update(min=0,max=6,description='Live cut count: X/Z for 2D, add Y for 3D; zero bypasses this axis')
    for i,axis in enumerate('XYZ'):
        x,y,z=[v*.525 for v in extent]
        vertices=[[(0,-y,-z),(0,y,-z),(0,y,z),(0,-y,z)],
                  [(-x,0,-z),(-x,0,z),(x,0,z),(x,0,-z)],
                  [(-x,-y,0),(x,-y,0),(x,y,0),(-x,y,0)]][i]
        for index in range(6):
            mesh=bpy.data.meshes.new(f'Dice {axis} {index+1}');mesh.from_pydata(vertices,[],[(0,1,2,3)])
            cutter=bpy.data.objects.new(mesh.name,mesh);collection.objects.link(cutter)
            cutter.parent=obj;cutter.display_type='WIRE';cutter.hide_render=True;cutter.hide_select=True
            driver=count_driver(cutter,'location',obj,axis,index,array=i)
            driver.expression=f'-{extent[i]/2}+{extent[i]}*{index+1}/(max(count,0)+1)'
            cutters.append((axis,index,cutter))
    return obj,cutters


def count_driver(owner,path,controller,axis,index,array=None):
    curve=owner.driver_add(path) if array is None else owner.driver_add(path,array)
    driver=curve.driver;driver.type='SCRIPTED'
    variable=driver.variables.new();variable.name='count';variable.type='SINGLE_PROP'
    variable.targets[0].id=controller;variable.targets[0].data_path='["Cuts '+axis+'"]'
    driver.expression=f'count>{index}'
    return driver


def transfer_from(obj,reference,keep):
    transfer=obj.modifiers.new('Recover weights and UVs from source reference','DATA_TRANSFER');transfer.object=reference
    transfer.use_vert_data=True;transfer.data_types_verts={'VGROUP_WEIGHTS'};transfer.vert_mapping='POLYINTERP_NEAREST'
    transfer.layers_vgroup_select_src='ALL';transfer.layers_vgroup_select_dst='NAME'
    transfer.vertex_group=keep;transfer.invert_vertex_group=True
    if reference.data.uv_layers:
        transfer.use_loop_data=True;transfer.data_types_loops={'UV'};transfer.loop_mapping='POLYINTERP_NEAREST'
        transfer.layers_uv_select_src='ALL';transfer.layers_uv_select_dst='NAME'
    return transfer


def attach(objects,settings):
    import bpy
    from mathutils import Vector
    if bpy.app.version<(4,5,0):raise RuntimeError('This local HOps node asset needs Blender 4.5 or newer')
    folder=Path(settings['provider'])/'utility/geometry_nodes'
    package=types.ModuleType('gbox_local_hops_nodes');package.__path__=[str(folder)];sys.modules[package.__name__]=package
    NodeBoolean=importlib.import_module(package.__name__+'.node_boolean').NodeBoolean
    collection=bpy.data.collections.new('TOPOLOGY CONTROLS - live nodes / voxel study')
    bpy.context.scene.collection.children.link(collection)
    references=bpy.data.collections.new('REFERENCE - topology transfer sources (hidden)')
    bpy.context.scene.collection.children.link(references)
    source_meshes=[o for o in objects if o.type=='MESH']
    points=[o.matrix_world@Vector(p) for o in source_meshes for p in o.bound_box]
    low=[min(p[i] for p in points) for i in range(3)];high=[max(p[i] for p in points) for i in range(3)]
    grid=None;cutters=[]
    if settings['mode']!='voxel_study':grid,cutters=node_grid(bpy,collection,low,high,settings['mode'],settings['cuts'])
    for obj in source_meshes:
        keep=obj.vertex_groups.new(name='gbox_keep_original_weights')
        keep.add(list(range(len(obj.data.vertices))),1,'REPLACE')
        reference=obj.copy();reference.data=obj.data.copy();reference.name='TRANSFER REFERENCE - '+obj.name
        reference.hide_render=True;reference.hide_select=True;reference['gbox_reference']=True
        if 'gbox_workspace_edit' in reference:del reference['gbox_workspace_edit']
        references.objects.link(reference)
        reference.vertex_groups.remove(reference.vertex_groups[keep.name])
        reference.hide_set(True)
        # Keep normal source deformation, remove any disabled review reduction modifier.
        for mod in list(reference.modifiers):
            if mod.type=='DECIMATE':reference.modifiers.remove(mod)
        if grid:
            # A node knife sees one plane per stage. Joining crossing open planes can erase the whole mesh.
            for axis,index,cutter in cutters:
                wrapper=NodeBoolean.from_object(obj);wrapper.object=cutter;wrapper.operation='KNIFE';wrapper.solver='EXACT';wrapper.non_manifold=True
                count_driver(wrapper.modifier,'show_viewport',grid,axis,index)
                count_driver(wrapper.modifier,'show_render',grid,axis,index)
            transfer_from(obj,reference,keep.name)
        else:
            study=obj.copy();study.data=obj.data.copy();study.name='VOXEL STUDY - '+obj.name
            study['gbox_reference']=True;study.hide_render=True
            if 'gbox_workspace_edit' in study:del study['gbox_workspace_edit']
            collection.objects.link(study);study.hide_set(True)
            remesh=study.modifiers.new('EXPERIMENTAL voxel size / adaptivity','REMESH');remesh.mode='VOXEL'
            remesh.voxel_size=max(high[2]-low[2],1e-5)/settings['voxel_resolution']
            remesh.show_viewport=False;remesh.show_render=False
            transfer_from(study,reference,keep.name)
    bpy.context.view_layer.update();depsgraph=bpy.context.evaluated_depsgraph_get()
    metrics=[]
    for obj in source_meshes:
        evaluated=obj.evaluated_get(depsgraph);mesh=evaluated.to_mesh(preserve_all_data_layers=True,depsgraph=depsgraph)
        try:
            mesh.calc_loop_triangles()
            if not mesh.vertices or not mesh.loop_triangles:raise RuntimeError(f'Node workflow erased {obj.name}; original donor retained')
            armature=obj.find_armature()
            bones={b.name for b in armature.data.bones if b.use_deform} if armature else None
            groups={g.index for g in obj.vertex_groups if g.name in bones} if bones else {g.index for g in obj.vertex_groups if not g.name.startswith('gbox_')}
            unweighted=sum(not any(g.group in groups and g.weight>1e-7 for g in v.groups) for v in mesh.vertices)
            metrics.append({'mesh':obj.name,'vertices':len(mesh.vertices),'triangles':len(mesh.loop_triangles),
                            'unweighted_vertices':unweighted,'uv_layers':len(mesh.uv_layers)})
            if armature and unweighted:raise RuntimeError(f'Node workflow left {unweighted} unweighted vertices in {obj.name}; original donor retained')
        finally:evaluated.to_mesh_clear()
    return {'mode':settings['mode'],'cuts':settings['cuts'],'blender':bpy.app.version_string,
            'source_meshes':len(source_meshes),'grid':grid.name if grid else None,
            'evaluated':metrics,
            'notice':'Editable node stack, not an approved mesh. Inspect weights, UVs, volume, joints and native budgets; voxel studies are hidden and disabled.'}
