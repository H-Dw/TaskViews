# Microsoft Excel (Windows)

目录 ID：`app.excel`。类型：`spreadsheet`。平台：`windows`。

状态：参考资料；当前 Linux/X11 不可启用。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Microsoft Excel。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.excel.cells

适用范围：Excel worksheet grid。

同调用查询格式：`<key_lookup>app.excel.cells</key_lookup>`。

```json
[
  {"intent": "format cells", "tool": {"action":"key","keys":["ctrl","1"]}},
  {"intent": "fill down", "tool": {"action":"key","keys":["ctrl","d"]}},
  {"intent": "insert current date", "tool": {"action":"key","keys":["ctrl",";"]}},
  {"intent": "go to cell", "tool": {"action":"key","keys":["ctrl","g"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Excel keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/excel/keyboard-shortcuts-in-excel)。
