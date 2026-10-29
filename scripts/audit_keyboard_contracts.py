"""Read-only keyword/card inventory; no provider, guest, or benchmark input."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from kobe_views import keyboard_guidance as guidance  # noqa: E402
from kobe_views.guidance_semantics import PATTERNS  # noqa: E402
from kobe_views.guidance_eligibility import catalog_operation  # noqa: E402
from kobe_views.keyboard_view import DATA  # noqa: E402


def inventory():
    cards, references = [], []
    for name, entry in sorted(guidance.LIBRARY['guides'].items()):
        assert entry['source'] in guidance.LIBRARY['sources']
        assert all(op in PATTERNS for op in entry['operations'])
        cards.append({'id': name, **entry, 'keys': {
            b: guidance.LIBRARY['bindings'][b] for b in entry['bindings']}})
    for directory, toolset in sorted(DATA['toolsets'].items()):
        runtime = not toolset['reference_only'] and DATA['runtime_platform'] in toolset['platforms']
        for topic, entry in sorted(toolset['topics'].items()):
            assert set(entry['sources']) <= DATA['sources'].keys()
            recipes = []
            for recipe in entry['recipes']:
                op = catalog_operation(recipe)
                recipes.append({**recipe, 'operation': op, 'status': (
                    'reference_only_platform' if not runtime else
                    'conditional_contract' if op else 'no_audited_operation_contract')})
            references.append({'id': topic if directory == 'general' else directory + '.' + topic,
                'directory': directory, 'scope': entry['scope'], 'check': entry['check'],
                'sources': entry['sources'], 'runtime_platform_eligible': runtime, 'recipes': recipes})
    counts = {status: sum(r['status'] == status for e in references for r in e['recipes'])
              for status in ('reference_only_platform', 'conditional_contract', 'no_audited_operation_contract')}
    return {'policy_version': guidance.VERSION, 'keywords': PATTERNS, 'cards': cards, 'references': references,
            'summary': {'cards': len(cards), 'topics': len(references), 'bindings': sum(counts.values()), **counts},
            'meaning': 'Contract coverage, not empirical GUI validity or model adoption',
            'source_sha256': {name: hashlib.sha256((PROJECT / name).read_bytes()).hexdigest() for name in (
                'kobe_views/guidance_semantics.py', 'kobe_views/guidance_eligibility.py',
                'kobe_views/keyboard_guidance.py', 'kobe_views/key_tools/guidance.json',
                'kobe_views/key_tools/catalog.json')}}


def render(data):
    def safe(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    lines = ['# Keyboard 逐项契约核验（2026-10-28）', '',
        '本表核对动作词、对象、操作卡、绑定和适用条件。快捷键来源沿用冻结目录；本轮没有重新访问所有官方网页，'
        '也没有启动 guest 逐键实测，因此不将“映射通过”写成“实际软件均可执行”。', '',
        '新的 capability_guidance_v7 不是历史 Mini v7。task_capabilities 路径先过滤、再排序；'
        '旧 task_names/manual 及历史冻结源码保留原行为。不能拿新代码静默恢复旧 checkpoint。', '',
        '核验范围：`' + json.dumps(data['summary'], ensure_ascii=False) + '`。', '',
        '## 检查顺序', '',
        '1. 从公开任务冻结能力及依赖；公开运行意图只能在该集合内选择，不能自行扩容。',
        '2. 区分动作、状态、否定、假设、字面字符串和对象类型；显式 then/然后及目的从句不作为当前步骤。',
        '3. 使用最新公开意图；过时意图进入排除审计。未明确当前阶段的跨类复合任务标为 current_phase_unspecified。',
        '4. 检查启用目录、动作契约、软件目标、相反对象和已有执行阶段；lookup 走相同检查。',
        '5. 仅对合格候选按相关性和稳定 ID 排序；当前包仍最多 3000 UTF-8 bytes，完整卡原子打包。', '',
        '软件名称只是条件线索，不是焦点证明。不能用任务中出现过 GIMP/VLC 或启用了目录，推断当前窗口。'
        '未知软件时优先无按键的可见控件指导；缺少契约则记录具体缺口，不发送猜测绑定。', '',
        '## 本次发现与修正', '',
        '| 问题 | 修正 |', '|---|---|',
        '| 能力未冻结只记日志仍选卡 | capability_not_frozen 阻断对应候选，依赖按冻结集合检查 |',
        '| open/find 对象不分 | 窗口、目录、网页、文件搜索分卡；不套用 Ctrl+O/Ctrl+F |',
        '| confirm details/that 被当作 Enter | 判作结果检查，不匹配确认键 |',
        '| 启用软件目录就选应用键 | 必须存在本次公开文本的软件目标，仍需当前图确认 |',
        '| lookup 分数高可越过阶段 | 使用同一准入契约；已输入/已确认阶段排除重新输入 |',
        '| 旧意图、未来步骤竞争 | 最新意图与显式当前步骤先筛选；其余记排除原因 |',
        '| 混合主题全部返回 | 按明确动作提取已审查的绑定；不是截取前 N 条 |',
        '| 新类型打断 Attempts 导航复用 | 导航索引和阅读调整链同步识别窗口/目录/网页/文件搜索类型 |', '',
        '## 完整操作卡逐项对照', '',
        'operations 是语义动作，不是只要字面出现就触发。绑定中 Enter/粘贴可以是后续依赖；'
        '不能据此反过来把所有 Enter 或粘贴需求匹配到整个工作流。', '',
        '| 卡 ID | 动作契约 | 精确绑定 | 范围／条件 | 完整指导 |', '|---|---|---|---|---|']
    for card in data['cards']:
        bindings = '; '.join(k + '=' + '+'.join(v['keys']) for k, v in card['keys'].items()) or '无固定按键'
        lines.append('| ' + ' | '.join(safe(v) for v in (card['id'], ', '.join(card['operations']) or '无匹配回退',
            bindings, card['scope'], card['steps'])) + ' |')
    lines += ['', '## 原目录逐主题、逐绑定对照', '',
        '“待契约”表示目录内容仍保留，但在新版能力路径中不接受仅凭 lookup 注入该绑定；'
        '这是一项明确的覆盖限制，需补充独立语义测试后才能放行。历史目录模式不受此门禁影响。'
        '“已映射”也仍受冻结能力、平台、软件对象、最新动作及当前阶段约束。', '',
        '| Topic | 每条 intent → 语义动作／状态 | 适用范围 | 检查方式 |', '|---|---|---|---|']
    for entry in data['references']:
        recipes = '; '.join(r['intent'] + ' [' + '+'.join(r['tool']['keys']) + '] → ' +
            ('仅平台参考' if r['status'] == 'reference_only_platform' else r['operation'] or '待契约') for r in entry['recipes'])
        lines.append('| ' + ' | '.join(safe(v) for v in (entry['id'], recipes, entry['scope'], entry['check'])) + ' |')
    lines += ['', '## 语义触发规则', '', '| 动作 | 有边界的规则（还需通过状态／对象／阶段排除） |', '|---|---|']
    lines += ['| ' + name + ' | `' + safe(pattern) + '` |' for name, pattern in sorted(data['keywords'].items())]
    lines += ['', '## 验证与限制', '',
        '独立通用例子见 tests/test_guidance_eligibility_v7.py：每张卡的正例、否定／状态／同词不同对象反例、'
        '冻结能力缺失、lookup 绕过、菜单目的从句、阶段冲突和目录重排。真实 actor 请求模拟另验证预算、来源、'
        '恢复及 flat/linked 同输入一致性；没有新增模型调用、GUI 重跑或成功率结论。', '',
        '语义仍是确定性有界规则，不是完备自然语言理解；不能保证所有新表达都已覆盖。未知情况保留本地排除原因。'
        '完整 URL、规则、排除列表和哈希留本地，模型只收到短完整卡及必要缺口。', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--markdown', type=Path, required=True)
    args = parser.parse_args()
    data = inventory()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    args.markdown.write_text(render(data), encoding='utf-8')
    print(json.dumps(data['summary']))


if __name__ == '__main__':
    main()
