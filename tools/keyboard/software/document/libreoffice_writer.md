# LibreOffice Writer

目录 ID：`app.libreoffice_writer`。类型：`document`。平台：`linux / windows`。

状态：任务名匹配或显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：LibreOffice Writer。

任务说明中的匹配别名：`LibreOffice Writer`、`LibreOfficeWriter`、`LibreOffice_Writer`。匹配规则与平台过滤见 [使用说明](../../README.md)。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.libreoffice_writer.formatting

适用范围：Writer document paragraphs。

同调用查询格式：`<key_lookup>app.libreoffice_writer.formatting</key_lookup>`。

```json
[
  {"intent": "Heading 1", "tool": {"action":"key","keys":["ctrl","1"]}},
  {"intent": "Heading 2", "tool": {"action":"key","keys":["ctrl","2"]}},
  {"intent": "insert page break", "tool": {"action":"key","keys":["ctrl","return"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[LibreOffice Writer shortcuts](https://help.libreoffice.org/latest/en-US/text/swriter/04/01020000.html)。

## app.libreoffice_writer.search

适用范围：Writer document。

同调用查询格式：`<key_lookup>app.libreoffice_writer.search</key_lookup>`。

```json
[
  {"intent": "find", "tool": {"action":"key","keys":["ctrl","f"]}},
  {"intent": "find and replace", "tool": {"action":"key","keys":["ctrl","h"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[LibreOffice general shortcuts](https://help.libreoffice.org/latest/en-US/text/shared/04/01010000.html)。
