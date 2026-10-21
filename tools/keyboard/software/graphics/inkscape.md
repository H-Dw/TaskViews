# Inkscape

目录 ID：`app.inkscape`。类型：`graphics`。平台：`linux / windows`。

状态：任务名匹配或显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Inkscape。

任务说明中的匹配别名：`Inkscape`。匹配规则与平台过滤见 [使用说明](../../README.md)。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.inkscape.objects

适用范围：Inkscape canvas selection。

同调用查询格式：`<key_lookup>app.inkscape.objects</key_lookup>`。

```json
[
  {"intent": "duplicate object", "tool": {"action":"key","keys":["ctrl","d"]}},
  {"intent": "group objects", "tool": {"action":"key","keys":["ctrl","g"]}},
  {"intent": "ungroup objects", "tool": {"action":"key","keys":["ctrl","shift","g"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Inkscape default keymap source](https://gitlab.com/inkscape/inkscape/-/raw/master/share/keys/inkscape.xml)。
