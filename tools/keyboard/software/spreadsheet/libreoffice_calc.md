# LibreOffice Calc

目录 ID：`app.libreoffice_calc`。类型：`spreadsheet`。平台：`linux / windows`。

状态：显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：LibreOffice Calc。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.libreoffice_calc.data

适用范围：Calc grid, not formula editing。

同调用查询格式：`<key_lookup>app.libreoffice_calc.data</key_lookup>`。

```json
[
  {"intent": "format cells", "tool": {"action":"key","keys":["ctrl","1"]}},
  {"intent": "fill down", "tool": {"action":"key","keys":["ctrl","d"]}},
  {"intent": "edit active cell", "tool": {"action":"key","keys":["f2"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[LibreOffice Calc shortcuts](https://help.libreoffice.org/latest/en-US/text/scalc/04/01020000.html)。
