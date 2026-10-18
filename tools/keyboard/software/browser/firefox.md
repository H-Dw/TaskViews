# Mozilla Firefox

目录 ID：`app.firefox`。类型：`browser`。平台：`linux / windows`。

状态：显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Mozilla Firefox。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.firefox.find

适用范围：Mozilla Firefox page content。

同调用查询格式：`<key_lookup>app.firefox.find</key_lookup>`。

```json
[
  {"intent": "find page text", "tool": {"action":"key","keys":["ctrl","f"]}},
  {"intent": "next find match", "tool": {"action":"key","keys":["ctrl","g"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Firefox keyboard shortcuts](https://support.mozilla.org/en-US/kb/keyboard-shortcuts-perform-firefox-tasks-quickly)。

## app.firefox.private_window

适用范围：Firefox browser UI。

同调用查询格式：`<key_lookup>app.firefox.private_window</key_lookup>`。

```json
[
  {"intent": "new private window", "tool": {"action":"key","keys":["ctrl","shift","p"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Firefox keyboard shortcuts](https://support.mozilla.org/en-US/kb/keyboard-shortcuts-perform-firefox-tasks-quickly)。
