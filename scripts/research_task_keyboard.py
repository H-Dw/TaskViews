"""Build an isolated task keyboard bundle without starting an actor or a VM."""
import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from kobe_views.keyboard_research import research  # noqa: E402
from ui_kobe.api.keyboard_research import settings  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    task = parser.add_mutually_exclusive_group(required=True)
    task.add_argument('--task-json', type=Path)
    task.add_argument('--prompt-file', type=Path)
    parser.add_argument('--related-app', action='append', default=[])
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path, help='Fresh task-local directory, never shared tools/keyboard')
    args = parser.parse_args()
    value = (json.loads(args.task_json.read_text(encoding='utf-8')) if args.task_json else
             {'instruction': args.prompt_file.read_text(encoding='utf-8'), 'related_apps': args.related_app})
    config = settings({}, json.loads(args.config.read_text(encoding='utf-8')))
    reference = research(value, args.output, config)
    print(json.dumps(reference, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
