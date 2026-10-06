"""Serial baseline -> TaskViews experiment; all descendants share one 2 GiB cgroup.

The hourly Codex heartbeat may fix project code after a failed experiment, record a
repair, and resume. A valid zero score is a completed run, not grounds for retry.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import re
from pathlib import Path
import sys
import subprocess
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import osworld_task035_background as supervisor  # noqa: E402 - repository path is initialized first
from scripts.osworld_task035_profiles import profile_for, description  # noqa: E402 - repository path is initialized first

REPORT = PROJECT / "docs/osworld21-qwen38-task035-comparison.md"
MAX_REPAIRS = 10
MAX_EXPERIMENT_CONNECTION_RETRIES = 3
MAX_UNSTARTED_RESOURCE_RETRIES = 3
MAX_AUTHORIZED_RESOURCE_RETRIES = 3
START_RESERVE_GIB = supervisor.START_AVAILABLE_GIB


def snapshot_project():
    roots = [PROJECT / name for name in ("scripts", "ui_kobe", "kobe_views")]
    paths = sorted(p for root in roots for p in root.rglob("*.py"))
    return {p.relative_to(PROJECT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def render_comparison(root):
    plan = supervisor.read_json(root / "plan.json", {})
    state = supervisor.read_json(root / "state.json", {})
    if not plan:
        return
    relative = root.relative_to(PROJECT / "docs").as_posix()
    model = plan.get("model", "qwen3.8-max")
    profile = profile_for(model)
    lines = [f"# OSWorld v2.1 Task035：{model} baseline / TaskViews", "",
             f"更新时间（UTC）：{supervisor.now()}；计划：`{root.name}`。", "",
             f"状态：**{state.get('status', 'prepared')}**；{state.get('reason', '')}", "",
             "## 共同条件", "",
             f"两组串行运行，使用 {profile['api_key_env']} 环境变量、`{model}` 和 `{plan.get('base_url')}`。",
             "官方 OSWorld v2.1 Qwen runner 和 run_single_example 执行 Task035，最多 500 决策步；DONE/FAIL 可提前结束。",
             "1920×1080，screenshot 输入，GUI/PyAutoGUI 动作，动作后等待 3 秒。" + description(model),
             f"模型裁判与用户模拟器也统一使用 {model}；保留官方任务提示和评分规则。此本机裁判条件不同于公开榜单。", "",
             "| 组件 | 硬内存上限 |", "| --- | ---: |",
             "| Docker VM，客体 2 GiB / 2 vCPU | 3 GiB |",
             "| TeamChat 后端 / 前端 / Caddy | 0.5 / 0.125 / 0.125 GiB |",
             "| pipeline、supervisor、runner、Agent worker、日志程序及全部子进程共享 cgroup | 2 GiB |",
             "| 评测组件合计 | **5.75 GiB < 6 GiB** |", "",
             f"以上组件禁止额外宿主 swap。当前流水线、supervisor 和 minimal VM 外部包装器的启动检查统一为 Windows 至少 {START_RESERVE_GIB} GiB 可用；运行期间低于 4 GiB 自动保护停止。组件占用硬上限仍为 5.75 GiB。WSL 内核、Docker daemon、Windows 和其他应用另计；不修改全局 WSL 配置或关闭其他程序。",
             "每 15 秒资源采样、每 5 分钟刷新记录；Codex 每 60 分钟检查进展和处理已授权的实验组代码缺陷。", "",
             "## 各次运行", "", "| 运行 | 状态 | 决策步 | 有效 result.txt 分数 | API 响应 / 错误 | 报告 |",
             "| --- | --- | ---: | --- | --- | --- |"]
    for entry in state.get("runs", []):
        path = root / entry["directory"]
        progress = supervisor.read_json(path / "state.json", {})
        score = progress.get("official_score")
        if progress.get("comparison_valid") is False and score is not None:
            score = f"无效候选分数 {score}"
        lines.append(f"| {entry['directory']} | {progress.get('status', 'queued')} | {progress.get('decisions', 0)}/500 | "
                     f"{score if score is not None else '未取得'} | {progress.get('api_responses', 0)} / {progress.get('api_errors', 0)} | "
                     f"[逐组报告]({relative}/{entry['directory']}/report.md) |")
    task_control = supervisor.read_json(root / "taskviews-config.json", {}).get("agent", {}).get("task_control", {}).get("enabled", False)
    framework_description = (
        f"本轮实验组启用持久任务图、核心事实、动态角色视图和有界 FAIL 审查；观察者、总控、规划/核验角色与执行者均使用同一 {model} API。每步一般 3–5 次模型调用；恢复步骤可能减少调用。每次完整运行使用独立 taskviews-memory 目录，避免跨实验带入经验。"
        if task_control else
        "TaskViews 每步有感知和决策两次 API 调用，提示、历史保留策略和 JSON 动作格式也不同。")
    lines += ["", "只有官方 result.txt 且评测未报错才认定完整评测；不把 summary 的占位 0 当有效分数。真实 0 分仍是有效失败结果，不为了提高分数而重试。", "",
              "## 实验组及修复范围", "",
              "实验组通过 UI-KOBE 项目的 API、OSWorldAgent、RuntimeBridge/TaskViews 与结构化动作编译路径接入同一官方 harness；baseline 保留官方 Qwen XML Agent。",
              framework_description + " 因此这是框架级比较，不是 TaskViews 记忆模块的单因素消融；需同时比较 API 调用数、token、耗时和动作轨迹。",
              f"初始实验为 r00。实际代码修复最多 {MAX_REPAIRS} 轮，目前 {state.get('repair_round', 0)} 轮；每轮保存原因、修改说明、验证结果及代码哈希，随后从干净任务环境重新跑完整实验。所有失败运行保留。",
              "允许修复接口、交互、TaskViews 投影/排列、输入输出和动作执行路径中的真实缺陷；不修改 OSWorld 源码、任务素材、裁判规则或 baseline 轨迹，不通过评分答案修改 Agent 提示。", "",
              "## 记录", "",
              f"- [计划]({relative}/plan.json) / [流水线状态]({relative}/state.json) / [TaskViews 固定配置]({relative}/taskviews-config.json)",
              f"- [修复记录]({relative}/repairs.jsonl)；各次运行保留 console.log、transcript.md、telemetry、resources.jsonl 和 official-task。",
              f"- [未开始评测的启动重排记录]({relative}/preparation-retries.jsonl)：不计入实验组代码修复轮数。",
              f"- [接口恢复后的受限重排记录]({relative}/connection-retries.jsonl)：baseline 仅允许首请求失败且没有输出/动作/分数；实验组允许未评分的纯传输中断，所有已执行动作必须确认成功。实验组外部连接恢复重排最多 {MAX_EXPERIMENT_CONNECTION_RETRIES} 次，独立计数，不计入代码修复轮数。",
              "- 记录模型实际返回的解释、原始 XML/JSON、TaskViews 上下文、编译动作、控制器返回码、截图、API 状态及 usage；不记录密钥，不推测未公开的内部思维。",
              f"- WSL 后台服务：`{plan['unit']}`；检查 `systemctl --user status {plan['unit']}`。",
              "- baseline 完整评分并清理后自动启动实验组；异常停止后由 60 分钟检查分析并处理，不并发运行两组。完成或耗尽修复额度后暂停本次 heartbeat。", ""]
    diagnosis = root / "diagnosis.md"
    if diagnosis.exists():
        lines += ["", diagnosis.read_text(encoding="utf-8")]
    supervisor.atomic(Path(plan.get("report_path", str(REPORT))), "\n".join(lines))


def new_stage(root, state, arm):
    index = sum(entry["arm"] == "baseline" for entry in state.get("runs", [])) if arm == "baseline" else state.get("repair_round", 0)
    directory = f"{root.name}-{arm}-r{index:02d}"
    recovery_index = state.get("pending_experiment_connection_retry") if arm == "taskviews" else None
    if recovery_index is not None:
        if type(recovery_index) is not int or not 1 <= recovery_index <= MAX_EXPERIMENT_CONNECTION_RETRIES:
            raise RuntimeError("Invalid experiment connection retry index")
        directory += f"-api{recovery_index:02d}"
    if (root / directory).exists():
        raise RuntimeError("Refusing to repeat an existing run directory")
    entry = {"arm": arm, "directory": directory, "repair_round": state.get("repair_round", 0)}
    if recovery_index is not None:
        entry["connection_retry"] = state.pop("pending_experiment_connection_retry")
    state.setdefault("runs", []).append(entry)
    state.update(active_run=directory, active_arm=arm, status=f"{arm}_running", reason="串行运行中。")
    supervisor.atomic(root / "state.json", state)
    return root / directory


def stage_accepted(path):
    state = supervisor.read_json(path / "state.json", {})
    if state.get("status") != "completed" or state.get("official_score") is None or state.get("cleanup_errors"):
        return False
    manifest = supervisor.read_json(path / "manifest.json", {})
    audit = supervisor.read_json(Path(manifest.get("official_results", str(path))) / "source-audit.json", {})
    if audit.get("unchanged") is not True:
        return False
    # Some official evaluators return a fallback zero after a failed judge API.
    # Keep the file as evidence but do not accept it as a clean comparison run.
    for event_file in (path / "telemetry").glob("events-*.jsonl"):
        with event_file.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event["event"] in ("evaluation_error", "framework_error", "action_error"):
                    return False
    return True


def stage_taskviews_config(root, path):
    """Keep generation settings frozen while isolating persistent memory per attempt."""
    source = root / "taskviews-config.json"
    config = supervisor.read_json(source, {})
    control = config.get("agent", {}).get("task_control", {})
    if not control.get("enabled"):
        return source
    memory = path / "taskviews-memory"
    if memory.exists():
        raise RuntimeError("A clean experiment cannot reuse existing task memory")
    control["memory_dir"] = str(memory)
    destination = path / "taskviews-config.json"
    supervisor.atomic(destination, config)
    return destination


def run_stage(root, plan, state, arm):
    path = new_stage(root, state, arm)
    path.mkdir()
    supervisor.atomic(path / "project-source-before.json", snapshot_project())
    config = stage_taskviews_config(root, path) if arm == "taskviews" else root / "taskviews-config.json"
    options = {"model": plan["model"], "base_url": plan["base_url"], "arm": arm,
               "heartbeat_minutes": 60, "report_path": str(path / "report.md"),
               "taskviews_config": str(config)}
    supervisor.run(path, plan["unit"], options)
    supervisor.atomic(path / "project-source-after.json", snapshot_project())
    progress = supervisor.read_json(path / "state.json", {})
    progress["comparison_valid"] = stage_accepted(path)
    supervisor.atomic(path / "state.json", progress)
    return path


def run(root):
    plan = supervisor.read_json(root / "plan.json")
    state = supervisor.read_json(root / "state.json", {})
    if not plan:
        raise RuntimeError("Missing pipeline plan")
    supervisor.verify_service_budget()
    if hashlib.sha256((root / "taskviews-config.json").read_bytes()).hexdigest() != plan["config_sha256"]:
        raise RuntimeError("The fixed experimental configuration changed after planning")
    if state.get("status") not in ("prepared", "experiment_queued"):
        raise RuntimeError(f"Pipeline is not runnable from state {state.get('status')}")
    supervisor.REPORT_CALLBACK = lambda: render_comparison(root)
    with (root / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if state["status"] == "prepared":
            wait_resources(root, state, "baseline")
            baseline = run_stage(root, plan, state, "baseline")
            if not stage_accepted(baseline):
                state.update(status="baseline_needs_attention", reason="baseline 未取得完整有效评测或清理失败；实验组未启动。")
                supervisor.atomic(root / "state.json", state)
                render_comparison(root)
                return
            state["baseline_completed"] = True
        elif not state.get("baseline_completed"):
            raise RuntimeError("Cannot start experiment before an accepted baseline")
        wait_resources(root, state, "experiment")
        experiment = run_stage(root, plan, state, "taskviews")
        if stage_accepted(experiment):
            state.update(status="completed", reason="baseline 与 TaskViews 均已产生完整任务评分；保留全部证据。", ended_utc=supervisor.now())
        else:
            status = "repair_limit_reached" if state.get("repair_round", 0) >= MAX_REPAIRS else "experiment_needs_repair"
            state.update(status=status, reason="实验组异常或证据不完整，等待诊断；不得把无效分数作为实验结果。")
        supervisor.atomic(root / "state.json", state)
        render_comparison(root)


def wait_resources(root, state, arm):
    state.update(status=f"waiting_for_{arm}_resources", reason=f"等待 Windows 可用内存达到 {START_RESERVE_GIB} GiB，随后自动开始 {arm}。")
    next_report = 0
    while True:
        resources = supervisor.host_status()
        state["waiting_windows"] = resources
        state["waiting_checked_utc"] = supervisor.now()
        supervisor.atomic(root / "state.json", state)
        if time.monotonic() >= next_report:
            render_comparison(root)
            next_report = time.monotonic() + 300
        if resources["available_ram_gib"] >= START_RESERVE_GIB and resources["c_free_gib"] >= 45 and resources["d_free_gib"] >= 12:
            return
        time.sleep(30)


def queue_unstarted_baseline(root):
    """Only the resource-preflight failure with no model/actions may be requeued."""
    state = supervisor.read_json(root / "state.json", {})
    if state.get("status") != "baseline_needs_attention":
        raise RuntimeError("Not a baseline preparation failure")
    path = root / state["active_run"]
    previous = supervisor.read_json(path / "state.json", {})
    console = (path / "console.log").read_text(encoding="utf-8")
    if (previous.get("official_score") is not None or any(previous.get(k, 0) for k in
            ("decisions", "completed_actions", "api_responses", "api_errors"))
            or previous.get("cleanup_errors") or "Windows available RAM" not in console):
        raise RuntimeError("Refusing to repeat a baseline that reached model actions or a different failure")
    with (root / "preparation-retries.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps({"time_utc": supervisor.now(), "previous_run": state["active_run"],
                              "reason": f"VM allocation was refused before any Agent/API action; queue under the current {START_RESERVE_GIB} GiB startup policy."}) + "\n")
    state.update(status="prepared", reason=f"按当前 {START_RESERVE_GIB} GiB 启动检查排队，等待资源后重新开始 baseline。")
    supervisor.atomic(root / "state.json", state)
    render_comparison(root)


def queue_resource_stopped_baseline(root):
    """Requeue only a protected setup interruption before the first model request."""
    with (root / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = supervisor.read_json(root / "state.json", {})
        plan = supervisor.read_json(root / "plan.json", {})
        if (state.get("status") != "baseline_needs_attention" or state.get("baseline_completed")
                or state.get("active_arm") != "baseline"):
            raise RuntimeError("Not an unstarted resource-stopped baseline")
        path = root / state["active_run"]
        previous = supervisor.read_json(path / "state.json", {})
        manifest = supervisor.read_json(path / "manifest.json", {})
        official = Path(manifest["official_results"])
        resources = previous.get("latest_resources", {})
        windows = resources.get("windows", {})
        protected = (windows.get("available_ram_gib", 100) < 4
                     or windows.get("c_free_gib", 100) < 35 or windows.get("d_free_gib", 100) < 10)
        if (previous.get("status") != "stopped" or previous.get("reason") != "Windows 内存或磁盘保留量触发保护停止。"
                or not protected or previous.get("official_score") is not None
                or any(previous.get(k, 0) for k in ("decisions", "completed_actions", "api_responses", "api_errors"))
                or previous.get("cleanup_errors") or not previous.get("cleanup_utc")
                or any(official.rglob("result.txt"))
                or any(int(resources.get("service_memory_events", {}).get(k, 0)) for k in ("oom", "oom_kill"))
                or any(item.get("oom_killed") for item in resources.get("containers", []))):
            raise RuntimeError("A model/API/action/score/OOM or different cause prevents resource requeue")
        for file in (path / "telemetry").glob("events-*.jsonl"):
            with file.open(encoding="utf-8") as handle:
                for line in handle:
                    event = json.loads(line).get("event", "")
                    if event.startswith(("api_", "decision_", "action_", "evaluation_")):
                        raise RuntimeError("Resource restart cannot repeat a model request or action")
        ledger_path = root / "preparation-retries.jsonl"
        records = [json.loads(line) for line in ledger_path.read_text().splitlines() if line.strip()] if ledger_path.exists() else []
        retries = sum(record.get("kind") == "unstarted_resource_recovery" for record in records)
        if retries >= MAX_UNSTARTED_RESOURCE_RETRIES:
            raise RuntimeError("Unstarted resource retry allowance exhausted")
        if hashlib.sha256((root / "taskviews-config.json").read_bytes()).hexdigest() != plan["config_sha256"]:
            raise RuntimeError("The fixed experimental configuration changed")
        require_recovery_cleanup(plan, manifest, official)
        record = {"kind": "unstarted_resource_recovery", "retry": retries + 1, "time_utc": supervisor.now(),
                  "previous_run": state["active_run"], "resource_sample": resources,
                  "reason": "Protected setup interruption had no model requests, actions or score; cleanup and unchanged source verified. Startup remains 6 GiB, runtime reserve remains 4 GiB."}
        with ledger_path.open("a", encoding="utf-8") as ledger:
            ledger.write(json.dumps(record, ensure_ascii=False) + "\n")
        state.update(status="prepared", unstarted_resource_retries=retries + 1,
                     reason="未开始模型评测的资源保护中止已留证；仍按6 GiB启动、4 GiB运行保护排队。")
        supervisor.atomic(root / "state.json", state)
        render_comparison(root)


def require_recovery_cleanup(plan, manifest, official):
    """Recheck actual service, containers and source rather than trusting metadata."""
    active = subprocess.run(["systemctl", "--user", "is-active", plan["unit"]],
                            capture_output=True, text=True, timeout=10)
    if active.stdout.strip() != "inactive":
        raise RuntimeError("The comparison service must be inactive before requeueing")
    import docker
    client = docker.from_env(timeout=15)
    try:
        if client.containers.list(all=True, filters={"label": f"ui-kobe.osworld.run={manifest['run_id']}"}):
            raise RuntimeError("The failed run's VM has not been removed")
        if client.containers.list(filters={"label": "osworld.local.owner=cua-lty-20260929"}):
            raise RuntimeError("Another local OSWorld desktop is running")
        if manifest.get("web_owned"):
            for identifier in manifest.get("web_container_ids", []):
                container = client.containers.get(identifier)
                container.reload()
                if container.labels.get("com.docker.compose.project") != "osworld-local-web" or container.attrs["State"]["Running"]:
                    raise RuntimeError("The failed run's TeamChat cleanup is incomplete")
    finally:
        client.close()
    from ui_kobe.osworld.runner import source_snapshot
    previous = supervisor.read_json(official / "osworld-source-before.json", {})
    if not previous or source_snapshot(supervisor.REPOSITORY) != previous:
        raise RuntimeError("OSWorld source changed since the failed baseline")


def require_recovery_probe(root, plan, probe_file):
    """Same-model text and vision proof expires after ten minutes."""
    probe = supervisor.read_json(probe_file, {})
    profile = profile_for(plan["model"])
    if probe.get("base_url") != plan["base_url"] or probe.get("key_env") != profile["api_key_env"]:
        raise RuntimeError("Recovery probe endpoint or credential source differs")
    now = datetime.now(timezone.utc)
    for case in ("control_text", "control_top_false_vision"):
        candidates = [item for item in probe.get("probes", []) if item.get("case") == case]
        item = candidates[-1] if candidates else {}
        request = item.get("request", {})
        started = datetime.fromisoformat(item.get("started_utc", "1970-01-01T00:00:00+00:00"))
        age = (now - started).total_seconds()
        if profile["provider"] == "kimi":
            generation_ok = ("temperature" not in request and "top_p" not in request
                             and not request.get("extra_body") and "max_tokens" not in request
                             and request.get("reasoning_effort") == "max"
                             and 0 < request.get("max_completion_tokens", 0) <= 16000
                             and item.get("finish_reason") == "stop")
        else:
            generation_ok = (request.get("extra_body") == {"enable_thinking": False}
                             and request.get("temperature") == 0 and request.get("top_p") == 0.9
                             and item.get("reasoning_chars") == 0)
        if (not -30 <= age <= 600 or item.get("status_code") != 200
                or item.get("valid_chat_completion") is not True or item.get("error_type")
                or item.get("response_model") != plan["model"] or request.get("model") != plan["model"]
                or not generation_ok or request.get("stream") is not False
                or not item.get("content_chars")):
            raise RuntimeError("Both text and vision must have fresh valid responses under the fixed model/settings")
    if hashlib.sha256((root / "taskviews-config.json").read_bytes()).hexdigest() != plan["config_sha256"]:
        raise RuntimeError("The fixed experimental configuration changed")


def queue_authorized_resource_baseline(root, authorization_file, probe_file):
    """Explicitly authorized clean restart of an unscored VM protection stop."""
    with (root / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = supervisor.read_json(root / "state.json", {})
        plan = supervisor.read_json(root / "plan.json", {})
        authorization = supervisor.read_json(authorization_file, {})
        # This is an audit record of the human request, not an authentication API.
        if (authorization.get("run_id") != plan.get("run_id")
                or authorization.get("scope") != "unscored_resource_interrupted_baseline"
                or not authorization.get("user_request") or not authorization.get("authorized_at_utc")
                or type(authorization.get("max_restarts")) is not int
                or not 1 <= authorization["max_restarts"] <= MAX_AUTHORIZED_RESOURCE_RETRIES):
            raise RuntimeError("Missing explicit run-specific baseline resource restart authorization")
        if (state.get("status") != "baseline_needs_attention" or state.get("baseline_completed")
                or state.get("active_arm") != "baseline"):
            raise RuntimeError("Not an interrupted incomplete baseline")
        path = (root / state["active_run"]).resolve()
        if path.parent != root.resolve():
            raise RuntimeError("Unexpected interrupted run directory")
        previous = supervisor.read_json(path / "state.json", {})
        manifest = supervisor.read_json(path / "manifest.json", {})
        official = Path(manifest["official_results"])
        if (previous.get("status") not in ("failed", "stopped") or previous.get("official_score") is not None
                or not 0 < previous.get("decisions", 0) < plan["max_steps"]
                or previous.get("cleanup_errors") or not previous.get("cleanup_utc")
                or manifest.get("model") != plan["model"] or manifest.get("base_url") != plan["base_url"]
                or any(official.rglob("result.txt"))
                or supervisor.read_json(official / "source-audit.json", {}).get("unchanged") is not True):
            raise RuntimeError("Valid score, completed policy, missing audit or cleanup prevents resource restart")
        profile = supervisor.read_json(official / "resource-profile.json", {})
        guard = None
        with (path / "console.log").open(encoding="utf-8") as handle:
            for line in handle:
                match = re.search(r"Windows resource reserve reached: (\{.*\}); stopping only OSWorld container ([a-f0-9]+)", line)
                if match and profile.get("container", "").startswith(match[2]):
                    sample = ast.literal_eval(match[1])
                    if (sample.get("available_ram_gib", 100) < 4 or sample.get("c_free_gib", 100) < 35
                            or sample.get("d_free_gib", 100) < 10):
                        guard = {"sample": sample, "container": profile["container"], "console_line": line.strip()}
        if guard is None:
            raise RuntimeError("Raw VM-specific resource protection stop is not proven")
        stop_time = datetime.fromisoformat(guard["sample"]["timestamp_utc"]).timestamp()
        protected_sample = False
        with (official / "resources.jsonl").open() as handle:
            for line in handle:
                sample = json.loads(line)
                if sample.get("oom_killed"):
                    raise RuntimeError("OOM prevents a pure host-resource recovery")
                protected_sample |= bool(sample.get("running") and sample.get("windows_available_gib", 100) < 4)
        if not protected_sample:
            raise RuntimeError("Raw resource samples do not corroborate the VM stop")
        counts = {"decision": 0, "api_response": 0, "controller_result": 0, "action_result": 0}
        unconfirmed = []
        for file in (path / "telemetry").glob("events-*.jsonl"):
            with file.open(encoding="utf-8") as handle:
                for line in handle:
                    event = json.loads(line)
                    kind = event.get("event", "")
                    if kind.startswith("evaluation_") or kind in ("framework_error", "decision_error", "api_error"):
                        raise RuntimeError("Judge, framework or API error prevents pure resource restart")
                    if kind in counts:
                        counts[kind] += 1
                    if kind == "decision" and any(action in ("DONE", "FAIL") for action in event.get("parsed_actions", [])):
                        raise RuntimeError("A policy termination cannot be restarted for a better score")
                    if kind == "api_response":
                        if event.get("status_code") != 200 or event.get("response", {}).get("model") != plan["model"]:
                            raise RuntimeError("Incomplete or changed model response evidence")
                    if kind in ("controller_result", "action_error"):
                        result = event.get("result")
                        confirmed = (isinstance(result, dict) and result.get("status") == "success"
                                     and type(result.get("returncode")) is int and result["returncode"] == 0)
                        if not confirmed:
                            if datetime.fromisoformat(event["time_utc"]).timestamp() < stop_time:
                                raise RuntimeError("Execution failed before the resource guard stopped the VM")
                            unconfirmed.append({"step": event.get("step"), "event": kind, "time_utc": event["time_utc"]})
        if (counts["decision"] != previous["decisions"] or counts["api_response"] != previous.get("api_responses")
                or not counts["controller_result"] or not unconfirmed):
            raise RuntimeError("Incomplete decision or post-stop controller evidence")
        memory = previous.get("latest_resources", {})
        if (any(int(memory.get("service_memory_events", {}).get(k, 0)) for k in ("oom", "oom_kill"))
                or any(item.get("oom_killed") for item in memory.get("containers", []))):
            raise RuntimeError("Observed OOM prevents pure resource restart")
        before = supervisor.read_json(path / "project-source-before.json", {})
        current = snapshot_project()
        for name in ("scripts/run_official_qwen_task035.py", "scripts/osworld_task035_background.py", "ui_kobe/osworld/telemetry.py"):
            if name not in before or before[name] != current.get(name):
                raise RuntimeError("Baseline execution or telemetry code changed")
        ledger_path = root / "authorized-resource-retries.jsonl"
        records = [json.loads(line) for line in ledger_path.read_text().splitlines() if line.strip()] if ledger_path.exists() else []
        if len(records) >= authorization["max_restarts"] or any(item["previous_run"] == state["active_run"] for item in records):
            raise RuntimeError("Authorized resource retry allowance exhausted or already queued")
        require_recovery_probe(root, plan, probe_file)
        require_recovery_cleanup(plan, manifest, official)
        record = {"time_utc": supervisor.now(), "retry": len(records) + 1, "previous_run": state["active_run"],
                  "authorization_file": str(authorization_file), "authorization_sha256": hashlib.sha256(authorization_file.read_bytes()).hexdigest(),
                  "probe_file": str(probe_file), "probe_sha256": hashlib.sha256(probe_file.read_bytes()).hexdigest(),
                  "guard": guard, "counts": counts, "unconfirmed_after_guard": unconfirmed,
                  "startup_available_ram_gib": START_RESERVE_GIB, "runtime_reserve_gib": 4,
                  "reason": "Human-authorized clean full restart after unscored host-memory protection interruption; no Agent/prompt/config/resource guard change."}
        with ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        state.update(status="prepared", authorized_resource_retries=len(records) + 1,
                     reason="用户已授权重启未评分的资源中断baseline；从干净环境按原6 GiB启动/4 GiB运行保护排队。")
        supervisor.atomic(root / "state.json", state)
        render_comparison(root)


def queue_recovered_baseline(root, probe_file):
    """Requeue only a first-call network failure with fresh text/vision recovery."""
    with (root / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = supervisor.read_json(root / "state.json", {})
        plan = supervisor.read_json(root / "plan.json", {})
        if state.get("status") != "baseline_needs_attention" or state.get("baseline_completed") or state.get("active_arm") != "baseline":
            raise RuntimeError("Not an incomplete baseline connection failure")
        path = (root / state["active_run"]).resolve()
        if path.parent != root.resolve():
            raise RuntimeError("Unexpected previous run directory")
        previous = supervisor.read_json(path / "state.json", {})
        if (previous.get("status") != "failed" or previous.get("official_score") is not None
                or any(previous.get(key, 0) for key in ("decisions", "completed_actions", "api_responses"))
                or not previous.get("api_errors") or previous.get("cleanup_errors") or not previous.get("cleanup_utc")):
            raise RuntimeError("Refusing to repeat a baseline with model output, actions, a score or incomplete cleanup")
        manifest = supervisor.read_json(path / "manifest.json", {})
        if manifest.get("model") != plan.get("model") or manifest.get("base_url") != plan.get("base_url"):
            raise RuntimeError("Previous baseline settings differ from the fixed plan")
        official = Path(manifest["official_results"])
        if (list(official.glob("**/result.txt"))
                or supervisor.read_json(official / "source-audit.json", {}).get("unchanged") is not True):
            raise RuntimeError("A score file exists or the official source audit is incomplete")
        error_count = 0
        for event_file in (path / "telemetry").glob("events-*.jsonl"):
            with event_file.open(encoding="utf-8") as events:
                for line in events:
                    event = json.loads(line)
                    kind = event.get("event", "")
                    if kind in ("api_response", "decision", "action_result", "evaluation_result"):
                        raise RuntimeError("Recorded model output, actions or evaluation prevents a connection retry")
                    if kind.endswith("error"):
                        if (kind not in ("api_error", "decision_error")
                                or event.get("error_type") not in ("APIConnectionError", "APITimeoutError")
                                or event.get("status_code") is not None):
                            raise RuntimeError("Failure was not exclusively a pre-response connection error")
                        error_count += kind == "api_error"
        if error_count != previous["api_errors"]:
            raise RuntimeError("Incomplete API failure evidence")
        require_recovery_probe(root, plan, probe_file)
        require_recovery_cleanup(plan, manifest, official)
        recovery = {"time_utc": supervisor.now(), "previous_run": state["active_run"],
                    "reason": "First-call connection failure had no model output, actions or score; same-model text and vision API recovered; cleanup and unchanged source verified.",
                    "probe_file": str(probe_file.resolve()), "probe_sha256": hashlib.sha256(probe_file.read_bytes()).hexdigest(),
                    "startup_available_ram_gib": START_RESERVE_GIB, "repair_round": state.get("repair_round", 0)}
        with (root / "connection-retries.jsonl").open("a", encoding="utf-8") as ledger:
            ledger.write(json.dumps(recovery, ensure_ascii=False) + "\n")
        state.update(status="prepared", reason="同一模型的文字与图片 API 已恢复，连接异常证据与清理已核验；等待按 6 GiB 启动检查开始新的干净 baseline。",
                     last_api_recovery=recovery)
        supervisor.atomic(root / "state.json", state)
        render_comparison(root)


def queue_recovered_experiment(root, probe_file):
    """Bounded clean rerun after transport interruption, never a strategy retry."""
    with (root / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = supervisor.read_json(root / "state.json", {})
        plan = supervisor.read_json(root / "plan.json", {})
        if (state.get("status") != "experiment_needs_repair" or state.get("active_arm") != "taskviews"
                or state.get("baseline_completed") is not True):
            raise RuntimeError("Not an interrupted experiment after a completed baseline")
        baselines = [root / item["directory"] for item in state.get("runs", []) if item["arm"] == "baseline"]
        if not baselines or not stage_accepted(baselines[-1]):
            raise RuntimeError("The original baseline must remain accepted")
        ledger_path = root / "connection-retries.jsonl"
        records = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line] if ledger_path.exists() else []
        count = sum(item.get("kind") == "taskviews_api_recovery" for item in records)
        if count != state.get("experiment_connection_retries", 0) or count >= MAX_EXPERIMENT_CONNECTION_RETRIES:
            raise RuntimeError("Experiment connection retry budget exhausted or ledger inconsistent")
        path = (root / state["active_run"]).resolve()
        if path.parent != root.resolve():
            raise RuntimeError("Unexpected previous run directory")
        previous = supervisor.read_json(path / "state.json", {})
        if (previous.get("status") != "failed" or previous.get("official_score") is not None
                or previous.get("decisions", 0) >= plan["max_steps"] or previous.get("cleanup_errors")
                or not previous.get("cleanup_utc") or previous.get("task_done")):
            raise RuntimeError("Scored, exhausted, completed or unclean experiments cannot be retried")
        manifest = supervisor.read_json(path / "manifest.json", {})
        if any(manifest.get(key) != plan.get(key) for key in ("model", "base_url")) or manifest.get("arm") != "taskviews":
            raise RuntimeError("The interrupted run differs from the fixed experiment")
        official = Path(manifest["official_results"])
        if list(official.glob("**/result.txt")) or supervisor.read_json(official / "source-audit.json", {}).get("unchanged") is not True:
            raise RuntimeError("Score present or official source audit incomplete")
        # Only this admission/report script may change; the evaluated Agent stays frozen.
        current = snapshot_project()
        before = supervisor.read_json(path / "project-source-before.json", {})
        changed = {p for p in set(before) | set(current) if before.get(p) != current.get(p)}
        if not before or changed - {"scripts/osworld_task035_pipeline.py"}:
            raise RuntimeError("Agent/runtime code changed; use the counted repair path instead")
        counts = {"decision": 0, "action_result": 0, "api_response": 0, "api_error": 0}
        successful_steps, action_steps, failures, api_errors = set(), set(), [], []
        # Match the fixed model's provider exactly, retaining all transport,
        # execution, cleanup and retry-budget admission checks below.
        provider = profile_for(plan["model"])["provider"].upper()
        expected = f"{provider} request_failed; HTTP=n/a; code=n/a; attempts=3"
        for event_file in (path / "telemetry").glob("events-*.jsonl"):
            with event_file.open(encoding="utf-8") as events:
                for line in events:
                    event = json.loads(line)
                    kind = event.get("event", "")
                    if kind in counts:
                        counts[kind] += 1
                    if kind.startswith("evaluation") or event.get("phase") == "judge":
                        raise RuntimeError("Evaluation evidence prevents a connection retry")
                    if kind == "execution_unconfirmed":
                        raise RuntimeError("An action was not confirmed successful")
                    if kind == "controller_result" and event.get("phase") == "action":
                        result = event.get("result") or {}
                        if result.get("status") != "success" or type(result.get("returncode")) is not int or result["returncode"] != 0:
                            raise RuntimeError("An action was not confirmed successful")
                        successful_steps.add(event["step"])
                    elif kind == "action_result":
                        action_steps.add(event["step"])
                    elif kind == "api_error":
                        causes = event.get("error_causes", [])
                        if (event.get("status_code") is not None or event.get("error_type") not in ("APIConnectionError", "APITimeoutError")
                                or not causes or any(item.get("type") not in ("RemoteProtocolError", "ReadTimeout", "ConnectError", "ConnectTimeout") for item in causes)):
                            raise RuntimeError("API failure is not a verified transport interruption")
                        api_errors.append({k: event.get(k) for k in ("step", "phase", "time_utc")})
                    elif kind.endswith("error"):
                        if kind not in ("framework_error", "decision_error") or event.get("error") != expected:
                            raise RuntimeError("A project, action or policy error prevents transport recovery")
                        failures.append((kind, event.get("step")))
        decisions = previous.get("decisions", 0)
        if (counts != {"decision": decisions, "action_result": previous.get("completed_actions", 0),
                      "api_response": previous.get("api_responses", 0), "api_error": previous.get("api_errors", 0)}
                or previous.get("completed_actions", 0) != decisions or action_steps != set(range(1, decisions + 1))
                or successful_steps != action_steps):
            raise RuntimeError("Incomplete decision, API or execution evidence")
        last = sorted(api_errors, key=lambda item: item["time_utc"])[-3:]
        if (len(last) != 3 or any(item["step"] != decisions + 1 for item in last)
                or len({item["phase"] for item in last}) != 1
                or last[0]["phase"] not in ("perception", "decision")
                or sorted(failures) != sorted([("framework_error", decisions + 1), ("decision_error", decisions + 1)])):
            raise RuntimeError("Terminal three-attempt transport failure is not proven")
        require_recovery_probe(root, plan, probe_file)
        require_recovery_cleanup(plan, manifest, official)
        recovery = {"kind": "taskviews_api_recovery", "time_utc": supervisor.now(), "previous_run": state["active_run"],
                    "connection_retry": count + 1, "maximum_connection_retries": MAX_EXPERIMENT_CONNECTION_RETRIES,
                    "repair_round": state.get("repair_round", 0), "interrupted_decisions": decisions,
                    "reason": "Unscored transport interruption; all prior actions confirmed; fresh same-model text/vision responses and actual cleanup/source verified. Clean episode restart, not continuation or code repair.",
                    "probe_file": str(probe_file.resolve()), "probe_sha256": hashlib.sha256(probe_file.read_bytes()).hexdigest(),
                    "source_hashes": current}
        with ledger_path.open("a", encoding="utf-8") as ledger:
            ledger.write(json.dumps(recovery, ensure_ascii=False) + "\n")
        state.update(status="experiment_queued", reason="外部 API 恢复核验通过；独立连接重排已计数，等待干净实验组启动。",
                     experiment_connection_retries=count + 1, pending_experiment_connection_retry=count + 1,
                     last_experiment_api_recovery=recovery)
        supervisor.atomic(root / "state.json", state)
        render_comparison(root)


def queue_adapter_preflight_baseline(root, note_file, validation_file, probe_file):
    """One bounded retry of the proven K3 argument-parser failure, before a VM."""
    with (root / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = supervisor.read_json(root / "state.json", {})
        plan = supervisor.read_json(root / "plan.json", {})
        if (plan.get("model") != "kimi-k3" or state.get("status") != "baseline_needs_attention"
                or state.get("active_arm") != "baseline" or state.get("adapter_preflight_retries", 0) >= 1):
            raise RuntimeError("Not an eligible first K3 adapter preflight failure")
        path = root / state["active_run"]
        previous = supervisor.read_json(path / "state.json", {})
        manifest = supervisor.read_json(path / "manifest.json", {})
        official = Path(manifest["official_results"])
        console = (path / "console.log").read_text(encoding="utf-8").strip()
        if (console != "K3 profile requires the exact official model and endpoint"
                or previous.get("status") != "failed" or previous.get("official_score") is not None
                or any(previous.get(k, 0) for k in ("api_responses", "api_errors", "decisions", "completed_actions"))
                or previous.get("cleanup_errors") or not previous.get("cleanup_utc")
                or (official / "resource-profile.json").exists() or list(official.rglob("result.txt"))
                or any(previous.get("latest_resources", {}).get("service_memory_events", {}).get(k, "0") != "0"
                       for k in ("oom", "oom_kill"))):
            raise RuntimeError("Raw adapter failure or zero-request/no-VM conditions are not proven")
        for events in (path / "telemetry").glob("events-*.jsonl"):
            with events.open(encoding="utf-8") as handle:
                if any(json.loads(line).get("event") != "telemetry_installed" for line in handle):
                    raise RuntimeError("The failed baseline reached model or execution events")
        note = supervisor.read_json(note_file, {})
        validation = supervisor.read_json(validation_file, {})
        current = snapshot_project()
        before = supervisor.read_json(path / "project-source-before.json", {})
        changed = sorted(k for k in set(before) | set(current) if before.get(k) != current.get(k))
        if (not all(isinstance(note.get(k), str) and note[k].strip() for k in ("cause", "changes", "validation"))
                or "scripts/run_official_qwen_task035.py" not in changed
                or any(before.get(k) != current.get(k) for k in before if k.startswith(("ui_kobe/", "kobe_views/")))
                or validation.get("status") != "passed" or validation.get("exit_code") != 0
                or not validation.get("tests_passed") or validation.get("project_source_sha256") != current):
            raise RuntimeError("Adapter-only code repair and current passing validation are required")
        require_recovery_probe(root, plan, probe_file)
        require_recovery_cleanup(plan, manifest, official)
        record = {"kind": "adapter_preflight_recovery", "retry": 1, "time_utc": supervisor.now(),
                  "previous_run": state["active_run"], **note, "changed_paths": changed,
                  "source_hashes": current, "probe_file": str(probe_file), "validation_file": str(validation_file)}
        with (root / "preparation-retries.jsonl").open("a", encoding="utf-8") as ledger:
            ledger.write(json.dumps(record, ensure_ascii=False) + "\n")
        state.update(status="prepared", adapter_preflight_retries=1,
                     reason="K3 参数解析接入缺陷已修复并验证；首轮无 VM/请求/动作/评分，排队干净 baseline。")
        supervisor.atomic(root / "state.json", state)
        render_comparison(root)


def queue_judge_adapter_baseline(root, note_file, validation_file, probe_file):
    """One clean restart of an unscored K3 episode with a proven judge adapter error."""
    with (root / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = supervisor.read_json(root / "state.json", {})
        plan = supervisor.read_json(root / "plan.json", {})
        if (plan.get("model") != "kimi-k3" or state.get("status") != "baseline_needs_attention"
                or state.get("active_arm") != "baseline" or state.get("judge_adapter_retries", 0) >= 1):
            raise RuntimeError("Not an eligible first K3 judge adapter failure")
        path = root / state["active_run"]
        progress = supervisor.read_json(path / "state.json", {})
        manifest = supervisor.read_json(path / "manifest.json", {})
        official = Path(manifest["official_results"])
        if (progress.get("official_score") is not None or list(official.rglob("result.txt"))
                or progress.get("status") != "failed" or progress.get("api_errors", 0)
                or not 0 < progress.get("decisions", 0) <= 500 or progress.get("cleanup_errors")
                or not progress.get("cleanup_utc")
                or supervisor.read_json(official / "source-audit.json", {}).get("unchanged") is not True
                or "ValueError: K3 temperature is fixed at 1" not in (path / "console.log").read_text(encoding="utf-8")
                or any(progress.get("latest_resources", {}).get("service_memory_events", {}).get(k, "0") != "0"
                       for k in ("oom", "oom_kill"))):
            raise RuntimeError("Unscored local judge failure is not proven")
        evaluations, decisions, actions = [], [], []
        for event_file in (path / "telemetry").glob("events-*.jsonl"):
            with event_file.open(encoding="utf-8") as handle:
                for line in handle:
                    event = json.loads(line)
                    kind = event.get("event")
                    if kind in ("api_error", "action_error", "decision_error", "framework_error", "execution_unconfirmed"):
                        raise RuntimeError("Another API/Agent/execution failure prevents judge adapter recovery")
                    if kind == "api_request" and event.get("phase") == "judge":
                        raise RuntimeError("A judge request was sent; cannot claim a pre-request adapter rejection")
                    if kind == "controller_result":
                        result = event.get("result")
                        if (not isinstance(result, dict) or result.get("status") != "success"
                                or type(result.get("returncode")) is not int or result["returncode"] != 0):
                            raise RuntimeError("Unconfirmed execution prevents judge recovery")
                    if kind in ("evaluation_error", "evaluation_result"):
                        evaluations.append(event)
                    if kind == "decision":
                        decisions.append(event)
                    if kind == "action_result":
                        actions.append(event)
        if (len(evaluations) != 1 or evaluations[0]["event"] != "evaluation_error"
                or evaluations[0].get("error") != "Task035 evaluator failed during the LLM whole-table judgment."
                or len(decisions) != progress["decisions"] or len(actions) != progress.get("completed_actions")
                or not actions or actions[-1].get("action") not in ("DONE", "FAIL")
                or actions[-1].get("done") is not True):
            raise RuntimeError("Original episode termination and sole judge error are not proven")
        note = supervisor.read_json(note_file, {})
        validation = supervisor.read_json(validation_file, {})
        current = snapshot_project()
        before = supervisor.read_json(path / "project-source-before.json", {})
        changed = sorted(k for k in set(before) | set(current) if before.get(k) != current.get(k))
        if (not all(isinstance(note.get(k), str) and note[k].strip() for k in ("cause", "changes", "validation"))
                or "ui_kobe/osworld/qwen_judge.py" not in changed
                or set(changed) - {"ui_kobe/osworld/qwen_judge.py", "scripts/osworld_task035_pipeline.py"}
                or validation.get("status") != "passed" or validation.get("exit_code") != 0
                or not validation.get("tests_passed") or validation.get("project_source_sha256") != current):
            raise RuntimeError("Only a validated judge/protocol queue repair is permitted")
        require_recovery_probe(root, plan, probe_file)
        require_recovery_cleanup(plan, manifest, official)
        record = {"kind": "judge_adapter_recovery", "retry": 1, "time_utc": supervisor.now(),
                  "previous_run": state["active_run"], **note, "changed_paths": changed,
                  "source_hashes": current, "probe_file": str(probe_file), "validation_file": str(validation_file)}
        with (root / "preparation-retries.jsonl").open("a", encoding="utf-8") as ledger:
            ledger.write(json.dumps(record, ensure_ascii=False) + "\n")
        state.update(status="prepared", judge_adapter_retries=1,
                     reason="未评分 baseline 的本地 K3 裁判参数缺陷已修复；保留旧 DONE/FAIL 和评分异常，排队新干净 baseline。")
        supervisor.atomic(root / "state.json", state)
        render_comparison(root)


def record_repair(root, note_file):
    state = supervisor.read_json(root / "state.json", {})
    if state.get("status") != "experiment_needs_repair":
        raise RuntimeError("A repair can only follow a failed experiment")
    next_round = state.get("repair_round", 0) + 1
    if next_round > MAX_REPAIRS:
        raise RuntimeError("The ten-round repair budget is exhausted")
    note = json.loads(note_file.read_text(encoding="utf-8"))
    if not all(isinstance(note.get(k), str) and note[k].strip() for k in ("cause", "changes", "validation")):
        raise ValueError("Repair note requires cause, changes and validation")
    previous = supervisor.read_json(root / state["active_run"] / "project-source-before.json", {})
    current = snapshot_project()
    changed = sorted(p for p in set(previous) | set(current) if previous.get(p) != current.get(p))
    if not changed:
        raise ValueError("No project code change; do not consume repair rounds on unchanged retries")
    record = {"round": next_round, "time_utc": supervisor.now(), "failed_run": state["active_run"],
              **note, "changed_paths": changed, "source_hashes": current}
    with (root / "repairs.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(record, ensure_ascii=False) + "\n")
    state.update(repair_round=next_round, status="experiment_queued", reason="修复记录已保存；等待启动干净的实验组任务。")
    supervisor.atomic(root / "state.json", state)
    render_comparison(root)


def cleanup(root):
    state = supervisor.read_json(root / "state.json", {})
    if state.get("active_run") and (root / state["active_run"] / "manifest.json").exists():
        supervisor.cleanup(root / state["active_run"])
    if state.get("status") in ("baseline_running", "taskviews_running", "waiting_for_experiment_resources", "waiting_for_baseline_resources"):
        state.update(status="service_stopped", reason="systemd 服务已停止；核对 OOM、保护事件及 journal，不自动重复运行。")
        supervisor.atomic(root / "state.json", state)
    render_comparison(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["run", "report", "cleanup", "record-repair", "queue-baseline", "queue-resource-stopped-baseline", "queue-authorized-resource-baseline", "queue-api-recovered-baseline", "queue-api-recovered-experiment", "queue-adapter-preflight-baseline", "queue-judge-adapter-baseline"])
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--note-file", type=Path)
    parser.add_argument("--probe-file", type=Path)
    parser.add_argument("--authorization-file", type=Path)
    parser.add_argument("--validation-file", type=Path)
    args = parser.parse_args()
    root = args.run_dir.resolve()
    if args.action == "run":
        run(root)
    elif args.action == "cleanup":
        cleanup(root)
    elif args.action == "report":
        render_comparison(root)
    elif args.action == "queue-baseline":
        queue_unstarted_baseline(root)
    elif args.action == "queue-resource-stopped-baseline":
        queue_resource_stopped_baseline(root)
    elif args.action == "queue-authorized-resource-baseline":
        if not args.authorization_file or not args.probe_file:
            parser.error("queue-authorized-resource-baseline requires --authorization-file and --probe-file")
        queue_authorized_resource_baseline(root, args.authorization_file.resolve(), args.probe_file.resolve())
    elif args.action == "queue-api-recovered-baseline":
        if not args.probe_file:
            parser.error("queue-api-recovered-baseline requires --probe-file")
        queue_recovered_baseline(root, args.probe_file)
    elif args.action == "queue-api-recovered-experiment":
        if not args.probe_file:
            parser.error("queue-api-recovered-experiment requires --probe-file")
        queue_recovered_experiment(root, args.probe_file)
    elif args.action == "queue-adapter-preflight-baseline":
        if not args.note_file or not args.validation_file or not args.probe_file:
            parser.error("Adapter recovery requires note, current validation, and fresh API proof")
        queue_adapter_preflight_baseline(root, args.note_file, args.validation_file, args.probe_file)
    elif args.action == "queue-judge-adapter-baseline":
        if not args.note_file or not args.validation_file or not args.probe_file:
            parser.error("Judge adapter recovery requires note, current validation, and fresh API proof")
        queue_judge_adapter_baseline(root, args.note_file, args.validation_file, args.probe_file)
    else:
        if not args.note_file:
            parser.error("record-repair requires --note-file")
        record_repair(root, args.note_file)


if __name__ == "__main__":
    main()
