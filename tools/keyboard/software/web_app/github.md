# GitHub

目录 ID：`app.github`。类型：`web_app`。平台：`linux / windows`。

状态：任务名匹配或显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：GitHub。

任务说明中的匹配别名：`GitHub`。匹配规则与平台过滤见 [使用说明](../../README.md)。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.github.repository

适用范围：GitHub repository outside editable fields; shortcuts enabled。

同调用查询格式：`<key_lookup>app.github.repository</key_lookup>`。

```json
[
  {"intent": "show keyboard help", "tool": {"action":"key","keys":["shift","/"]}},
  {"intent": "file finder", "tool": {"action":"key","keys":["t"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GitHub keyboard shortcuts](https://docs.github.com/en/get-started/accessibility/keyboard-shortcuts)。
