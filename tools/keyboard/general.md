# 通用软件控制（默认）

目录 ID：`general`。类型：`general`。平台：`linux / windows`。

状态：默认启用。资料核对日期：2026-10-17；快捷键未在 guest 中逐项实测。

跨软件的传统 GUI 控件和文本操作；需要当前控件支持。终端、画布和游戏不得直接套用文本语义。

## editing

适用范围：focused conventional editable text field。

同调用查询格式：`<key_lookup>editing</key_lookup>`。

```json
[
  {"intent": "select field text", "tool": {"action":"key","keys":["ctrl","a"]}},
  {"intent": "confirm current field or dialog", "tool": {"action":"key","keys":["return"]}},
  {"intent": "dismiss current popup", "tool": {"action":"key","keys":["escape"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GNOME useful shortcuts](https://help.gnome.org/gnome-help/shell-keyboard-shortcuts.html)，[GNOME keyboard navigation](https://help.gnome.org/gnome-help/keyboard-nav.html)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)。

## clipboard

适用范围：selected text/items in a conventional GUI; paste replaces a selection。

同调用查询格式：`<key_lookup>clipboard</key_lookup>`。

```json
[
  {"intent": "copy selection", "tool": {"action":"key","keys":["ctrl","c"]}},
  {"intent": "cut selection", "tool": {"action":"key","keys":["ctrl","x"]}},
  {"intent": "paste clipboard", "tool": {"action":"key","keys":["ctrl","v"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GNOME useful shortcuts](https://help.gnome.org/gnome-help/shell-keyboard-shortcuts.html)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)。

## undo

适用范围：focused editable GUI supporting undo。

同调用查询格式：`<key_lookup>undo</key_lookup>`。

```json
[
  {"intent": "undo last edit", "tool": {"action":"key","keys":["ctrl","z"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GNOME useful shortcuts](https://help.gnome.org/gnome-help/shell-keyboard-shortcuts.html)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)。

## focus_navigation

适用范围：visible focusable controls。

同调用查询格式：`<key_lookup>focus_navigation</key_lookup>`。

```json
[
  {"intent": "next control", "tool": {"action":"key","keys":["tab"]}},
  {"intent": "previous control", "tool": {"action":"key","keys":["shift","tab"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GNOME keyboard navigation](https://help.gnome.org/gnome-help/keyboard-nav.html)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)。

## control_activation

适用范围：focused button or checkbox; Return can submit a default dialog action。

同调用查询格式：`<key_lookup>control_activation</key_lookup>`。

```json
[
  {"intent": "activate focused button", "tool": {"action":"key","keys":["return"]}},
  {"intent": "toggle focused checkbox or button", "tool": {"action":"key","keys":["space"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GNOME keyboard navigation](https://help.gnome.org/gnome-help/keyboard-nav.html)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)。

## popup_dismiss

适用范围：focused popup, menu or cancellable dialog。

同调用查询格式：`<key_lookup>popup_dismiss</key_lookup>`。

```json
[
  {"intent": "dismiss popup", "tool": {"action":"key","keys":["escape"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GNOME keyboard navigation](https://help.gnome.org/gnome-help/keyboard-nav.html)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)。

## context_menu

适用范围：focused conventional GUI item。

同调用查询格式：`<key_lookup>context_menu</key_lookup>`。

```json
[
  {"intent": "open focused item context menu", "tool": {"action":"key","keys":["shift","f10"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GNOME keyboard navigation](https://help.gnome.org/gnome-help/keyboard-nav.html)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)。

## page_navigation

适用范围：scrollable text/document pane; not timeline/grid/terminal。

同调用查询格式：`<key_lookup>page_navigation</key_lookup>`。

```json
[
  {"intent": "scroll one viewport down", "tool": {"action":"key","keys":["pagedown"]}},
  {"intent": "scroll one viewport up", "tool": {"action":"key","keys":["pageup"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GTK TextView cursor and viewport keys](https://docs.gtk.org/gtk3/signal.TextView.move-cursor.html)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)，[Firefox keyboard shortcuts](https://support.mozilla.org/en-US/kb/keyboard-shortcuts-perform-firefox-tasks-quickly)。

## cursor_navigation

适用范围：focused conventional single-line text field; check selection and cursor。

同调用查询格式：`<key_lookup>cursor_navigation</key_lookup>`。

```json
[
  {"intent": "previous character", "tool": {"action":"key","keys":["left"]}},
  {"intent": "next character", "tool": {"action":"key","keys":["right"]}},
  {"intent": "field or line start", "tool": {"action":"key","keys":["home"]}},
  {"intent": "field or line end", "tool": {"action":"key","keys":["end"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GTK Entry cursor and selection keys](https://docs.gtk.org/gtk3/signal.Entry.move-cursor.html)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)。

## text_selection

适用范围：focused conventional single-line text field。

同调用查询格式：`<key_lookup>text_selection</key_lookup>`。

```json
[
  {"intent": "extend selection right", "tool": {"action":"key","keys":["shift","right"]}},
  {"intent": "select to field or line end", "tool": {"action":"key","keys":["shift","end"]}},
  {"intent": "select to field or line start", "tool": {"action":"key","keys":["shift","home"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GTK Entry cursor and selection keys](https://docs.gtk.org/gtk3/signal.Entry.move-cursor.html)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)。

## window_switch

适用范围：Linux/Windows desktop; GNOME groups windows by app; recheck selection。

同调用查询格式：`<key_lookup>window_switch</key_lookup>`。

```json
[
  {"intent": "switch window or application", "tool": {"action":"key","keys":["alt","tab"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GNOME default window keymap source](https://raw.githubusercontent.com/GNOME/gsettings-desktop-schemas/master/schemas/org.gnome.desktop.wm.keybindings.gschema.xml.in)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)。
