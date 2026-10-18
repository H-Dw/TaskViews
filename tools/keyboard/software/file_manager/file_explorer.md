# Windows File Explorer

目录 ID：`app.file_explorer`。类型：`file_manager`。平台：`windows`。

状态：参考资料；当前 Linux/X11 不可启用。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：File Explorer。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.file_explorer.navigation

适用范围：File Explorer folder view。

同调用查询格式：`<key_lookup>app.file_explorer.navigation</key_lookup>`。

```json
[
  {"intent": "edit address", "tool": {"action":"key","keys":["alt","d"]}},
  {"intent": "parent folder", "tool": {"action":"key","keys":["alt","up"]}},
  {"intent": "create folder", "tool": {"action":"key","keys":["ctrl","shift","n"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)。
