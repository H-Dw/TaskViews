# Windows 窗口管理

目录 ID：`platform.windows`。类型：`desktop`。平台：`windows`。

状态：参考资料；当前 Linux/X11 不可启用。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Windows。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## platform.windows.window_maximize

适用范围：Windows active window。

同调用查询格式：`<key_lookup>platform.windows.window_maximize</key_lookup>`。

```json
[
  {"intent": "maximize active window", "tool": {"action":"key","keys":["win","up"]}},
  {"intent": "restore or minimize", "tool": {"action":"key","keys":["win","down"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)。

## platform.windows.window_menu

适用范围：Windows active window。

同调用查询格式：`<key_lookup>platform.windows.window_menu</key_lookup>`。

```json
[
  {"intent": "open window menu", "tool": {"action":"key","keys":["alt","space"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)。
