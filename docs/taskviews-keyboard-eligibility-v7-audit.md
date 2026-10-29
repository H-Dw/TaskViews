# Keyboard 逐项契约核验（2026-10-28）

本表核对动作词、对象、操作卡、绑定和适用条件。快捷键来源沿用冻结目录；本轮没有重新访问所有官方网页，也没有启动 guest 逐键实测，因此不将“映射通过”写成“实际软件均可执行”。

新的 capability_guidance_v7 不是历史 Mini v7。task_capabilities 路径先过滤、再排序；旧 task_names/manual 及历史冻结源码保留原行为。不能拿新代码静默恢复旧 checkpoint。

核验范围：`{"cards": 43, "topics": 99, "bindings": 253, "reference_only_platform": 63, "conditional_contract": 47, "no_audited_operation_contract": 143}`。

## 检查顺序

1. 从公开任务冻结能力及依赖；公开运行意图只能在该集合内选择，不能自行扩容。
2. 区分动作、状态、否定、假设、字面字符串和对象类型；显式 then/然后及目的从句不作为当前步骤。
3. 使用最新公开意图；过时意图进入排除审计。未明确当前阶段的跨类复合任务标为 current_phase_unspecified。
4. 检查启用目录、动作契约、软件目标、相反对象和已有执行阶段；lookup 走相同检查。
5. 仅对合格候选按相关性和稳定 ID 排序；当前包仍最多 3000 UTF-8 bytes，完整卡原子打包。

软件名称只是条件线索，不是焦点证明。不能用任务中出现过 GIMP/VLC 或启用了目录，推断当前窗口。未知软件时优先无按键的可见控件指导；缺少契约则记录具体缺口，不发送猜测绑定。

## 本次发现与修正

| 问题 | 修正 |
|---|---|
| 能力未冻结只记日志仍选卡 | capability_not_frozen 阻断对应候选，依赖按冻结集合检查 |
| open/find 对象不分 | 窗口、目录、网页、文件搜索分卡；不套用 Ctrl+O/Ctrl+F |
| confirm details/that 被当作 Enter | 判作结果检查，不匹配确认键 |
| 启用软件目录就选应用键 | 必须存在本次公开文本的软件目标，仍需当前图确认 |
| lookup 分数高可越过阶段 | 使用同一准入契约；已输入/已确认阶段排除重新输入 |
| 旧意图、未来步骤竞争 | 最新意图与显式当前步骤先筛选；其余记排除原因 |
| 混合主题全部返回 | 按明确动作提取已审查的绑定；不是截取前 N 条 |
| 新类型打断 Attempts 导航复用 | 导航索引和阅读调整链同步识别窗口/目录/网页/文件搜索类型 |

## 完整操作卡逐项对照

operations 是语义动作，不是只要字面出现就触发。绑定中 Enter/粘贴可以是后续依赖；不能据此反过来把所有 Enter 或粘贴需求匹配到整个工作流。

| 卡 ID | 动作契约 | 精确绑定 | 范围／条件 | 完整指导 |
|---|---|---|---|---|
| capture.image | capture | 无固定按键 | application or desktop capture controls; confirm what will be captured | Use the visible capture command; choose the intended area/window; inspect capture settings and actual output location; open the resulting image. |
| clipboard.copy | copy | copy=ctrl+c | selected GUI content; not a terminal | Confirm selection; copy; inspect selection and clipboard availability. |
| clipboard.copy_paste | copy | copy=ctrl+c; paste=ctrl+v | selected GUI content and intended destination; not a terminal | Confirm source selection; copy; navigate and focus the intended destination; paste; inspect the resulting content. Observe between stages. |
| clipboard.cut | cut | cut=ctrl+x | selected movable GUI content; not a terminal | Confirm source; cut; keep the intended destination in view before pasting. |
| clipboard.move_paste | cut | cut=ctrl+x; paste=ctrl+v | movable selected GUI content and intended destination; not a terminal | Confirm source selection; cut; navigate and focus the intended destination; paste; inspect both source and destination. Observe between stages. |
| clipboard.paste | paste | paste=ctrl+v | intended destination field or file pane; not a terminal | Confirm clipboard source and destination focus; paste once; inspect resulting content. |
| clipboard.transfer | copy, cut, transfer | copy=ctrl+c; cut=ctrl+x; paste=ctrl+v | selected GUI content and intended destination; not a terminal | Choose copy to keep the source or cut to move it; never perform both. Confirm destination focus; paste; inspect the resulting content. |
| clipboard.verify | paste | 无固定按键 | the destination of the previous paste | Inspect destination content and location; command return does not confirm the intended transfer. Do not paste again without checking. |
| document.find | find | find=ctrl+f | content window whose menu supports Find | Open Find; enter the desired query; inspect matches and navigation controls. |
| document.open | open | open=ctrl+o | content window whose File menu supports Open | Open the file dialog; choose the intended file; confirm and inspect the opened content. |
| document.read | reading | page_down=pagedown | focused scrollable document pane, not an input field | Read the visible region directly if readable; do not adjust to an arbitrary percentage. Reuse source-bound reading claims only for unchanged content. Advance only for an unseen region, then compare content. If unreadable, choose one direct adjustment and inspect its effect. |
| document.save | save | save=ctrl+s | editable document whose File menu supports Save | Save; handle any name/location dialog; inspect the saved result. Save is not format export. |
| document.save_as | save_as | save_as=ctrl+shift+s | editable content whose File menu explicitly supports Save As; not Export | Use the verified Save As command; inspect name, location and format; confirm and inspect the saved file. Do not substitute Save or assume format export. |
| export.file | export | 无固定按键 | application with a visible Export command | Use Export or Export As; choose format, name and location; review format options; confirm and reopen the output. Do not assume Save exports. |
| files.copy | copy | copy=ctrl+c; paste=ctrl+v | GNOME Files or compatible file pane; verify focus | Select source; copy; navigate to intended destination; paste; inspect source and destination. Observe between steps. |
| files.find | file_find | 无固定按键 | file manager or file chooser with a visible file-search control | Use the visible search control for the named file/folder; inspect the scope and matches. Do not assume content Find searches files. |
| files.move | cut, move | cut=ctrl+x; paste=ctrl+v | GNOME Files or compatible file pane; verify focus | Select source; cut; navigate to intended destination; paste; inspect source and destination. Observe between steps. |
| files.rename | rename | rename=f2; confirm=return | selected file in GNOME Files or compatible file pane | Open rename; inspect selected basename and extension; enter the requested name; confirm and inspect the resulting name. |
| files.transfer | transfer, copy, cut, move | copy=ctrl+c; cut=ctrl+x; paste=ctrl+v | GNOME Files or compatible file pane; verify focus | Choose copy to keep the source, or cut to move it; never perform both. Navigate to destination; paste; inspect both locations. Observe between stages. |
| focus.verify | 无匹配回退 | 无固定按键 | current visible GUI | Confirm application, modal dialog and focused control. Re-locate the target in the current image before retrying. If the expected change is absent, inspect a visible menu or another supported route; do not reuse old coordinates blindly. No shortcut is selected without a matching need. |
| folder.open | folder_open | 无固定按键 | visible file manager, folder pane or location control | Locate the intended folder or location control; open/navigate once; inspect the displayed location. Do not substitute a document Open shortcut. |
| gimp.export | export | gimp_export=ctrl+shift+e | GIMP image window; documented for 2.10, verify current menu binding | Use File > Export As; choose format, name and location; inspect format options; confirm and reopen the output. |
| history.undo | undo | undo=ctrl+z | editable content window supporting Undo | Undo one edit; inspect the result before repeating. |
| image.edit | image_edit | undo=ctrl+z | visible editable image canvas; confirm layer, selection and active tool | Choose the applicable visible editing tool; inspect selection/affected region before an edit and the result after it. Repeated Delete without a changed selection is not evidence of progress. Check the whole requested result before finishing; export only when required by the public task. |
| menu.open | menu_open | 无固定按键 | visible enabled application menu | Locate the named menu in the current image; open it once; inspect the expanded items before choosing. Do not substitute the document Open shortcut. |
| navigation.down | down | page_down=pagedown | focused scrollable content pane | Scroll one page down and inspect the newly visible region. |
| navigation.horizontal | horizontal_scroll | 无固定按键 | content pane with a visible horizontal scrollbar or supported horizontal scrolling | Confirm the pane and requested left/right direction; scroll a small amount using its visible control; inspect newly exposed content and the scrollbar position before repeating. Do not scroll vertically to reveal clipped columns. |
| navigation.up | up | page_up=pageup | focused scrollable content pane | Scroll one page up and inspect the newly visible region. |
| pointer.drag | drag | 无固定按键 | visible draggable object and destination; native computer tool | Locate source in the current image; mouse_move to its coordinate, then left_click_drag to the destination coordinate. Duration changes speed, not start position. Inspect actual movement; if unclear, re-ground or use an applicable menu/clipboard workflow. |
| text.confirm | confirm | confirm=return | focused dialog control with a known confirm action | Inspect the entered value and active button before confirming; observe the resulting state. |
| text.edit | edit | select_text=ctrl+a | focused editable text field; not a canvas or terminal | Confirm editable focus and intended replacement range; select text only if replacing the whole field; type the user-provided value; inspect it. |
| text.replace_confirm | edit, confirm | select_text=ctrl+a; confirm=return | editable field in a dialog with a verified Enter-to-confirm action | Verify editable focus and replacement range; select the field text only for full replacement; type; inspect the value; confirm; inspect the resulting state. |
| ui.dismiss | dismiss | dismiss=escape | active dismissible popup | Check whether dismissing discards unsaved input; dismiss once and inspect focus. |
| url.open | url_open | 无固定按键 | confirmed browser address/navigation control | Use the visible address control for the requested URL; inspect the destination page after navigation. Do not substitute document Open. |
| view.readability | reading, readability | 无固定按键 | reading goal or reported unreadability; inspect the current view | Readable now: read directly. Unreadable: choose ONE applicable visible fit command, window adjustment or frozen app zoom binding; verify app/focus, execute once, inspect readability. Use a numeric field only for a required precise ratio. Clipping is not clipboard cut. |
| view.zoom_check | zoom_value | 无固定按键 | after confirmation of a proposed zoom entry | Inspect actual scale/content first. Enter or a new screenshot does not prove the change. If readable, read directly. If still unreadable, choose one applicable visible fit/window/zoom command and check its effect; do not repeat numeric entry without a precise-ratio need. |
| view.zoom_confirm | zoom_value | confirm=return | a zoom value was entered; verify the zoom field is still focused | Do not select or type again. If the zoom field is still focused, confirm once; inspect actual scale/content. If focus changed, inspect the field before any key. Read directly when readable; a key receipt does not prove zoom. |
| view.zoom_in | zoom_in | 无固定按键 | confirmed visible Zoom In control; relative increase is needed | If already readable, read. Otherwise use the visible Zoom In command once and inspect readability/clipping. A frozen app binding is an alternative only after checking app/focus. Do not enter a number unless a precise ratio is required. |
| view.zoom_out | zoom_out | 无固定按键 | confirmed visible Zoom Out control; relative decrease is needed | If already readable with the needed bounds visible, read. Otherwise use the visible Zoom Out command once and inspect bounds/readability. A frozen app binding needs confirmed app/focus. Do not use numeric entry for an arbitrary percentage. |
| view.zoom_value | zoom_value | select_text=ctrl+a; confirm=return | an exact zoom ratio is required and the editable zoom field is confirmed | Only for a required precise ratio: focus the field, select text, type the value, confirm once; inspect actual scale and content. If already entered, only confirm/check; if confirmed, only check. Readable content needs no arbitrary target percentage. |
| vlc.capture | capture | vlc_snapshot=shift+s | VLC 3.x Linux player; verify menu binding, not a text field | Use Video > Take Snapshot or its verified shortcut; inspect the configured snapshot location and resulting image. Do not assume a default path. |
| window.locate | window_locate | 无固定按键 | a named application/window or desktop overview; focus unconfirmed | Locate the requested window in the current view or visible switcher; select it once and inspect its title/content. Do not use document Open as a window-switch command. |
| window.maximize | maximize | maximize=alt+f10 | GNOME active window; verify it is not already maximized | Toggle maximization once; inspect window bounds. This is a toggle: repeating it can undo the change. Re-locate controls after resizing. |

## 原目录逐主题、逐绑定对照

“待契约”表示目录内容仍保留，但在新版能力路径中不接受仅凭 lookup 注入该绑定；这是一项明确的覆盖限制，需补充独立语义测试后才能放行。历史目录模式不受此门禁影响。“已映射”也仍受冻结能力、平台、软件对象、最新动作及当前阶段约束。

| Topic | 每条 intent → 语义动作／状态 | 适用范围 | 检查方式 |
|---|---|---|---|
| app.after_effects.timeline | position property [p] → 仅平台参考; scale property [s] → 仅平台参考; rotation property [r] → 仅平台参考; opacity property [t] → 仅平台参考 | After Effects timeline; selected layer, no text editing | Recheck app/focus, enabled state and visible effect. |
| app.audacity.editing | split clip [ctrl+i] → 待契约; duplicate audio [ctrl+d] → 待契约; export audio dialog [ctrl+shift+e] → 待契约 | Audacity selected audio | An export dialog or saved project does not establish an exported audio file; inspect format, path and output. |
| app.audacity.playback | play or pause [space] → play; record [r] → 待契约 | Audacity project timeline | Recheck app/focus, enabled state and visible effect. |
| app.autocad.panels | toggle properties palette [ctrl+1] → 仅平台参考; toggle command line [ctrl+9] → 仅平台参考; toggle clean screen [ctrl+0] → 仅平台参考; toggle ortho mode [f8] → 仅平台参考 | AutoCAD active drawing | Recheck app/focus, enabled state and visible effect. |
| app.blender.viewport | menu search [f3] → 待契约; toggle edit mode [tab] → 待契约; toggle sidebar [n] → 待契约; toggle toolbar [t] → 待契约 | Blender 3D viewport; pointer over viewport, not text input | Recheck app/focus, enabled state and visible effect. |
| app.chrome.bookmarks | bookmark page [ctrl+d] → 待契约; bookmark manager [ctrl+shift+o] → 待契约 | Chrome browser UI | Recheck app/focus, enabled state and visible effect. |
| app.chrome.find | find page text [ctrl+f] → find; next find match [ctrl+g] → 待契约 | Google Chrome page content | Recheck app/focus, enabled state and visible effect. |
| app.chrome.panels | downloads [ctrl+j] → 待契约; history [ctrl+h] → 待契约 | Chrome browser UI | Recheck app/focus, enabled state and visible effect. |
| app.edge.find | find page text [ctrl+f] → 仅平台参考; next find match [ctrl+g] → 仅平台参考 | Microsoft Edge page content | Recheck app/focus, enabled state and visible effect. |
| app.edge.private_window | new InPrivate window [ctrl+shift+n] → 仅平台参考 | Edge browser UI | Recheck app/focus, enabled state and visible effect. |
| app.evince.page_navigation | next PDF page [ctrl+pagedown] → 待契约; previous PDF page [ctrl+pageup] → 待契约 | Evince PDF document pane | Recheck app/focus, enabled state and visible effect. |
| app.evince.zoom | zoom out [ctrl+-] → zoom_out; zoom in [ctrl++] → zoom_in | Evince PDF document | Recheck app/focus, enabled state and visible effect. |
| app.excel.cells | format cells [ctrl+1] → 仅平台参考; fill down [ctrl+d] → 仅平台参考; insert current date [ctrl+;] → 仅平台参考; go to cell [ctrl+g] → 仅平台参考 | Excel worksheet grid | Recheck app/focus, enabled state and visible effect. |
| app.file_explorer.navigation | edit address [alt+d] → 仅平台参考; parent folder [alt+up] → 仅平台参考; create folder [ctrl+shift+n] → 仅平台参考 | File Explorer folder view | Recheck app/focus, enabled state and visible effect. |
| app.finder.files | rename selected item [return] → 仅平台参考; new folder [command+shift+n] → 仅平台参考; Go to Folder dialog [command+shift+g] → 仅平台参考; Quick Look selection [space] → 仅平台参考 | Finder file selection | Recheck app/focus, enabled state and visible effect. |
| app.firefox.find | find page text [ctrl+f] → find; next find match [ctrl+g] → 待契约 | Mozilla Firefox page content | Recheck app/focus, enabled state and visible effect. |
| app.firefox.private_window | new private window [ctrl+shift+p] → 待契约 | Firefox browser UI | Recheck app/focus, enabled state and visible effect. |
| app.gimp.history | undo image edit [ctrl+z] → undo; redo image edit [ctrl+y] → 待契约 | GIMP image editing | Recheck app/focus, enabled state and visible effect. |
| app.gimp.zoom | zoom out [-] → zoom_out; actual pixels [1] → actual_pixels | GIMP canvas; not text tool | Recheck app/focus, enabled state and visible effect. |
| app.github.repository | show keyboard help [shift+/] → 待契约; file finder [t] → 待契约 | GitHub repository outside editable fields; shortcuts enabled | Recheck app/focus, enabled state and visible effect. |
| app.gitlab.help | show keyboard help [shift+/] → 待契约 | GitLab page outside editable fields; shortcuts enabled | Recheck app/focus, enabled state and visible effect. |
| app.gnome_files.hidden_files | toggle hidden files [ctrl+h] → 待契约 | GNOME Files folder view | Recheck app/focus, enabled state and visible effect. |
| app.gnome_files.rename | rename file [f2] → rename | GNOME Files selected file; basename or complete name | Observe selection: basename or full name. Preserve the extension exactly once; verify after confirm. |
| app.inkscape.objects | duplicate object [ctrl+d] → 待契约; group objects [ctrl+g] → 待契约; ungroup objects [ctrl+shift+g] → 待契约 | Inkscape canvas selection | Recheck app/focus, enabled state and visible effect. |
| app.libreoffice_calc.data | format cells [ctrl+1] → 待契约; fill down [ctrl+d] → 待契约; edit active cell [f2] → 待契约 | Calc grid, not formula editing | Recheck app/focus, enabled state and visible effect. |
| app.libreoffice_impress.slideshow | slideshow from first slide [f5] → 待契约; slideshow from current slide [shift+f5] → 待契约 | Impress editor | Recheck app/focus, enabled state and visible effect. |
| app.libreoffice_writer.formatting | Heading 1 [ctrl+1] → 待契约; Heading 2 [ctrl+2] → 待契约; insert page break [ctrl+return] → 待契约 | Writer document paragraphs | Recheck app/focus, enabled state and visible effect. |
| app.libreoffice_writer.search | find [ctrl+f] → find; find and replace [ctrl+h] → 待契约 | Writer document | Recheck app/focus, enabled state and visible effect. |
| app.mail.drafts | new draft [command+n] → 仅平台参考; attach file dialog [command+shift+a] → 仅平台参考 | Mail compose UI | Recheck app/focus, enabled state and visible effect. |
| app.matlab.editor | focus editor [ctrl+shift+0] → 待契约; new script [ctrl+n] → 待契约; save script [ctrl+s] → 待契约; maximize editor [ctrl+shift+m] → 待契约 | MATLAB Editor, not Command Window or Simulink | Recheck app/focus, enabled state and visible effect. |
| app.notes.notes | new note [command+n] → 仅平台参考; new folder [command+shift+n] → 仅平台参考; main Notes window [command+0] → 仅平台参考 | Notes editor | Recheck app/focus, enabled state and visible effect. |
| app.outlook.drafts | new mail draft [ctrl+shift+m] → 仅平台参考; reply [ctrl+r] → 仅平台参考; reply to all [ctrl+shift+r] → 仅平台参考 | Outlook classic mail view | Recheck app/focus, enabled state and visible effect. |
| app.photoshop.layers | duplicate selected layer [ctrl+j] → 仅平台参考; new layer dialog [ctrl+shift+n] → 仅平台参考; free transform [ctrl+t] → 仅平台参考 | Photoshop default keymap, selected layer | Recheck app/focus, enabled state and visible effect. |
| app.powerpoint.editing | new slide [ctrl+m] → 仅平台参考; duplicate selected object [ctrl+d] → 仅平台参考; group selected objects [ctrl+g] → 仅平台参考 | PowerPoint slide editor, not outline text | Recheck app/focus, enabled state and visible effect. |
| app.premiere.playback | play backwards [j] → 仅平台参考; stop [k] → 仅平台参考; play forwards [l] → 仅平台参考; play or stop [space] → 仅平台参考 | Premiere timeline; no text field focus | Recheck app/focus, enabled state and visible effect. |
| app.preview.navigation | next page [alt+down] → 仅平台参考; previous page [alt+up] → 仅平台参考; full screen toggle [ctrl+command+f] → 仅平台参考 | Preview PDF/image viewer | Recheck app/focus, enabled state and visible effect. |
| app.pycharm.navigation | find action [ctrl+shift+a] → 待契约; recent files [ctrl+e] → 待契约; go to file [ctrl+shift+n] → 待契约; go to line [ctrl+g] → 待契约 | PyCharm Windows/Linux keymap | Recheck app/focus, enabled state and visible effect. |
| app.safari.navigation | address bar [command+l] → 仅平台参考; new tab [command+t] → 仅平台参考; reload page [command+r] → 仅平台参考 | Safari browser UI | Recheck app/focus, enabled state and visible effect. |
| app.textedit.document | new document [command+n] → 仅平台参考; open document [command+o] → 仅平台参考; save document [command+s] → 仅平台参考 | TextEdit editable document | Recheck app/focus, enabled state and visible effect. |
| app.thunderbird.messages | new draft [ctrl+n] → 待契约; reply to sender [ctrl+r] → 待契约; reply to all [ctrl+shift+r] → 待契约; archive selected message [a] → 待契约 | Thunderbird message list, not compose body | Draft/reply actions do not send mail. Check recipient and body before any separately authorized send action. |
| app.vlc.playback | toggle playback [space] → play; stop playback [s] → stop; toggle full screen [f] → fullscreen | VLC player; not preferences text fields | Recheck app/focus, enabled state and visible effect. |
| app.vlc.seeking | short seek backward [shift+left] → seek_backward; short seek forward [shift+right] → seek_forward | VLC focused player | Recheck app/focus, enabled state and visible effect. |
| app.vscode.navigation | command palette [ctrl+shift+p] → 待契约; quick open file [ctrl+p] → 待契约; go to line [ctrl+g] → 待契约 | VS Code Linux default keymap; no Vim/Emacs extension | Recheck app/focus, enabled state and visible effect. |
| app.vscode.search | find in editor [ctrl+f] → 待契约; search workspace [ctrl+shift+f] → 待契约 | VS Code editor/workspace | Recheck app/focus, enabled state and visible effect. |
| app.word.paragraphs | align left [ctrl+l] → 仅平台参考; center paragraph [ctrl+e] → 仅平台参考; align right [ctrl+r] → 仅平台参考; page break [ctrl+return] → 仅平台参考 | Word editable document | Recheck app/focus, enabled state and visible effect. |
| clipboard | copy selection [ctrl+c] → copy; cut selection [ctrl+x] → cut; paste clipboard [ctrl+v] → paste | selected text/items in a conventional GUI; paste replaces a selection | Recheck app/focus, enabled state and visible effect. |
| combobox_open | open combobox option popup if supported [alt+down] → 待契约 | Focused dropdown/combobox with Alt+Down support; optional in WAI-ARIA widgets. | Verify the popup opened; otherwise use its visible opener. Do not apply this to ordinary text. |
| combobox_selection | focus previous option [up] → 待契约; focus next option [down] → 待契约; accept focused option [return] → 待契约; dismiss option popup [escape] → 待契约 | Open combobox list popup with option-navigation focus; not a calendar/grid popup. | Verify the committed field value; highlight alone may be provisional. Escape may clear editable input. |
| context_menu | open focused item context menu [shift+f10] → context_menu | focused conventional GUI item | Recheck app/focus, enabled state and visible effect. |
| control_activation | activate focused button [return] → 待契约; toggle focused checkbox or button [space] → 待契约 | focused button or checkbox; Return can submit a default dialog action | Recheck app/focus, enabled state and visible effect. |
| cursor_navigation | previous character [left] → 待契约; next character [right] → 待契约; field or line start [home] → 待契约; field or line end [end] → 待契约 | focused conventional single-line text field; check selection and cursor | Recheck app/focus, enabled state and visible effect. |
| document_file | open file chooser [ctrl+o] → open; save current editable content [ctrl+s] → save; open Save As dialog [ctrl+shift+s] → save_as; open print dialog [ctrl+p] → 待契约 | Active document/text/image content window whose File menu lists these bindings; no web-app shortcut capture. | Verify target content, path, format and dialog. Save may prompt; Save As is not Export. Print dialog is not print completion. |
| editing | select field text [ctrl+a] → edit; confirm current field or dialog [return] → confirm; dismiss current popup [escape] → dismiss | focused conventional editable text field | Verify focus and selection; Return may submit a default action or insert a newline. Inspect the resulting field/dialog. |
| find_text | open or focus content search [ctrl+f] → find | Content view with Ctrl+F listed as Find/Search; editors, readers or browsers, not a terminal. | Verify the search UI and its scope; type the query separately and inspect actual matches. |
| focus_navigation | next control [tab] → focus_next; previous control [shift+tab] → 待契约 | visible focusable controls | Recheck app/focus, enabled state and visible effect. |
| list_focus | focus previous item while retaining selection [ctrl+up] → 待契约; focus next item while retaining selection [ctrl+down] → 待契约 | Focused vertical multi-select list with modifier-based focus navigation. | Confirm focus moved but selected items stayed unchanged before list_selection. |
| list_navigation | focus previous list item [up] → 待契约; focus next list item [down] → 待契约; focus first item if supported [home] → 待契约; focus last item if supported [end] → 待契约 | Focused vertical list/listbox implementing standard navigation; Home/End are optional in web lists. | Distinguish focus from selection; arrows may select immediately. Home/End do not imply all virtualized items are loaded. |
| list_selection | extend selected range to previous item [shift+up] → 待契约; extend selected range to next item [shift+down] → 待契约; toggle focused item without clearing other selections [ctrl+space] → 待契约 | Focused multi-select list using modifier-based selection, not a text box; Ctrl+Space must not be captured by IME. | Verify selected items/count. Web listboxes may use a different selection model; stop if an IME opens. |
| menu_navigation | focus previous menu item [up] → 待契约; focus next menu item [down] → 待契约; activate focused menu item or open its submenu [return] → 待契约; close current menu level [escape] → 待契约 | Open vertical command menu with keyboard focus; excludes listboxes and text fields. | Read the item label and enabled state before activation; check resulting submenu, dialog or action. |
| menu_open | focus or open application menu [f10] → menu_open | Desktop application with a native menu/menubar supporting F10; not an arbitrary web page. | Verify a menu appeared, then use menu_navigation; custom menus may need their visible button. |
| multiline_navigation | move caret up one displayed line [up] → 待契约; move caret down one displayed line [down] → 待契约; move caret to document start [ctrl+home] → 待契约; move caret to document end [ctrl+end] → 待契约 | Focused multiline text editor in text-edit mode; no completion popup or grid focus. | Verify caret position and scroll offset; wrapping and editor keymaps affect line movement. |
| multiline_selection | extend selection up one displayed line [shift+up] → 待契约; extend selection down one displayed line [shift+down] → 待契约; select to document start [ctrl+shift+home] → 待契约; select to document end [ctrl+shift+end] → 待契约 | Focused multiline text editor; selection anchored at the current caret. | Inspect highlighted text; do not interpret a spreadsheet range as a text selection. |
| page_navigation | scroll one viewport down [pagedown] → down; scroll one viewport up [pageup] → up | scrollable text/document pane; not timeline/grid/terminal | Verify the intended pane scrolled; editable text may also move the caret. Do not infer exact PDF page changes. |
| popup_dismiss | dismiss popup [escape] → dismiss | focused popup, menu or cancellable dialog | Recheck app/focus, enabled state and visible effect. |
| radio_group | select previous radio option [left] → 待契约; select next radio option [right] → 待契约; select focused radio option [space] → 待契约 | Focused standard radio group outside a toolbar; horizontal arrow navigation supported. | Check the filled radio indicator; arrows may change the value immediately. Tab leaves the group. |
| slider_adjust | decrease slider one step [left] → 待契约; increase slider one step [right] → 待契约; set slider to minimum [home] → 待契约; set slider to maximum [end] → 待契约 | Focused horizontal slider using normal left=decrease/right=increase and Home/End endpoints; no canvas focus. | Read the actual value/units after one key; inverted/RTL sliders can reverse direction. Endpoint keys change the value. |
| spinbutton_adjust | increase numeric value one step [up] → 待契约; decrease numeric value one step [down] → 待契约 | Focused numeric spinbutton supporting Up/Down stepping; not a plain text field. | Verify value, units, bounds and step size. Use text editing only if direct input is supported. |
| submenu_navigation | open focused item submenu when present [right] → 待契约; return from submenu to parent menu [left] → 待契约 | Focused item in a conventional left-to-right menu hierarchy with nested submenus. | Verify submenu and focus; top-level menubars and reversed layouts can change arrow behavior. |
| tablist_navigation | focus previous tab label [left] → 待契约; focus next tab label [right] → 待契约; activate focused tab if manual activation [return] → 待契约; activate focused tab with Space if manual activation [space] → 待契约 | Focus on a tab label in a horizontal tablist implementing arrow navigation; not browser content or editor text. | Inspect active tab and panel; focus can activate automatically. Vertical tablists use a different arrow axis. |
| text_delete | delete selection or preceding character [backspace] → 待契约; delete selection or following character [delete] → 待契约 | Focused editable text field only; existing selection is deleted as a whole. | Check the resulting text; outside a text field Delete may remove an item or file. |
| text_selection | extend selection right [shift+right] → 待契约; select to field or line end [shift+end] → 待契约; select to field or line start [shift+home] → 待契约; extend selection left [shift+left] → 待契约 | focused conventional single-line text field | Recheck app/focus, enabled state and visible effect. |
| tree_navigation | focus previous visible node [up] → 待契约; focus next visible node [down] → 待契约; expand collapsed node or enter first child [right] → 待契约; collapse expanded node or focus parent [left] → 待契约 | Focused tree implementing unmodified-arrow expansion (WAI-ARIA/Windows convention); check keymap first. | Verify node expansion and focus. GNOME documents Shift+arrows for expansion; do not assume all desktop trees match. |
| undo | undo last edit [ctrl+z] → undo | focused editable GUI supporting undo | Recheck app/focus, enabled state and visible effect. |
| window_close | request closing active window [alt+f4] → 待契约 | Active application window on Linux/Windows; no desktop-only focus or save dialog pending. | Confirm the intended window; handle Save/Discard/Cancel explicitly. Closing a window is not task completion. |
| window_menu | open active window system menu [alt+space] → 待契约 | Active managed desktop window on Linux/Windows supporting the system window menu. | Verify the system menu and choose by its visible labels; do not assume localized mnemonic letters. |
| window_switch | switch window or application [alt+tab] → window_switch; switch window or application in reverse order [alt+shift+tab] → 待契约 | Linux/Windows desktop; GNOME groups windows by app; recheck selection | Recheck app/focus, enabled state and visible effect. |
| word_delete | delete toward previous word boundary [ctrl+backspace] → 待契约; delete toward next word boundary [ctrl+delete] → 待契约 | Focused editable text field with no selection; default word-deletion bindings. | Inspect the text and caret; for a precise range select first, then use text_delete. |
| word_navigation | move to previous word boundary [ctrl+left] → 待契约; move to next word boundary [ctrl+right] → 待契约 | Focused conventional text field; default word-navigation keymap, no terminal/IME capture. | Check caret and selection; word boundaries depend on language and punctuation. |
| word_selection | extend selection by one word left [ctrl+shift+left] → 待契约; extend selection by one word right [ctrl+shift+right] → 待契约 | Focused conventional text field; extend from the current selection anchor. | Inspect the highlighted range before replacing or deleting it. |
| platform.gnome.window_geometry | begin moving window [alt+f7] → 待契约; begin resizing window [alt+f8] → 待契约 | GNOME active window; arrows then Return/Escape | Recheck app/focus, enabled state and visible effect. |
| platform.gnome.window_maximize | toggle maximize [alt+f10] → maximize | GNOME active window; maximize/restore toggle | Recheck app/focus, enabled state and visible effect. |
| platform.gnome.window_minimize | minimize active window [win+h] → 待契约 | GNOME active window | Recheck app/focus, enabled state and visible effect. |
| platform.macos.editing | copy selection [command+c] → 仅平台参考; paste clipboard [command+v] → 仅平台参考; undo edit [command+z] → 仅平台参考; select all [command+a] → 仅平台参考 | macOS conventional text controls | Recheck app/focus, enabled state and visible effect. |
| platform.macos.windows | switch application [command+tab] → 仅平台参考; minimize window [command+m] → 仅平台参考; close current window [command+w] → 仅平台参考 | macOS application windows | Recheck app/focus, enabled state and visible effect. |
| platform.windows.window_maximize | maximize active window [win+up] → 仅平台参考; restore or minimize [win+down] → 仅平台参考 | Windows active window | Recheck app/focus, enabled state and visible effect. |
| platform.windows.window_menu | open window menu [alt+space] → 仅平台参考 | Windows active window | Recheck app/focus, enabled state and visible effect. |
| type.browser.navigation | focus address bar [ctrl+l] → 待契约; back in history [alt+left] → 待契约; forward in history [alt+right] → 待契约; reload page [ctrl+r] → 待契约 | Chrome/Firefox/Edge browser chrome; page scripts can intercept keys | Recheck app/focus, enabled state and visible effect. |
| type.browser.tabs | new tab [ctrl+t] → 待契约; close current tab [ctrl+w] → 待契约; restore closed tab [ctrl+shift+t] → 待契约 | Chrome/Firefox/Edge tab controls | Recheck app/focus, enabled state and visible effect. |
| type.browser.zoom | zoom page out [ctrl+-] → zoom_out; zoom page in [ctrl++] → zoom_in; reset page zoom [ctrl+0] → 待契约 | Chrome/Firefox/Edge page zoom, not embedded application zoom | Recheck app/focus, enabled state and visible effect. |
| type.document.document | open document dialog [ctrl+o] → open; save current document [ctrl+s] → save; print dialog [ctrl+p] → 待契约 | Writer/Word editable document | Recheck app/focus, enabled state and visible effect. |
| type.document.formatting | toggle bold [ctrl+b] → 待契约; toggle italic [ctrl+i] → 待契约; toggle underline [ctrl+u] → 待契约 | selected text in Writer/Word | Recheck app/focus, enabled state and visible effect. |
| type.file_manager.file_transfer | cut selected files [ctrl+x] → cut; copy selected files [ctrl+c] → copy; paste into current folder [ctrl+v] → paste | GNOME Files/Explorer selected source; navigate to destination before paste | Verify selected source, destination and resulting files; clipboard return does not prove transfer. |
| type.file_manager.rename | rename selected file [f2] → rename | GNOME Files/Explorer selected file; observe editable basename or complete name | Observe selection: basename or full name. Preserve the extension exactly once; verify the confirmed filename. |
| type.media.playback | toggle play or pause [space] → play | VLC/Audacity playback area; text input must not have focus | Recheck app/focus, enabled state and visible effect. |
| type.presentation.slides | start presentation from beginning [f5] → 待契约; exit presentation [escape] → 待契约 | Impress/PowerPoint presentation editor | Recheck app/focus, enabled state and visible effect. |
| type.spreadsheet.cells | edit active cell [f2] → 待契约; confirm cell entry [return] → confirm; next worksheet [ctrl+pagedown] → 待契约; previous worksheet [ctrl+pageup] → 待契约 | Calc/Excel grid; leave cell edit mode before sheet navigation | Recheck app/focus, enabled state and visible effect. |
| type.terminal.clipboard | copy selected terminal text [ctrl+shift+c] → 待契约; paste into terminal [ctrl+shift+v] → 待契约 | GNOME Terminal; Ctrl+C interrupts a foreground process | Pasting can execute multiline shell input; inspect the text and current prompt first. |
| type.text_editor.files | open file dialog [ctrl+o] → open; save file [ctrl+s] → save; find text [ctrl+f] → find | VS Code/Writer text editing, not terminal prompt | Recheck app/focus, enabled state and visible effect. |
| type.web_app.focus | next focusable control [tab] → 待契约; previous focusable control [shift+tab] → 待契约 | standard HTML controls in web applications; custom widgets may differ | Recheck app/focus, enabled state and visible effect. |

## 语义触发规则

| 动作 | 有边界的规则（还需通过状态／对象／阶段排除） |
|---|---|
| actual_pixels | `\bactual pixels\b\|实际像素` |
| capture | `\bscreenshot\b\|\bsnapshot\b\|\bcapture\b\|截图\|截屏\|快照` |
| confirm | `\bconfirm\b\|确认\|确定` |
| context_menu | `\bcontext menu\b\|上下文菜单\|右键菜单` |
| copy | `\bcopy\b\|复制` |
| cut | `\bcut\b\|剪切` |
| dismiss | `\bdismiss\b\|\bcancel\b\|取消\|关闭弹窗` |
| down | `\bscroll down\b\|向下滚` |
| drag | `\bdrag(?:ging)?\b\|拖拽\|拖动` |
| edit | `\breplace\b\|\btype\b\|\benter text\b\|输入\|替换` |
| export | `\bexport\w*\b\|导出` |
| file_find | `\b(?:find\|search for\|locate)\s+(?:(?!(?:then\|and\|but\|to)\b)[\w-]+\s+){0,5}(?:file\|folder\|directory)\b\|(?:查找\|搜索)(?:(?!然后\|随后\|并且)[^。；]){0,12}(?:文件\|目录)` |
| find | `\bfind\b\|\bsearch\b\|搜索\|查找` |
| focus_next | `\bnext (?:field\|control)\b\|下一个控件\|下一个输入框` |
| folder_open | `\b(?:open\|enter\|navigate to)\s+(?:(?!(?:then\|and\|but\|to)\b)[\w-]+\s+){0,5}(?:folder\|directory)\b\|(?:打开\|进入)(?:(?!然后\|随后\|并且)[^。；]){0,12}(?:目录\|文件夹)` |
| fullscreen | `\bfull ?screen\b\|全屏` |
| horizontal_scroll | `\bscroll (?:left\|right)\b\|向左滚\|向右滚\|横向滚动` |
| image_edit | `\b(?:edit\|modify\|crop\|retouch\|resize)\b[^.;\n]{0,32}\b(?:image\|picture\|photo\|canvas)\b\|\b(?:remove\|erase\|delete)\b[^.;\n]{0,32}\bbackground\b\|\b(?:make\|set)\b[^.;\n]{0,32}\btransparent\b\|(?:编辑\|裁剪\|修改\|缩放)(?:图像\|图片\|照片)\|(?:删除\|移除\|去除)背景\|(?:设为\|变为\|改为)透明` |
| maximize | `\bmaximi[sz]e\b\|最大化` |
| menu_open | `\bopen\s+(?:(?!(?:then\|and\|but\|to)\b)[\w-]+\s+){0,4}menu\b\|打开(?:(?!然后\|随后\|并且)[^。；]){0,8}菜单` |
| move | `\bmove\b\|移动\|搬移` |
| open | `\bopen\b\|打开` |
| paste | `\bpaste\b\|粘贴` |
| play | `\b(?:play\|pause)\b\|播放\|暂停` |
| readability | `\b(?:make\|keep)\b[^.;\n]{0,32}\breadable\b\|\b(?:adjust\|change)\s+(?:the\s+)?zoom\b\|提高可读性\|调整缩放` |
| reading | `\b(?:read\|review\|compare\|cross[- ]?check\|reconcile\|inspect)\b\|阅读\|核对\|对比\|比较\|查看(?:内容\|文档\|文本\|数据)` |
| rename | `\brenam\w*\b\|重命名` |
| save | `\bsav(?:e\|ing)\b\|保存` |
| save_as | `\bsave\s+as\b\|另存为` |
| seek_backward | `\bseek backward\b\|快退` |
| seek_forward | `\bseek forward\b\|快进` |
| stop | `\bstop playback\b\|停止播放` |
| transfer | `\btransfer\b\|转移\|传送` |
| undo | `\bundo\b\|撤销` |
| up | `\bscroll up\b\|向上滚` |
| url_open | `\b(?:open\|visit\|navigate to)\s+(?:(?!(?:then\|and\|but\|to)\b)[\w-]+\s+){0,5}(?:website\|webpage\|url\|web page)\b\|(?:打开\|访问)(?:(?!然后\|随后\|并且)[^。；]){0,12}(?:网页\|网站\|网址)` |
| window_locate | `\b(?:open\|find\|locate\|reopen)\s+(?:(?!(?:then\|and\|but\|to)\b)[\w-]+\s+){0,5}(?:window\|application\|app\|overview)\b\|(?:打开\|查找\|定位)(?:(?!然后\|随后\|并且)[^。；]){0,12}(?:窗口\|应用\|概览)` |
| window_switch | `\bswitch\b[^.;。]*\b(?:window\|application\|app)\b\|切换窗口\|切换应用` |
| zoom_in | `\bzoom in\b\|\benlarge\b\|放大` |
| zoom_out | `\bzoom out\b\|缩小` |
| zoom_value | `\b(?:set\|change\|adjust\|type\|enter)\b[^.;\n]{0,24}\b(?:zoom\|scale)\b[^.;\n]{0,16}(?:\d+(?:\.\d+)?\s*%\|exact\|precise\|numeric)\|\b(?:set\|type\|enter)\s+(?:the\s+)?(?:exact\|precise\|numeric)\s+zoom\b\|\bzoom\s+(?:in\s+\|out\s+)?to\s+\d+(?:\.\d+)?\s*%\|(?:设置\|输入\|调整)(?:精确\|准确)?(?:缩放\|比例)[^。；\n]{0,12}\d+(?:\.\d+)?\s*%` |

## 验证与限制

独立通用例子见 tests/test_guidance_eligibility_v7.py：每张卡的正例、否定／状态／同词不同对象反例、冻结能力缺失、lookup 绕过、菜单目的从句、阶段冲突和目录重排。真实 actor 请求模拟另验证预算、来源、恢复及 flat/linked 同输入一致性；没有新增模型调用、GUI 重跑或成功率结论。

语义仍是确定性有界规则，不是完备自然语言理解；不能保证所有新表达都已覆盖。未知情况保留本地排除原因。完整 URL、规则、排除列表和哈希留本地，模型只收到短完整卡及必要缺口。
