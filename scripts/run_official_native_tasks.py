"""Run either K3 arm through the pinned, untouched official execution/evaluation runner."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import runpy
import sys


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
    from scripts.osworld_native_experiment import frozen_check, host_status
    frozen_check(Path(manifest["plan_root"]))
    from ui_kobe.osworld.official_base import verify_official_base
    official_base = verify_official_base(repo)
    from ui_kobe.osworld.cua_contract import CUAContract
    plan = json.loads((Path(manifest["plan_root"]) / "plan.json").read_text())
    if not isinstance(plan.get("cua_contract"), dict):
        raise RuntimeError("This v5 entry requires a fresh frozen plan with its predeclared CUA contract")
    contract = CUAContract(**plan["cua_contract"])
    if manifest.get("cua_contract") != contract.snapshot():
        raise RuntimeError("Manifest CUA contract differs from frozen plan")
    os.environ["UI_KOBE_CUA_CONTRACT_JSON"] = json.dumps(contract.snapshot())
    from ui_kobe.api.kimi import generation_profile
    profile = manifest['generation_profile']
    if generation_profile(profile['name']).__dict__ != profile:
        raise RuntimeError('Manifest generation profile does not match frozen implementation')
    os.environ['UI_KOBE_GENERATION_PROFILE'] = profile['name']
    if not os.environ.get("KIMI_API_KEY"):
        raise RuntimeError("KIMI_API_KEY is absent")
    os.environ.update(OPENAI_API_KEY=os.environ["KIMI_API_KEY"], OSWORLD_LOCAL_WEB="0",
        UI_KOBE_TASK_ID=manifest["task_id"], UI_KOBE_TELEMETRY_DIR=str(root / "telemetry"),
        OSWORLD_FULL_RUN_ID=manifest["run_id"],
        WEBSITE_HOST_SUFFIX="127.0.0.1.nip.io:21280",
        OSWORLD_BENCHMARK_RELEASE="osworld-v2.1",
        OSWORLD_FILE_BASE_URL=str(Path.home() / "osworld2/assets/osworld-v2.1"))
    # Preserve the existing K3 judge/user-simulator compatibility configuration.
    os.environ.update(OSWORLD_EVAL_MODEL_PROVIDER="ui_kobe_qwen_judge",
        OSWORLD_EVAL_MODEL_API_KEY_ENV="KIMI_API_KEY", OSWORLD_EVAL_MODEL_NAME="kimi-k3",
        OSWORLD_EVAL_MODEL_BASE_URL="https://api.moonshot.ai/v1", OSWORLD_EVAL_MODEL_TEMPERATURE="1",
        OSWORLD_EVAL_MODEL_MAX_OUTPUT_TOKENS="16000", OSWORLD_EVAL_MODEL_RETRY_ATTEMPTS="2",
        OSWORLD_USER_SIM_PROVIDER="openai_compatible", OSWORLD_USER_SIM_API_KEY_ENV="KIMI_API_KEY",
        OSWORLD_USER_SIM_MODEL="kimi-k3", OSWORLD_USER_SIM_BASE_URL="https://api.moonshot.ai/v1",
        OSWORLD_USER_SIM_TEMPERATURE="1", OSWORLD_USER_SIM_MAX_TOKENS="16000")
    from desktop_env.providers.docker import local_budget
    from scripts.native_resource_accounting import BudgetHostProbe, STARTUP_AVAILABLE_GIB
    local_budget.host_status = BudgetHostProbe(args.manifest, host_status)
    from scripts.run_official_qwen_task035 import install_local_memory_profile
    output = Path(manifest["official_results"])
    install_local_memory_profile(output, "minimal", startup_available_gib=STARTUP_AVAILABLE_GIB)
    import mm_agents.qwen
    if manifest["arm"] == "baseline":
        from ui_kobe.osworld.kimi_native import KimiNativeAgent
        mm_agents.qwen.QwenAgent = KimiNativeAgent
    else:
        from ui_kobe.osworld.kimi_taskviews_native import KimiTaskViewsNativeAgent
        mm_agents.qwen.QwenAgent = KimiTaskViewsNativeAgent
    from ui_kobe.osworld.telemetry import install
    from ui_kobe.api.kimi import install_official_k3_transport
    from ui_kobe.osworld.qwen_judge import install_qwen_judge_backend
    install(root / "telemetry")
    install_official_k3_transport()
    install_qwen_judge_backend()
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
