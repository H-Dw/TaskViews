# AutoCAD (Windows)

目录 ID：`app.autocad`。类型：`cad`。平台：`windows`。

状态：参考资料；当前 Linux/X11 不可启用。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

已核对的适用对象：AutoCAD。

2023 官方默认 CUIx；基准任务可能使用更早版本，须核对实际 keymap。命令别名需要 type 后确认，不能当作 chord。

此目录不会自动继承或覆盖 general；启用一个软件也不会隐式启用同类软件。

## app.autocad.panels

适用范围：AutoCAD active drawing。

同调用查询格式：`<key_lookup>app.autocad.panels</key_lookup>`。

```json
[
  {"intent": "toggle properties palette", "tool": {"action":"key","keys":["ctrl","1"]}},
  {"intent": "toggle command line", "tool": {"action":"key","keys":["ctrl","9"]}},
  {"intent": "toggle clean screen", "tool": {"action":"key","keys":["ctrl","0"]}},
  {"intent": "toggle ortho mode", "tool": {"action":"key","keys":["f8"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[AutoCAD default shortcuts (2023)](https://help.autodesk.com/cloudhelp/2023/ENU/AutoCAD-Customization/files/GUID-B6A9C126-230D-47F5-8973-464BC80E3736.htm)。
