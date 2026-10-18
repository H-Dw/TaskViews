# 终端控件

目录 ID：`type.terminal`。类型：`terminal`。平台：`linux`。

状态：显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：GNOME Terminal。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## type.terminal.clipboard

适用范围：GNOME Terminal; Ctrl+C interrupts a foreground process。

同调用查询格式：`<key_lookup>type.terminal.clipboard</key_lookup>`。

```json
[
  {"intent": "copy selected terminal text", "tool": {"action":"key","keys":["ctrl","shift","c"]}},
  {"intent": "paste into terminal", "tool": {"action":"key","keys":["ctrl","shift","v"]}}
]
```

结果检查：Pasting can execute multiline shell input; inspect the text and current prompt first.

官方来源：[GNOME Terminal shortcuts](https://help.gnome.org/users/gnome-terminal/stable/adv-keyboard-shortcuts.html.en)。
