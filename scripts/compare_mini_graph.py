"""Offline same-input ablation of all three Mini modes; mock actor/GUI only."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New report directory')
    parser.add_argument('--compiler-repo', type=Path, default=Path.home() / 'osworld2/OSWorld-V2')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Keep earlier ablations; select a new output directory')
    sys.path.insert(1, str(args.compiler_repo))
    sys.path.insert(2, str(PROJECT / 'tests'))
    import pytest
    from mini_graph_support import actor_fixture, projection_snapshot
    from kobe_views import mini_graph as graph
    from kobe_views.fixed_views import materialize as legacy_materialize
    from kobe_views.model import dumps
    from ui_kobe.osworld.official_base import verify_official_base
    from scripts.verified_invoice import project_identity, write

    official = verify_official_base(args.compiler_repo)
    identity = project_identity()
    report = {'schema_version': graph.VERSION, 'kind': 'offline_same_input_mini_graph_ablation',
              'live_api_called': False, 'gui_actions': 0, 'vm_started': False, 'benchmark_score': None,
              'official_base': official, 'project_source': identity, 'frames': []}
    args.output.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as temporary, pytest.MonkeyPatch.context() as patch:
        with actor_fixture(patch, Path(temporary), 'legacy') as (actor, obs, transport, predict):
            for step in range(3):
                predict(actor, obs, error='Original controller error' if step == 0 else None)
                index, inputs = projection_snapshot(actor)
                legacy = legacy_materialize(episode_id=index.episode_id, **inputs)
                common = dict(index=index, instruction='Original public task', toolsets=actor.keyboard_toolsets,
                              task_catalog=actor.task_keyboard, **inputs)
                linked = graph.materialize(graph_mode='linked', **common)
                flat = graph.materialize(graph_mode='flat', **common)
                identical = linked is None and flat is None or (
                    linked is not None and flat is not None
                    and {**flat, 'mode': 'linked', 'links': linked['links']} == linked)
                if not identical:
                    raise AssertionError('flat/linked fact selection diverged')
                frame = {'step': step + 1, 'journal_seq': index.cursor, 'flat_linked_same_facts': identical, 'modes': {}}
                for mode, packet in (('legacy', legacy), ('flat', flat), ('linked', linked)):
                    info = {'packet_bytes': len(dumps(packet).encode()) if packet else 0,
                            'packet_omitted': packet is None, 'links': len(packet.get('links', [])) if packet else 0,
                            'omitted_records': {k: v['omitted_records'] for k, v in packet['views'].items()} if packet else {},
                            'sources': len(packet['sources']) if packet else 0}
                    if mode != 'legacy' and packet:
                        info['nodes'] = len(packet['nodes'])
                        info['facts_sha256'] = graph.sha({k: packet[k] for k in ('nodes', 'views', 'sources')})
                    frame['modes'][mode] = info
                    write(args.output / f'frame-{step + 1}-{mode}.json', packet)
                write(args.output / f'frame-{step + 1}-identity-index.json', index.audit())
                report['frames'].append(frame)
            report['mock_actor_requests'] = len(transport.requests)
    report['passed'] = all(f['flat_linked_same_facts'] and all(v['packet_bytes'] <= 3000
        for v in f['modes'].values()) for f in report['frames'])
    report['source_unchanged'] = project_identity() == identity
    report['passed'] = report['passed'] and report['source_unchanged']
    write(args.output / 'report.json', report)
    lines = ['# Mini Graph v1 离线同输入消融', '',
             '三个模式使用同一日志快照、相同候选记录与 3000 UTF-8 bytes 上限。flat 按 linked 成本选择，不回填空余。', '',
             '| 帧 | 模式 | 包字节 | 来源数 | 关系数 | 包省略 |', '|---|---|---:|---:|---:|---|']
    for frame in report['frames']:
        for mode, info in frame['modes'].items():
            lines.append(f"| {frame['step']} | {mode} | {info['packet_bytes']} | {info['sources']} | {info['links']} | {info['packet_omitted']} |")
    lines += ['', f"flat/linked 事实一致：{all(f['flat_linked_same_facts'] for f in report['frames'])}。",
              '字节与遗漏差异是结构开销观测，不能据此推断成功率或 token 收益。',
              '全部操作为离线模拟：无真实 API、GUI、VM 或 benchmark 分数。', '']
    (args.output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('project_source', 'official_base')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
