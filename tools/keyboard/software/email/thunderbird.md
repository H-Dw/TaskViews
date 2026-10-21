# Thunderbird

目录 ID：`app.thunderbird`。类型：`email`。平台：`linux / windows`。

状态：任务名匹配或显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Thunderbird。

任务说明中的匹配别名：`Mozilla Thunderbird`、`Thunderbird`、`雷鸟邮件`。匹配规则与平台过滤见 [使用说明](../../README.md)。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.thunderbird.messages

适用范围：Thunderbird message list, not compose body。

同调用查询格式：`<key_lookup>app.thunderbird.messages</key_lookup>`。

```json
[
  {"intent": "new draft", "tool": {"action":"key","keys":["ctrl","n"]}},
  {"intent": "reply to sender", "tool": {"action":"key","keys":["ctrl","r"]}},
  {"intent": "reply to all", "tool": {"action":"key","keys":["ctrl","shift","r"]}},
  {"intent": "archive selected message", "tool": {"action":"key","keys":["a"]}}
]
```

结果检查：Draft/reply actions do not send mail. Check recipient and body before any separately authorized send action.

官方来源：[Thunderbird keyboard shortcuts](https://support.mozilla.org/en-US/kb/keyboard-shortcuts-thunderbird)。
