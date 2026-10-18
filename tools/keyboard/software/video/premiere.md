# Adobe Premiere (Windows)

目录 ID：`app.premiere`。类型：`video`。平台：`windows`。

状态：参考资料；当前 Linux/X11 不可启用。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Adobe Premiere Pro。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.premiere.playback

适用范围：Premiere timeline; no text field focus。

同调用查询格式：`<key_lookup>app.premiere.playback</key_lookup>`。

```json
[
  {"intent": "play backwards", "tool": {"action":"key","keys":["j"]}},
  {"intent": "stop", "tool": {"action":"key","keys":["k"]}},
  {"intent": "play forwards", "tool": {"action":"key","keys":["l"]}},
  {"intent": "play or stop", "tool": {"action":"key","keys":["space"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Premiere default shortcuts](https://helpx.adobe.com/premiere/desktop/get-started/keyboard-shortcuts/default-keyboard-shortcuts.html)。
