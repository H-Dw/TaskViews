# TaskViews-mini v4：产物核验、有效操作记忆和相关键盘参考

本次实现修订为 `mini_artifact_evidence_v4`，保留 `mini_fixed_v1` profile 名、current/keyboard/attempts/lessons 四视图和 **3000 UTF-8 bytes** 总包上限。没有增加模型角色、应用 API、GUI 探测、任务专用答案或正式评测。baseline、共同 compiler、模型/坐标/轮数/输出预算和官方环境不变。

## 产物状态与成功终止

current.artifact.verification 与 lessons 的 artifact_verification_state 显式记录四项：

- `source_confirmed`：产物来源是否确认。
- `content_previewed`：候选内容是否预览。
- `name_correct`：最终文件名是否正确。
- `destination_confirmed`：目标目录是否确认。

没有独立认证证据时均为 `unknown`。模型写“confirmed”、观察图发生变化、文件时间更新、菜单关闭或控制器返回成功，都不会把它们升级为 verified。

同一 actor 可以在公开文本中给出 `<artifact_review>` JSON；这与隐藏推理无关，也不会启动另一个模型。例子中的路径和观察描述均是占位说明，实际必须来自当前任务 GUI：

```text
<artifact_review>{"applicable":true,"candidate":"observed candidate path","checks":{
"source_confirmed":{"ref":12,"observed":"visible source evidence"},
"content_previewed":{"ref":28,"observed":"candidate contents visible in current preview"},
"name_correct":{"ref":24,"observed":"visible final filename"},
"destination_confirmed":{"ref":24,"observed":"visible target folder"}}}</artifact_review>
```

`ref` 是包内 sources 表引用的 observation 序号。成功终止前会检查四项报告齐全、引用属于当前 episode 与同一原始任务、内容预览引用当前观察。无产物任务可明确报告 `{"applicable":false,"reason":"why no artifact is required"}`。缺失、伪造或过期引用会在派发 DONE 前拒绝候选，并沿用原有 actor 修复池和截止时间；不新增重试池。失败终止保持原语义。

**这个门禁验证复核过程和来源引用，不自动认证视觉语义。** 四项模型报告仍分级为未独立验证；无产物声明也属于模型报告，并非程序自动判定任务适用性。程序不会假装具备未实现的通用产物识别器。将来若加入独立语义验证器，应单独声明来源、权限和评测协议，不能把本实现的 unknown 改成伪造的 verified。

artifact review 从本 episode 的不可变 journal 重新投影，不依赖模型历史窗口；任务输入改变后不复用旧任务的产物报告和关键操作投影。键盘参考继续按同episode的实际键盘记录分级展示，不据此宣称当前任务效果。检查点绑定新 profile contract，旧 v3 不能静默载入新语义。

## 3000 bytes内的选择与审计

默认顺序为：当前原始观察与未知状态 → 最近有效操作及后续观察 → 未解决执行错误／产物报告 → 匹配的键盘参考 → 可容纳的重复证据、其他历史和通用提醒。

操作检索跳过 screenshot/wait，因此连续很多被动调用也不会将上一个点击、输入或快捷键挤出检索窗口。被动调用作为有效操作的 followup 关联，记录其后真实观察。关键操作的前、后观察与 followup 均有独立引用，效果仍是 unknown。

每个原始 event 的SHA-256与kind只在 `sources` 表保留一次，记录用数字ref关联；episode_id与ref序号共同定位原journal中的完整UUID和原始payload，再核对hash，避免在prompt重复UUID。完整命令、回执、错误和图片继续保存在原journal。大错误不切片成断章取义的文本，会明确转向原始引用；可容纳的原失败status/returncode/error作为failure_signal保留。未选中的来源不占包空间。

遥测除了四个view_id，还记录 `selected_operations`、`latest_operation_delivered`、`artifact_review_delivered`，用于检查关键内容是否实际进入prompt。四视图存在不等同于每个视图都有记录。键盘未匹配和整条记录不能容纳时允许显式省略，不扩大预算。

## 具体键盘需求

keyboard升级为 `mini_keyboard_v2`。只按最新公开意图或显式 `<key_lookup>主题</key_lookup>` 选择；单独出现“window”“folder”等词、不匹配或格式错误时不提供泛用参考，不沿用陈旧计划。目录区分：

| 主题 | 适用范围/参考 |
|---|---|
| window_maximize | GNOME最大化切换，Alt+F10 |
| window_minimize | GNOME最小化，Super+H，后端token为win |
| window_switch | GNOME应用切换，Super+Tab，操作后重查焦点 |
| rename | Files中F2；先观察选中的是basename还是完整文件名，扩展名保留一次，确认后再观察 |
| file_transfer | Files中剪切、复制、粘贴；保留原始焦点/效果未知说明 |

没有新增任何媒体截帧、特定任务文件名、固定坐标或gold知识。键名与GNOME参考来源为[官方键盘导航](https://help.gnome.org/gnome-help/keyboard-nav.html)、[最大化说明](https://help.gnome.org/gnome-help/shell-windows-maximize.html)、[文件重命名说明](https://help.gnome.org/gnome-help/files-rename.html)，以及冻结PyAutoGUI/Qwen backend。它们是有适用范围的参考，不证明当前焦点或实际快捷键配置。

## 观察图与用户产物

Mini通用说明明确：computer_use.screenshot是桌面观察，不是应用导出的用户产物。时间更新、菜单关闭和returned回执都不能认证内容正确。说明在当前frame contract中，即使可选包不能容纳也不会被历史折叠移除。

观察服务缓存文件在普通文件管理器Recent可见的问题，需要另立环境版本处理。本次没有修改guest、Recent、server缓存路径或官方OSWorld初态，避免悄悄改变已有实验条件。未来环境隔离需要新镜像/配置哈希、两组共同条件和独立报告。

## 验证范围

新增离线回归覆盖：普通confirmed不产生事实；四项报告仍unknown；伪造/过期/跨任务引用拒绝；裸成功候选在派发前拒绝并只使用原修复池；当前内容复核和无产物报告；多个被动调用后保留真实操作及后观察；真实来源hash可解引用；具体窗口意图与不匹配省略；baseline和失败终止不受Mini门禁影响；旧检查点拒绝。

原500轮mock恢复、原始native策略、provider和冻结预算回归一起检查。模拟runner的终止响应补充了明确标为synthetic的review，只验证协议，benchmark_score仍为null；不能作为真实图像理解或成绩提升的证据。

2026-10-16最终验收：**313项回归全部通过、Ruff通过**，其中新增20项产物/证据回归；500轮及第250轮恢复通过，末轮原生assistant/tool配对保留。固定当前帧说明限制在700字符以内，未扩大原上下文预算。回归使用128MiB/零swap scope，峰值122,675,200 bytes（约117MiB），无OOM。

四个原运行器模拟场景通过：baseline与Mini各7轮提前终止；Mini40轮上限、80条模拟命令；Mini40轮空动作、0命令。运行器在2GiB/零swap scope串行执行，HTTP、VM与GUI均由夹具阻断/模拟；发票夹具不输出单例cgroup指标，scope证据来自显式启动参数。原GIMP/VLC的35个证据文件逐一核对hash均未改变，巡检仍PAUSED。

- [完整验收记录](../outputs/mini-artifact-v4-acceptance-20261016.json)
- [313项回归与源码/资源检查](../outputs/mini-artifact-v4-regression-20261016-v3.json)
- [实际送入模拟传输层的视图包示例](../outputs/mini-artifact-v4-prompt-example-20261016.json)
- [四个模拟场景输出](../outputs/mini-artifact-v4-runner-20261016-v3/)

开发过程中触及长历史边界的v1/v2失败报告保留。最终v3在原预算内通过，没有降低500轮测试的原生历史配对要求。

旧GIMP/VLC运行、原结果、prompt和审计不覆盖。旧media入口仍锁定v3检查点并拒绝当前源码；新正式评测必须另建经审阅的计划和源码快照。本次没有启动或恢复正式评测，也没有启用巡检。

用户随后授权单独评测VLC/Mini。通用`verified_invoice.py`入口的`--task vlc --experiment sx-mini-max-high40`现在只派发taskviews一组，保持原双组实验的模型、high推理、40次predict、3000 bytes、坐标、资源保护和评分条件。该单组分支不能用于GIMP；旧四格入口的源码锁保持原样。新增入口通过28项契约测试及VLC的limit/terminate/empty三个原运行器模拟场景、四个合成官方metric案例和Ruff检查，证据位于`outputs/verified-vlc-mini-v4-20261016-v1/`。正式结果必须保存到新的runs目录。
