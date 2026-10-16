# Max/high40 三组差异与 Mini 键盘视图修正

分析对象为 `runs/verified-invoice-sx-max-high40-20261015-v1`，运行提交 `0eff232`，同一随想 qwen3.8-max/high、40 次决策上限。原得分 UI-KOBE-like / baseline / Mini 为 **0 / 1 / 0**。本次修改不会回写原运行、重新评分或自动恢复评测。

## 分数的直接原因

官方任务要求比对后把不匹配发票放到 `problematic` 文件夹。原评分器从 `/home/user/Desktop/problematic/Invoice # 243729.pdf` 取文件并比较 PDF 文本。baseline 下载回来的结果文件与输入发票、gold 的 SHA256 完全相同（`39c23a5792795583184c3694de5b0187d895e6ef75d2e2cbfbdd16b23f1c3594`）。另两组取目标文件返回 404，因此得 0。这里不是要求“生成新的对账 PDF”，而是把原发票交付到指定位置。

三组最终都正确识别过 Staples 的 500 对 540 差异；决定分数的是是否完成文件操作。

| 阶段 | UI-KOBE-like | baseline | Mini |
|---|---|---|---|
| 首次打开流水 | 第1轮未出现阅读器，等待后第3轮重开成功 | 第1轮打开 | 第1轮打开 |
| 读到三笔付款 | 第5轮后已可读 | 第20轮 `pagedown` 后可读 | 第25轮选择70%后可读 |
| 看完三张发票 | 第11轮后已具备比较信息 | 第34轮后 | 第34轮后 |
| 创建目录 | 未执行 | 第29–31轮，确认 Create | 第38–40轮，只输入名称 |
| 移动发票 | 未执行 | 第36轮首次拖动不当；第37–40轮重定位、按下、拖动、释放 | 未执行 |
| 最后状态 | 回到文件管理器准备再次查看 | 目标文件已移入目录 | 新建目录对话框仍打开 |

UI-KOBE-like 第12–40轮主要用于重复核对、调整缩放和寻找流水行，已经得到的信息没有转化为交付进度。Mini 前25轮消耗在阅读流水，末尾又搜索 Home/Documents；40轮耗尽时连目录创建都尚未确认。baseline 也有错点、空白页误判、大幅滚动和一次拖动失败；它并非全程顺利，只是在预算内完成了关键操作。

## 已排除与尚未证实的环境问题

- 三组4份输入 PDF 分别逐字节一致，均能被离线 PDF 解析器打开；没有导入损坏证据。
- 流水共3页：文本长度分别933、0、17。第2页本来无文本，第3页仅模板署名。截图也显示对应空白页，不能把这类空白直接判断成渲染失败。
- Mini 与 baseline 第1轮后的截图均有已打开的阅读器；UI-KOBE-like 第3轮后也正常打开。第1轮未打开的具体原因无法仅凭现存记录区分双击时序、命中位置或启动延迟，没有日志证明持续应用故障。
- 三组 API 均完整返回，无网络重试、VM OOM或控制器报错；真实空闲 RAM 均大于2 GiB。零分不是这次的资源保护或网关问题。
- 控制器 `returncode=0/status=success` 只说明 Python 命令返回。它不能证明按键有效、页面滚动或文件移动。

## 两个确定的操作语义缺口

**键名命名空间混用。** baseline 第20轮原生参数是 `keys=["pagedown"]`。Mini 第15轮与 UI-KOBE-like 第33轮是 `keys=["Page_Down"]`；原 compiler 仅转小写，生成 `pyautogui.press("page_down")`。Mini 第21轮还生成了 `hotkey("ctrl", "minus")`。PyAutoGUI 接受的是 `pagedown` 和字符 `-`，这些 X11 风格名称不会被自动翻译。离线执行已安装 X11 后端的原函数、替换所有 I/O 后，无效名称产生0个键事件，正确名称产生按下/释放2个事件。

**滚动单位与定位语义不清。** schema 的字段名为 `pixels`，但原 compiler 直接生成 `pyautogui.scroll(n)`；PyAutoGUI 的 n 是滚轮格数。原后端的离线测试中 `-5/-300/-600` 分别产生5/300/600个滚轮事件。scroll 中的 coordinate 会被验证，却没有进入最终命令，也不会移动指针。三组都有数百格滚动，常越过正文或在侧栏滚动；这不是软件不响应的充分证据。

原官方 compiler、schema、评分器保持不变。Mini 新增的是生成前的准确说明、可检索操作参考和末端校验，未偷偷改写坐标、键名或滚动值。

## LLM 输入究竟有什么不同

对照 baseline20、Mini15/21、UI-KOBE-like33 的真实 `api_request`：system SHA 全部为 `57d2dab7…`，tools SHA 全部为 `ef58b5b3…`。共同 `keys` 描述只有 `Keys for key/key_down/key_up.`，没有元素枚举、backend 名称或映射例子。共同 system 强调 action 标识符中的 underscores；此要求本身正确，但没有明确区分 action 和 keys 的命名空间。

| 生成前的输入 | baseline20 | Mini15 | UI-KOBE-like33 |
|---|---:|---:|---:|
| 保留 assistant 轮数 | 11 | 14 | 15 |
| assistant 字段中的 `Page Down` 文本次数 | 1 | 9 | 4 |
| 当前额外视图重复 `Page Down` 的次数 | 0 | 2 | 0 |
| 输入里已有正确 `pagedown` 示例 | 0 | 0 | 0 |
| 输入里已有错误 `page_down` 示例 | 0 | 0 | 0 |

计数按保存的消息文本统计，包含 assistant reasoning 字段；不是对模型内部因果机制的测量。

baseline 没有更完整的键名字典，也没有抄到此前正确示范。这次它从已有模型知识生成了正确拼写。Mini 的最近2条 proposals 又在 lessons 中重复自然语言“Page Down”，加强操作意图，却没有把意图转换成 backend 参数；UI-KOBE-like 检索的大量回执、路径、哈希也不提供这项知识。Mini21 的保留历史里已出现错误 `page_down` 和 `minus` 的文字，存在自我重复风险。

因此，已证实的是**三组共同缺少映射，扩展记忆没有填补它**。自然语言重复、action 下划线规则泛化、成功回执、历史裁剪和上下文负担都可成为诱因，但单次轨迹无法证明哪一个导致错误。新视图采用独立命名空间、完整工具参数示例以及来源分级；不把“更多历史”视为默认改进。

## 本次实际代码修改

Mini 实现修订变为 `mini_keyboard_memory_v3`，默认固定视图由3个变为4个，总上限仍为3000 UTF-8 bytes：

| View | 当前职责 |
|---|---|
| current | 当前截图来源、坐标合同、滚轮真实单位、交付确认提醒 |
| keyboard | 意图→确切 keys 参数；按主题查询本 episode 的键盘记录 |
| attempts | 最近执行边及来源引用，效果不能由返回成功推定 |
| lessons | 真正执行错误优先，其次历史模型计划；都带来源和等级 |

`kobe_views/keyboard_view.py` 提供翻页、缩放、文件移动、窗口、编辑5类索引。优先处理同一 actor 的 `<key_lookup>zoom</key_lookup>` 等明确请求，否则依据最近计划的文字选择主题。选路标记为意图推断，**没有假装进行了视觉 app/focus 检测**。模型在生成前能直接读到 `{"action":"key","keys":["pagedown"]}`、`{"action":"key","keys":["ctrl","-"]}` 等完整调用。

快捷键参考来自 [Evince 导航/缩放文档](https://help.gnome.org/evince/movingaround.html)、[GNOME 文件移动文档](https://help.gnome.org/gnome-help/files-copy.html)、[窗口最大化文档](https://help.gnome.org/gnome-help/shell-windows-maximize.html)，键名编码来自本地 PyAutoGUI/官方 compiler。应用快捷键和 backend 键名分别标注；例如“滚动一个视口”和“切换 PDF 页”不是同一个操作。

keyboard memory 从原 journal 单独查询最近32条键盘执行边，按当前主题取最多2条，因而不会因中间超过4次鼠标操作而丢失。每条保留原事件 ID/SHA，分别记录键名是否可发出、截图字节是否改变及效果是否未知。无效旧键的建议修正标为“未执行的建议”，不伪造成功；截图改变也不升级为业务成功。新 episode 从空记忆开始，不跨运行导入 baseline 答案。检查点从 journal 重建同一索引。

视图是有界的可选输入：真实错误优先于通用工作流提醒；超预算时整条省略并报告遗漏，不增加文本、图片、模型输出或轮数预算。旧的 opt-in `mini_controls_v1` 保留其独立 pack，不与默认 keyboard pack 强塞到同一预算内。末端无效键名拦截只是兜底，沿用已有两次语义修复池，不自动重写候选。

## 验证和解释边界

离线回放把已保存的截图、原生候选和回执送入新 Mini，验证编译、历史、视图和记忆模块，**模型回复由记录提供**；它不证明新 Mini 自主完成了任务。按键生成探针另用当前 API，对相同截图/历史添加共同意图约束，比较三个上下文变体的首个候选，不执行 GUI、不给修复第二次机会。这两种证据分开报告。

原运行、gold、结果文件、完整图像均只在开发诊断中读取，不成为 runtime 的答案库。baseline 的1分与 Mini 新代码的潜在得分不能互相替代；正式分数仍需下一次独立冻结评测。

相关文件：[取证脚本](../scripts/analyze_verified_replay.py)、[离线回放脚本](../scripts/replay_mini_saved_run.py)、[输入/生成对照脚本](../scripts/probe_keyboard_generation.py)、[auto-research 策略](taskviews-mini-auto-research.md)。

## 已完成的验证

### 相同输入的真实模型生成对照

使用随想 `qwen3.8-max` / high，沿用 SX_URL_SB、原截图、原 schema 和输出上限。分别取旧 Mini 第15、21轮的保存输入，给每个变体添加相同的诊断意图。共6次 API 请求，每次仅一个首候选，无语义修复、GUI 或评分：

| 保存现场与共同意图 | 同一历史，移除附加视图 | 旧 Mini v2 视图 | 新 keyboard view＋键名引导 |
|---|---|---|---|
| Mini15：按 Page Down | `Page_Down`，无效 | `Page_Down`，无效 | `pagedown`，正确 |
| Mini21：键盘缩小 PDF | `ctrl,minus`，无效 | `ctrl,minus`，无效 | `ctrl,-`，正确 |

新上下文在两个案例均首轮给出正确键名，支持“生成前提供明确映射”的方向；它不依赖拦截后的重试。第一列使用的是 **Mini 的相同历史**，并非实际 baseline20 的历史。因此不能由此把原 baseline 成功归因于没有视图，也不能凭每格1次采样宣称总体成功率提高。此探针没有单独消融参考映射、引导文本和记忆；该问题留给后续研究批次。

总 usage 为56,310输入、612输出、56,922 total tokens；费用未知。在线测试完成后只调整了真实错误在视图打包中的优先级；最终实现重新构建的6份输入哈希与已发送输入全部一致，没有为得到更好结果再次请求 API。记录见 [生成报告](../outputs/mini-keyboard-generation-20261016-v1/report.json) 和 [最终证据索引](../outputs/mini-keyboard-release-20261016.json)。

### 模块与兼容性回归

- **231项不同测试全部通过**：键名引导/选择/来源验证、原生协议、修复上限、旧 controls、profile、检查点和500轮模拟轨迹。500轮测试在250轮恢复，验证早期真实错误与最新工具记录均保留。
- 三组保存轨迹共 **120次决策、122条编译命令** 与原 compiler 完全匹配。新拦截识别 UI33、Mini15/21 的已知无效键；baseline 全部候选保留。
- 将 baseline 的40份真实观察、记录回复和回执送入实际 Mini `predict`，40轮回放通过；所有视图包不超过3000 bytes，无模型请求、GUI执行或评分。上游源码未变。
- 原运行器的 Mini/Max/high/40轮限制路径通过离线集成：模拟40请求、80命令、一次模拟评分，确认默认四视图送达和资源/轮数配置。报告中的0.125是 **mock sentinel**，没有新官方成绩。
- Ruff 与 `git diff --check` 通过。开发中发现并修复过“keyboard 挤掉早期真实错误”的回归；最终打包优先级已覆盖该测试，失败记录保留。

证据：[93项核心回归](../outputs/mini-keyboard-final-r3.xml)、[138项兼容回归](../outputs/mini-keyboard-compat-final.xml)、[完整保存轨迹回放](../outputs/mini-keyboard-baseline-replay-20261016-final/report.json)、[原运行器模拟集成](../outputs/mini-keyboard-official-runner-20261016/validation.json)。本轮未启动新 VM 或正式评测，`osworld-20` 继续暂停；新代码的 `official_score=null`。
