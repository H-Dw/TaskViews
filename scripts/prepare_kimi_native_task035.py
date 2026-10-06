"""Offline validation and bounded real-frame SSE preflight; never starts a VM."""
from pathlib import Path
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
OFFICIAL = Path.home() / 'osworld2/OSWorld-V2'
OLD = PROJECT / 'docs/experiments/osworld21-kimi-k3-task035-compare-20261003-223838'
sys.path[:0] = [str(PROJECT), str(OFFICIAL)]


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_hashes():
    names = ['ui_kobe/api/kimi_stream.py', 'ui_kobe/osworld/kimi_native.py',
             'scripts/run_official_qwen_task035.py', 'scripts/osworld_task035_background.py',
             'ui_kobe/api/kimi.py', 'ui_kobe/osworld/qwen_judge.py', 'ui_kobe/osworld/local_web.py',
             'ui_kobe/osworld/telemetry.py']
    return {name: digest(PROJECT / name) for name in names}


def tests(output):
    # Keep pytest in the test environment; use the official environment's
    # runtime dependencies first, without installing or modifying either one.
    commands, statuses = [], []
    for name in ('test_kimi_stream.py', 'test_kimi_api.py', 'test_osworld_pipeline.py'):
        command = [sys.executable, str(Path(__file__)), 'pytest', '--output', str(output), '--test-file', name]
        with (output / (name + '.log')).open('w') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, cwd=PROJECT)
        commands.append(command)
        statuses.append(result.returncode)
    from ui_kobe.osworld.runner import source_snapshot
    snapshot = source_snapshot(OFFICIAL)
    write(output / 'osworld-source-before.json', snapshot)
    write(output / 'validation.json', {'time_utc': datetime.now(timezone.utc).isoformat(),
        'exit_code': 0 if all(x == 0 for x in statuses) else 1, 'statuses': statuses, 'commands': commands, 'code_hashes': code_hashes(),
        'official_source_files': len(snapshot), 'memory_max': 128 * 1024**2, 'memory_swap_max': 0})
    print(json.dumps({'tests_exit_codes': statuses, 'output': str(output)}), flush=True)
    return 0 if all(x == 0 for x in statuses) else 1


def original_request(suffix, step):
    root = OLD / (OLD.name + '-' + suffix)
    for path in sorted((root / 'telemetry').glob('events-*.jsonl')):
        with path.open() as file:
            for number, line in enumerate(file, 1):
                event = json.loads(line)
                if event.get('event') == 'api_request' and event.get('step') == step and event.get('phase') == 'perception':
                    return event['payload'], root / 'telemetry', {'file': str(path), 'line': number,
                        'event_sha256': hashlib.sha256(line.encode()).hexdigest(), 'request_id': event.get('request_id')}
    raise ValueError(f'Original perception request not found: {suffix} step {step}')


def rehydrate(value, root, images):
    if isinstance(value, dict) and 'image' in value and 'sha256' in value:
        path = (root / value['image']).resolve()
        if not path.is_relative_to(root.resolve()) or digest(path) != value['sha256']:
            raise ValueError('Saved image path/hash mismatch')
        from PIL import Image
        with Image.open(path) as image:
            size = list(image.size)
        images.append({'sha256': value['sha256'], 'bytes': path.stat().st_size, 'size': size})
        return 'data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode()
    if isinstance(value, dict):
        return {k: rehydrate(v, root, images) for k, v in value.items()}
    if isinstance(value, list):
        return [rehydrate(v, root, images) for v in value]
    return value


def replay(output):
    from ui_kobe.api.kimi_stream import KimiStreamClient, StreamBudget
    from ui_kobe.osworld import telemetry
    from ui_kobe.osworld.actions import json_object
    from ui_kobe.osworld.runner import source_snapshot
    telemetry._root = output
    cases = [('taskviews-r01', 1), ('taskviews-r01-api03', 2), ('taskviews-r01', 3)]
    results = []
    for suffix, step in cases:
        case = {'suffix': suffix, 'step': step}
        payload, root, original = original_request(suffix, step)
        images = []
        request = rehydrate(payload, root, images)
        case.update(original=original, images=images, original_payload_sha256=hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest())
        client = KimiStreamClient(budget=StreamBudget(attempts=1), emit=telemetry.emit,
                                 stream_dir=output / 'streams')
        telemetry.set_context(step, 'replay_' + suffix)
        print(json.dumps({'starting': suffix, 'step': step, 'images': images}), flush=True)
        try:
            response = client.create(**request)
            data = response.model_dump()
            parsed = json_object(data['choices'][0]['message']['content'])
            if not isinstance(parsed.get('summary'), str) or not isinstance(parsed.get('elements'), list):
                raise ValueError('Perception output has invalid structure')
            case.update(passed=True, model=data['model'], finish_reason=data['choices'][0]['finish_reason'],
                        usage=data['usage'], json_keys=list(parsed))
            write(output / f'{suffix}-step{step}-response.json', data)
        except Exception as exc:
            case.update(passed=False, error_type=type(exc).__name__, error=telemetry.safe(str(exc))[:1000])
        case['timing'] = client.last_timing
        results.append(case)
        write(output / 'replay.json', {'cases': results, 'passed': len(results) == 3 and all(x['passed'] for x in results),
            'code_hashes': code_hashes(), 'official_source_unchanged': source_snapshot(OFFICIAL) == json.loads(
                (output / 'osworld-source-before.json').read_text())})
        print(json.dumps(case, ensure_ascii=False), flush=True)
        if not case['passed']:
            return 1
    return 0


def native_probe(output):
    from ui_kobe.api.kimi_stream import KimiStreamClient, StreamBudget
    from ui_kobe.osworld.kimi_native import SYSTEM, native_schema, validate_native
    from ui_kobe.osworld import telemetry
    payload, root, original = original_request('taskviews-r01', 1)
    images = []
    restored = rehydrate(payload, root, images)
    instruction = None
    for path in root.glob('events-*.jsonl'):
        for line in path.open():
            event = json.loads(line)
            if event.get('event') == 'observation' and event.get('step') == 1:
                instruction = event['instruction']
                break
        if instruction:
            break
    if not instruction:
        raise ValueError('Original task instruction is missing')
    image_parts = [part for message in restored['messages'] if isinstance(message.get('content'), list)
                   for part in message['content'] if part.get('type') == 'image_url']
    messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': [
        {'type': 'text', 'text': 'Original task: ' + instruction + '\nCurrent screenshot; choose one GUI tool action.'},
        *image_parts]}]
    telemetry._root = output
    telemetry.set_context(0, 'native_tool_probe')
    client = KimiStreamClient(budget=StreamBudget(attempts=1), emit=telemetry.emit, stream_dir=output / 'streams')
    response = client.create(model='kimi-k3', messages=messages, tools=[native_schema()], tool_choice='required',
                             reasoning_effort='max', max_completion_tokens=16000)
    arguments, batch = validate_native(response)
    write(output / 'native-probe-response.json', response.model_dump())
    result = {'passed': True, 'gui_executed': False, 'source': original, 'images': images,
              'timing': client.last_timing, 'usage': response.model_dump()['usage'], 'native_arguments': arguments,
              'compiled_commands': batch.commands, 'code_hashes': code_hashes()}
    write(output / 'native-probe.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['validate', 'pytest', 'replay', 'native-probe'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--test-file')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.action == 'pytest':
        sys.path.append(str(Path.home() / '.local/share/ui-kobe-glm/venv/lib/python3.12/site-packages'))
        import pytest
        raise SystemExit(pytest.main(['-q', 'tests/' + args.test_file]))
    raise SystemExit({'validate': tests, 'replay': replay, 'native-probe': native_probe}[args.action](args.output))
