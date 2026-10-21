"""Scoped metadata transport for favorite research; never runs an unlock action."""
import re
from urllib.parse import quote


async def run(args, get, post):
    gid, rid = args['game_id'], args['request_id']
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', gid) or not re.fullmatch(r'[0-9a-f]{16}', rid):
        raise ValueError('Exact game and request identifiers are required')
    request = await get('/api/requests/' + rid)
    context = request.get('context') or {}
    if (context.get('custom_build_unlocks') != gid or context.get('favorite_default') is not True
            or request.get('status') not in {'open', 'in_progress'}):
        raise ValueError('This is not the active favorite unlock request for that game')
    op = args.get('op', 'status')
    base = '/api/custom-build-unlocks/' + gid
    native = '/api/games/' + gid + '/live-controls'
    if op == 'status':
        return {'unlocks': await get(base + '/profile'), 'native_controls': await get(native)}
    if op in {'native_profile', 'unlock_profile'}:
        return await post((native if op == 'native_profile' else base) + '/profile', args.get('body') or {})
    if op in {'manifest', 'verify'}:
        name = args.get('build', '@original')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9@._~-]{1,160}', name) or name in {'.', '..'}:
            raise ValueError('An exact build name is required')
        path = base + '/' + quote(name, safe='') + '/' + op
        return await get(path) if op == 'manifest' else await post(path, args.get('body') or {})
    raise ValueError('Only status, native_profile, unlock_profile, manifest and verify metadata operations are supported')
