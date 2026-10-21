"""Audited guest-code research for one immutable live request target."""
from __future__ import annotations

from .live_request import bind_target


def investigate(agent, session_id: str = '', goal: str = '') -> dict:
    target = getattr(agent, 'live_target', None)
    if not target or session_id and session_id != target['session_id']:
        raise ValueError('Live research requires the exact game attached to this request')
    bind_target(target, agent.api.get('/api/sessions').json())
    sid = target['session_id']
    # Check the actual runtime before queueing extraction. In particular, native
    # games without a guest-memory provider must not fall through to ROM staging.
    info = agent._rpc(sid, 'info')
    if not isinstance(info, dict) or info.get('game_id') != target['game_id']:
        raise ValueError('Live research received a different runtime game identity')
    runtime = info.get('runtime') or {}
    capabilities = info.get('capabilities') or {}
    from .re_lab_tool import PLATFORM_CPU
    reason = ('The attached runtime is no longer running' if runtime.get('running') is not True else
              'The attached runtime has no verified guest RAM reader' if capabilities.get('read_memory') != 'supported' else
              f"No verified CPU mapping for live platform {info.get('platform')!r}" if info.get('platform') not in PLATFORM_CPU else '')
    if reason:
        agent._live_phase('research', reason, status='blocked')
        return {'session_id': sid, 'state': 'blocked', 'error': reason,
                'rom_copy': False, 'verified': False,
                'next': 'Keep the game running. Add or activate a verified guest-memory provider; do not extract the disc as a fallback for this live request.'}
    binding = (sid, target['game_id'], target.get('mod', ''), target.get('worker_id'),
               info.get('platform'), info.get('emulator'), info.get('core'), info.get('rom'), runtime.get('pid'))
    workers = agent.api.get('/api/workers').json()
    available = [w for w in workers if w.get('online') and w.get('os') == 'linux'
                 and {'re_executable', 'ghidra_bridge'} <= set(w.get('tools') or [])]
    cached = getattr(agent, 'live_research_cache', None)
    captured = None
    if cached and cached['binding'] == binding:
        worker, ex = cached['result']['worker_id'], cached['result']['executable']
        if not any(w['id'] == worker for w in available):
            return {'session_id': sid, 'state': 'blocked', 'verified': False, 'rom_copy': False,
                    'error': 'The worker holding this captured guest analysis is no longer available'}
        try:
            checked = agent._job('ghidra_bridge', {'op': 'info', 'expected_binary_path': ex['elf_path'],
                                 'expected_sha256': ex['sha256']}, worker=worker, limit=30)
        except Exception as error:
            checked = {'state': 'failed', 'error': str(error)}
        output = checked.get('output') or {}
        payload = output.get('result') if isinstance(output.get('result'), dict) else output
        if (checked.get('state') == 'succeeded' and not output.get('error')
                and not payload.get('error') and payload.get('ok') is not False):
            bind_target(target, agent.api.get('/api/sessions').json())
            agent._live_phase('research', 'Reusing the verified captured guest analysis for this request')
            return dict(cached['result'], goal=goal[:1000], reused_analysis=True)
        # A different conversation may have replaced Ghidra's program. Reopen
        # this exact captured ELF; reading live RAM or the ROM again is needless.
        captured = (ex, worker)
    if not available:
        return {'session_id': sid, 'state': 'blocked',
                'error': 'No online analysis worker currently provides guest extraction and Ghidra Bridge', 'verified': False}
    if captured:
        ex, worker = captured
    else:
        analysis_worker = available[0]['id']
        agent._live_phase('research', 'Reading the running game for reverse engineering')
        job = agent._job('re_executable', {'game_id': target['game_id'], 'source': 'ram', 'session_id': sid},
                         worker=analysis_worker, limit=3600)
        if job.get('state') != 'succeeded' or not isinstance(job.get('output'), dict):
            return {'session_id': sid, 'state': job.get('state', 'failed'),
                    'error': job.get('error') or 'The running guest executable could not be captured',
                    'job_id': job.get('id')}
        ex, worker = job['output'], job.get('worker_id')
    if ex.get('session_id') != sid or ex.get('game_id') != target['game_id'] or ex.get('mod', '') != target.get('mod', ''):
        raise ValueError('The executable snapshot does not match the attached game and build')
    if not worker or not ex.get('elf_path') or not ex.get('sha256') or not ex.get('processor'):
        raise ValueError('Guest research needs the capture worker, executable identity and Ghidra processor')
    # REA's native provider contract covers x86/ARM. Other guest CPUs use
    # Ghidra's explicit processor; checking REA is not a claim of attachment.
    supported = str(ex.get('cpu') or '').lower() in {'x86', 'x86_64', 'arm', 'arm64', 'aarch64'}
    agent._live_phase('research', 'Opening the captured guest image in REA' if supported else 'Checking REA capabilities')
    try:
        rea = agent.run_tool('rea_open_binary' if supported else 'rea_binary_session',
                             {'path': ex['elf_path'], 'provider_id': 'ghidra'} if supported else {}, worker_id=worker)
    except Exception as error:
        rea = {'state': 'failed', 'error': str(error), 'guest_attached': False}
    if not supported:
        rea = dict(rea, guest_attached=False, limitation=f"REA native provider does not verify {ex.get('cpu')}; use Ghidra {ex['processor']}")
    bind_target(target, agent.api.get('/api/sessions').json())
    agent._live_phase('research', 'Analyzing game code with its Ghidra processor')
    try:
        ghidra = agent._job('ghidra_bridge', {'op': 'open', 'binary_path': ex['elf_path'],
                            'processor': ex['processor'], 'analyze': True}, worker=worker, limit=3600)
    except Exception as error:
        ghidra = {'state': 'failed', 'error': str(error)}
    bridge = ghidra.get('output') or {}
    agent.live_analysis_worker = worker
    agent.rea_worker = worker
    if ghidra.get('state') == 'succeeded':
        agent.live_analysis_executable = dict(ex)
    result = {'session_id': sid, 'game_id': target['game_id'], 'mod': target.get('mod', ''),
              'worker_id': worker, 'goal': goal[:1000], 'executable': ex, 'rea': rea,
              'ghidra': {'state': ghidra.get('state'), 'error': ghidra.get('error'),
                         'receipt': ghidra.get('receipt_id'), 'output': bridge},
              'verified': False,
              'next': 'Use ghidra_bridge functions/strings/decompile/xrefs on worker_id, correlate findings with '
                      'this exact live session, then use tested game controls or guarded native patches. '
                      'Analysis is not a game change. Preserve unsupported provider diagnostics and verify the requested outcome.'}
    if ghidra.get('state') != 'succeeded':
        result['error'] = ghidra.get('error') or 'Ghidra research is still pending'
    try:
        bind_target(target, agent.api.get('/api/sessions').json())
    except ValueError as error:
        result['error'] = str(error)
        result['target_ended'] = True
    # Findings are revision-scoped. A live mod/RAM image must not replace the
    # base title dossier's executable and analysis metadata.
    agent.api.post(f"/api/re/dossier/{target['game_id']}/findings", json={
        'kind': 'note', 'name': f"Live request {getattr(agent, 'parent_request_id', '')}",
        'role': f"session={sid}; mod={target.get('mod', '')}; RAM snapshot={ex.get('source_sha256')}; "
                f"ELF={ex['sha256']}; processor={ex['processor']}; analysis worker={worker}; goal={goal[:500]}",
        'status': 'hypothesis', 'evidence': []})
    if ghidra.get('state') == 'succeeded' and not result.get('target_ended'):
        agent.live_research_cache = {'binding': binding, 'result': dict(result)}
    return result
