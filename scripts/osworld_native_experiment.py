"""Serial, no-rerun native K3 experiments under the user's fixed resource caps."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
ROOT = Path.home() / "osworld2"
REPO = ROOT / "OSWorld-V2"
PYTHON = REPO / ".venv/bin/python"
GIB = 1024 ** 3
AUX = ["systemd-run", "--user", "--scope", "--quiet", "--property=MemoryMax=128M",
       "--property=MemorySwapMax=0", str(PYTHON), str(Path(__file__).resolve())]


def now():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def project_snapshot():
    return {str(p.relative_to(PROJECT)): digest(p) for folder in ("ui_kobe", "kobe_views", "scripts")
            for p in sorted((PROJECT / folder).rglob("*.py"))}


def host_status():
    # Native OS inspection, no Windows Python process outside the bounded Linux runtime.
    code = ("$os = Get-CimInstance Win32_OperatingSystem; $c = Get-PSDrive C; $d = Get-PSDrive D; "
            "[pscustomobject]@{available_ram_gib=$os.FreePhysicalMemory*1024/1GB;"
            "c_free_gib=$c.Free/1GB;d_free_gib=$d.Free/1GB} | ConvertTo-Json -Compress")
    return json.loads(subprocess.check_output(["/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
        "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", code], text=True, timeout=20))


def require_scope(limit):
    from scripts.osworld_task035_background import cgroup
    group = cgroup()
    if (group / "memory.max").read_text().strip() != str(limit) or (group / "memory.swap.max").read_text().strip() != "0":
        raise RuntimeError(f"Expected bounded cgroup: MemoryMax={limit}, MemorySwapMax=0")
    if limit == 128 * 1024**2:
        from scripts.native_resource_accounting import register_auxiliary
        register_auxiliary(group)
    return group


def resources_ready():
    from scripts.native_resource_accounting import sample, reserve_ok, STARTUP_AVAILABLE_GIB
    from scripts.osworld_task035_background import cgroup
    if len(Path("/proc/swaps").read_text().splitlines()) != 1:
        raise RuntimeError("Host swap is enabled")
    if not Path("/dev/kvm").is_char_device():
        raise RuntimeError("KVM is unavailable")
    import docker
    client = docker.from_env(timeout=15)
    try:
        if client.containers.list(filters={"label": "osworld.local.owner=cua-lty-20260929"}):
            raise RuntimeError("An OSWorld VM already runs")
        status = sample(client, {}, host_status, cgroup())["windows"]
        if not reserve_ok(status, startup=True):
            raise RuntimeError(f"Windows startup reserve excluding experiment memory is below {STARTUP_AVAILABLE_GIB}/45/12 GiB")
        return status
    finally:
        client.close()


def frozen_check(root):
    from ui_kobe.osworld.runner import source_snapshot
    if digest(root / "plan.json") != load(root / "preparation.json")["plan_sha256"]:
        raise RuntimeError("Frozen experiment plan changed")
    plan = load(root / "plan.json")
    if project_snapshot() != load(root / "project-source-planned.json"):
        raise RuntimeError("Project runtime source differs from frozen plan")
    if source_snapshot(REPO) != load(root / "osworld-source-planned.json"):
        raise RuntimeError("OSWorld source differs from frozen plan")
    for name, expected in plan["asset_sha256"].items():
        if digest(Path(name)) != expected:
            raise RuntimeError("Official task asset changed: " + name)
    for name, expected in plan.get("native_web_deployment", {}).get("files", {}).items():
        if digest(Path(name)) != expected:
            raise RuntimeError("Frozen native website deployment changed: " + name)
    admission = plan.get("setup_admission")
    if admission and digest(Path(admission["path"])) != admission["sha256"]:
        raise RuntimeError("Task046 setup admission changed")
    proof = plan.get('provider_compatibility_ref')
    if proof and digest(Path(proof['path'])) != proof['sha256']:
        raise RuntimeError('Frozen provider compatibility evidence changed')


ARMS = ('baseline', 'ui_kobe_like', 'taskviews')


def interface_protocols(interface):
    protocol = {'official-xml': 'kimi-k3-official-qwen-xml-v7',
                'k3-native': 'kimi-k3-native-tools-official-cua-v7'}[interface]
    return [protocol] * len(ARMS)


def check_interface(plan):
    if plan.get('agent_interface') == 'qwen-native':
        from ui_kobe.api.qwen_native import BASE_URL, MODEL, PROTOCOL, QwenGenerationProfile
        if (plan.get('implementation_version') != 9 or plan.get('arms') != ['taskviews']
                or plan.get('protocols') != [PROTOCOL] or plan.get('task_id') != '059'
                or plan.get('model') != MODEL or plan.get('base_url') != BASE_URL
                or plan.get('api_key_env') != 'QWEN_API_KEY'
                or plan.get('generation_profile') != QwenGenerationProfile().__dict__
                or not plan.get('provider_compatibility', {}).get('compatible')
                or not plan.get('checkpoint_policy', {}).get('enabled')):
            raise RuntimeError('Use a fresh Qwen Task059 TaskViews checkpoint plan with passing provider evidence')
        return
    if (plan.get('implementation_version') != 7 or plan.get('arms') != list(ARMS)
            or plan.get('agent_interface') not in ('official-xml', 'k3-native')
            or plan.get('protocols') != interface_protocols(plan['agent_interface'])):
        raise RuntimeError('Use a fresh v7 three-arm plan with one preselected shared Agent interface')
    if plan['agent_interface'] == 'official-xml' and not plan.get('k3_compatibility', {}).get('compatible'):
        raise RuntimeError('Official XML interface requires passing K3 response/history compatibility evidence')


def trial_max_steps(purpose, max_steps=None):
    if purpose == 'cua_smoke':
        if type(max_steps) is not int or not 1 <= max_steps <= 10:
            raise ValueError('Declare 1..10 official decisions for a CUA smoke trial before freezing')
        return max_steps
    if purpose not in ('evaluation', 'setup_validation') or max_steps not in (None, 500):
        raise ValueError('Formal evaluations retain the official 500-decision limit')
    return 500


def taskviews_workflow(plan):
    enabled = plan.get('taskviews_feedback', False)
    if type(enabled) is not bool:
        raise ValueError('TaskViews feedback opt-in must be a boolean')
    if enabled and (plan.get('agent_interface') != 'qwen-native' or plan.get('arms') != ['taskviews']
                    or not plan.get('checkpoint_policy', {}).get('enabled')):
        raise ValueError('Feedback workflow requires isolated Qwen TaskViews checkpoints')
    return {'UI_KOBE_TASKVIEWS_FEEDBACK_V10': '1' if enabled else '0'}


def committed_source():
    status = subprocess.check_output(['git', '-C', str(PROJECT), 'status', '--porcelain'], text=True)
    if status.strip():
        raise RuntimeError('Commit the validated TaskViews iteration before preparing or resuming')
    return subprocess.check_output(['git', '-C', str(PROJECT), 'rev-parse', 'HEAD'], text=True).strip()


def prepare(root, task, validation, purpose="evaluation", admission=None, profile_name="low-16k", cua_config=None,
            agent_interface='official-xml', compatibility=None, max_steps=None, checkpoints=False,
            taskviews_feedback=False):
    from examples.osworld2_eval import official_identity
    from ui_kobe.osworld.task_examples import task_example
    from ui_kobe.osworld.runner import source_snapshot
    from ui_kobe.api.kimi_stream import StreamBudget
    from ui_kobe.api.kimi import generation_profile
    from ui_kobe.api.qwen_native import BASE_URL as QWEN_URL, MODEL as QWEN_MODEL, PROTOCOL as QWEN_PROTOCOL, QwenGenerationProfile
    qwen = agent_interface == 'qwen-native'
    if qwen and (task != '059' or not checkpoints or purpose != 'evaluation'):
        raise ValueError('Qwen native runs require isolated Task059 TaskViews checkpoints')
    profile = QwenGenerationProfile() if qwen else generation_profile(profile_name)
    from ui_kobe.osworld.cua_contract import CUAContract
    from ui_kobe.osworld.official_base import verify_official_base, OFFICIAL_COMMIT
    verify_official_base(REPO)
    contract = CUAContract(**load(cua_config)) if cua_config else CUAContract()
    decisions = trial_max_steps(purpose, max_steps)
    if purpose == 'cua_smoke' and (task != '059' or agent_interface != 'k3-native'):
        raise ValueError('This CUA smoke trial uses Task059 with the preselected K3 native interface')
    from scripts.native_resource_accounting import POLICY, STARTUP_AVAILABLE_GIB, RUNTIME_AVAILABLE_GIB
    if root.exists():
        raise RuntimeError("Use a new plan directory; never overwrite a trial")
    checked = load(validation)
    if checked["exit_code"] != 0 or checked["project_source"] != project_snapshot():
        raise RuntimeError("Current interface needs passing bounded validation")
    proof = load(compatibility) if compatibility else None
    if qwen and (not proof or not all(proof.get(k) is True for k in
            ['compatible', 'vision_json', 'native_tools', 'original_tool_history'])
            or proof.get('model') != QWEN_MODEL or proof.get('base_url') != QWEN_URL
            or proof.get('key_env') != 'QWEN_API_KEY' or proof.get('stream') is not False
            or len(proof.get('requests', [])) != 3
            or any(r.get('http_status') != 200 or not r.get('usage') for r in proof['requests'])):
        raise RuntimeError('Qwen requires actual vision, native tools and original tool history compatibility evidence')
    if agent_interface == 'official-xml':
        if (not proof or not proof.get('compatible') or not proof.get('live_api_called')
                or proof.get('official_commit') != OFFICIAL_COMMIT
                or proof.get('project_source') != project_snapshot()
                or proof.get('generation_profile') != generation_profile(profile_name).__dict__
                or proof.get('cua_contract') != contract.snapshot()):
            raise RuntimeError('Verify live K3 XML/assistant history against this source/profile/contract before migration')
    # Freezing a read-only plan does not create a VM. Actual startup admission
    # remains in launch() and the VM guard, under the authorized resource policy.
    status = host_status()
    identity = official_identity(REPO, task, "osworld-v2.1")
    assets = {str(ROOT / "assets/osworld-v2.1" / f"task_{task}" / name):
              digest(ROOT / "assets/osworld-v2.1" / f"task_{task}" / name)
              for name in task_example(task).assets}
    plan = {"created_utc": now(), "task_id": task, "model": QWEN_MODEL if qwen else "kimi-k3", "base_url": QWEN_URL if qwen else "https://api.moonshot.ai/v1",
        "api_key_env": "QWEN_API_KEY" if qwen else "KIMI_API_KEY", "official": identity, "asset_sha256": assets,
        "arms": ['taskviews'] if qwen else list(ARMS), "protocols": [QWEN_PROTOCOL] if qwen else interface_protocols(agent_interface),
        'implementation_version': 9 if qwen else 7, 'agent_interface': agent_interface,
        'arm_variables': {'baseline': 'no transition database or optional memory context',
                         'ui_kobe_like': 'transition database and bounded edge retrieval',
                         'taskviews': 'transition database plus task modules and adaptive context'},
        'k3_compatibility': proof, 'stream_budget': StreamBudget().__dict__,
        "cua_contract": contract.snapshot(),
        "generation_profile": profile.__dict__,
        "arm_admission": {"baseline_score_required": False, "baseline_run_required": False,
            "serial_execution": True, "existing_predecessor_source_and_cleanup_required": True},
        'actor_policy': {'shared_entry': 'one selected actor implementation for all three arms',
            'prompt': 'pinned official prompt; native wire-format substitution only',
            'feedback': 'minimal protocol result, actual command error or actual user answer',
            'complete_evidence': 'separate audit; experimental transition journals only',
            'optional_context_omission': 'omit whole packet; never evict actor history'},
        'budget_scopes': {'actor': 'full unchanged step output/deadline and repair pool',
            'advisory': 'separate output admission and analysis deadline; actual usage retained',
            'equal_total_budget_comparison': False},
        "max_steps": decisions, "screen": [1920, 1080], "sleep_after_execution": 3,
        "history": {"turns": contract.history_n, "images": contract.image_max, "fold_size": contract.fold_size,
                    "context_max_text_chars": contract.context_max_text_chars},
        "resource_limits": {"vm": 3 * GIB, "guest": 2 * GIB, "vcpus": 2, "web": 3 * GIB // 4,
            "service": 2 * GIB, "auxiliary": 128 * 1024**2, "swap": 0,
            "nominal_component_total": int(5.75 * GIB), "with_one_auxiliary": int(5.875 * GIB)},
        "memory_accounting": {"policy": POLICY,
            "formula": "Windows raw free physical GiB + measured experiment-owned cgroup/container bytes / 2**30",
            "startup_adjusted_gib": STARTUP_AVAILABLE_GIB, "runtime_adjusted_gib": RUNTIME_AVAILABLE_GIB,
            "raw_free_retained": True, "hard_limits_unchanged": True,
            "scope": "Owned VM and website containers plus the shared service and one registered auxiliary scope; nested scopes and container IDs counted once",
            "limits": "Charged-memory attribution, not an exact host physical footprint; unrelated WSL/Docker memory and unmeasured virtualization overhead are not credited"},
        "startup_windows": status, "retries": "At most two transport attempts; same actor output/deadline and repair pool in all arms; optional analysis has a separate bounded ledger/deadline; all attempts charged; no episode reruns",
        "execution_policy": {"batch_actions": True, "compiler": "unchanged official translate_tool_calls",
            "extra_tool_count_limit": None, "extra_argument_ranges": False, "affirmative_receipt_gate": False,
            "terminal_status_judge": False, "terminal_policy": "explicit model terminate or official max_steps; upstream optional terminal judge disabled to preserve the user-authorized no-automatic-DONE policy",
            "taskviews_advisers": "best effort; invalid views recorded without blocking the reserved executor"},
        "user_authorization": "User requested a shared official CUA interface and source commit; preparing this plan does not authorize a new evaluation episode. Launch requires experiment authorization; generation profiles and resource protections remain declared in this plan",
        "taskviews_variant": "optional context provider consumes experimental passive execution graph and task modules; same selected actor interface"}
    plan["purpose"] = purpose
    if qwen:
        plan['provider_compatibility'] = proof
        plan['provider_compatibility_ref'] = {'path': str(compatibility.resolve()), 'sha256': digest(compatibility)}
        plan['provider_request'] = {'stream': False, 'enable_thinking': False, 'temperature': 0, 'top_p': 0.9,
            'actor_max_tokens': 16000, 'advisory_max_tokens': 4000, 'response_format': 'native tools / advisory JSON',
            'transport': 'non-stream HTTP JSON; preserve actual raw response and usage; no synthetic SSE'}
        plan['k3_compatibility'] = None
        plan['actor_policy']['shared_entry'] = 'Qwen native actor using original official CUA compiler and common native history'
    if checkpoints:
        if task != '059' or agent_interface not in ('k3-native', 'qwen-native'):
            raise ValueError('Checkpoint rewind requires isolated Task059 native TaskViews')
        plan['runtime_revision'] = 9 if qwen else 8
        plan['checkpoint_policy'] = {'enabled': True, 'before_every_decision': True, 'retained_snapshots': 3,
                                     'startup_resume_probe': True,
            'cpu_flags': 'migratable=on,-invtsc', 'snapshot_preflight_before_task_reset': True,
            'firmware_storage': 'same pinned UEFI bytes; writable qcow2 pflash included in savevm',
            'advisory_effort': 'disabled' if qwen else 'low', 'read_error_policy': 'pause before actor; repair and resume aligned snapshot',
            'inspection_minutes': 60, 'no_reset_on_resume': True, 'cumulative_max_steps': decisions,
            'scope': 'Task059 local guest; not external web side effects', 'core': 'original task contract mandatory; candidates in views'}
        plan['benchmark_comparable'] = False
        plan['execution_policy']['taskviews_advisers'] = 'invalid reads pause before executor; aligned checkpoint repair/resume'
        plan['taskviews_variant'] = 'strict bounded context reads; independent advisory pool; checkpoint recovery'
        plan['user_authorization'] = 'User authorized TaskViews fixes, a new Task059 run, checkpoints and 60-minute inspection on 2026-10-09'
        if qwen:
            plan['user_authorization'] += '; explicitly requested qwen3.8-max Task059 TaskViews execution and real-time debugging'
            plan['comparison_limit'] = 'New Qwen native-tools, non-stream, thinking-disabled protocol; not the original Qwen XML agent or the completed Kimi comparison conditions'
    plan['taskviews_feedback'] = taskviews_feedback
    taskviews_workflow(plan)
    if taskviews_feedback:
        plan['taskviews_variant'] = 'action-bound feedback, stable subgoals, pointer frame contract, event-triggered analysis'
        plan['advisory_concurrency'] = 1
        plan['source_commit'] = committed_source()
        plan['iteration_commit_required'] = True
        plan['user_authorization'] = '2026-10-11: user authorized current TaskViews Task059 test, autonomous diagnosis/repair and a commit after each validated iteration; official evaluation source unchanged'
    if purpose == 'cua_smoke':
        plan['benchmark_comparable'] = False
        plan['user_authorization'] = 'The predeclared short official decision limit is a compatibility smoke trial, not a benchmark rerun. Preparation does not authorize a new evaluation episode'
    if task == "046":
        from scripts.native_task046_web import deployment_snapshot, validate_admission
        plan["native_web_deployment"] = deployment_snapshot()
        if purpose == "evaluation":
            if admission is None:
                raise RuntimeError("Task046 requires a completed official setup/resource proof before evaluation")
            plan["setup_admission"] = validate_admission(admission, project_snapshot())
    elif purpose not in ("evaluation", 'cua_smoke'):
        raise RuntimeError("Setup validation is only supported for Task046")
    root.mkdir(parents=True, exist_ok=False)
    write(root / "plan.json", plan)
    write(root / "project-source-planned.json", project_snapshot())
    write(root / "osworld-source-planned.json", source_snapshot(REPO))
    write(root / "preparation.json", {"status": "prepared", "time_utc": now(), "scope_limit": 128 * 1024**2,
                                       "plan_sha256": digest(root / "plan.json")})
    write(root / "validation.json", checked)
    print(json.dumps({"prepared": str(root), "task": task, "windows": status}), flush=True)


def official_arguments(task, output, profile=None, contract=None, max_steps=500, provider='kimi'):
    from ui_kobe.osworld.cua_contract import CUAContract
    cua = CUAContract(**contract) if contract else CUAContract()
    if provider not in ('kimi', 'qwen'):
        raise ValueError('Unknown official runner provider')
    from ui_kobe.api.qwen_native import BASE_URL, MODEL
    qwen = provider == 'qwen'
    return ["--headless", "--provider_name", "docker", "--path_to_vm", str(ROOT / "images/osworld-v2-ubuntu-x86.qcow2"),
        "--screen_width", "1920", "--screen_height", "1080", "--observation_type", "screenshot",
        "--action_space", "pyautogui", "--model", MODEL if qwen else "kimi-k3", "--base_url", BASE_URL if qwen else "https://api.moonshot.ai/v1",
        *(["--no-enable_thinking", "--no-stream"] if qwen else ["--enable_thinking", "--stream"]), "--batch_actions",
        "--coord", cua.coordinate_type,
        *([] if cua.model_screen_width is None else ["--model_screen_width", str(cua.model_screen_width),
                                                    "--model_screen_height", str(cua.model_screen_height)]),
        "--history_n", str(cua.history_n), "--image_max", str(cua.image_max), "--fold_size", str(cua.fold_size),
        "--tool_repair_retries", str(cua.tool_repair_retries), "--no-endless_retry",
        "--context_max_payload_chars", str(cua.context_max_payload_chars),
        "--context_max_text_chars", str(cua.context_max_text_chars),
        "--context_rough_text_token_budget", str(cua.context_rough_text_token_budget),
        "--context_rescue" if cua.enable_context_rescue else "--no-context_rescue",
        "--no-terminal_status_judge", "--temperature", "0" if qwen else "1", "--top_p", "0.9" if qwen else "0.95",
        "--max_tokens", str((profile or {}).get("max_completion_tokens", 16000)), "--max_steps", str(max_steps), "--sleep_after_execution", "3", "--num_envs", "1",
        "--eval_version", "v2", "--domain", "tasks", "--specific_task_id", task,
        "--client_password", "osworld-public-evaluation", "--max_api_retries", "2", "--request_timeout", "900",
        "--generation_timeout", "600", "--cache_dir", str(output.parent / "cache"), "--result_dir", str(output),
        "--save_model_eval_raw_info"]


def launch(root, arm):
    frozen_check(root)
    plan = load(root / "plan.json")
    check_interface(plan)
    decisions = trial_max_steps(plan.get('purpose', 'evaluation'), plan.get('max_steps'))
    from ui_kobe.osworld.cua_contract import CUAContract
    if arm not in ARMS or arm not in plan['arms']:
        raise ValueError('Unknown experimental arm')
    if not isinstance(plan.get("cua_contract"), dict):
        raise RuntimeError("This v7 entry requires a fresh frozen plan with its predeclared CUA contract")
    CUAContract(**plan["cua_contract"])
    resources_ready()
    if plan["task_id"] == "046":
        if not plan.get("native_web_deployment"):
            raise RuntimeError("Task046 web deployment/resource admission must be completed before launch")
        if plan.get("purpose") != "setup_validation":
            from scripts.native_task046_web import validate_admission
            validate_admission(plan["setup_admission"]["path"], project_snapshot())
        elif arm != "baseline":
            raise RuntimeError("Setup-only validation is a single non-evaluation baseline interface probe")
    # OSWorld evaluates each run independently. An absent or unsuccessful baseline
    # is not a score prerequisite; an existing predecessor must still be audited
    # and cleaned before sharing its plan/resources with the next arm.
    for predecessor in ARMS[:ARMS.index(arm)]:
        if (root / predecessor).exists():
            previous = load(root / predecessor / 'audit.json')
            if not previous['source_unchanged'] or not previous['cleanup_ok']:
                raise RuntimeError(f'{predecessor} source audit or cleanup failed; diagnose before proceeding')
    active = subprocess.check_output(["systemctl", "--user", "list-units", "--type=service", "--state=active",
                                      "--no-legend", "--no-pager"], text=True)
    if any(line.strip().startswith("osworld21-") for line in active.splitlines()):
        raise RuntimeError("An evaluation service already runs")
    stage = root / arm
    stage.mkdir(exist_ok=False)
    run_id = root.name + "-" + arm
    unit = run_id + ".service"
    output = ROOT / "results" / run_id / "qwen"
    manifest = {"run_id": run_id, "run_dir": str(stage), "plan_root": str(root), "task_id": plan["task_id"],
        "arm": arm, "agent_protocol": plan["protocols"][plan["arms"].index(arm)], "unit": unit,
        'agent_interface': plan['agent_interface'], 'implementation_version': plan['implementation_version'],
        'transition_recording': arm != 'baseline',
        "official_results": str(output), "official_arguments": official_arguments(plan["task_id"], output,
                                                    plan.get("generation_profile"), plan.get("cua_contract"), decisions,
                                                    provider='qwen' if plan['agent_interface'] == 'qwen-native' else 'kimi'),
        "cua_contract": plan.get("cua_contract"),
        "generation_profile": plan.get("generation_profile"),
        "model": plan.get('model', 'kimi-k3'), "base_url": plan.get('base_url', 'https://api.moonshot.ai/v1'),
        'api_key_env': plan.get('api_key_env', 'KIMI_API_KEY'), "web_container_ids": [], "web_owned": False,
        'purpose': plan.get('purpose', 'evaluation'), 'max_steps': decisions,
        'benchmark_comparable': plan.get('benchmark_comparable', True),
        "runtime_paths": [], "created_utc": now()}
    manifest['taskviews_feedback'] = plan.get('taskviews_feedback', False)
    manifest['source_commit'] = plan.get('source_commit')
    if plan.get('checkpoint_policy', {}).get('enabled'):
        if arm != 'taskviews':
            raise ValueError('Checkpoint-enabled recovery run is TaskViews only')
        manifest['checkpoint_policy'] = plan['checkpoint_policy']
        manifest['runtime_revision'] = plan['runtime_revision']
    manifest["setup_only"] = plan.get("purpose") == "setup_validation"
    write(stage / "manifest.json", manifest)
    command = shlex.join([str(PYTHON), str(Path(__file__).resolve()), "supervise", "--root", str(stage)])
    cleanup_command = shlex.join(AUX + ["cleanup", "--root", str(stage)])
    text = ("[Unit]\nDescription=Frozen native OSWorld experiment\n\n[Service]\nType=simple\n"
        f"WorkingDirectory={REPO}\nExecStart=/bin/bash -ic {shlex.quote('source ~/osworld2/env.sh; exec ' + command)}\n"
        f"ExecStopPost={cleanup_command}\nMemoryMax=2G\nMemoryHigh=1792M\nMemorySwapMax=0\n"
        "OOMPolicy=stop\nKillMode=control-group\nTimeoutStopSec=120\nRestart=no\nCPUQuota=100%\n"
        "CPUWeight=50\nIOWeight=50\nNice=10\nEnvironment=PYTHONDONTWRITEBYTECODE=1\nEnvironment=PYTHONUNBUFFERED=1\n")
    service = Path.home() / ".config/systemd/user" / unit
    service.write_text(text)
    (stage / "service.unit").write_text(text)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "start", unit], check=True)
    print(json.dumps({"unit": unit, "stage": str(stage), "official_results": str(output)}), flush=True)


def supervise(stage):
    import docker
    from scripts import osworld_task035_background as base
    from scripts.native_resource_accounting import sample, reserve_ok
    from ui_kobe.osworld.lifecycle import is_teardown, read_phase
    group = require_scope(2 * GIB)
    manifest = load(stage / "manifest.json")
    frozen_check(Path(manifest["plan_root"]))
    recovering = manifest.get('checkpoint_policy', {}).get('enabled') and (stage/'resume-request.json').exists()
    if not recovering:
        resources_ready()
    else:
        # Startup admission with the preserved owned VM credited exactly once.
        current = sample(__import__('docker').from_env(), manifest, host_status, group)['windows']
        if not reserve_ok(current, startup=True):
            raise RuntimeError('Preserved checkpoint waiting for startup resource reserve')
    key_env = manifest.get('api_key_env', 'KIMI_API_KEY')
    if not os.environ.get(key_env):
        raise RuntimeError(key_env + " missing; no VM was allocated")
    manifest.update(cgroup=str(group), started_utc=now(), started_epoch=time.time(),
        service_limits={p: (group / p).read_text().strip() for p in ("memory.max", "memory.swap.max")})
    write(stage / "manifest.json", manifest)
    state = {"status": "running", "peak_aggregate_bytes": 0, "started_utc": now()}
    write(stage / "state.json", state)
    stop = False

    def stop_signal(signum, frame):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    client = docker.from_env(timeout=15)
    env = {**os.environ, "OSWORLD_FULL_RUN_ID": manifest["run_id"], "PYTHONUNBUFFERED": "1",
           "PYTHONDONTWRITEBYTECODE": "1", "NO_PROXY": "localhost,127.0.0.1,::1,.nip.io",
           "no_proxy": "localhost,127.0.0.1,::1,.nip.io"}
    command = [str(PYTHON), str(PROJECT / "scripts/run_official_native_tasks.py"),
               "--manifest", str(stage / "manifest.json")]
    child = None
    native_web = None
    teardown_started = None
    try:
        if manifest["task_id"] == "046":
            from scripts.native_task046_web import NativeWeb
            native_web = NativeWeb(stage, client)
            native_web.start()
            manifest = load(stage / "manifest.json")
        with (stage / "console.log").open("a" if recovering else "w", encoding="utf-8") as log:
            child = subprocess.Popen(command, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            state["runner_pid"] = child.pid
            while child.poll() is None:
                teardown = is_teardown(stage)
                if teardown:
                    teardown_started = teardown_started or time.monotonic()
                    if time.monotonic() - teardown_started > 120:
                        raise RuntimeError("Official runner teardown exceeded 120 seconds")
                    state["runner_lifecycle"] = read_phase(stage)
                if native_web is not None and not teardown:
                    native_web.check()
                if len(Path("/proc/swaps").read_text().splitlines()) != 1:
                    raise RuntimeError("Host swap changed during run")
                # The runner may register websites after this supervisor starts.
                manifest = load(stage / "manifest.json")
                record = {"time_utc": now(), **sample(client, manifest, host_status, group, teardown=teardown)}
                teardown = teardown or is_teardown(stage)
                record["teardown"] = teardown
                with (stage / "resources.jsonl").open("a", encoding="utf-8") as resource_log:
                    resource_log.write(json.dumps(record) + "\n")
                state["latest_resources"] = record
                state["peak_aggregate_bytes"] = max(state["peak_aggregate_bytes"], record["aggregate_usage_bytes"])
                reserve = record["windows"]
                state["min_windows_available_gib"] = min(state.get("min_windows_available_gib", 999), reserve["available_ram_gib"])
                state["min_windows_excluding_experiment_gib"] = min(state.get("min_windows_excluding_experiment_gib", 999), reserve["available_excluding_experiment_gib"])
                # Once official close starts, VM charged pages legitimately
                # disappear. Continue swap/disk/OOM/hard-cap checks without
                # mistaking released VM memory for an active-task RAM failure.
                if (not teardown and not reserve_ok(reserve)) or (teardown and
                        (reserve["c_free_gib"] < 35 or reserve["d_free_gib"] < 10)):
                    if manifest.get('checkpoint_policy', {}).get('enabled') and (stage/'checkpoint-vm.json').exists():
                        write(stage/'pause-request.json', {'reason': 'runtime resource threshold', 'windows': reserve,
                                                         'time_utc': now()})
                        vm = load(stage/'checkpoint-vm.json')
                        os.kill(vm['worker_pid'], signal.SIGUSR1)
                        child.wait(timeout=120)
                        if not (stage/'paused.json').exists():
                            raise RuntimeError('Checkpoint resource pause did not complete')
                        break
                    raise RuntimeError("Windows runtime reserve excluding experiment memory below 4/35/10 GiB")
                if any(item["oom_killed"] for item in record["containers"]):
                    raise RuntimeError("Owned container OOM")
                metadata = base.read_json(ROOT / "logs/last-container.json", {})
                profile = base.read_json(Path(manifest["official_results"]) / "resource-profile.json", {})
                if profile.get("container") == metadata.get("id") and metadata.get("runtime"):
                    manifest["runtime_paths"] = [metadata["runtime"]]
                    write(stage / "manifest.json", manifest)
                write(stage / "state.json", state)
                if stop:
                    raise RuntimeError("Supervisor received stop signal")
                for _ in range(10):
                    if child.poll() is not None or stop:
                        break
                    time.sleep(1)
            state.update(status="runner_exited", runner_exit_code=child.returncode)
    except BaseException as exc:
        state.update(status="stopped", error_type=type(exc).__name__, reason=str(exc))
        if child and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=10)
        if child is not None:
            state["runner_exit_code"] = child.returncode
    finally:
        if native_web is not None:
            native_web.stop()
        state.update(ended_utc=now(), ended_epoch=time.time(),
            service_memory_peak=int((group / "memory.peak").read_text()),
            service_memory_events=(group / "memory.events").read_text())
        write(stage / "state.json", state)
        if manifest.get('checkpoint_policy', {}).get('enabled') and (stage/'paused.json').exists():
            state.update(status='checkpoint_paused', pause=load(stage/'paused.json'))
            write(stage/'state.json', state)
            return
        # Exactly one external 128 MiB auxiliary scope; never overlap helpers.
        subprocess.run(AUX + ["cleanup", "--root", str(stage)], check=True)


def cleanup(stage):
    if not (stage / "manifest.json").exists():
        return
    if (load(stage/'manifest.json').get('checkpoint_policy', {}).get('enabled')
            and (stage/'paused.json').exists()):
        # ExecStopPost also calls cleanup. A recoverable pause is not terminal
        # teardown; deleting this overlay would destroy the user's checkpoint.
        return
    manifest = load(stage/'manifest.json')
    if (manifest.get('checkpoint_policy', {}).get('enabled')
            and (stage/'checkpoint-vm.json').exists() and (stage/'checkpoints/latest.json').exists()
            and not any(event.get('event') == 'evaluation_result' for _, _, event in event_stream(stage))):
        # Covers an unexpected worker/service failure before its own pause hook.
        # Preserve real evidence; never invent a provider outcome or usage=0.
        from ui_kobe.osworld.checkpoints import Checkpoints, QMP
        vm = load(stage/'checkpoint-vm.json')
        Checkpoints(stage, manifest, qmp=QMP(Path(vm['storage'])/'taskviews.qmp')).pause(
            RuntimeError('Service ended before original evaluation; inspect failed branch before checkpoint resume'))
        return
    from scripts import osworld_task035_background as base
    base.render_report = lambda root: base.read_json(root / "state.json", {})
    base.cleanup(stage)
    if load(stage / "manifest.json").get("native_web"):
        from scripts.native_task046_web import cleanup_proxy
        cleanup_proxy(stage)
    audit(stage)


def event_stream(stage):
    for path in sorted((stage / "telemetry").glob("events-*.jsonl")):
        with path.open(encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                try:
                    yield path, number, json.loads(line)
                except json.JSONDecodeError:
                    continue


def audit(stage):
    from ui_kobe.osworld.runner import source_snapshot
    manifest = load(stage / "manifest.json")
    plan_root = Path(manifest["plan_root"])
    before, after = load(plan_root / "osworld-source-planned.json"), source_snapshot(REPO)
    changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
    plan = load(plan_root / "plan.json")
    changed_assets = [p for p, sha in plan["asset_sha256"].items() if not Path(p).exists() or digest(Path(p)) != sha]
    output = Path(manifest["official_results"])
    source_audit = {"unchanged": not changed, "changed_paths": changed,
                    "project_unchanged": project_snapshot() == load(plan_root / "project-source-planned.json"),
                    "assets_unchanged": not changed_assets, "changed_assets": changed_assets,
                    "plan_unchanged": digest(plan_root / "plan.json") == load(plan_root / "preparation.json")["plan_sha256"],
                    "plan_sha256": digest(plan_root / "plan.json")}
    write(output / "source-audit.json", source_audit)
    counters = {k: 0 for k in ("decisions", "actions", "api_requests", "api_success", "transport_retries", "semantic_regenerations", "native_tool_calls", "controller_receipts", "evaluation_results")}
    usage = {k: 0 for k in ("prompt_tokens", "completion_tokens", "total_tokens")}
    errors, terminals, receipt_errors = [], [], []
    request_usage, request_ids, request_phases = {}, set(), {}
    timing, phases = {}, {}
    categories = {k: [] for k in ("protocol", "transport", "execution", "judge", "resource", "framework", "budget")}
    index = stage / "evidence-index.jsonl"
    with index.open("w", encoding="utf-8") as evidence:
        for path, line, event in event_stream(stage):
            kind = event.get("event")
            ref = {"file": str(path), "line": line, "event": kind, "time_utc": event.get("time_utc"),
                   "step": event.get("step"), "phase": event.get("phase")}
            if kind == "decision":
                counters["decisions"] += 1
                trace = event.get("framework_trace") or {}
                if trace.get("terminal_origin"):
                    terminals.append({**ref, "source": trace["terminal_origin"], "native_action": trace.get("native_action")})
            elif kind == "action_result":
                counters["actions"] += 1
            elif kind == "api_request":
                request_ids.add(event["request_id"])
                request_phases[event["request_id"]] = event.get("phase", "unknown")
                counters["api_requests"] += 1
                counters["transport_retries"] += int(event.get("attempt", 1) > 1)
            elif kind == "api_response":
                counters["api_success"] += 1
                phase = phases.setdefault(event.get("phase", "unknown"), {"success": 0, "total_tokens": 0})
                phase["success"] += 1
                response = event.get("response") or {}
                request_usage[event["request_id"]] = response.get("usage")
                for choice in response.get("choices", []):
                    counters["native_tool_calls"] += len((choice.get("message") or {}).get("tool_calls") or [])
                t = event.get("timings") or {}
                for name in ("headers_s", "first_chunk_s", "first_reasoning_s", "first_content_s", "first_tool_s", "complete_s", "max_chunk_gap_s", "chunks"):
                    if isinstance(t.get(name), (int, float)):
                        metric = timing.setdefault(name, {"count": 0, "min": t[name], "max": t[name], "total": 0})
                        metric.update(count=metric["count"] + 1, min=min(metric["min"], t[name]),
                                      max=max(metric["max"], t[name]), total=metric["total"] + t[name])
            elif kind == "request_outcome":
                request_usage[event["request_id"]] = event.get("usage")
            elif kind == "semantic_regeneration":
                counters["semantic_regenerations"] += 1
            elif kind == "controller_result" and event.get("phase") == "action":
                counters["controller_receipts"] += 1
                result = event.get("result") or {}
                if result.get("returncode") != 0 or result.get("status") != "success":
                    receipt_errors.append(ref)
            elif kind == "evaluation_result":
                counters["evaluation_results"] += 1
            if kind and (kind.endswith("error") or kind == "execution_unconfirmed"):
                error = {**ref, "request_id": event.get("request_id"), "error_type": event.get("error_type"),
                         "error_code": event.get("error_code"), "error": event.get("error")}
                errors.append(error)
                if event.get("error_code") == "output_token_limit" or event.get("error_type") in {"OutputTokenLimitError", "StepTokenBudgetError"}:
                    category = "budget"
                elif kind == "evaluation_error" or event.get("phase") == "evaluation":
                    category = "judge"
                elif kind in {"action_error", "execution_unconfirmed"}:
                    category = "execution"
                elif kind == "protocol_error" or event.get("error_type") == "StreamProtocolError":
                    category = "protocol"
                elif kind == "api_error":
                    category = "transport"
                else:
                    category = "framework"
                categories[category].append(error)
            if kind in {"decision", "action_result", "controller_result", "evaluation_result", "evaluation_error", "protocol_error", "request_outcome", "semantic_regeneration", "candidate_rejected"}:
                evidence.write(json.dumps(ref, ensure_ascii=False) + "\n")
    known_requests = set()
    for request_id, measured in request_usage.items():
        if isinstance(measured, dict) and all(type(measured.get(k)) is int and measured[k] >= 0 for k in usage):
            known_requests.add(request_id)
            for key in usage:
                usage[key] += measured[key]
            phase = phases.setdefault(request_phases.get(request_id, "unknown"), {"success": 0, "total_tokens": 0})
            phase["total_tokens"] += measured['total_tokens']
    outputs = [Path(p) for p in manifest.get('result_segments', [str(output)])]
    results = sorted(p for segment in outputs for p in segment.glob(f"**/tasks/{manifest['task_id']}/result.txt"))
    score = None
    if len(results) == 1:
        try:
            score = float(results[0].read_text().strip())
            if not math.isfinite(score) or not 0 <= score <= 1:
                score = None
        except ValueError:
            pass
    state = load(stage / "state.json") if (stage / "state.json").exists() else {}
    if state.get("error_type"):
        reason = state.get("reason", "")
        category = "resource" if any(s in reason.lower() for s in ("memory", "disk", "reserve", "swap", "oom")) else "framework"
        categories[category].append({"file": str(stage / "state.json"), "error": reason})
    for metric in timing.values():
        metric["mean"] = metric.pop("total") / metric["count"]
    terminals.sort(key=lambda item: item.get("time_utc") or "")
    trajectories = sorted(p for segment in outputs for p in segment.glob(f"**/tasks/{manifest['task_id']}/traj.jsonl"))
    source_ok = not changed and source_audit["project_unchanged"] and source_audit["plan_unchanged"] and not changed_assets
    # The official persisted result defines the score. Provenance/telemetry
    # warnings are reported separately, not extra conditions on that grade.
    valid_score = score is not None
    import docker
    remaining = docker.from_env().containers.list(all=True, filters={"label": f"ui-kobe.osworld.run={manifest['run_id']}"})
    cleanup_ok = bool(state.get("cleanup_utc")) and not state.get("cleanup_errors") and not remaining
    result = {"time_utc": now(), "task_id": manifest["task_id"], "arm": manifest["arm"],
        "protocol": manifest["agent_protocol"], "score": score, "valid_score": valid_score,
        "memory_accounting": plan.get("memory_accounting"),
        "full_success": score == 1 if score is not None else None,
        "result_files": [str(p) for p in results], "counters": counters, "usage": usage,
        "usage_unknown_request_ids": sorted(request_ids - known_requests), "generation_profile": plan.get("generation_profile"),
        "timing": timing, "api_phases": phases, "terminals": terminals, "errors": errors,
        "error_categories": categories, "controller_receipt_errors": receipt_errors,
        "source_unchanged": source_ok, "cleanup_ok": cleanup_ok,
        "state": state, "wall_seconds": max(0, state.get("ended_epoch", time.time()) - manifest.get("started_epoch", time.time())),
        "judge_logs": [str(p) for p in output.rglob("*") if p.is_file() and
                       ("judge-api-response" in p.name or "model_eval_file_log" in p.parts)],
        "traj_files": [str(p) for p in trajectories],
        "sse_files": sum(1 for _ in (stage / "telemetry/streams").glob("*.jsonl")),
        "evidence_index": str(index), "source_audit": str(output / "source-audit.json")}
    write(stage / "audit.json", result)
    report = [f"# Task{manifest['task_id']} / {manifest['arm']}", "", f"协议：`{manifest['agent_protocol']}`。",
        f"有效官方分数：{score if valid_score else '无有效成绩（不能使用 summary 占位 0）'}。",
        f"决策 {counters['decisions']}/500；动作 {counters['actions']}；墙钟 {result['wall_seconds']:.1f} 秒。",
        f"请求成功 {counters['api_success']}；传输重试 {counters['transport_retries']}；usage `{usage}`。",
        f"原生 terminal：`{terminals}`。", f"SSE 时序：`{timing}`。",
        f"资源采样峰值 {state.get('peak_aggregate_bytes', 0) / GIB:.3f} GiB；service memory.peak {state.get('service_memory_peak', 0) / GIB:.3f} GiB。",
        f"内存计量：`{(plan.get('memory_accounting') or {}).get('policy', 'legacy-raw-free-memory')}`；原始 Windows 可用最低 {state.get('min_windows_available_gib')} GiB；排除本实验实测占用后最低 {state.get('min_windows_excluding_experiment_gib')} GiB。",
        "调整值用于启动5/运行4 GiB门槛，不代表真实空闲物理内存；关闭阶段不把VM释放后的RAM计量作为活跃任务失败，磁盘/swap/OOM/硬限仍检查。",
        f"源码与计划一致：{result['source_unchanged']}；清理完成：{cleanup_ok}。", "",
        "原始证据：manifest.json、resources.jsonl、console.log、telemetry/events-*.jsonl、telemetry/streams/*.jsonl、",
        "evidence-index.jsonl、audit.json；完整截图/轨迹/评分文件见 manifest.official_results。",
        "本地保留既有 K3 裁判/用户模拟器兼容配置；059 为程序化评分，046 含图像与网站检查，不能称为公开榜单同条件复现。",
        "本版本不使用旧 XML 恢复上限自动 DONE；仅接受原生模型 terminate，或达到 500 决策上限后官方评分。",
        "TaskViews 组使用同一原生执行端，增加完整 SSE 的观察、语义视图与 adviser 调用；无自动补偿动作。", "",
        f"错误索引：`{errors}`。", f"异常控制器回执：`{receipt_errors}`。"]
    (stage / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("task_id", "arm", "score", "valid_score", "source_unchanged", "cleanup_ok", "counters")}), flush=True)


def status(stage):
    state = load(stage / "state.json") if (stage / "state.json").exists() else {}
    counts, recent = {}, []
    for path, number, event in event_stream(stage):
        kind = event.get("event", "unknown")
        counts[kind] = counts.get(kind, 0) + 1
        if kind in {"observation", "decision", "api_request", "api_response", "api_error", "protocol_error", "evaluation_result"}:
            recent.append({"time": event.get("time_utc"), "event": kind, "step": event.get("step"),
                           "phase": event.get("phase"), "file": path.name, "line": number})
            recent = sorted(recent, key=lambda item: item.get("time") or "")[-6:]
    print(json.dumps({"state": state, "events": counts, "recent": recent}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "launch", "supervise", "cleanup", "audit", "status"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--task", choices=("059", "046"))
    parser.add_argument("--arm", choices=ARMS)
    parser.add_argument("--validation", type=Path)
    parser.add_argument("--purpose", choices=("evaluation", "setup_validation", "cua_smoke"), default="evaluation")
    parser.add_argument('--max-steps', type=int, help='Predeclare a short official decision limit for cua_smoke only')
    parser.add_argument("--admission", type=Path)
    parser.add_argument("--profile", choices=("low-16k", "max-16k", "max-32k"), default="low-16k")
    parser.add_argument("--cua-config", type=Path)
    parser.add_argument('--agent-interface', choices=('official-xml', 'k3-native', 'qwen-native'), default='official-xml')
    parser.add_argument('--k3-compatibility', '--provider-compatibility', type=Path)
    parser.add_argument('--checkpoints', action='store_true')
    parser.add_argument('--taskviews-feedback', action='store_true', help='Freeze the validated action feedback/pointer workflow for Qwen TaskViews')
    args = parser.parse_args()
    require_scope(2 * GIB if args.action == "supervise" else 128 * 1024**2)
    root = args.root.resolve()
    if args.action == "prepare":
        prepare(root, args.task, args.validation, args.purpose, args.admission, args.profile, args.cua_config,
                args.agent_interface, args.k3_compatibility, args.max_steps, args.checkpoints, args.taskviews_feedback)
    elif args.action == "launch":
        lock = Path.home() / ".cache/ui-kobe-osworld-experiment.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            launch(root, args.arm)
    elif args.action == "supervise":
        supervise(root)
    elif args.action == "cleanup":
        cleanup(root)
    elif args.action == "audit":
        audit(root)
    else:
        status(root)


if __name__ == "__main__":
    main()
