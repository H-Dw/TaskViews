# Microsoft Edge

目录 ID：`app.edge`。类型：`browser`。平台：`windows`。

状态：参考资料；当前 Linux/X11 不可启用。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Microsoft Edge。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.edge.find

适用范围：Microsoft Edge page content。

同调用查询格式：`<key_lookup>app.edge.find</key_lookup>`。

```json
[
  {"intent": "find page text", "tool": {"action":"key","keys":["ctrl","f"]}},
  {"intent": "next find match", "tool": {"action":"key","keys":["ctrl","g"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Edge keyboard shortcuts](https://support.microsoft.com/en-us/edge/keyboard-shortcuts-in-microsoft-edge)。

## app.edge.private_window

适用范围：Edge browser UI。

同调用查询格式：`<key_lookup>app.edge.private_window</key_lookup>`。

```json
[
  {"intent": "new InPrivate window", "tool": {"action":"key","keys":["ctrl","shift","n"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Edge keyboard shortcuts](https://support.microsoft.com/en-us/edge/keyboard-shortcuts-in-microsoft-edge)。
