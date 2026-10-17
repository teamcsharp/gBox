"""Fixed model-management recipe executed over authenticated SSH on the dedicated Spark.

Input is a validated plan on stdin. Credentials stay in Docker's existing configuration,
never in progress reports. The original container is retained for rollback.
"""
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

MODEL = 'nvidia/Qwen3.6-35B-A3B-NVFP4'


def run(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs).stdout


def emit(state, **details):
    print(json.dumps({'state': state, **details}), flush=True)


def main(plan):
    assert plan['action'] in ('pull', 'start') and plan['model'] == MODEL
    container = plan['container']
    old = json.loads(run(['docker', 'inspect', container]))[0]
    assert old['State']['Running'], 'Configured vLLM container is not running'
    if plan['action'] == 'pull':
        emit('downloading', model=MODEL)
        code = 'from huggingface_hub import snapshot_download; snapshot_download(repo_id='+repr(MODEL)+')'
        # Existing authenticated cache and HF_TOKEN remain inside the container.
        run(['docker', 'exec', container, 'python3', '-c', code], timeout=7200)
        emit('downloaded', model=MODEL)
        return
    code = ('from huggingface_hub import snapshot_download; '
            'snapshot_download(repo_id='+repr(MODEL)+', local_files_only=True)')
    run(['docker', 'exec', container, 'python3', '-c', code], timeout=60)
    emit('draining', message='Waiting for current vLLM requests to finish')
    import re
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        text = urllib.request.urlopen('http://127.0.0.1:8101/metrics', timeout=5).read().decode()
        values = re.findall(r'^vllm:num_requests_(?:running|waiting)(?:\{[^\n]*\})?\s+([0-9.eE+-]+)', text, re.M)
        assert values, 'Cannot prove vLLM is idle'
        if sum(float(v) for v in values) == 0:
            break
        time.sleep(3)
    else:
        raise RuntimeError('Current inference did not drain; original container retained')
    name = 'gbox-vllm-' + plan['id']
    # An immutable, installed image avoids pulling an untested moving tag during a switch.
    args = ['docker', 'run', '-d', '--name', name, '--gpus', 'all', '--restart', 'unless-stopped',
            '--shm-size', '1g', '-p', '8101:8000']
    for mount in old.get('Mounts', []):
        if mount['Destination'] == '/root/.cache/huggingface' and mount['Type'] == 'bind':
            args += ['-v', mount['Source']+':/root/.cache/huggingface']
            break
    else:
        raise RuntimeError('Existing persistent Hugging Face cache was not found')
    # Token is passed through the subprocess environment, never as a command argument.
    import os
    env = os.environ.copy()
    for entry in old['Config'].get('Env', []):
        key, _, value = entry.partition('=')
        if key == 'HF_TOKEN':
            env[key] = value
            args += ['-e', key]
    args += [old['Image'], MODEL, '--served-model-name', MODEL, '--host', '0.0.0.0', '--port', '8000',
        '--trust-remote-code', '--tensor-parallel-size', '1', '--kv-cache-dtype', 'fp8',
        '--attention-backend', 'flashinfer', '--moe-backend', 'marlin',
        '--gpu-memory-utilization', '0.9', '--max-model-len', '65536', '--max-num-seqs', '4',
        '--max-num-batched-tokens', '8192', '--enable-chunked-prefill', '--async-scheduling',
        '--enable-prefix-caching', '--reasoning-parser', 'qwen3', '--tool-call-parser', 'qwen3_xml',
        '--enable-auto-tool-choice']
    stopped = False
    try:
        run(['docker', 'stop', '-t', '30', container], timeout=45)
        stopped = True
        emit('starting', gpu_memory_utilization=.9)
        run(args, env=env, timeout=120)
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen('http://127.0.0.1:8101/v1/models', timeout=5) as r:
                    if any(m['id'] == MODEL for m in json.load(r)['data']):
                        break
            except Exception:
                pass
            time.sleep(5)
        else:
            raise RuntimeError('Replacement model did not become healthy')
        body = {'model': MODEL, 'messages': [{'role': 'user', 'content': 'Call report_status with status ready.'}],
                'tools': [{'type': 'function', 'function': {'name': 'report_status',
                'parameters': {'type': 'object', 'properties': {'status': {'type': 'string'}}, 'required': ['status']}}}],
                'tool_choice': 'auto', 'max_tokens': 256, 'chat_template_kwargs': {'enable_thinking': False}}
        req = urllib.request.Request('http://127.0.0.1:8101/v1/chat/completions',
              data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=120) as r:
            calls = json.load(r)['choices'][0]['message'].get('tool_calls', [])
        assert any(c['function']['name'] == 'report_status' and
                   json.loads(c['function']['arguments']).get('status') == 'ready' for c in calls), 'Tool-call validation failed'
        emit('ready', model=MODEL, container=name, rollback_container=container, gpu_memory_utilization=.9)
    except BaseException:
        if stopped:
            subprocess.run(['docker', 'stop', '-t', '10', name], capture_output=True, timeout=30)
            run(['docker', 'start', container], timeout=60)
            emit('rolled_back', container=container)
        raise


if __name__ == '__main__':
    try:
        main(json.load(sys.stdin))
    except Exception as exc:
        # Docker output may contain credentials; only emit the exception class.
        emit('failed', error=type(exc).__name__, message='Management failed; original model retained or restored. Inspect the container locally for details.')
        sys.exit(1)
