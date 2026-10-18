# 电子表格共性

目录 ID：`type.spreadsheet`。类型：`spreadsheet`。平台：`linux / windows`。

状态：显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：LibreOffice Calc、Microsoft Excel。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## type.spreadsheet.cells

适用范围：Calc/Excel grid; leave cell edit mode before sheet navigation。

同调用查询格式：`<key_lookup>type.spreadsheet.cells</key_lookup>`。

```json
[
  {"intent": "edit active cell", "tool": {"action":"key","keys":["f2"]}},
  {"intent": "confirm cell entry", "tool": {"action":"key","keys":["return"]}},
  {"intent": "next worksheet", "tool": {"action":"key","keys":["ctrl","pagedown"]}},
  {"intent": "previous worksheet", "tool": {"action":"key","keys":["ctrl","pageup"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[LibreOffice Calc shortcuts](https://help.libreoffice.org/latest/en-US/text/scalc/04/01020000.html)，[Excel keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/excel/keyboard-shortcuts-in-excel)。
