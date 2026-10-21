# 通用软件控制（默认）

目录 ID：`general`。类型：`general`。平台：`linux / windows`。

状态：默认启用。资料核对日期：2026-10-20；快捷键未在 guest 中逐项实测。

本目录提供 Linux / Windows 传统 GUI 的跨软件控件操作，以及有明确菜单绑定的常见内容命令。当前 Mini 仍只运行 Linux/X11；不能把 Ctrl 机械替换成 Command 后用于 macOS。

运行时维护源为 [`kobe_views/key_tools/catalog.json`](../../kobe_views/key_tools/catalog.json) 的 `toolsets.general.topics`；本文件由 `scripts/render_keyboard_tools.py` 生成。v7 实验原版为 11 个主题、23 条配方，见[逐字节备份](backups/general.2026-10-20.pre-expansion.md)和[来源、实验配置与补充调研](../../docs/taskviews-mini-v7-keyboard-audit-20261020.md)。

使用顺序：先依据当前截图确认活动窗口、控件类型、焦点和模式，再查询一个主题；执行一次按键后重新观察光标、选区、选中标记、数值或弹窗变化。可视焦点、选中状态和业务完成是不同事实。网页控件仅在实现相应键盘交互时适用；ARIA 角色本身不会自动实现快捷键。

每个 `keys` 数组是一次同时按下的组合键；JSON 列表是可选配方，不能整组依次执行。多个步骤必须分成独立调用并观察中间状态，文字/文件路径继续使用原生 `type`。例如先 `<key_lookup>combobox_open</key_lookup>` 打开下拉列表，再查询 `combobox_selection` 选择选项。通用控件主题通过精确 `<key_lookup>主题</key_lookup>` 查询；新计划可依据任务软件名启用专用目录，详见 [使用说明](README.md)。名称匹配不推断当前控件或焦点。

文本编辑只适用于已聚焦的可编辑文本控件。终端、Vim 模式、画布、媒体播放区、时间轴、表格浏览模式和输入法候选窗不能直接套用；同一个箭头键可能移动光标、切换选项、调数值或控制媒体。标准控件不响应时应重新确认焦点或使用当前界面提供的控件，不盲目重复按键。

浏览器地址栏/标签管理、文件重命名、应用缩放、媒体播放、最大化/最小化等继续由 `type.*`、`platform.*`、`app.*` 目录提供。重做的 Ctrl+Y 与 Ctrl+Shift+Z、纯文本粘贴与选择性粘贴也不能当作同一个通用动作。打开/保存/打印仅在当前内容窗口菜单明确支持时使用；保存不等于导出，弹窗消失或工具回执也不证明文件已正确生成。

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

结果检查：Verify focus and selection; Return may submit a default action or insert a newline. Inspect the resulting field/dialog.

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

结果检查：Verify the intended pane scrolled; editable text may also move the caret. Do not infer exact PDF page changes.

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
  {"intent": "select to field or line start", "tool": {"action":"key","keys":["shift","home"]}},
  {"intent": "extend selection left", "tool": {"action":"key","keys":["shift","left"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GTK Entry cursor and selection keys](https://docs.gtk.org/gtk3/signal.Entry.move-cursor.html)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)。

## window_switch

适用范围：Linux/Windows desktop; GNOME groups windows by app; recheck selection。

同调用查询格式：`<key_lookup>window_switch</key_lookup>`。

```json
[
  {"intent": "switch window or application", "tool": {"action":"key","keys":["alt","tab"]}},
  {"intent": "switch window or application in reverse order", "tool": {"action":"key","keys":["alt","shift","tab"]}}
]
```

结果检查：Recheck app/focus, enabled state and visible effect.

官方来源：[GNOME default window keymap source](https://raw.githubusercontent.com/GNOME/gsettings-desktop-schemas/master/schemas/org.gnome.desktop.wm.keybindings.gschema.xml.in)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)，[GNOME standard keyboard shortcuts](https://developer.gnome.org/hig/reference/keyboard.html)。

## word_navigation

适用范围：Focused conventional text field; default word-navigation keymap, no terminal/IME capture.。

同调用查询格式：`<key_lookup>word_navigation</key_lookup>`。

```json
[
  {"intent": "move to previous word boundary", "tool": {"action":"key","keys":["ctrl","left"]}},
  {"intent": "move to next word boundary", "tool": {"action":"key","keys":["ctrl","right"]}}
]
```

结果检查：Check caret and selection; word boundaries depend on language and punctuation.

官方来源：[GTK Entry cursor and selection keys](https://docs.gtk.org/gtk3/signal.Entry.move-cursor.html)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)，[LibreOffice general shortcuts](https://help.libreoffice.org/latest/en-US/text/shared/04/01010000.html)。

## word_selection

适用范围：Focused conventional text field; extend from the current selection anchor.。

同调用查询格式：`<key_lookup>word_selection</key_lookup>`。

```json
[
  {"intent": "extend selection by one word left", "tool": {"action":"key","keys":["ctrl","shift","left"]}},
  {"intent": "extend selection by one word right", "tool": {"action":"key","keys":["ctrl","shift","right"]}}
]
```

结果检查：Inspect the highlighted range before replacing or deleting it.

官方来源：[GTK Entry cursor and selection keys](https://docs.gtk.org/gtk3/signal.Entry.move-cursor.html)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)，[LibreOffice general shortcuts](https://help.libreoffice.org/latest/en-US/text/shared/04/01010000.html)。

## text_delete

适用范围：Focused editable text field only; existing selection is deleted as a whole.。

同调用查询格式：`<key_lookup>text_delete</key_lookup>`。

```json
[
  {"intent": "delete selection or preceding character", "tool": {"action":"key","keys":["backspace"]}},
  {"intent": "delete selection or following character", "tool": {"action":"key","keys":["delete"]}}
]
```

结果检查：Check the resulting text; outside a text field Delete may remove an item or file.

官方来源：[GTK TextView deletion keys](https://docs.gtk.org/gtk3/signal.TextView.delete-from-cursor.html)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)。

## word_delete

适用范围：Focused editable text field with no selection; default word-deletion bindings.。

同调用查询格式：`<key_lookup>word_delete</key_lookup>`。

```json
[
  {"intent": "delete toward previous word boundary", "tool": {"action":"key","keys":["ctrl","backspace"]}},
  {"intent": "delete toward next word boundary", "tool": {"action":"key","keys":["ctrl","delete"]}}
]
```

结果检查：Inspect the text and caret; for a precise range select first, then use text_delete.

官方来源：[GTK TextView deletion keys](https://docs.gtk.org/gtk3/signal.TextView.delete-from-cursor.html)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)。

## multiline_navigation

适用范围：Focused multiline text editor in text-edit mode; no completion popup or grid focus.。

同调用查询格式：`<key_lookup>multiline_navigation</key_lookup>`。

```json
[
  {"intent": "move caret up one displayed line", "tool": {"action":"key","keys":["up"]}},
  {"intent": "move caret down one displayed line", "tool": {"action":"key","keys":["down"]}},
  {"intent": "move caret to document start", "tool": {"action":"key","keys":["ctrl","home"]}},
  {"intent": "move caret to document end", "tool": {"action":"key","keys":["ctrl","end"]}}
]
```

结果检查：Verify caret position and scroll offset; wrapping and editor keymaps affect line movement.

官方来源：[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)，[GTK TextView cursor and viewport keys](https://docs.gtk.org/gtk3/signal.TextView.move-cursor.html)。

## multiline_selection

适用范围：Focused multiline text editor; selection anchored at the current caret.。

同调用查询格式：`<key_lookup>multiline_selection</key_lookup>`。

```json
[
  {"intent": "extend selection up one displayed line", "tool": {"action":"key","keys":["shift","up"]}},
  {"intent": "extend selection down one displayed line", "tool": {"action":"key","keys":["shift","down"]}},
  {"intent": "select to document start", "tool": {"action":"key","keys":["ctrl","shift","home"]}},
  {"intent": "select to document end", "tool": {"action":"key","keys":["ctrl","shift","end"]}}
]
```

结果检查：Inspect highlighted text; do not interpret a spreadsheet range as a text selection.

官方来源：[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)，[GTK TextView cursor and viewport keys](https://docs.gtk.org/gtk3/signal.TextView.move-cursor.html)。

## find_text

适用范围：Content view with Ctrl+F listed as Find/Search; editors, readers or browsers, not a terminal.。

同调用查询格式：`<key_lookup>find_text</key_lookup>`。

```json
[
  {"intent": "open or focus content search", "tool": {"action":"key","keys":["ctrl","f"]}}
]
```

结果检查：Verify the search UI and its scope; type the query separately and inspect actual matches.

官方来源：[GNOME standard keyboard shortcuts](https://developer.gnome.org/hig/reference/keyboard.html)，[LibreOffice general shortcuts](https://help.libreoffice.org/latest/en-US/text/shared/04/01010000.html)，[Firefox keyboard shortcuts](https://support.mozilla.org/en-US/kb/keyboard-shortcuts-perform-firefox-tasks-quickly)。

## document_file

适用范围：Active document/text/image content window whose File menu lists these bindings; no web-app shortcut capture.。

同调用查询格式：`<key_lookup>document_file</key_lookup>`。

```json
[
  {"intent": "open file chooser", "tool": {"action":"key","keys":["ctrl","o"]}},
  {"intent": "save current editable content", "tool": {"action":"key","keys":["ctrl","s"]}},
  {"intent": "open Save As dialog", "tool": {"action":"key","keys":["ctrl","shift","s"]}},
  {"intent": "open print dialog", "tool": {"action":"key","keys":["ctrl","p"]}}
]
```

结果检查：Verify target content, path, format and dialog. Save may prompt; Save As is not Export. Print dialog is not print completion.

官方来源：[GNOME standard keyboard shortcuts](https://developer.gnome.org/hig/reference/keyboard.html)，[GIMP file shortcuts](https://docs.gimp.org/3.0/en/key-reference-file.html)，[LibreOffice general shortcuts](https://help.libreoffice.org/latest/en-US/text/shared/04/01010000.html)。

## menu_open

适用范围：Desktop application with a native menu/menubar supporting F10; not an arbitrary web page.。

同调用查询格式：`<key_lookup>menu_open</key_lookup>`。

```json
[
  {"intent": "focus or open application menu", "tool": {"action":"key","keys":["f10"]}}
]
```

结果检查：Verify a menu appeared, then use menu_navigation; custom menus may need their visible button.

官方来源：[GNOME keyboard navigation](https://help.gnome.org/gnome-help/keyboard-nav.html)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)，[LibreOffice general shortcuts](https://help.libreoffice.org/latest/en-US/text/shared/04/01010000.html)。

## menu_navigation

适用范围：Open vertical command menu with keyboard focus; excludes listboxes and text fields.。

同调用查询格式：`<key_lookup>menu_navigation</key_lookup>`。

```json
[
  {"intent": "focus previous menu item", "tool": {"action":"key","keys":["up"]}},
  {"intent": "focus next menu item", "tool": {"action":"key","keys":["down"]}},
  {"intent": "activate focused menu item or open its submenu", "tool": {"action":"key","keys":["return"]}},
  {"intent": "close current menu level", "tool": {"action":"key","keys":["escape"]}}
]
```

结果检查：Read the item label and enabled state before activation; check resulting submenu, dialog or action.

官方来源：[W3C APG menus and menubars](https://www.w3.org/WAI/ARIA/apg/patterns/menubar/)，[GNOME keyboard navigation](https://help.gnome.org/gnome-help/keyboard-nav.html)。

## submenu_navigation

适用范围：Focused item in a conventional left-to-right menu hierarchy with nested submenus.。

同调用查询格式：`<key_lookup>submenu_navigation</key_lookup>`。

```json
[
  {"intent": "open focused item submenu when present", "tool": {"action":"key","keys":["right"]}},
  {"intent": "return from submenu to parent menu", "tool": {"action":"key","keys":["left"]}}
]
```

结果检查：Verify submenu and focus; top-level menubars and reversed layouts can change arrow behavior.

官方来源：[W3C APG menus and menubars](https://www.w3.org/WAI/ARIA/apg/patterns/menubar/)。

## list_navigation

适用范围：Focused vertical list/listbox implementing standard navigation; Home/End are optional in web lists.。

同调用查询格式：`<key_lookup>list_navigation</key_lookup>`。

```json
[
  {"intent": "focus previous list item", "tool": {"action":"key","keys":["up"]}},
  {"intent": "focus next list item", "tool": {"action":"key","keys":["down"]}},
  {"intent": "focus first item if supported", "tool": {"action":"key","keys":["home"]}},
  {"intent": "focus last item if supported", "tool": {"action":"key","keys":["end"]}}
]
```

结果检查：Distinguish focus from selection; arrows may select immediately. Home/End do not imply all virtualized items are loaded.

官方来源：[W3C APG listbox](https://www.w3.org/WAI/ARIA/apg/patterns/listbox/)，[GNOME keyboard navigation](https://help.gnome.org/gnome-help/keyboard-nav.html)。

## list_selection

适用范围：Focused multi-select list using modifier-based selection, not a text box; Ctrl+Space must not be captured by IME.。

同调用查询格式：`<key_lookup>list_selection</key_lookup>`。

```json
[
  {"intent": "extend selected range to previous item", "tool": {"action":"key","keys":["shift","up"]}},
  {"intent": "extend selected range to next item", "tool": {"action":"key","keys":["shift","down"]}},
  {"intent": "toggle focused item without clearing other selections", "tool": {"action":"key","keys":["ctrl","space"]}}
]
```

结果检查：Verify selected items/count. Web listboxes may use a different selection model; stop if an IME opens.

官方来源：[GNOME keyboard navigation](https://help.gnome.org/gnome-help/keyboard-nav.html)，[W3C APG listbox](https://www.w3.org/WAI/ARIA/apg/patterns/listbox/)。

## list_focus

适用范围：Focused vertical multi-select list with modifier-based focus navigation.。

同调用查询格式：`<key_lookup>list_focus</key_lookup>`。

```json
[
  {"intent": "focus previous item while retaining selection", "tool": {"action":"key","keys":["ctrl","up"]}},
  {"intent": "focus next item while retaining selection", "tool": {"action":"key","keys":["ctrl","down"]}}
]
```

结果检查：Confirm focus moved but selected items stayed unchanged before list_selection.

官方来源：[GNOME keyboard navigation](https://help.gnome.org/gnome-help/keyboard-nav.html)，[W3C APG listbox](https://www.w3.org/WAI/ARIA/apg/patterns/listbox/)。

## combobox_open

适用范围：Focused dropdown/combobox with Alt+Down support; optional in WAI-ARIA widgets.。

同调用查询格式：`<key_lookup>combobox_open</key_lookup>`。

```json
[
  {"intent": "open combobox option popup if supported", "tool": {"action":"key","keys":["alt","down"]}}
]
```

结果检查：Verify the popup opened; otherwise use its visible opener. Do not apply this to ordinary text.

官方来源：[LibreOffice general shortcuts](https://help.libreoffice.org/latest/en-US/text/shared/04/01010000.html)，[W3C APG combobox](https://www.w3.org/WAI/ARIA/apg/patterns/combobox/)。

## combobox_selection

适用范围：Open combobox list popup with option-navigation focus; not a calendar/grid popup.。

同调用查询格式：`<key_lookup>combobox_selection</key_lookup>`。

```json
[
  {"intent": "focus previous option", "tool": {"action":"key","keys":["up"]}},
  {"intent": "focus next option", "tool": {"action":"key","keys":["down"]}},
  {"intent": "accept focused option", "tool": {"action":"key","keys":["return"]}},
  {"intent": "dismiss option popup", "tool": {"action":"key","keys":["escape"]}}
]
```

结果检查：Verify the committed field value; highlight alone may be provisional. Escape may clear editable input.

官方来源：[W3C APG combobox](https://www.w3.org/WAI/ARIA/apg/patterns/combobox/)，[LibreOffice general shortcuts](https://help.libreoffice.org/latest/en-US/text/shared/04/01010000.html)。

## radio_group

适用范围：Focused standard radio group outside a toolbar; horizontal arrow navigation supported.。

同调用查询格式：`<key_lookup>radio_group</key_lookup>`。

```json
[
  {"intent": "select previous radio option", "tool": {"action":"key","keys":["left"]}},
  {"intent": "select next radio option", "tool": {"action":"key","keys":["right"]}},
  {"intent": "select focused radio option", "tool": {"action":"key","keys":["space"]}}
]
```

结果检查：Check the filled radio indicator; arrows may change the value immediately. Tab leaves the group.

官方来源：[W3C APG radio group](https://www.w3.org/WAI/ARIA/apg/patterns/radio/)，[GNOME keyboard navigation](https://help.gnome.org/gnome-help/keyboard-nav.html)，[LibreOffice general shortcuts](https://help.libreoffice.org/latest/en-US/text/shared/04/01010000.html)。

## slider_adjust

适用范围：Focused horizontal slider using normal left=decrease/right=increase and Home/End endpoints; no canvas focus.。

同调用查询格式：`<key_lookup>slider_adjust</key_lookup>`。

```json
[
  {"intent": "decrease slider one step", "tool": {"action":"key","keys":["left"]}},
  {"intent": "increase slider one step", "tool": {"action":"key","keys":["right"]}},
  {"intent": "set slider to minimum", "tool": {"action":"key","keys":["home"]}},
  {"intent": "set slider to maximum", "tool": {"action":"key","keys":["end"]}}
]
```

结果检查：Read the actual value/units after one key; inverted/RTL sliders can reverse direction. Endpoint keys change the value.

官方来源：[W3C APG slider](https://www.w3.org/WAI/ARIA/apg/patterns/slider/)。

## spinbutton_adjust

适用范围：Focused numeric spinbutton supporting Up/Down stepping; not a plain text field.。

同调用查询格式：`<key_lookup>spinbutton_adjust</key_lookup>`。

```json
[
  {"intent": "increase numeric value one step", "tool": {"action":"key","keys":["up"]}},
  {"intent": "decrease numeric value one step", "tool": {"action":"key","keys":["down"]}}
]
```

结果检查：Verify value, units, bounds and step size. Use text editing only if direct input is supported.

官方来源：[W3C APG spinbutton](https://www.w3.org/WAI/ARIA/apg/patterns/spinbutton/)。

## tablist_navigation

适用范围：Focus on a tab label in a horizontal tablist implementing arrow navigation; not browser content or editor text.。

同调用查询格式：`<key_lookup>tablist_navigation</key_lookup>`。

```json
[
  {"intent": "focus previous tab label", "tool": {"action":"key","keys":["left"]}},
  {"intent": "focus next tab label", "tool": {"action":"key","keys":["right"]}},
  {"intent": "activate focused tab if manual activation", "tool": {"action":"key","keys":["return"]}},
  {"intent": "activate focused tab with Space if manual activation", "tool": {"action":"key","keys":["space"]}}
]
```

结果检查：Inspect active tab and panel; focus can activate automatically. Vertical tablists use a different arrow axis.

官方来源：[W3C APG tabs](https://www.w3.org/WAI/ARIA/apg/patterns/tabs/)。

## tree_navigation

适用范围：Focused tree implementing unmodified-arrow expansion (WAI-ARIA/Windows convention); check keymap first.。

同调用查询格式：`<key_lookup>tree_navigation</key_lookup>`。

```json
[
  {"intent": "focus previous visible node", "tool": {"action":"key","keys":["up"]}},
  {"intent": "focus next visible node", "tool": {"action":"key","keys":["down"]}},
  {"intent": "expand collapsed node or enter first child", "tool": {"action":"key","keys":["right"]}},
  {"intent": "collapse expanded node or focus parent", "tool": {"action":"key","keys":["left"]}}
]
```

结果检查：Verify node expansion and focus. GNOME documents Shift+arrows for expansion; do not assume all desktop trees match.

官方来源：[W3C APG tree view](https://www.w3.org/WAI/ARIA/apg/patterns/treeview/)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)，[GNOME keyboard navigation](https://help.gnome.org/gnome-help/keyboard-nav.html)。

## window_close

适用范围：Active application window on Linux/Windows; no desktop-only focus or save dialog pending.。

同调用查询格式：`<key_lookup>window_close</key_lookup>`。

```json
[
  {"intent": "request closing active window", "tool": {"action":"key","keys":["alt","f4"]}}
]
```

结果检查：Confirm the intended window; handle Save/Discard/Cancel explicitly. Closing a window is not task completion.

官方来源：[GNOME keyboard navigation](https://help.gnome.org/gnome-help/keyboard-nav.html)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)。

## window_menu

适用范围：Active managed desktop window on Linux/Windows supporting the system window menu.。

同调用查询格式：`<key_lookup>window_menu</key_lookup>`。

```json
[
  {"intent": "open active window system menu", "tool": {"action":"key","keys":["alt","space"]}}
]
```

结果检查：Verify the system menu and choose by its visible labels; do not assume localized mnemonic letters.

官方来源：[GNOME keyboard navigation](https://help.gnome.org/gnome-help/keyboard-nav.html)，[Windows keyboard shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows)。
