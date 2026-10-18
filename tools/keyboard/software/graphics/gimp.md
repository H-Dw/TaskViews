# GIMP

目录 ID：`app.gimp`。类型：`graphics`。平台：`linux / windows`。

状态：显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：GIMP。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.gimp.history

适用范围：GIMP image editing。

同调用查询格式：`<key_lookup>app.gimp.history</key_lookup>`。

```json
[
  {"intent": "undo image edit", "tool": {"action":"key","keys":["ctrl","z"]}},
  {"intent": "redo image edit", "tool": {"action":"key","keys":["ctrl","y"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GIMP editing shortcuts](https://docs.gimp.org/3.0/en/key-reference-edit.html)。

## app.gimp.zoom

适用范围：GIMP canvas; not text tool。

同调用查询格式：`<key_lookup>app.gimp.zoom</key_lookup>`。

```json
[
  {"intent": "zoom out", "tool": {"action":"key","keys":["-"]}},
  {"intent": "actual pixels", "tool": {"action":"key","keys":["1"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GIMP view shortcuts](https://docs.gimp.org/3.0/en/key-reference-view.html)。
