# GIMP 背景透明化与 VLC 截帧：Max/high40 待审评测

本批只准备代码、素材和离线证据。用户尚未授权正式启动。配置为随想 `qwen3.8-max`、`enable_thinking=true`、`reasoning_effort=high`，每组最多40次 `actor.predict`，包含空动作。模型原生名为 `qwen3.8-max`，与用户所称 qwen-3.8-max 对应。

当前 TaskViews-mini 已先提交快照 `49fefeb8b9d028f420b986790fa25d534409a3bf`，父提交为 `0a5b6f2`。快照前工作树中的受跟踪代码已全部提交，因此使用空 checkpoint commit 标记此版本。原有未跟踪 `ccfa-workfiles/` 不在本批提交中。新入口会核对 Mini 实现文件与该快照逐字节一致。

## 任务中的工具操作

| 任务 | 任务初态与目标 | GUI 操作涉及的工具 | 官方评分 |
| --- | --- | --- | --- |
| GIMP `2a729ded-3296-423d-aec4-7dd55ed5fbb3` | GIMP 打开桌面 `dog_with_background.png`；使背景透明，保留狗的主体 | 处理可能出现的色彩配置弹窗；检查 alpha 通道，必要时 Layer → Transparency → Add Alpha Channel；Fuzzy Select（魔棒）或 Select by Color 选择背景、调整阈值、逐块 Delete；误伤主体时 Undo；观察棋盘格、毛发边缘和残留 | 原 `check_structure_sim`，尺寸必须一致，再按 RGB 结构相似度默认阈值0.9返回0/1。alpha 不被单独验证，满分不等于逐像素抠图完美 |
| VLC `fba2c100-79e8-42df-ae74-b592418d54f4` | 官方先打开 Interstellar 预告片，按120.5–121秒参数播放并暂停；将当前帧存为桌面 `interstellar.png` | Video → Take Snapshot，或 Linux 默认 Shift+S；文件管理器查找新截帧，F2/重命名；需要时 Ctrl+X → Desktop → Ctrl+V，或拖动；检查文件名、扩展名和位置 | 原 `compare_images`：转灰度、按原逻辑调整尺寸并返回 SSIM 浮点值；不设自定义二值阈值 |

GIMP 原 evaluator 自带 `postconfig`：Ctrl+Shift+E、输入 `dog_without_background`、确认 PNG 导出，再取 `/home/user/Desktop/dog_without_background.png`。此流程保持原样，由官方评分阶段执行，不增加到40个 actor 决策轮中。Agent 原始指令不要求预知该隐藏评分文件名；不把后处理步骤、gold 路径或示范解法加入 actor 提示。

VLC 的 `computer_use.screenshot` 仅取得桌面观察图；交付的视频帧由 VLC 内部的 Take Snapshot 功能生成。模型应根据实际界面定位菜单或使用快捷键，随后通过文件管理器完成文件交付。Shift+S 是常见默认绑定，不能据此假定某一实际配置永远不变。

两组模型都只调用现有 native `computer_use`：`left_click/right_click/double_click`、`mouse_move/left_click_drag`、`key/key_down/key_up`、`type`、`scroll/hscroll`、`screenshot/wait`、`terminate/call_user` 等。快捷键以 `key` 的 `keys` 参数传递，例如 `['shift','s']`。Agent 不使用终端、脚本或应用 API。官方 setup / evaluator 自带的命令仍由原执行器执行。

以上为评测者阅读的操作解释，不是向任一 actor 注入的任务攻略。历史 UI-TARS 轨迹与 gold 均不进入新 episode 和记忆。当前 GIMP 官方配置只向 guest 下载原图；2025年历史轨迹曾使用的桌面 gold 配置不复用。

官方依据：[GIMP 固定任务](https://github.com/xlang-ai/OSWorld/blob/b138d348256078fa634fc3b73567a7337c793e6b/evaluation_examples/examples/gimp/2a729ded-3296-423d-aec4-7dd55ed5fbb3.json)、[VLC 固定任务](https://github.com/xlang-ai/OSWorld/blob/b138d348256078fa634fc3b73567a7337c793e6b/evaluation_examples/examples/vlc/fba2c100-79e8-42df-ae74-b592418d54f4.json)、[GIMP 透明度说明](https://docs.gimp.org/2.10/en/gimp-using-web-transparency.html)、[VLC 3.0 默认截图键源码](https://videolan.videolan.me/vlc-3.0/libvlc-module_8c.html)。评分实现：[GIMP](https://github.com/xlang-ai/OSWorld/blob/b138d348256078fa634fc3b73567a7337c793e6b/desktop_env/evaluators/metrics/gimp.py)、[VLC](https://github.com/xlang-ai/OSWorld/blob/b138d348256078fa634fc3b73567a7337c793e6b/desktop_env/evaluators/metrics/vlc.py)。

## 四组配置

固定顺序为 GIMP/baseline → GIMP/TaskViews-mini → VLC/baseline → VLC/TaskViews-mini。每格一次；每组独立进程、新官方 Docker guest 可写层、新 actor、新 journal。上一组完成原评分并清理其精确所有权容器后接续；异常停止，不自动重跑或恢复旧 episode。

| 设置 | LLM baseline | TaskViews-mini |
| --- | --- | --- |
| 模型、推理、轮数 | `qwen3.8-max / high / 40` | 相同 |
| actor / 工具链 | 共同 native actor、SX provider、官方 Qwen compiler 与 OSWorld-1 controller | 相同的共同执行链 |
| 扩展上下文 | 无 selector，无 Mini 对象，无额外 frame guidance；被动审计不回注模型 | `mini_fixed_v1 / mini_keyboard_memory_v3`，`current/keyboard/attempts/lessons`，合计3000 UTF-8 bytes |
| 额外分析角色请求 | 0 | 0 |
| 历史与坐标 | history20、image1、fold1；relative 每轴0–1000；1920×1080 | 相同 |
| 文本与输出 | text32000/reserve10000；消息序列化上限12M字符；请求输出16000、单步32000、两次语义修复池 | 相同 |

Mini 继续使用当前通用键盘视图，没有新增 GIMP/VLC 快捷键知识、任务专用视图或固定动作路线。40轮按 `actor.predict` 计，API重试、修复、GUI动作及 evaluator 后处理另外计数。

共同资源保持 VM3GiB（guest2GiB）、actor2GiB、辅助进程128MiB、零swap；Windows真实空闲RAM>2GiB，C/D空闲阈值45/12GiB。运行前、每轮和评分前复查，启动时重新测量。官方环境和评分取自 `xlang-ai/OSWorld@b138d348256078fa634fc3b73567a7337c793e6b`；共同 actor helper/compiler 取自 `OSWorld-V2@3d778a3c9a34a079316f70df023b166700445792`。

## 准备与审阅入口

- 配置：[configs/verified-media-max-high40.json](../configs/verified-media-max-high40.json)。
- 新入口：[scripts/verified_media.py](../scripts/verified_media.py)，复用扩展后的 `verified_invoice.py` 生命周期与资源保护。
- 待审矩阵：`runs/verified-media-sx-max-high40-20261016-v1/matrix.json`；每个任务各有独立 `plan.json`、`state.json`、`preflight.json`。
- 官方素材及哈希：`../osworld_verified_setup/media-assets-20261016/gimp/assets.json` 和 `vlc/assets.json`。只向 guest stage 原任务 `download` 输入；gold 仅放宿主 evaluator cache。
- 离线原 runner 集成：`outputs/verified-media-validation-20261016-v3/<gimp|vlc>/<baseline|taskviews>-<limit|terminate|empty>/validation.json`。
- 合成图片评分接入验证：同级 `<task>/metrics/validation.json`。使用原 `DesktopEnv.evaluate`、原 getters 和原 metric；GUI后处理模拟、图片合成，不读取官方任务/gold像素，不产生 benchmark 成绩。
- 相关回归：`outputs/verified-media-regression-20261016-v4.json`。原先的开发验证失败原件保留，不作为当前通过证明。
- 审阅汇总：`runs/verified-media-sx-max-high40-20261016-v1/review.json`。

最终代码已通过118项相关回归与全仓Ruff检查；12个原runner模拟场景及8个合成图片评分接入场景全部通过。上限场景各40次模拟请求、80条模拟GUI命令；提前终止场景7轮、12条模拟命令；空动作场景40轮、0命令。Mini每次提供声明的四视图，baseline无扩展视图。完整actor集成的实际峰值约151.5–206.4MiB，零swap。日志中的 `0.125` 是模拟 evaluator 哨兵值，所有离线报告均为 `benchmark_score=null`。

`prepare` 只读取本地素材与离线证据、冻结计划。`check` 只验证源码、计划、依赖、镜像和已有兼容证据；不调用模型、不启动 VM、不操作 GUI、不运行真实任务评分。此次不调用真实模型探针，所以在用户审阅阶段 `ready_for_launch=false` 是预期状态；需要当前源码绑定的真实 provider 与 Mini 定位诊断证据后，启动门禁才放行。旧发票任务的接口证明不会冒充本次新源码验证。

回归、素材准备和独立评分函数验证使用128MiB/零swap。完整 actor/runner 集成验证按现有 actor-service 预算使用2GiB/零swap，并记录实际峰值；真实运行预算保持原配置。该集成的 `evaluate` 返回模拟哨兵值，另以合成文件验证原 `DesktopEnv.evaluate/getters/metric`，两处都载入原评分器。开发阶段尝试将完整 actor 集成限制为128MiB时触及上限，失败目录v1/v2保留；最终证据使用独立v3目录。

后续正式启动仍须用户明确指令。届时先以各任务计划为 `--root` 运行 `probe_native_provider.py --provider sx`（文本、大图native工具、tool reply）及 `probe_mini_grounding.py --live`（Mini实际predict四位置诊断），收集全部位置并单列精度。通过兼容门禁后，在128MiB/零swap辅助scope内显式调用：

```bash
python scripts/verified_media.py launch \
  --root runs/verified-media-sx-max-high40-20261016-v1 \
  --execute-approved-plan
```

此命令在本次准备期间不执行。不更改既有发票任务计划指针、定时巡检或其他运行目录。
