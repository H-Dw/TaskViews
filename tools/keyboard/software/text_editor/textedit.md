# TextEdit (macOS 资料)

目录 ID：`app.textedit`。类型：`text_editor`。平台：`macos`。

状态：参考资料；当前 Linux/X11 不可启用。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：TextEdit。

macOS 专用资料；当前 Linux/X11 Mini 不得启用 command 组合键。Option 记为 alt；移植时须验证原生适配器。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.textedit.document

适用范围：TextEdit editable document。

同调用查询格式：`<key_lookup>app.textedit.document</key_lookup>`。

```json
[
  {"intent": "new document", "tool": {"action":"key","keys":["command","n"]}},
  {"intent": "open document", "tool": {"action":"key","keys":["command","o"]}},
  {"intent": "save document", "tool": {"action":"key","keys":["command","s"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Mac keyboard shortcuts](https://support.apple.com/en-us/102650)。
