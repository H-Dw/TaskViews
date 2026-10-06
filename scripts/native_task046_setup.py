"""Harness-only verification of official Task046 setup and native site routing."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from scripts.osworld_native_experiment import digest, load, now, write

APPS = ("teamchat", "vaultbank", "mailhub")


def install_setup_verification(stage):
    from desktop_env.desktop_env import DesktopEnv
    from desktop_env.controllers import website
    from ui_kobe.osworld.local_web import configure_local_websites, verify_local_websites
    from scripts.osworld_task035_background import cgroup

    stage = Path(stage)
    manifest = load(stage / "manifest.json")
    plan = load(Path(manifest["plan_root"]) / "plan.json")
    if website.HOST_SUFFIX != "127.0.0.1.nip.io:21280":
        raise RuntimeError("Task046 needs the frozen local website origin suffix")
    original_setup = DesktopEnv._setup_task
    original_prepare = website.prepare_stateful_website_urls

    def prepare(*args, **kwargs):
        # Called by the unchanged official task. The official helper performs
        # GET/PUT of the original state. The observer returns every response as-is.
        import requests
        original_put = requests.put
        receipts = []

        def put(url, **options):
            app = urlsplit(url).hostname.split(".")[0]
            if app not in APPS or urlsplit(url).path != "/api/state":
                return original_put(url, **options)
            asset_path = Path.home() / "osworld2/assets/osworld-v2.1/task_046" / (app + "_state.json")
            if digest(asset_path) != plan["asset_sha256"][str(asset_path)]:
                raise RuntimeError("Task046 original state asset changed")
            expected = load(asset_path)
            if options.get("json") != expected:
                raise RuntimeError("Official state import payload differs from its original asset")
            response = original_put(url, **options)
            receipts.append({"app": app, "time_utc": now(), "url": url, "http_status": response.status_code,
                "source_sha256": digest(asset_path), "payload_matches_original": True,
                "canonical_payload_sha256": hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()})
            return response

        requests.put = put
        try:
            urls = original_prepare(*args, **kwargs)
        finally:
            requests.put = original_put
            write(stage / "official-state-import.json", {"time_utc": now(), "receipts": receipts})
        if {item["app"] for item in receipts if 200 <= item["http_status"] < 300} != set(APPS):
            raise RuntimeError("Official Task046 state import did not succeed for all sites")
        return urls

    website.prepare_stateful_website_urls = prepare

    def setup(env, task_config, use_proxy):
        group = cgroup()
        if group.resolve() != Path(manifest["cgroup"]).resolve():
            raise RuntimeError("Official runner/Agent do not share the website service cgroup")
        configure_local_websites(env, APPS)
        result = original_setup(env, task_config, use_proxy)
        if result[0]:
            opened = verify_local_websites(env, APPS)
            env.provider.container.reload()
            proof = {"time_utc": now(), "official_setup_success": True, "browser_tabs": opened,
                "runner_pid": os.getpid(), "runner_agent_cgroup": str(group),
                "website_cgroups": [p["cgroup"] for p in load(stage / "manifest.json")["native_web"]["processes"]],
                "vm_container": env.provider.container.id,
                "origins": ["http://" + app + ".127.0.0.1.nip.io:21280" for app in APPS],
                "state_import_evidence": str(stage / "official-state-import.json"),
                "state_import_evidence_sha256": digest(stage / "official-state-import.json"),
                "model_visible": False}
            write(stage / "official-setup-verification.json", proof)
        return result

    DesktopEnv._setup_task = setup


def run_setup_only(runner, manifest):
    """Instantiate official environment/Agent, reset once, never predict/evaluate."""
    from desktop_env.desktop_env import DesktopEnv

    args = runner["config"](manifest["official_arguments"])
    example = runner["_load_example"]("tasks", "046", args)
    spec = runner["_env_spec"](example, args)
    env, agent = None, None
    stage = Path(manifest["run_dir"])
    try:
        env = DesktopEnv(path_to_vm=args.path_to_vm, action_space=args.action_space,
            provider_name=args.provider_name, region=spec["region"], snapshot_name=spec["snapshot_name"],
            screen_size=(args.screen_width, args.screen_height), headless=args.headless,
            os_type=spec["os_type"], require_a11y_tree=False, enable_proxy=args.enable_proxy,
            client_password=args.client_password, instance_type=spec["instance_type"], volume_size=spec["volume_size"],
            use_public_ip=args.use_public_ip, force_disable_vnc=not args.enable_vnc,
            force_disable_recording=not args.enable_recording, cache_dir=args.cache_dir)
        agent = runner["_new_agent"](args, spec["os_type"])
        agent.reset()
        observation = env.reset(task_config=example)
        if not observation.get("screenshot"):
            raise RuntimeError("Official setup returned no screenshot")
        (stage / "setup-screenshot.png").write_bytes(observation["screenshot"])
        write(stage / "setup-only-result.json", {"status": "passed", "time_utc": now(),
            "model_requests": 0, "actions": 0, "evaluations": 0, "score": None,
            "agent_type": type(agent).__name__, "official_reset_completed": True,
            "setup_evidence_sha256": digest(stage / "official-setup-verification.json")})
    except BaseException as error:
        write(stage / "setup-only-error.json", {"time_utc": now(), "type": type(error).__name__, "error": str(error)})
        raise
    finally:
        if agent is not None:
            agent.close()
        if env is not None:
            env.close()
