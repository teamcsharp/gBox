"""Configure host MercMode, or inspect prepared caches without starting a game."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, StrictBool
from .models import Permission as P
from .registry import tool, Unsupported


class MercModeIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    op: Literal['status','configure','prepare']='status'
    host: str | None=None
    enabled: StrictBool | None=None
    titles: list[Literal['re4','re5','re6','re3','merc3d']] | None=None
    rounds_per_title: int | None=None
    presentation_priority: StrictBool | None=None
    queue: list[dict] | None=None         # the DJ queue (gbox.mercmode.queue_entry validates each round)
    keep_warm: int | None=None            # titles kept paused beside the playing one, next one preloaded (0 = off)
    preferred_editions: dict | None=None  # gbox.re_switch: e.g. RE5 on Switch, No Mercy
    stalemate_cut: StrictBool | None=None # gbox.mercs.stalemate: the bots cut the clock when no enemy shows for 15 s
    stalemate_cut_s: int | None=None      # ... to this many seconds (1..60; default 5)
    coop_ratio: Literal['off','1:1','2:1','3:1','4:1','5:1','6:1','8:1','10:1','only'] | None=None  # co-op : solo turns (Switch)


class MercModeOut(BaseModel):
    result: dict


@tool('mercmode','1.0',MercModeIn,MercModeOut,capabilities=['runtime'],permissions=[P.EXECUTE],timeout_s=30)
def mercmode(inp: MercModeIn,ctx):
    import httpx
    from . import mercmode as M
    if not ctx.server:
        raise Unsupported('MercMode needs its connected control plane and an exact registered host')
    with httpx.Client(base_url=ctx.server,headers=ctx.headers,timeout=10) as client:
        if inp.op=='prepare':
            result=M.inspect_preparation(ctx.config.runtime)
            result['games']={}
            from . import re_switch as RS
            # the native discs and the Switch No Mercy editions a host may prefer (preferred_editions)
            for gid in (*M.TITLES['re4']['game_ids'],*M.TITLES['re5']['game_ids'],RS.RE5_GAME_ID,RS.RE6_GAME_ID,
                        *M.TITLES['merc3d']['game_ids']):
                catalog=client.get('/api/catalog/'+gid)
                if catalog.status_code==404:continue
                catalog.raise_for_status()
                result['games'][gid]=M.inspect_rom_access(ctx.config,catalog.json())
            response=client.post('/api/mercmode/preparation',json={'worker_id':ctx.worker,'result':result})
        elif inp.op=='configure':
            if not inp.host:raise ValueError('Choose an exact registered host name')
            response=client.post('/api/mercmode',json=inp.model_dump(exclude_none=True,exclude={'op'}))
        else:
            response=client.get('/api/mercmode')
        response.raise_for_status()
        return {'result':response.json()}
