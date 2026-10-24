"""Operator intent for session-scoped Mercenaries teammate and training roles."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool

from .models import Permission as P
from .registry import Unsupported, tool
from .mercs import teamplay


class TeamIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: str
    op: Literal['status', 'configure', 'prepare_player2'] = 'status'
    role: Literal['solo_p1', 'teammate_p2', 'observe_human'] | None = None
    training_profile: Literal['assisted', 'unmodified_evaluation'] | None = None
    auto_reduce_mods: StrictBool | None = None
    selected_route_id: str | None = None


class TeamOut(BaseModel):
    result: dict


@tool('mercs_team', '1.0', TeamIn, TeamOut, capabilities=['runtime'], permissions=[P.EXECUTE], timeout_s=30)
def mercs_team(inp: TeamIn, ctx):
    """Save team/training intent without changing modifiers or sending inputs.

    Player 2 remains pending until native actor and separate pad ownership are
    freshly verified. Unmodified evaluation pauses until original settings are
    verified; it never silently removes the current assisted-training settings.
    """
    from .tools import SESSIONS
    try:
        adapter, game = SESSIONS[inp.session_id]
    except KeyError as exc:
        raise Unsupported('This exact session has ended or is not owned by this worker.') from exc
    game_id = game.get('game_id')
    if game_id not in (teamplay.RE5, teamplay.RE6):
        raise Unsupported('Team/training controls currently cover Resident Evil 5 and 6.')
    process = getattr(adapter, 'proc', None)
    if process is not None and process.poll() is not None:
        raise Unsupported('This exact game process has ended.')
    store = teamplay.TeamStore(ctx.config.data_dir)
    preparation = None
    if inp.op == 'prepare_player2':
        prepare = getattr(adapter, 'prepare_teammate_pad', None)
        if game_id != teamplay.RE5 or not callable(prepare):
            raise Unsupported('This runtime cannot prepare a separate RE5 Player 2 controller.')
        preparation = prepare(player=2)
        if not isinstance(preparation, dict) or preparation.get('player') != 2:
            raise Unsupported('Player 2 controller preparation returned no identifiable result.')
    if inp.op == 'configure':
        patch = inp.model_dump(exclude_unset=True, exclude={'session_id', 'op'})
        if patch:
            from .mercs.reviewer import Reviewer
            reader = Reviewer(ctx.config.data_dir)
            lookup = getattr(reader, 'demonstration', None)
            store.configure(inp.session_id, patch, game_id=game_id, route_lookup=lookup)
    status = store.status(inp.session_id, game_id=game_id, adapter=adapter)
    inspector = getattr(adapter, 'teammate_pad_status', None)
    if preparation is None and callable(inspector):
        preparation = inspector()
    status['player2_preparation'] = preparation
    status['capabilities']['prepare_player2'] = {'available': game_id == teamplay.RE5 and callable(getattr(adapter, 'prepare_teammate_pad', None)),
        'reason': 'Prepares a separate controller for the next launch; never restarts the running game.'}
    return {'result': {'verified': True, 'configuration_verified': True,
                       'runtime_verified': status['phase'] == 'active', 'status': status}}
