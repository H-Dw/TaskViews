# Adobe After Effects (Windows)

目录 ID：`app.after_effects`。类型：`video`。平台：`windows`。

状态：参考资料；当前 Linux/X11 不可启用。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Adobe After Effects。

任务说明中的匹配别名：`Adobe After Effects`、`After Effects`。匹配规则与平台过滤见 [使用说明](../../README.md)。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.after_effects.timeline

适用范围：After Effects timeline; selected layer, no text editing。

同调用查询格式：`<key_lookup>app.after_effects.timeline</key_lookup>`。

```json
[
  {"intent": "position property", "tool": {"action":"key","keys":["p"]}},
  {"intent": "scale property", "tool": {"action":"key","keys":["s"]}},
  {"intent": "rotation property", "tool": {"action":"key","keys":["r"]}},
  {"intent": "opacity property", "tool": {"action":"key","keys":["t"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[After Effects keyboard shortcuts](https://helpx.adobe.com/after-effects/desktop/get-started/keyboard-shortcuts/keyboard-shortcuts-reference.html)。
