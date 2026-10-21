# LibreOffice Impress

目录 ID：`app.libreoffice_impress`。类型：`presentation`。平台：`linux / windows`。

状态：任务名匹配或显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：LibreOffice Impress。

任务说明中的匹配别名：`LibreOffice Impress`、`LibreOfficeImpress`、`LibreOffice_Impress`。匹配规则与平台过滤见 [使用说明](../../README.md)。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.libreoffice_impress.slideshow

适用范围：Impress editor。

同调用查询格式：`<key_lookup>app.libreoffice_impress.slideshow</key_lookup>`。

```json
[
  {"intent": "slideshow from first slide", "tool": {"action":"key","keys":["f5"]}},
  {"intent": "slideshow from current slide", "tool": {"action":"key","keys":["shift","f5"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[LibreOffice Impress shortcuts](https://help.libreoffice.org/latest/en-US/text/simpress/04/01020000.html)。
