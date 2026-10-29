"""Run the actual three-check provider probe under a 128MiB offline scope."""
import json
import os
from pathlib import Path
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import probe_native_provider as probe  # noqa: E402
from ui_kobe.api import sx_native as sx  # noqa: E402


def main():
    output, effort = Path(sys.argv[1]), sys.argv[2]
    os.environ.update(SX_URL_SB='https://fixture.invalid/v1', SX_URL='https://fixture.invalid/v1',
                      SX_QWEN_API_KEY='fixture-not-a-key')
    calls = []

    def handler(request):
        number = len(calls) + 1
        has_image = b'"image_url"' in request.content
        calls.append({'request': number, 'bytes': len(request.content), 'has_image': has_image})
        assert has_image == (number == 2)
        assert len(request.content) > 2_000_000 if number == 2 else len(request.content) < 20_000
        if number == 3:
            body = json.loads(request.content)
            assert body['messages'][2]['tool_call_id'] == 'original-tool-id'
            assert body['messages'][1]['tool_calls'][0]['id'] == 'original-tool-id'
            assert body['tool_choice'] == 'none'
        message = {'role': 'assistant', 'reasoning_content': 'fixture', 'content': 'OK.'}
        finish = 'stop'
        if number == 2:
            message.update(content=None, tool_calls=[{'index': 0, 'id': 'original-tool-id',
                'type': 'function', 'function': {'name': 'computer_use',
                'arguments': json.dumps({'action': 'mouse_move', 'coordinate': [208, 278]})}}])
            finish = 'tool_calls'
        common = {'id': f'fixture-response-{number}', 'model': 'qwen3.8-max', 'created': 100}
        chunk = {**common, 'choices': [{'index': 0, 'delta': message, 'finish_reason': None}]}
        done = {**common, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}
        data = 'data: ' + json.dumps(chunk) + '\n\ndata: ' + json.dumps(done) + '\n\ndata: [DONE]\n\n'
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=data.encode())

    original = sx.SXNativeClient

    class FixtureClient(original):
        def __init__(self, **kwargs):
            super().__init__(**kwargs, client=httpx.Client(transport=httpx.MockTransport(handler)))

    sx.SXNativeClient = FixtureClient
    sys.argv = ['probe_native_provider.py', '--provider', 'sx', '--sx-url-env', 'SX_URL_SB',
                '--coordinate-type', 'relative', '--experiment', f'sx-mini-max-{effort}40',
                '--output', str(output)]
    result = probe.main()
    group = Path('/sys/fs/cgroup') / Path(Path('/proc/self/cgroup').read_text().strip().split('::', 1)[1]).relative_to('/')
    memory = {name: int((group / name).read_text()) for name in ('memory.peak', 'memory.max', 'memory.swap.max')}
    evidence = {'passed': result == 0 and len(calls) == 3, 'live_api_called': False,
                'vm_started': False, 'calls': calls, 'memory': memory, 'reasoning': effort}
    (output / 'memory-validation.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence))
    return result


if __name__ == '__main__':
    raise SystemExit(main())
