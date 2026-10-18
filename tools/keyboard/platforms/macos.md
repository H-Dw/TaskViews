# macOS 通用控制（资料）

目录 ID：`platform.macos`。类型：`desktop`。平台：`macos`。

状态：参考资料；当前 Linux/X11 不可启用。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：macOS。

当前 Mini 固定 Linux/X11，macOS 文档只作移植参考；不可在本后端启用。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## platform.macos.editing

适用范围：macOS conventional text controls。

同调用查询格式：`<key_lookup>platform.macos.editing</key_lookup>`。

```json
[
  {"intent": "copy selection", "tool": {"action":"key","keys":["command","c"]}},
  {"intent": "paste clipboard", "tool": {"action":"key","keys":["command","v"]}},
  {"intent": "undo edit", "tool": {"action":"key","keys":["command","z"]}},
  {"intent": "select all", "tool": {"action":"key","keys":["command","a"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Mac keyboard shortcuts](https://support.apple.com/en-us/102650)。

## platform.macos.windows

适用范围：macOS application windows。

同调用查询格式：`<key_lookup>platform.macos.windows</key_lookup>`。

```json
[
  {"intent": "switch application", "tool": {"action":"key","keys":["command","tab"]}},
  {"intent": "minimize window", "tool": {"action":"key","keys":["command","m"]}},
  {"intent": "close current window", "tool": {"action":"key","keys":["command","w"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Mac keyboard shortcuts](https://support.apple.com/en-us/102650)。
