# Microsoft PowerPoint (Windows)

目录 ID：`app.powerpoint`。类型：`presentation`。平台：`windows`。

状态：参考资料；当前 Linux/X11 不可启用。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Microsoft PowerPoint。

任务说明中的匹配别名：`Microsoft PowerPoint`、`MS PowerPoint`、`PowerPoint`。匹配规则与平台过滤见 [使用说明](../../README.md)。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.powerpoint.editing

适用范围：PowerPoint slide editor, not outline text。

同调用查询格式：`<key_lookup>app.powerpoint.editing</key_lookup>`。

```json
[
  {"intent": "new slide", "tool": {"action":"key","keys":["ctrl","m"]}},
  {"intent": "duplicate selected object", "tool": {"action":"key","keys":["ctrl","d"]}},
  {"intent": "group selected objects", "tool": {"action":"key","keys":["ctrl","g"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[PowerPoint editing shortcuts](https://support.microsoft.com/en-us/accessibility/powerpoint/use-keyboard-shortcuts-to-create-powerpoint-presentations)。
