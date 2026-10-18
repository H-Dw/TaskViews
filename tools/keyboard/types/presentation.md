# 演示文稿共性

目录 ID：`type.presentation`。类型：`presentation`。平台：`linux / windows`。

状态：显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：LibreOffice Impress、Microsoft PowerPoint。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## type.presentation.slides

适用范围：Impress/PowerPoint presentation editor。

同调用查询格式：`<key_lookup>type.presentation.slides</key_lookup>`。

```json
[
  {"intent": "start presentation from beginning", "tool": {"action":"key","keys":["f5"]}},
  {"intent": "exit presentation", "tool": {"action":"key","keys":["escape"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[LibreOffice Impress shortcuts](https://help.libreoffice.org/latest/en-US/text/simpress/04/01020000.html)，[PowerPoint editing shortcuts](https://support.microsoft.com/en-us/accessibility/powerpoint/use-keyboard-shortcuts-to-create-powerpoint-presentations)。
