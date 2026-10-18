# 文本编辑器共性

目录 ID：`type.text_editor`。类型：`text_editor`。平台：`linux / windows`。

状态：显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：VS Code、LibreOffice Writer。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## type.text_editor.files

适用范围：VS Code/Writer text editing, not terminal prompt。

同调用查询格式：`<key_lookup>type.text_editor.files</key_lookup>`。

```json
[
  {"intent": "open file dialog", "tool": {"action":"key","keys":["ctrl","o"]}},
  {"intent": "save file", "tool": {"action":"key","keys":["ctrl","s"]}},
  {"intent": "find text", "tool": {"action":"key","keys":["ctrl","f"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[VS Code Linux key reference](https://code.visualstudio.com/shortcuts/keyboard-shortcuts-linux.pdf)，[LibreOffice general shortcuts](https://help.libreoffice.org/latest/en-US/text/shared/04/01010000.html)。
