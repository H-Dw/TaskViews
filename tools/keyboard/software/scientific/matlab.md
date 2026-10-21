# MATLAB Editor

目录 ID：`app.matlab`。类型：`scientific`。平台：`linux / windows`。

状态：任务名匹配或显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：MATLAB。

任务说明中的匹配别名：`MATLAB`。匹配规则与平台过滤见 [使用说明](../../README.md)。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.matlab.editor

适用范围：MATLAB Editor, not Command Window or Simulink。

同调用查询格式：`<key_lookup>app.matlab.editor</key_lookup>`。

```json
[
  {"intent": "focus editor", "tool": {"action":"key","keys":["ctrl","shift","0"]}},
  {"intent": "new script", "tool": {"action":"key","keys":["ctrl","n"]}},
  {"intent": "save script", "tool": {"action":"key","keys":["ctrl","s"]}},
  {"intent": "maximize editor", "tool": {"action":"key","keys":["ctrl","shift","m"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[MATLAB Editor keyboard shortcuts](https://www.mathworks.com/help/matlab/matlab_prog/editor-keyboard-shortcuts.html)。
