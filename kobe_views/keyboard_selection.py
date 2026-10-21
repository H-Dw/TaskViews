"""Resolve keyboard directories once from public task fields before freezing."""
import hashlib
import re
import unicodedata

from .keyboard_view import DATA, TOOLSETS, normalize_toolsets, policy
from .model import dumps

VERSION = 'mini_keyboard_task_names_v1'
MODES = ('task_names', 'manual')


def normalized_name(text):
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def task_fields(task):
    """Never inspect setup commands, evaluator data, observations or model prose."""
    if not isinstance(task, dict):
        raise ValueError('Keyboard selection requires a public task mapping')
    instruction = task.get('instruction', '')
    apps = task.get('related_apps', [])
    if (not isinstance(instruction, str) or not isinstance(apps, (list, tuple))
            or any(not isinstance(app, str) for app in apps)):
        raise ValueError('Keyboard task instruction/apps have invalid types')
    return {'instruction': instruction, 'related_apps': list(apps)}


def resolve_task_toolsets(task, *, mode='task_names', requested=()):
    """A name match enables references, never identifies the focused application."""
    if mode not in MODES:
        raise ValueError('Unknown keyboard selection mode')
    manual = normalize_toolsets(requested)
    fields = task_fields(task)
    text = normalized_name(fields['instruction'])
    apps = {normalized_name(app) for app in fields['related_apps']}
    enabled, matches, skipped = set(manual), [], []
    if mode == 'task_names':
        for key, aliases in sorted(DATA['task_aliases'].items()):
            entry = TOOLSETS[key]
            candidates = [*aliases, key]
            if key.startswith('app.'):
                candidates.append(key.removeprefix('app.'))
            match = next((alias for alias in candidates if normalized_name(alias) in apps), None)
            source = 'related_apps'
            if match is None:
                source = 'instruction'
                # ASCII word guards allow "用VLC播放" but reject "my_vlc_player".
                match = next((alias for alias in aliases if re.search(
                    r'(?<![a-z0-9_])' + re.escape(normalized_name(alias)) + r'(?![a-z0-9_])', text)), None)
            if match is None:
                continue
            evidence = {'toolset': key, 'source': source, 'alias': match}
            if entry['reference_only'] or not entry['topics'] or DATA['runtime_platform'] not in entry['platforms']:
                skipped.append({**evidence, 'reason': 'unavailable_on_runtime_platform'})
                continue
            enabled.add(key)
            matches.append(evidence)
    return {'version': VERSION, 'mode': mode,
            'task_input_sha256': hashlib.sha256(dumps(fields).encode()).hexdigest(),
            'requested_toolsets': list(manual), 'matches': matches, 'skipped': skipped,
            'enabled_toolsets': ['general', *normalize_toolsets(sorted(enabled))]}


def task_keyboard_policy(task, *, mode='task_names', requested=()):
    selection = resolve_task_toolsets(task, mode=mode, requested=requested)
    return {'mini_keyboard_tools': policy(selection['enabled_toolsets'][1:]),
            'mini_keyboard_selection': selection}


def validate_task_keyboard(plan, task):
    """Recompute frozen choices; a changed task, alias table or manual list fails."""
    selection = plan.get('mini_keyboard_selection')
    if not isinstance(selection, dict):
        raise ValueError('Missing frozen task keyboard selection')
    expected = task_keyboard_policy(task, mode=selection.get('mode'),
                                    requested=selection.get('requested_toolsets'))
    if any(plan.get(key) != value for key, value in expected.items()):
        raise ValueError('Frozen task keyboard selection differs from task or catalog')


def main():
    """Read-only preview; no experiment, model request or GUI action."""
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instruction', default='')
    parser.add_argument('--related-app', action='append', default=[])
    parser.add_argument('--keyboard-mode', choices=MODES, default='task_names')
    parser.add_argument('--keyboard-toolset', action='append', default=[])
    args = parser.parse_args()
    selection = resolve_task_toolsets({'instruction': args.instruction, 'related_apps': args.related_app},
                                     mode=args.keyboard_mode, requested=args.keyboard_toolset)
    print(json.dumps(selection, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
