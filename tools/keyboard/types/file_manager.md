# 文件管理器共性

目录 ID：`type.file_manager`。类型：`file_manager`。平台：`linux / windows`。

状态：显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：GNOME Files、Windows File Explorer。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## type.file_manager.rename

适用范围：GNOME Files/Explorer selected file; editable basename or complete name; preserve the extension exactly once。

同调用查询格式：`<key_lookup>type.file_manager.rename</key_lookup>`。

```json
[
  {"intent": "rename selected file", "tool": {"action":"key","keys":["f2"]}}
]
```

结果检查：Observe selection: basename or full name. Preserve the extension exactly once; verify the confirmed filename.

官方来源：[GNOME Files rename](https://help.gnome.org/gnome-help/files-rename.html)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)。

## type.file_manager.file_transfer

适用范围：GNOME Files/Explorer selected source; navigate to destination before paste。

同调用查询格式：`<key_lookup>type.file_manager.file_transfer</key_lookup>`。

```json
[
  {"intent": "cut selected files", "tool": {"action":"key","keys":["ctrl","x"]}},
  {"intent": "copy selected files", "tool": {"action":"key","keys":["ctrl","c"]}},
  {"intent": "paste into current folder", "tool": {"action":"key","keys":["ctrl","v"]}}
]
```

结果检查：Verify selected source, destination and resulting files; clipboard return does not prove transfer.

官方来源：[GNOME Files transfer](https://help.gnome.org/gnome-help/files-copy.html)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)。
