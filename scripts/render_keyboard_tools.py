"""Render reviewable tools documents from the runtime's single catalog source."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from kobe_views.keyboard_view import DATA, TOOLSETS  # noqa: E402


def document_path(key, value):
    if key == 'general':
        return Path('general.md')
    kind, name = key.split('.', 1)
    if kind == 'app':
        return Path('software') / value['category'] / (name + '.md')
    return Path('types' if kind == 'type' else 'platforms') / (name + '.md')


def render_documents():
    result, rows = {}, []
    for key, value in TOOLSETS.items():
        path = document_path(key, value)
        usable = bool(value['topics']) and not value['reference_only'] and DATA['runtime_platform'] in value['platforms']
        aliases = DATA['task_aliases'].get(key, [])
        status = ('默认启用' if key == 'general' else '分类说明；无可启用配方' if not value['topics']
                  else '任务名匹配或显式选择后可检索' if usable and aliases
                  else '显式选择后可检索' if usable else '参考资料；当前 Linux/X11 不可启用')
        researched_on = value.get('researched_on', DATA['researched_on'])
        lines = [f"# {value['title']}", '', f"目录 ID：`{key}`。类型：`{value['category']}`。平台：`{' / '.join(value['platforms'])}`。", '',
                 f'状态：{status}。资料核对日期：{researched_on}；快捷键未在 guest 中逐项实测。', '']
        if value['members']:
            lines += ['已核对的适用对象：' + '、'.join(value['members']) + '。', '']
        if aliases:
            lines += ['任务说明中的匹配别名：' + '、'.join(f'`{alias}`' for alias in aliases)
                      + '。匹配规则与平台过滤见 [使用说明]('
                      + ('../../README.md' if key.startswith('app.') else '../README.md') + ')。', '']
        if value['note']:
            lines += [value['note'], '']
        if key != 'general':
            lines += ['此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。', '']
        if not value['topics']:
            lines += ['本层没有已确认可共享的业务组合键；按当前画面控件操作，或读取具体软件目录。', '']
        for name, entry in value['topics'].items():
            topic = name if key == 'general' else key + '.' + name
            lines += [f'## {topic}', '', '适用范围：' + entry['scope'] + '。', '',
                      '同调用查询格式：`<key_lookup>' + topic + '</key_lookup>`。', '', '```json', '[']
            recipes = ['  {"intent": ' + json.dumps(recipe['intent'], ensure_ascii=False) + ', "tool": '
                      + json.dumps(recipe['tool'], ensure_ascii=False, separators=(',', ':')) + '}'
                      for recipe in entry['recipes']]
            lines += [',\n'.join(recipes), ']', '```', '', '结果检查：' + entry['check'], '', '官方来源：' + '，'.join(
                f"[{DATA['sources'][ref]['title']}]({DATA['sources'][ref]['url']})" for ref in entry['sources']) + '。', '']
        result[path] = '\n'.join(lines)
        recipes = sum(len(entry['recipes']) for entry in value['topics'].values())
        rows.append(f"| `{key}` | [{value['title']}]({path.as_posix()}) | {recipes} | {status} |")
    total = sum(len(entry['recipes']) for value in TOOLSETS.values() for entry in value['topics'].values())
    latest = max(value.get('researched_on', DATA['researched_on']) for value in TOOLSETS.values())
    result[Path('index.md')] = '\n'.join([
        '# 按键 tools 目录', '',
        f"最近目录核对：{latest}；各目录日期见对应文档。{len(TOOLSETS)} 份分类文档，"
        f"{sum(key.startswith('app.') for key in TOOLSETS)} 份软件文档，{total} 条配方（包含不同范围下的重复组合键）。", '',
        '新 Mini 计划默认保留 general，并依据任务说明及 related_apps 匹配可用的软件目录；'
        '未匹配目录仍需显式配置。窗口与焦点继续由当前截图确认。', '',
        '[使用与分类规则](README.md) · [评测集检索与覆盖缺口](survey.md)', '',
        '| 目录 ID | tools 文档 | 配方数 | 当前 Mini 状态 |', '| --- | --- | ---: | --- |', *rows, ''])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Fail if a generated document differs; never writes')
    args = parser.parse_args()
    root = PROJECT / 'tools' / 'keyboard'
    changed = []
    for path, content in render_documents().items():
        target = root / path
        if not target.exists() or target.read_text(encoding='utf-8') != content:
            changed.append(path.as_posix())
            if not args.check:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding='utf-8', newline='\n')
    print(json.dumps({'check': args.check, 'changed': changed}, ensure_ascii=False))
    return int(args.check and bool(changed))


if __name__ == '__main__':
    raise SystemExit(main())
