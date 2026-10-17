"""Optional local Hard Ops node-knife workspaces. No native ROM or automatic approval."""
from pathlib import Path
import os
import re
import subprocess
from typing import Literal

from pydantic import Field
from . import mesh_workspace as M
from .models import Permission as P
from .registry import tool


class HopsIn(M.WorkspaceIn):
    mode: Literal['2d','3d','voxel_study']='2d'
    cuts: int=Field(default=2,ge=1,le=6)
    voxel_resolution: int=Field(default=128,ge=32,le=256)


def provider():
    return Path(os.environ.get('GBOX_HOPS_PATH','C:/_tools/HOps'))


def available(config):
    if not (provider()/'utility/geometry_nodes/HOPS_Nodes/HOPS_Boolean.blend').is_file():
        return 'Local Hard Ops node asset not installed (set GBOX_HOPS_PATH)'
    return None


def compatible_blender():
    from .blender_copy import find_blender
    candidates=[Path(find_blender())]
    candidates+=sorted((Path.home()/'Desktop/Blender/builds').glob('*/*/blender.exe'),reverse=True)
    for path in dict.fromkeys(candidates):
        try:
            result=subprocess.run([str(path),'--factory-startup','--version'],capture_output=True,text=True,timeout=15,
                                  creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except (OSError,subprocess.TimeoutExpired):continue
        match=re.search(r'Blender (\d+)\.(\d+)',result.stdout)
        if result.returncode==0 and match and tuple(map(int,match.groups()))>=(4,5):return str(path)
    raise RuntimeError('Local HOps node workspaces require Blender 4.5 or newer; original model unchanged')


@tool('hops_workspace','1.0',HopsIn,M.WorkspaceOut,capabilities=['assets'],permissions=[P.READ,P.EXECUTE],
      timeout_s=420,check=available,artifacts=['geometry-review.blend','workspace.json'])
def hops_workspace(inp:HopsIn,ctx):
    """Export a controllable 2D/3D HOps node-knife or disabled voxel-study .blend; original source and ROM preserved."""
    return M.create_workspace(inp,ctx,blender_exe=compatible_blender(),topology={'mode':inp.mode,'cuts':inp.cuts,'voxel_resolution':inp.voxel_resolution,
                                              'provider':str(provider()),'helper':str(Path(__file__).with_name('hops_workspace_blender.py'))})
