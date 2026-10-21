# PyCharm (Windows/Linux keymap)

目录 ID：`app.pycharm`。类型：`text_editor`。平台：`linux / windows`。

状态：任务名匹配或显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：PyCharm。

任务说明中的匹配别名：`JetBrains PyCharm`、`PyCharm`。匹配规则与平台过滤见 [使用说明](../../README.md)。

只适用于明确选用的 Windows/Linux 默认 keymap；双击 Shift 是连续事件，未编码成组合键。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.pycharm.navigation

适用范围：PyCharm Windows/Linux keymap。

同调用查询格式：`<key_lookup>app.pycharm.navigation</key_lookup>`。

```json
[
  {"intent": "find action", "tool": {"action":"key","keys":["ctrl","shift","a"]}},
  {"intent": "recent files", "tool": {"action":"key","keys":["ctrl","e"]}},
  {"intent": "go to file", "tool": {"action":"key","keys":["ctrl","shift","n"]}},
  {"intent": "go to line", "tool": {"action":"key","keys":["ctrl","g"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[PyCharm Windows/Linux keymap card](https://resources.jetbrains.com/storage/products/pycharm/docs/PyCharm_ReferenceCard.pdf)。
