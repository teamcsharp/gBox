"""The asset pipeline as tools, so every other system can rip, extract and replace a title's files.

Three operations over one title archive (NSP):

* ``inventory`` — list the RomFS: every path, size and kind (model / texture / audio / archive / data).
* ``extract``   — write one RomFS file out to disk (targeted read; the archive is never unpacked whole).
* ``stage``     — write a replacement into a LayeredFS overlay so the game reads it over its own file at boot.

The decoding lives in `gbox.switch_assets`; this module only exposes it to the registry with the usual
budgets and permissions, so the agent, the MCP server and any other caller use the same code path.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import Permission as P
from .registry import tool, Unsupported

from . import switch_assets


class AssetIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    op: Literal['inventory', 'extract', 'stage'] = 'inventory'
    title: str = Field(description="label for the title, e.g. re5_switch")
    nsp_path: str = Field(default='', description="path to the title's .nsp on this worker")
    path: str = Field(default='', description="RomFS path, for extract/stage")
    out_path: str = Field(default='', description="where extract writes the file")
    data_b64: str = Field(default='', description="replacement bytes for stage (base64)")
    build: str = Field(default='gbox-lab', description="LayeredFS overlay name for stage")


class AssetOut(BaseModel):
    result: dict


def _resolve(inp, ctx) -> Path:
    """The NSP to open: the one given, else the first for this title under the switch titles folder."""
    if inp.nsp_path:
        p = Path(inp.nsp_path).expanduser()
        if not p.is_file():
            raise Unsupported(f"{inp.nsp_path} is not a file on this worker")
        return p
    roots = [Path.home() / 'gBox_alt' / 'switch' / 'titles',
             Path.home() / 'gBox' / 'system' / 'gbox-data' / 'switch' / 'titles']
    for root in roots:
        if root.is_dir():
            for cand in sorted(root.glob('*.nsp')):
                if inp.title.lower() in cand.name.lower():
                    return cand
    raise Unsupported("no nsp_path given and none found for this title on the worker")


@tool('switch_assets', '1.0', AssetIn, AssetOut, capabilities=['asset', 'extract'],
      permissions=[P.READ, P.STAGE, P.FILE_MUTATION], timeout_s=1800, retries=0,
      side_effects=['Reads a title archive on this worker; extract writes a file, stage writes into a LayeredFS overlay'])
def run(inp, ctx):
    """Inventory, extract from, or stage a replacement into a Nintendo Switch title's RomFS."""
    nsp = _resolve(inp, ctx)
    if inp.op == 'inventory':
        ctx.progress(5, f'opening {nsp.name}')
        cache = Path(getattr(ctx.config, 'data_dir', Path.home() / 'gBox' / 'system' / 'gbox-data')) / 'switch-assets'
        inv = switch_assets.inventory(nsp, cache_dir=cache)
        ctx.progress(95, f'{len(inv.entries)} files')
        return {'result': {'title': inp.title, 'nsp': str(nsp), 'files': len(inv.entries),
                           'counts': inv.counts(), 'romfs_section': inv.romfs_section,
                           'cache': str(cache), 'sample': [{'path': e.path, 'size': e.size}
                                                           for e in inv.entries[:25]]}}
    if inp.op == 'extract':
        if not inp.path:
            raise Unsupported('extract needs a RomFS path')
        out = Path(inp.out_path).expanduser() if inp.out_path else \
            Path(getattr(ctx.config, 'cache', Path.home() / 'gBox' / 'gbox-cache')) / 'switch-assets' / Path(inp.path).name
        ctx.progress(20, f'extracting {inp.path}')
        written = switch_assets.extract(nsp, inp.path, out)
        data = written.read_bytes()
        ctx.progress(100, 'extracted')
        return {'result': {'path': str(written), 'size': len(data),
                           'sha256': hashlib.sha256(data).hexdigest(), 'kind': switch_assets.kind_of(inp.path)}}
    # stage
    if not inp.path or not inp.data_b64:
        raise Unsupported('stage needs a RomFS path and data_b64')
    try:
        data = base64.b64decode(inp.data_b64, validate=True)
    except Exception as exc:
        raise Unsupported(f'data_b64 is not valid base64: {exc}') from exc
    inner = inp.path.strip().lstrip('/')
    if not inner or '..' in inner.split('/'):
        raise Unsupported('path must be a relative RomFS path')
    cache = Path(getattr(ctx.config, 'cache', Path.home() / 'gBox' / 'gbox-cache'))
    target = cache / 'mods' / inp.title / inp.build / 'romfs' / inner
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    ctx.progress(100, 'staged')
    return {'result': {'target': str(target), 'size': len(data),
                       'note': 'the overlay applies when the title next boots (LayeredFS)'}}
