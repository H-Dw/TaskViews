"""Run a declared native provider through the pinned official runner."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import runpy
import sys


def agent_class(interface, arm, taskviews_profile='full_checkpoint'):
    from ui_kobe.osworld.taskviews_profiles import FULL_PROFILE, MINI_PROFILE
    if taskviews_profile == MINI_PROFILE:
        if interface != 'qwen-native':
            raise ValueError('Mini requires the declared Qwen native interface')
        from ui_kobe.osworld.mini_taskviews_native import QwenMiniTaskViewsNativeAgent
        from ui_kobe.osworld.qwen_native_base import QwenTransitionNativeAgent
        return {'taskviews': QwenMiniTaskViewsNativeAgent,
                'ui_kobe_like': QwenTransitionNativeAgent}[arm]
    if taskviews_profile != FULL_PROFILE:
        raise ValueError('Unknown TaskViews profile')
    if interface == 'official-xml':
        from ui_kobe.osworld.kimi_official import OfficialK3Agent, OfficialK3TransitionAgent, OfficialK3TaskViewsAgent
        classes = {'baseline': OfficialK3Agent, 'ui_kobe_like': OfficialK3TransitionAgent,
                   'taskviews': OfficialK3TaskViewsAgent}
    elif interface == 'k3-native':
        from ui_kobe.osworld.kimi_native import KimiNativeAgent
        from ui_kobe.osworld.kimi_transition_native import KimiTransitionNativeAgent
        from ui_kobe.osworld.kimi_taskviews_native import KimiTaskViewsNativeAgent
        classes = {'baseline': KimiNativeAgent, 'ui_kobe_like': KimiTransitionNativeAgent,
                   'taskviews': KimiTaskViewsNativeAgent}
    elif interface == 'qwen-native':
        from ui_kobe.osworld.qwen_taskviews_native import QwenTaskViewsNativeAgent
        classes = {'taskviews': QwenTaskViewsNativeAgent}
    else:
        raise ValueError('Unknown Agent interface')
    return classes[arm]


def configure_profile(plan, manifest):
    from ui_kobe.osworld.taskviews_profiles import FULL_PROFILE, MINI_PROFILE, validate_profile
    profile = validate_profile(plan)
    if manifest.get('taskviews_profile', FULL_PROFILE) != profile:
        raise RuntimeError('Manifest actor profile differs from frozen plan')
    if profile == MINI_PROFILE:
        from scripts.osworld_native_experiment import require_mini_branch
        if (manifest.get('mini_profile') != plan['mini_profile']
                or manifest.get('source_branch') != plan['source_branch']):
            raise RuntimeError('Manifest fixed-view contract differs from frozen Mini plan')
        require_mini_branch()
    os.environ['UI_KOBE_TASKVIEWS_PROFILE'] = profile
    return profile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    root = Path(manifest["run_dir"])
    project = Path(__file__).resolve().parents[1]
    repo = Path.home() / "osworld2/OSWorld-V2"
    sys.path[:0] = [str(project), str(repo), str(repo / "scripts/python")]
    os.chdir(repo)
    from scripts.osworld_native_experiment import frozen_check, host_status, check_interface, taskviews_workflow
    frozen_check(Path(manifest["plan_root"]))
    from ui_kobe.osworld.official_base import verify_official_base
    official_base = verify_official_base(repo)
    from ui_kobe.osworld.cua_contract import CUAContract
    plan = json.loads((Path(manifest["plan_root"]) / "plan.json").read_text())
    check_interface(plan)
    actor_profile = configure_profile(plan, manifest)
    if manifest.get('taskviews_feedback', False) != plan.get('taskviews_feedback', False):
        raise RuntimeError('Manifest feedback workflow differs from frozen plan')
    os.environ.update(taskviews_workflow(plan))
    if (manifest.get('agent_interface') != plan['agent_interface']
            or manifest.get('agent_protocol') != plan['protocols'][plan['arms'].index(manifest['arm'])]):
        raise RuntimeError('Manifest Agent interface differs from the frozen three-arm plan')
    if not isinstance(plan.get("cua_contract"), dict):
        raise RuntimeError("This v7 entry requires a fresh frozen plan with its predeclared CUA contract")
    contract = CUAContract(**plan["cua_contract"])
    if manifest.get("cua_contract") != contract.snapshot():
        raise RuntimeError("Manifest CUA contract differs from frozen plan")
    os.environ["UI_KOBE_CUA_CONTRACT_JSON"] = json.dumps(contract.snapshot())
    profile = manifest['generation_profile']
    qwen = manifest['agent_interface'] == 'qwen-native'
    if qwen:
        from ui_kobe.api.qwen_native import QwenGenerationProfile
        expected_profile = QwenGenerationProfile().__dict__
    else:
        from ui_kobe.api.kimi import generation_profile
        expected_profile = generation_profile(profile['name']).__dict__
    if expected_profile != profile:
        raise RuntimeError('Manifest generation profile does not match frozen implementation')
    os.environ['UI_KOBE_GENERATION_PROFILE'] = profile['name']
    key_env = 'QWEN_API_KEY' if qwen else 'KIMI_API_KEY'
    if manifest.get('api_key_env', key_env) != key_env or not os.environ.get(key_env):
        raise RuntimeError(key_env + " is absent or differs from the frozen provider")
    os.environ.update(OPENAI_API_KEY=os.environ[key_env], OSWORLD_LOCAL_WEB="0",
        UI_KOBE_TASK_ID=manifest["task_id"], UI_KOBE_TELEMETRY_DIR=str(root / "telemetry"),
        OSWORLD_FULL_RUN_ID=manifest["run_id"],
        WEBSITE_HOST_SUFFIX="127.0.0.1.nip.io:21280",
        OSWORLD_BENCHMARK_RELEASE="osworld-v2.1",
        OSWORLD_FILE_BASE_URL=str(Path.home() / "osworld2/assets/osworld-v2.1"))
    # Task059 is deterministically scored. Any original runner-side provider
    # use nevertheless receives this run's declared model and endpoint.
    os.environ.update(OSWORLD_EVAL_MODEL_PROVIDER="ui_kobe_qwen_judge",
        OSWORLD_EVAL_MODEL_API_KEY_ENV=key_env, OSWORLD_EVAL_MODEL_NAME=manifest['model'],
        OSWORLD_EVAL_MODEL_BASE_URL=manifest['base_url'], OSWORLD_EVAL_MODEL_TEMPERATURE="0" if qwen else "1",
        OSWORLD_EVAL_MODEL_MAX_OUTPUT_TOKENS="16000", OSWORLD_EVAL_MODEL_RETRY_ATTEMPTS="2",
        OSWORLD_USER_SIM_PROVIDER="openai_compatible", OSWORLD_USER_SIM_API_KEY_ENV=key_env,
        OSWORLD_USER_SIM_MODEL=manifest['model'], OSWORLD_USER_SIM_BASE_URL=manifest['base_url'],
        OSWORLD_USER_SIM_TEMPERATURE="0" if qwen else "1", OSWORLD_USER_SIM_MAX_TOKENS="16000")
    from desktop_env.providers.docker import local_budget
    from scripts.native_resource_accounting import BudgetHostProbe, STARTUP_AVAILABLE_GIB
    local_budget.host_status = BudgetHostProbe(args.manifest, host_status)
    from scripts.run_official_qwen_task035 import install_local_memory_profile
    output = Path(manifest["official_results"])
    install_local_memory_profile(output, "minimal", startup_available_gib=STARTUP_AVAILABLE_GIB)
    import mm_agents.qwen
    selected = agent_class(manifest['agent_interface'], manifest['arm'], actor_profile)
    if manifest.get('transition_recording') != selected.transition_recording:
        raise RuntimeError('Recording policy differs from the frozen experimental arm')
    mm_agents.qwen.QwenAgent = selected
    from ui_kobe.osworld.telemetry import install
    from ui_kobe.api.kimi import install_official_k3_transport
    from ui_kobe.osworld.qwen_judge import install_qwen_judge_backend
    install(root / "telemetry")
    if not qwen:
        install_official_k3_transport()
    install_qwen_judge_backend()
    if manifest.get('checkpoint_policy', {}).get('enabled'):
        os.environ['UI_KOBE_CHECKPOINT_READS'] = '1'
        os.environ['UI_KOBE_ADVISORY_EFFORT'] = manifest['checkpoint_policy']['advisory_effort']
        from ui_kobe.osworld.checkpoints import install as install_checkpoints
        install_checkpoints(root, manifest, agent_type=selected)
    if manifest["task_id"] == "046":
        from scripts.native_task046_setup import install_setup_verification
        install_setup_verification(root)
    runner = repo / "scripts/python/run_multienv_qwen.py"
    sys.argv = [str(runner), *manifest["official_arguments"]]
    from ui_kobe.osworld.runner import source_snapshot
    from scripts.osworld_native_experiment import write
    before = source_snapshot(repo)
    write(output / "osworld-source-before.json", before)
    write(output / "official-base.json", official_base)
    from ui_kobe.osworld.lifecycle import write_phase
    write_phase(root, "running", official_base=official_base["commit"])
    try:
        if manifest.get("setup_only"):
            from scripts.native_task046_setup import run_setup_only
            run_setup_only(runpy.run_path(str(runner), run_name="native_setup_validation"), manifest)
        else:
            runpy.run_path(str(runner), run_name="__main__")
    finally:
        write_phase(root, "runner_exited")
        after = source_snapshot(repo)
        changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
        write(output / "source-audit.json", {"unchanged": not changed, "changed_paths": changed})


if __name__ == "__main__":
    main()
