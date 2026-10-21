# Visual Studio Code (Linux)

目录 ID：`app.vscode`。类型：`text_editor`。平台：`linux`。

状态：任务名匹配或显式选择后可检索。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：Visual Studio Code。

任务说明中的匹配别名：`Visual Studio Code`、`VS Code`、`VSCode`、`VS_Code`。匹配规则与平台过滤见 [使用说明](../../README.md)。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.vscode.navigation

适用范围：VS Code Linux default keymap; no Vim/Emacs extension。

同调用查询格式：`<key_lookup>app.vscode.navigation</key_lookup>`。

```json
[
  {"intent": "command palette", "tool": {"action":"key","keys":["ctrl","shift","p"]}},
  {"intent": "quick open file", "tool": {"action":"key","keys":["ctrl","p"]}},
  {"intent": "go to line", "tool": {"action":"key","keys":["ctrl","g"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[VS Code Linux key reference](https://code.visualstudio.com/shortcuts/keyboard-shortcuts-linux.pdf)。

## app.vscode.search

适用范围：VS Code editor/workspace。

同调用查询格式：`<key_lookup>app.vscode.search</key_lookup>`。

```json
[
  {"intent": "find in editor", "tool": {"action":"key","keys":["ctrl","f"]}},
  {"intent": "search workspace", "tool": {"action":"key","keys":["ctrl","shift","f"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[VS Code Linux key reference](https://code.visualstudio.com/shortcuts/keyboard-shortcuts-linux.pdf)。
