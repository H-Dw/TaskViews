"""Four independent Task059 episodes, high UI/Mini followed by xhigh UI/Mini."""
from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts.osworld_native_experiment import digest, load, require_scope  # noqa: E402
from scripts.task059_low50_pipeline import advance as advance_pair, record  # noqa: E402


def advance(root):
    root = Path(root).resolve()
    cfg, state = load(root / 'pipeline.json'), load(root / 'state.json')
    if digest(root / 'pipeline.json') != state['config_sha256']:
        raise RuntimeError('Reasoning matrix configuration changed')
    if (cfg.get('version') != 'qwen-task059-reasoning-matrix-v1' or cfg.get('order') != ['high', 'xhigh']
            or cfg.get('max_steps') != 50 or cfg.get('evaluation_steps') != [15, 30, 50]):
        raise ValueError('Not the authorized high/xhigh Task059 matrix')
    if state.get('phase') == 'complete' or state.get('formal_actor_resume_authorized') is False:
        return state
    for effort in cfg['order']:
        pair = Path(cfg['pairs'][effort]).resolve()
        if not pair.is_relative_to(root):
            raise ValueError('Serial pair escaped its matrix')
        pair_cfg, pair_state = load(pair / 'pipeline.json'), load(pair / 'state.json')
        if (digest(pair / 'pipeline.json') != pair_state['config_sha256']
                or pair_cfg.get('generation_profile') != f'qwen-sse-{effort}-total16k'):
            raise RuntimeError('Serial pair profile or configuration changed')
        try:
            current = advance_pair(pair)
        except RuntimeError as exc:
            if not str(exc).startswith('Windows startup reserve excluding experiment memory is below '):
                raise
            record(root, state, phase=effort + '_waiting_startup_resources', current_effort=effort,
                   current_pair=str(pair), current_arm=load(pair / 'state.json').get('current_arm'),
                   waiting_reason=str(exc))
            return state
        if current['phase'] != 'complete':
            record(root, state, phase=effort + '_' + current['phase'], current_effort=effort,
                   current_pair=str(pair), current_arm=current.get('current_arm'), pair_state=current)
            return state
        record(root, state, **{effort + '_completed': {'state': str(pair / 'state.json'),
            'state_sha256': digest(pair / 'state.json'), 'results': {arm: current[arm + '_completed']
                for arm in ('ui_kobe_like', 'taskviews')}}})
    record(root, state, phase='complete', current_effort=None, current_pair=None, current_arm=None,
           no_remaining_owned_vm=True)
    return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['advance'])
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    require_scope(128 * 1024**2)
    root = args.root.resolve()
    with (root / '.dispatch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = advance(root)
    print(json.dumps({k: state.get(k) for k in ('phase', 'current_effort', 'current_pair', 'current_arm')}))


if __name__ == '__main__':
    main()
