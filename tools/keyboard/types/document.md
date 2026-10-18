# 文档编辑器共性

目录 ID：`type.document`。类型：`document`。平台：`linux / windows`。

状态：显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：LibreOffice Writer、Microsoft Word。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## type.document.document

适用范围：Writer/Word editable document。

同调用查询格式：`<key_lookup>type.document.document</key_lookup>`。

```json
[
  {"intent": "open document dialog", "tool": {"action":"key","keys":["ctrl","o"]}},
  {"intent": "save current document", "tool": {"action":"key","keys":["ctrl","s"]}},
  {"intent": "print dialog", "tool": {"action":"key","keys":["ctrl","p"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[LibreOffice general shortcuts](https://help.libreoffice.org/latest/en-US/text/shared/04/01010000.html)，[Word keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/word/keyboard-shortcuts-in-word)。

## type.document.formatting

适用范围：selected text in Writer/Word。

同调用查询格式：`<key_lookup>type.document.formatting</key_lookup>`。

```json
[
  {"intent": "toggle bold", "tool": {"action":"key","keys":["ctrl","b"]}},
  {"intent": "toggle italic", "tool": {"action":"key","keys":["ctrl","i"]}},
  {"intent": "toggle underline", "tool": {"action":"key","keys":["ctrl","u"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[LibreOffice general shortcuts](https://help.libreoffice.org/latest/en-US/text/shared/04/01010000.html)，[Word keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/word/keyboard-shortcuts-in-word)。
