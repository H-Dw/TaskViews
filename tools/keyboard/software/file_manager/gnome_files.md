# GNOME Files

目录 ID：`app.gnome_files`。类型：`file_manager`。平台：`linux`。

状态：显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：GNOME Files。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.gnome_files.hidden_files

适用范围：GNOME Files folder view。

同调用查询格式：`<key_lookup>app.gnome_files.hidden_files</key_lookup>`。

```json
[
  {"intent": "toggle hidden files", "tool": {"action":"key","keys":["ctrl","h"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GNOME Files hidden files](https://help.gnome.org/gnome-help/files-hidden.html)。

## app.gnome_files.rename

适用范围：GNOME Files selected file; basename or complete name。

同调用查询格式：`<key_lookup>app.gnome_files.rename</key_lookup>`。

```json
[
  {"intent": "rename file", "tool": {"action":"key","keys":["f2"]}}
]
```

结果检查：Observe selection: basename or full name. Preserve the extension exactly once; verify after confirm.

官方来源：[GNOME Files rename](https://help.gnome.org/gnome-help/files-rename.html)。
