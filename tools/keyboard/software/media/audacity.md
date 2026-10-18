# Audacity

目录 ID：`app.audacity`。类型：`media`。平台：`linux / windows`。

状态：显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Audacity。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.audacity.playback

适用范围：Audacity project timeline。

同调用查询格式：`<key_lookup>app.audacity.playback</key_lookup>`。

```json
[
  {"intent": "play or pause", "tool": {"action":"key","keys":["space"]}},
  {"intent": "record", "tool": {"action":"key","keys":["r"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Audacity command and keyboard reference](https://manual.audacityteam.org/man/keyboard_shortcut_reference.html)。

## app.audacity.editing

适用范围：Audacity selected audio。

同调用查询格式：`<key_lookup>app.audacity.editing</key_lookup>`。

```json
[
  {"intent": "split clip", "tool": {"action":"key","keys":["ctrl","i"]}},
  {"intent": "duplicate audio", "tool": {"action":"key","keys":["ctrl","d"]}},
  {"intent": "export audio dialog", "tool": {"action":"key","keys":["ctrl","shift","e"]}}
]
```

结果检查：An export dialog or saved project does not establish an exported audio file; inspect format, path and output.

官方来源：[Audacity command and keyboard reference](https://manual.audacityteam.org/man/keyboard_shortcut_reference.html)。
