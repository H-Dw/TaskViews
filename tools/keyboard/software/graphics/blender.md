# Blender

目录 ID：`app.blender`。类型：`graphics`。平台：`linux / windows`。

状态：任务名匹配或显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Blender。

任务说明中的匹配别名：`Blender`。匹配规则与平台过滤见 [使用说明](../../README.md)。

Blender 默认 keymap；Industry Compatible 与插件键位不在本条范围。资料为 4.1，实际版本需核对。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.blender.viewport

适用范围：Blender 3D viewport; pointer over viewport, not text input。

同调用查询格式：`<key_lookup>app.blender.viewport</key_lookup>`。

```json
[
  {"intent": "menu search", "tool": {"action":"key","keys":["f3"]}},
  {"intent": "toggle edit mode", "tool": {"action":"key","keys":["tab"]}},
  {"intent": "toggle sidebar", "tool": {"action":"key","keys":["n"]}},
  {"intent": "toggle toolbar", "tool": {"action":"key","keys":["t"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Blender 4.1 default keymap](https://docs.blender.org/manual/en/4.1/interface/keymap/blender_default.html)。
