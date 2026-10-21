# Microsoft Outlook classic (Windows)

目录 ID：`app.outlook`。类型：`email`。平台：`windows`。

状态：参考资料；当前 Linux/X11 不可启用。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Microsoft Outlook classic。

任务说明中的匹配别名：`Microsoft Outlook`、`Outlook`。匹配规则与平台过滤见 [使用说明](../../README.md)。

新 Outlook/web 与 classic 的默认绑定不同，此处仅 classic。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.outlook.drafts

适用范围：Outlook classic mail view。

同调用查询格式：`<key_lookup>app.outlook.drafts</key_lookup>`。

```json
[
  {"intent": "new mail draft", "tool": {"action":"key","keys":["ctrl","shift","m"]}},
  {"intent": "reply", "tool": {"action":"key","keys":["ctrl","r"]}},
  {"intent": "reply to all", "tool": {"action":"key","keys":["ctrl","shift","r"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Outlook keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/outlook/keyboard-shortcuts-for-outlook)。
