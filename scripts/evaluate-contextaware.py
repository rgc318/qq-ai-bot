"""Reproducible, network-disabled ContextAware evaluation, never a deployment.

Run from Windows with WSL Docker. Only source code is mounted read-only. The
temporary container has no production volume, env_file, secret or QQ login.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT/'integrations/contextaware/source-lock.json').read_text())
SOURCE = ROOT/'downloads/contextaware-f026c56'
OMNI = ROOT/'downloads/omnidraw-3.3.23-main.py'


def wsl_path(path):
    value = str(path.resolve()).replace('\\', '/')
    if len(value) < 3 or value[1] != ':':
        raise ValueError('Use an absolute Windows workspace path')
    return '/mnt/'+value[0].lower()+value[2:]


def command(*args, **kwargs):
    return subprocess.run(['wsl', '-d', 'Ubuntu', '--exec', 'docker', *args],
                          text=True, encoding='utf-8', errors='replace', capture_output=True, check=True, **kwargs)


def prepare_source(download=False):
    SOURCE.mkdir(parents=True, exist_ok=True)
    for name, entry in LOCK['files'].items():
        path = SOURCE/name
        valid = path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256']
        if not valid and download:
            url = 'https://raw.githubusercontent.com/muyouzhi6/astrbot_plugin_context_aware/'+LOCK['commit']+'/'+name
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read(entry['size']+2)
            # Normalize connector/checkout line endings, but nothing else.
            data = data.replace(b'\r\n', b'\n')
            if hashlib.sha256(data).hexdigest() != entry['sha256']:
                raise ValueError('Pinned upstream source mismatch: '+name)
            path.write_bytes(data)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('Missing/changed source '+name+'; run --download-source')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download-source', action='store_true')
    parser.add_argument('--inspect-core', action='store_true', help='Read native source signatures only')
    parser.add_argument('--models', action='store_true', help='Synthetic real-model selection tests; at most 40 text/vision requests, no real images or image API')
    parser.add_argument('--max-model-requests', type=int, default=40)
    args = parser.parse_args()
    prepare_source(args.download_source)
    image = command('inspect', 'qq-ai-bot-astrbot-1', '--format', '{{.Image}}', timeout=20).stdout.strip()
    if not OMNI.is_file():
        command('cp', 'qq-ai-bot-astrbot-1:/AstrBot/data/plugins/astrbot_plugin_omnidraw/main.py', wsl_path(OMNI), timeout=30)
    container_name = 'qq-contextaware-eval-'+uuid4().hex[:12]
    docker_args = ['run', '--rm', '--name', container_name, '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                   '--security-opt', 'no-new-privileges', '--memory', '768m', '--pids-limit', '128',
                   '--tmpfs', '/tmp:rw,size=128m', '--tmpfs', '/AstrBot/data:rw,size=128m',
                   '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'TZ=Asia/Shanghai']
    for source, target in [(ROOT/'integrations', '/workspace/integrations'),
                           (ROOT/'extensions', '/workspace/extensions'),
                           (ROOT/'scripts/evaluate-contextaware-native.py', '/workspace/evaluate.py'),
                           (SOURCE, '/candidate'), (OMNI, '/omnidraw.py')]:
        docker_args.extend(['--mount', 'type=bind,src='+wsl_path(source)+',dst='+target+',readonly'])
    docker_args.extend(['--entrypoint', 'python', image])
    if args.inspect_core:
        docker_args.extend(['-c', "import inspect;from astrbot.core.provider.func_tool_manager import _PermissionGuardedTool;print(inspect.getsource(_PermissionGuardedTool))"])
    elif args.models:
        docker_args.insert(1, '-i')
        docker_args.extend(['/workspace/evaluate.py', '--models'])
        if not 1 <= args.max_model_requests <= 40:
            raise ValueError('Model request limit must be between 1 and 40')
        return run_models(docker_args, image, args.max_model_requests, container_name)
    else:
        docker_args.append('/workspace/evaluate.py')
    try:
        result = command(*docker_args, timeout=180)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        command('rm', '-f', container_name, timeout=20)
        raise
    if args.inspect_core:
        print(result.stdout)
        return
    marker = 'CA_EVALUATION_REPORT='
    payload = next(line[len(marker):] for line in result.stdout.splitlines() if line.startswith(marker))
    report = json.loads(payload)
    report['runtime_image'] = image
    report['candidate_commit'] = LOCK['commit']
    report['omnidraw_source_sha256'] = hashlib.sha256(OMNI.read_bytes()).hexdigest()
    (ROOT/'logs').mkdir(exist_ok=True)
    (ROOT/'logs/contextaware-isolated-evaluation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report['passed']:
        sys.exit(1)


def run_models(docker_args, image, limit, container_name):
    from deployment_api import DeploymentAPI, write_report
    api = DeploymentAPI()
    routes = {
        'DeepSeek1017': ('siliconflow/deepseek-ai/DeepSeek-V4.1-Flash-1017', {'enable_thinking': False}),
        'Sol-low': ('cliproxyapi/gpt-6.1-sol', {'reasoning_effort': 'low', 'allowed_openai_params': ['reasoning_effort']}),
    }
    process = subprocess.Popen(['wsl', '-d', 'Ubuntu', '--exec', 'docker', *docker_args],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace', bufsize=1)
    requests = []
    report = None
    try:
        for line in process.stdout:
            if line.startswith('CA_MODEL_REQUEST='):
                request = json.loads(line.split('=', 1)[1])
                if len(requests) >= limit:
                    raise RuntimeError('Synthetic model request budget exhausted')
                model, options = routes[request['route']]
                started = time.perf_counter()
                answer = {'error': 'not_started'}
                try:
                    response = api.model('/chat/completions', {
                        'model': model, 'messages': request['messages'], 'tools': request['tools'],
                        'tool_choice': 'auto', 'max_tokens': 4096, **options,
                    }, timeout=100)
                    answer = {'message': response['choices'][0]['message']}
                except Exception as exc:
                    # Never persist prompt, pixels, model text or exception bodies.
                    answer = {'error': type(exc).__name__}
                item = {'route': request['route'], 'case': request['case'],
                        'seconds': round(time.perf_counter()-started, 3),
                        'tools': [c.get('function', {}).get('name') for c in answer.get('message', {}).get('tool_calls', [])],
                        'error_type': answer.get('error')}
                requests.append(item)
                print(json.dumps(item, ensure_ascii=False), flush=True)
                process.stdin.write(json.dumps(answer, ensure_ascii=False)+'\n')
                process.stdin.flush()
            elif line.startswith('CA_MODEL_REPORT='):
                report = json.loads(line.split('=', 1)[1])
            # All other native logs are synthetic; keep normal output compact.
        if process.wait(timeout=20) != 0 or report is None:
            raise RuntimeError('Isolated model test process failed')
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=20)
            # Only remove the uniquely named temporary container created above.
            command('rm', '-f', container_name, timeout=20)
    report.update(requests=requests, model_api_calls=len(requests), runtime_image=image,
                  candidate_commit=LOCK['commit'], real_history_replayed=False,
                  image_generations=0, qq_messages_sent=0, production_writes=0)
    write_report('contextaware-model-evaluation.json', report)
    write_report('contextaware-model-evaluation-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if not report['passed']:
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print((exc.stdout or '')[-12000:], file=sys.stderr)
        print((exc.stderr or '')[-6000:], file=sys.stderr)
        raise SystemExit(exc.returncode)
