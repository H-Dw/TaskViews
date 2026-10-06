"""Bounded background supervisor/report generator for this local WSL profile.

Docker caps total 3.75 GiB; this process and the entire runner process tree must
be in one systemd service with MemoryMax=2 GiB and MemorySwapMax=0.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import traceback

GIB = 1024**3
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts.osworld_task035_profiles import profile_for, description  # noqa: E402 - repository path is initialized first
ROOT = Path.home() / "osworld2"
REPOSITORY = ROOT / "OSWorld-V2"
PYTHON = REPOSITORY / ".venv/bin/python"
SERVICE_LIMIT = 2 * GIB
DOCKER_LIMIT = 3.75 * GIB
START_AVAILABLE_GIB = 6
REPORT = PROJECT / "docs/osworld21-qwen-task035-full-run.md"
WEB_CAPS = {"caddy": 128 * 1024**2, "teamchat_web_backend": 512 * 1024**2,
            "teamchat_web_frontend": 128 * 1024**2}
REPORT_CALLBACK = None


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_json(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def host_status():
    return json.loads(subprocess.check_output([
        "/mnt/c/Users/Wei/AppData/Local/Programs/Python/Python313/python.exe",
        r"D:\cua_lty\osworld_local_setup\host_status.py"], text=True, timeout=15))


def cgroup():
    relative = Path("/proc/self/cgroup").read_text().strip().split(":")[-1]
    return Path("/sys/fs/cgroup") / relative.lstrip("/")


def verify_service_budget():
    group = cgroup()
    actual = {name: (group / name).read_text().strip() for name in ("memory.max", "memory.high", "memory.swap.max")}
    if actual["memory.max"] != str(SERVICE_LIMIT) or actual["memory.swap.max"] != "0":
        raise RuntimeError("Start through the supplied bounded systemd service; memory limits are required")
    return str(group), actual


def runner_command(manifest):
    output = Path(manifest["official_results"])
    profile = profile_for(manifest.get("model"))
    command = [str(PYTHON), str(PROJECT / "scripts/run_official_qwen_task035.py"),
            "--local-memory-profile", "minimal", "--detailed-log-dir", str(Path(manifest["run_dir"]) / "telemetry"),
            "--headless", "--provider_name", "docker", "--path_to_vm", str(ROOT / "images/osworld-v2-ubuntu-x86.qcow2"),
            "--screen_width", "1920", "--screen_height", "1080", "--observation_type", "screenshot",
            "--action_space", "pyautogui", "--model", manifest.get("model", "qwen3.6-35b-a3b"),
            "--base_url", manifest.get("base_url", "https://pjfdspqowq.a.pinggy.link"),
            "--no-enable_thinking", "--no-stream", "--no-batch_actions", "--temperature", str(profile["temperature"]), "--top_p", str(profile["top_p"]),
            "--max_tokens", "16000", "--max_steps", "500", "--sleep_after_execution", "3", "--num_envs", "1",
            "--eval_version", "v2", "--domain", "tasks", "--specific_task_id", "035",
            "--client_password", "osworld-public-evaluation", "--max_api_retries", "3", "--request_timeout", "120",
            "--generation_timeout", "90", "--cache_dir", str(output.parent / "cache"), "--result_dir", str(output),
            "--save_model_eval_raw_info"]
    if profile["provider"] == "kimi":
        command.extend(["--model-profile", "kimi-k3"])
    if manifest.get('agent_protocol') == 'kimi-k3-native-tools-stream-v1':
        if manifest.get('model') != 'kimi-k3' or manifest.get('arm') != 'baseline':
            raise ValueError('Native K3 protocol is a separately named baseline')
        command.append('--native-kimi')
        command[command.index('--no-stream')] = '--stream'
        command[command.index('--request_timeout') + 1] = '600'
        command[command.index('--generation_timeout') + 1] = '600'
        command[command.index('--max_api_retries') + 1] = '2'
    if manifest.get("arm") == "taskviews":
        command.extend(["--taskviews-config", manifest["taskviews_config"]])
    return command


def prepare_web(client, manifest, manifest_path):
    containers = client.containers.list(all=True, filters={"label": "com.docker.compose.project=osworld-local-web"})
    services = {item.labels.get("com.docker.compose.service"): item for item in containers}
    if set(services) != set(WEB_CAPS):
        raise RuntimeError("Expected the three existing TeamChat containers; no build or extra services are allowed")
    running = []
    for name, container in services.items():
        config = container.attrs["HostConfig"]
        if config["Memory"] != WEB_CAPS[name] or config["MemorySwap"] != WEB_CAPS[name]:
            raise RuntimeError(f"TeamChat hard limit mismatch: {name}")
        running.append(bool(container.attrs["State"]["Running"]))
    if any(running) and not all(running):
        raise RuntimeError("Partially running TeamChat profile; refusing ambiguous service ownership")
    manifest["web_owned"] = not all(running)
    manifest["web_container_ids"] = [item.id for item in services.values()]
    atomic(manifest_path, manifest)
    if manifest["web_owned"]:
        for name in ("teamchat_web_backend", "teamchat_web_frontend", "caddy"):
            services[name].start()
    import requests
    with requests.Session() as session:
        session.trust_env = False
        for _ in range(60):
            try:
                response = session.get("http://127.0.0.1:21280/api/info", headers={"Host": "teamchat.127.0.0.1.nip.io"}, timeout=3)
                if response.status_code == 200:
                    return
            except requests.RequestException:
                pass
            time.sleep(1)
    raise RuntimeError("TeamChat did not become ready")


def sample(client, manifest):
    group = Path(manifest["cgroup"])
    service_memory = int((group / "memory.current").read_text())
    events = dict(line.split() for line in (group / "memory.events").read_text().splitlines())
    items = client.containers.list(all=True, filters={"label": f"ui-kobe.osworld.run={manifest['run_id']}"})
    web = [client.containers.get(identifier) for identifier in manifest.get("web_container_ids", [])]
    containers = []
    total_cap, total_used = 0, 0
    for container in items + web:
        container.reload()
        config, state = container.attrs["HostConfig"], container.attrs["State"]
        expected = 3 * GIB if container in items else WEB_CAPS[container.labels["com.docker.compose.service"]]
        if config["Memory"] != expected or config["MemorySwap"] != expected:
            raise RuntimeError(f"Container memory cap changed: {container.name}")
        total_cap += config["Memory"]
        stats = container.stats(stream=False, one_shot=True).get("memory_stats", {}) if state["Running"] else {}
        used = stats.get("usage", 0)
        total_used += used
        containers.append({"id": container.id, "name": container.name, "usage_bytes": used,
                           "limit_bytes": config["Memory"], "running": state["Running"],
                           "oom_killed": state["OOMKilled"], "memory_stats": stats})
    if total_cap + SERVICE_LIMIT >= 6 * GIB:
        raise RuntimeError("Aggregate component hard limits reached 6 GiB")
    return {"time_utc": now(), "windows": host_status(), "service_memory_bytes": service_memory,
            "service_memory_events": events, "aggregate_usage_bytes": service_memory + total_used,
            "aggregate_hard_cap_bytes": int(DOCKER_LIMIT + SERVICE_LIMIT), "containers": containers}


def read_events(run_dir):
    events = []
    for path in (run_dir / "telemetry").glob("events-*.jsonl"):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                    # Full requests remain on disk; report generation needs no
                    # accumulated message histories or embedded request payloads.
                    event.pop("payload", None)
                    events.append(event)
                except json.JSONDecodeError:
                    continue  # The last record may still be being written.
    return sorted(events, key=lambda record: record["time_utc"])


def render_report(run_dir):
    manifest = read_json(run_dir / "manifest.json", {})
    state = read_json(run_dir / "state.json", {"status": "preparing"})
    model = manifest.get("model", "qwen3.6-35b-a3b")
    arm = manifest.get("arm", "baseline")
    native = manifest.get('agent_protocol') == 'kimi-k3-native-tools-stream-v1'
    agent_label = "官方 Qwen Agent" if arm == "baseline" else "UI-KOBE TaskViews Agent（官方 harness）"
    if native:
        agent_label = 'K3 原生工具协议 baseline（SSE，官方动作编译器与 harness）'
    events = read_events(run_dir)
    decisions = [event for event in events if event["event"] == "decision"]
    actions = [event for event in events if event["event"] == "action_result"]
    responses = [event for event in events if event["event"] == "api_response"]
    errors = [event for event in events if event["event"].endswith("error")]
    official = Path(manifest["official_results"])
    result_files = list(official.glob("**/tasks/035/result.txt"))
    score = result_files[0].read_text().strip() if result_files else None
    state.update(decisions=len(decisions), completed_actions=len(actions), api_responses=len(responses),
                 api_errors=sum(event["event"] == "api_error" for event in errors),
                 official_score=score, task_done=actions[-1].get("done") if actions else None,
                 latest_event=events[-1]["time_utc"] if events else None, report_updated_utc=now())
    atomic(run_dir / "state.json", state)
    blocks = ["# Task035 Qwen 完整运行：逐步记录", "",
              "仅记录接口实际返回的文字说明、XML 与执行结果。thinking 关闭；不推断未公开的内部推理。", ""]
    if native:
        blocks = ['# K3 原生工具协议 baseline：逐步记录', '',
                  '记录 API 实际返回的 reasoning/content/tool_calls、完整分片、动作与回执；K3 thinking=max。', '']
    for event in events:
        kind = event["event"]
        if kind == "observation":
            blocks += [f"## 第 {event['step']} 步 — {event['time_utc']}", ""]
            image = event.get("screenshot")
            if image:
                blocks += [f"动作前截图：[打开](telemetry/{image['image']})", ""]
        elif kind == "decision":
            blocks += ["模型返回（原生 reasoning/content/tool_calls）：" if native else "模型返回（包含解释及原始 XML）：", "", "````text", event.get("response", ""), "````", "",
                       "解析后的动作：", "", "````json", json.dumps(event.get("parsed_actions"), ensure_ascii=False, indent=2), "````", ""]
        elif kind in ("controller_result", "action_result", "action_error", "decision_error", "evaluation_result", "evaluation_error"):
            details = {k:v for k,v in event.items() if k not in ("pid", "time_utc", "phase", "step", "screenshot")}
            blocks += ["````json", json.dumps(details, ensure_ascii=False, indent=2), "````", ""]
            image = event.get("screenshot")
            if image:
                blocks += [f"动作后截图：[打开](telemetry/{image['image']})", ""]
        elif kind in ("api_response", "api_error"):
            response = event.get("response", {})
            blocks += [f"API：{event.get('status_code')}；耗时 {event.get('duration_s')} s；request_id={event.get('request_id')}。", ""]
            if kind == "api_response":
                blocks += [f"模型={response.get('model')}；usage={json.dumps(response.get('usage'), ensure_ascii=False)}。", ""]
            else:
                blocks += [f"错误：{event.get('error_type')} {event.get('error')}", ""]
    atomic(run_dir / "transcript.md", "\n".join(blocks))
    relative = run_dir.relative_to(PROJECT / "docs").as_posix()
    status_labels = {"preparing": "正在准备", "running": "后台运行中", "completed": "运行及评分结束",
                     "failed": "异常停止，未取得有效评分", "stopped": "保护或用户停止", "service_stopped": "后台服务停止"}
    sample_data = state.get("latest_resources", {})
    windows = sample_data.get("windows", {})
    audit = read_json(official / "source-audit.json", {})
    end_epoch = datetime.fromisoformat(state["ended_utc"]).timestamp() if state.get("ended_utc") else time.time()
    elapsed = round(end_epoch-manifest.get("started_epoch", end_epoch), 1)
    lines = ["# OSWorld v2.1 Task035：Qwen 完整评测", "",
             f"更新时间（UTC）：{now()}；运行标识：`{manifest['run_id']}`。", "",
             f"**状态：{status_labels.get(state['status'], state['status'])}。** {state.get('reason', '')}", "",
             f"模型 `{model}`，{agent_label}，Task035，Docker，最多 **500 个 Agent 决策轮次**。模型返回终止动作时可提前结束。", "",
             "## 资源预算", "", "| 组件 | 硬上限 |", "| --- | ---: |",
             "| VM 容器（客体 RAM 2 GiB、2 vCPU） | 3 GiB |",
             "| TeamChat 后端 / 前端 / Caddy | 0.5 / 0.125 / 0.125 GiB |",
             "| supervisor、runner、全部 Python 子进程及日志程序共用 cgroup | 2 GiB |",
             "| 以上组件合计 | **5.75 GiB，小于 6 GiB** |", "",
             "上述为本次评测组件的内存硬上限，包含其 cgroup 计入的缓存；禁止这些组件使用额外宿主 swap。WSL 内核、Docker daemon 和其他程序另计，全局 WSL 保持原 8 GB 设置；客体自己的磁盘 swap 仍由原镜像管理。", "",
             f"启动前 Windows 至少 {manifest.get('startup_available_ram_gib', 8)} GiB 可用，运行期间低于 4 GiB，或 C/D 盘低于 35/10 GiB 时停止本次任务。仅停止本次 VM 与本次启动的 TeamChat。", "",
             "## 进度与结果", "", f"- 已返回决策：{len(decisions)}/500；已执行动作：{len(actions)}；运行约 {elapsed/60:.1f} 分钟。",
             f"- API 成功响应：{len(responses)}；API 错误：{state['api_errors']}。",
             f"- 最近动作 done：`{state['task_done']}`；官方 result.txt：`{score if score is not None else '尚未生成有效分数'}`。",
             f"- 已采样组件占用峰值：{state.get('peak_aggregate_bytes', 0)/GIB:.3f} GiB；最近采样：{sample_data.get('aggregate_usage_bytes', 0)/GIB:.3f} GiB。",
             f"- Windows 采样最低可用：{state.get('min_windows_available_gib', '尚无')} GiB；最近：{windows.get('available_ram_gib', '尚无')} GiB。",
             f"- OSWorld 源码校验：{audit.get('unchanged', '结束后进行')}；runner exit code：{state.get('runner_exit_code', '尚未退出')}。", "",
             "评分为 0 也是有效失败结果；进程退出 0 本身不证明任务通过。没有 result.txt 时不采用 summary 中的错误占位分数。", "",
             "## 记录与复查", "", f"- [逐步分析、XML、动作结果、截图索引]({relative}/transcript.md)",
             f"- [运行状态]({relative}/state.json) / [启动参数与硬限制]({relative}/manifest.json)",
             f"- [后台控制台]({relative}/console.log) / [15 秒资源采样]({relative}/resources.jsonl)",
             f"- 完整请求、响应、HTTP 状态、token usage 与截图：`{run_dir / 'telemetry'}`；请求图片按 SHA-256 去重，密钥不记录。",
             f"- 官方原始结果目录：`{official}`；评分结束后复制该任务证据到本记录目录 `official-task/`。", "",
             "## 参数与可比性", "",
             f"使用 {profile_for(model)['api_key_env']}，仅在 runner 进程映射 OPENAI_API_KEY。接口 {manifest.get('base_url')}；{description(model)} API 最多 3 次尝试，request_timeout=120 s。", "",
             "Task035 有随时间推进的消息；runner 按官方步骤和 DONE/FAIL 语义运行，不人工增加步骤或等待，也不把 500 理解为必须执行完 500 步。", "",
             f"环境、日志、内存和裁判兼容通过 UI-KOBE 项目外部包装器实现。本次不写 OSWorld 源码；保留此前已有的本机 Docker provider 配置。裁判和用户模拟器模型为 `{model}`；生成配置同模型协议，官方提示与评分规则保持原样。这是本机条件下的结果，不能等同公开榜单复现。", "",
             "WSL 中检查：`systemctl --user status " + manifest["unit"] + "`。停止本次运行：`systemctl --user stop " + manifest["unit"] + "`。", "",
             f"后台服务每 15 秒采样，约每 5 分钟刷新本报告；Codex 另设 {manifest.get('heartbeat_minutes', 5)} 分钟检查。无需前台终端，保持 Windows、WSL 和 Docker 运行，避免睡眠。", ""]
    if arm == "taskviews":
        lines += ["实验组每轮包含感知与决策两次 API 调用；记录返回的 JSON、TaskViews 上下文和编译后的 GUI 动作。500 步计数仍由官方 harness 执行。该组同时更换提示、历史策略与动作格式，因此不是只切换 TaskViews 的单因素消融。", ""]
    if native:
        lines[0] = '# OSWorld v2.1 Task035：K3 原生工具协议 baseline'
        lines = [line.replace('逐步分析、XML、动作结果', '逐步分析、原生工具调用、动作结果') for line in lines]
        lines = [line if 'API 最多 3 次尝试，request_timeout=120 s' not in line else
                 'K3 Agent 使用 SSE 与 tool_choice=required；reasoning_effort=max，max_completion_tokens=16000。连接15秒、分片空闲120秒、单次完整生成600秒、最多2次传输尝试合计900秒、整步930秒。完整 JSON 与动作校验后执行，协议失败不合成 DONE。既有裁判/模拟器 API 兼容与评分流程保持不变。' for line in lines]
        lines += ['新实验版本仅更换 Agent 接口、动作协议和期限；旧 XML baseline 的 0 分保留。原始 SSE 分片及首包/首片/完成时序在 telemetry/streams 与 api_response.timings。', '']
    atomic(Path(manifest.get("report_path", str(REPORT))), "\n".join(lines))
    if REPORT_CALLBACK is not None:
        REPORT_CALLBACK()
    return state


def cleanup(run_dir):
    import docker
    manifest_path = run_dir / "manifest.json"
    manifest = read_json(manifest_path, {})
    if not manifest:
        return
    client = docker.from_env(timeout=15)
    errors = []
    owned = client.containers.list(all=True, filters={"label": f"ui-kobe.osworld.run={manifest['run_id']}"})
    runtime_paths = set(manifest.get("runtime_paths", []))
    for container in owned:
        for mount in container.attrs.get("Mounts", []):
            source = Path(mount["Source"])
            candidate = source.parent
            if candidate.parent == (ROOT / "runtime") and candidate.name.startswith("desktop-"):
                runtime_paths.add(str(candidate))
        try:
            if container.attrs["State"]["Running"]:
                container.stop(timeout=15)
            container.remove()
        except Exception as exc:
            errors.append(f"VM cleanup: {type(exc).__name__}")
    if not errors:
        for value in runtime_paths:
            path = Path(value).resolve()
            if path.parent != (ROOT / "runtime").resolve() or not path.name.startswith("desktop-"):
                errors.append("Unexpected runtime path; not removed")
                continue
            if path.exists():
                shutil.rmtree(path)
    if manifest.get("web_owned"):
        for identifier in manifest.get("web_container_ids", []):
            try:
                container = client.containers.get(identifier)
                if container.labels.get("com.docker.compose.project") != "osworld-local-web":
                    raise RuntimeError("Web ownership label changed")
                container.reload()
                if container.attrs["State"]["Running"]:
                    container.stop(timeout=10)
            except docker.errors.NotFound:
                pass
            except Exception as exc:
                errors.append(f"Web cleanup: {type(exc).__name__}")
    official = Path(manifest["official_results"])
    before_path = official / "osworld-source-before.json"
    if before_path.exists() and not (official / "source-audit.json").exists():
        sys.path.insert(0, str(PROJECT))
        from ui_kobe.osworld.runner import source_snapshot
        before, after = read_json(before_path), source_snapshot(REPOSITORY)
        changed = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
        atomic(official / "source-audit.json", {"unchanged": not changed, "changed_paths": changed,
                                              "audit_by": "cleanup after runner exit"})
    state = read_json(run_dir / "state.json", {})
    state.update(cleanup_utc=now(), cleanup_errors=errors)
    if state.get("status") in (None, "preparing", "running"):
        state.update(status="service_stopped", ended_utc=now(), reason="后台服务已停止；请核对 systemd journal 中的退出或 OOM 原因。")
    atomic(run_dir / "state.json", state)
    render_report(run_dir)


def run(run_dir, unit, options=None):
    import docker
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        raise RuntimeError("Use a new run directory; refusing to repeat a previous task")
    group, limits = verify_service_budget()
    run_id = run_dir.name
    manifest = {"run_id": run_id, "run_dir": str(run_dir), "unit": unit, "started_utc": now(),
                "started_epoch": time.time(), "cgroup": group, "service_limits": limits,
                "official_results": str(ROOT / "results" / run_id / "qwen"),
                "aggregate_hard_cap_bytes": int(SERVICE_LIMIT + DOCKER_LIMIT), "runtime_paths": [],
                "startup_available_ram_gib": START_AVAILABLE_GIB}
    manifest.update(options or {})
    command = runner_command(manifest)
    manifest["runner_command"] = command
    atomic(manifest_path, manifest)
    state = {"status": "preparing", "peak_aggregate_bytes": 0}
    atomic(run_dir / "state.json", state)
    render_report(run_dir)
    client = docker.from_env(timeout=20)
    child = None
    stop_requested = False

    def request_stop(signum, frame):
        nonlocal stop_requested
        stop_requested = True
    previous_signals = {kind: signal.getsignal(kind) for kind in (signal.SIGTERM, signal.SIGINT)}
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        key_env = profile_for(manifest.get("model"))["api_key_env"]
        if not os.environ.get(key_env):
            raise RuntimeError(f"{key_env} is absent; nothing will be started")
        initial = host_status()
        if initial["available_ram_gib"] < START_AVAILABLE_GIB or initial["c_free_gib"] < 45 or initial["d_free_gib"] < 12:
            raise RuntimeError(f"Windows preflight reserve not met: {initial}")
        if client.containers.list(filters={"label": "osworld.local.owner=cua-lty-20260929"}):
            raise RuntimeError("Another OSWorld desktop is already running")
        prepare_web(client, manifest, manifest_path)
        environment = os.environ.copy()
        environment.update(OSWORLD_FULL_RUN_ID=run_id, PYTHONUNBUFFERED="1",
                           NO_PROXY="localhost,127.0.0.1,::1,.nip.io", no_proxy="localhost,127.0.0.1,::1,.nip.io")
        with (run_dir / "console.log").open("a", encoding="utf-8") as console:
            child = subprocess.Popen(command, cwd=REPOSITORY, env=environment, stdout=console,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            state.update(status="running", runner_pid=child.pid, initial_windows=initial)
            atomic(run_dir / "state.json", state)
            next_report = 0
            failures = 0
            while child.poll() is None:
                try:
                    record = sample(client, manifest)
                    failures = 0
                    with (run_dir / "resources.jsonl").open("a", encoding="utf-8") as log:
                        log.write(json.dumps(record) + "\n")
                    state["latest_resources"] = record
                    state["peak_aggregate_bytes"] = max(state["peak_aggregate_bytes"], record["aggregate_usage_bytes"])
                    available = record["windows"]["available_ram_gib"]
                    state["min_windows_available_gib"] = min(state.get("min_windows_available_gib", available), available)
                    profile = read_json(Path(manifest["official_results"]) / "resource-profile.json", {})
                    metadata = read_json(ROOT / "logs/last-container.json", {})
                    if profile.get("container") == metadata.get("id") and metadata.get("runtime"):
                        manifest["runtime_paths"] = [metadata["runtime"]]
                        atomic(manifest_path, manifest)
                    windows = record["windows"]
                    if available < 4 or windows["c_free_gib"] < 35 or windows["d_free_gib"] < 10:
                        state.update(status="stopped", reason="Windows 内存或磁盘保留量触发保护停止。")
                        stop_requested = True
                    if any(item["oom_killed"] for item in record["containers"]):
                        state.update(status="stopped", reason="本次容器发生 OOM，停止评测。")
                        stop_requested = True
                except Exception as exc:
                    failures += 1
                    state["monitor_error"] = f"{type(exc).__name__}: {exc}"
                    if isinstance(exc, RuntimeError) or failures >= 3:
                        state.update(status="stopped", reason="资源监测失败或硬限制不匹配，停止评测。")
                        stop_requested = True
                atomic(run_dir / "state.json", state)
                if time.monotonic() >= next_report:
                    state = render_report(run_dir)
                    next_report = time.monotonic() + 300
                if stop_requested:
                    state.setdefault("reason", "收到停止请求。")
                    state["status"] = "stopped"
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait(timeout=10)
                    break
                for _ in range(15):
                    if stop_requested or child.poll() is not None:
                        break
                    time.sleep(1)
            state["runner_exit_code"] = child.returncode
        official = Path(manifest["official_results"])
        task_dirs = list(official.glob("**/tasks/035"))
        if task_dirs:
            shutil.copytree(task_dirs[0], run_dir / "official-task", dirs_exist_ok=True)
        if state["status"] == "running":
            if child.returncode == 0 and any(official.glob("**/tasks/035/result.txt")):
                state.update(status="completed", reason="已生成官方任务评分文件；分数与任务是否通过见下方记录。")
            else:
                state.update(status="failed", reason="runner 已退出但缺少有效评分文件，请检查控制台与原始结果。")
        state["ended_utc"] = now()
        atomic(run_dir / "state.json", state)
    except Exception as exc:
        state.update(status="failed", reason=f"{type(exc).__name__}: {exc}", ended_utc=now())
        atomic(run_dir / "state.json", state)
        with (run_dir / "supervisor-error.log").open("a", encoding="utf-8") as error:
            traceback.print_exc(file=error)
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=10)
    finally:
        try:
            cleanup(run_dir)
        finally:
            for kind, handler in previous_signals.items():
                signal.signal(kind, handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["run", "report", "cleanup"])
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--unit")
    args = parser.parse_args()
    if args.action == "run":
        if not args.unit:
            parser.error("run requires --unit")
        run(args.run_dir.resolve(), args.unit)
    elif args.action == "report":
        render_report(args.run_dir.resolve())
    else:
        cleanup(args.run_dir.resolve())


if __name__ == "__main__":
    main()
