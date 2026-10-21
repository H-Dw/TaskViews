# Microsoft Word (Windows)

目录 ID：`app.word`。类型：`document`。平台：`windows`。

状态：参考资料；当前 Linux/X11 不可启用。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Microsoft Word。

任务说明中的匹配别名：`Microsoft Word`、`MS Word`、`Word文档`。匹配规则与平台过滤见 [使用说明](../../README.md)。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.word.paragraphs

适用范围：Word editable document。

同调用查询格式：`<key_lookup>app.word.paragraphs</key_lookup>`。

```json
[
  {"intent": "align left", "tool": {"action":"key","keys":["ctrl","l"]}},
  {"intent": "center paragraph", "tool": {"action":"key","keys":["ctrl","e"]}},
  {"intent": "align right", "tool": {"action":"key","keys":["ctrl","r"]}},
  {"intent": "page break", "tool": {"action":"key","keys":["ctrl","return"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Word keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/word/keyboard-shortcuts-in-word)。
