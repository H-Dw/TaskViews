"""Attribute this experiment's charged memory without counting unrelated WSL use.

The adjusted reserve is a budget metric, not Windows free physical memory.
All source counters are retained; hard limits are never used as usage credits.
"""
from __future__ import annotations

import atexit
import json
import math
import os
from pathlib import Path
import time
import threading

GIB = 1024**3
AUX_LIMIT = 128 * 1024**2
SERVICE_LIMIT = 2 * GIB
POLICY = "windows-free-plus-owned-charged-memory-v1"
STARTUP_AVAILABLE_GIB = 5
RUNTIME_AVAILABLE_GIB = 4
WEB_CAPS = {"caddy": AUX_LIMIT, "teamchat_web_backend": 512 * 1024**2,
            "teamchat_web_frontend": AUX_LIMIT}
REGISTRY = Path.home() / "osworld2/logs/native-auxiliary-memory"
_registered = set()


def register_auxiliary(group):
    """Called only after the current helper's 128 MiB/zero-swap scope is checked."""
    group = Path(group).resolve()
    pid = os.getpid()
    if (pid, str(group)) in _registered:
        return
    REGISTRY.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = REGISTRY / f"{pid}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"pid": pid, "cgroup": str(group), "owner": "ui-kobe-native-auxiliary"}))
    temporary.replace(path)
    _registered.add((pid, str(group)))
    atexit.register(lambda: path.unlink(missing_ok=True))


def auxiliary_groups():
    groups = set()
    for path in REGISTRY.glob("*.json"):
        try:
            item = json.loads(path.read_text())
            if item.get("owner") != "ui-kobe-native-auxiliary":
                continue
            relative = Path(f"/proc/{int(item['pid'])}/cgroup").read_text().strip().split(":")[-1]
            actual = (Path("/sys/fs/cgroup") / relative.lstrip("/")).resolve()
            if str(actual) == item["cgroup"]:
                groups.add(actual)
        except (FileNotFoundError, ProcessLookupError):
            continue
    if len(groups) > 1:
        raise RuntimeError("More than one experiment auxiliary scope is active")
    return groups


def outer_groups(groups):
    """A parent's memory.current already includes every descendant."""
    result = []
    for group in sorted({Path(p).resolve() for p in groups}, key=lambda p: len(p.parts)):
        if not any(group == parent or parent in group.parents for parent in result):
            result.append(group)
    return result


def charged_group(group, expected_limit):
    group = Path(group)
    limit = (group / "memory.max").read_text().strip()
    swap = (group / "memory.swap.max").read_text().strip()
    if limit != str(expected_limit) or swap != "0":
        raise RuntimeError(f"Experiment cgroup limits changed: {group}")
    used = int((group / "memory.current").read_text())
    if used < 0:
        raise RuntimeError("Negative cgroup memory counter")
    return {"source": "cgroup-v2/memory.current", "cgroup": str(group),
            "usage_bytes": used, "limit_bytes": expected_limit, "swap_max": 0,
            "memory_events": dict(line.split() for line in (group / "memory.events").read_text().splitlines())}


def adjusted_windows(raw, owned_bytes):
    if isinstance(owned_bytes, bool) or not isinstance(owned_bytes, int) or owned_bytes < 0:
        raise ValueError("Owned memory must be a measured nonnegative byte count")
    free = raw["available_ram_gib"]
    if isinstance(free, bool) or not isinstance(free, (int, float)) or not math.isfinite(free) or free < 0:
        raise ValueError("Windows free memory counter is invalid")
    return {**raw, "raw_available_ram_gib": free, "owned_memory_bytes": owned_bytes,
            "available_excluding_experiment_gib": free + owned_bytes / GIB,
            "memory_policy": POLICY}


def sample(client, manifest, raw_host_status, current_group, *, teardown=False):
    from ui_kobe.osworld.lifecycle import is_teardown
    def closing_now():
        return teardown or (bool(manifest.get("run_dir")) and is_teardown(manifest["run_dir"]))
    started = time.monotonic()
    group = Path(manifest.get("cgroup") or current_group).resolve()
    expected = SERVICE_LIMIT if manifest.get("cgroup") else AUX_LIMIT
    # The supervisor also checks admission from inside its 2 GiB service.
    if group == Path(current_group).resolve() and (group / "memory.max").read_text().strip() == str(SERVICE_LIMIT):
        expected = SERVICE_LIMIT
    groups = outer_groups([group, *auxiliary_groups()])
    group_records = [charged_group(p, expected if p == group else AUX_LIMIT) for p in groups]
    primary = next(item for item in group_records if item["cgroup"] == str(group))
    items = []
    run_id = manifest.get("run_id")
    if run_id:
        items = client.containers.list(all=True, filters={"label": f"ui-kobe.osworld.run={run_id}"})
    if len(items) > 1:
        raise RuntimeError("More than one VM belongs to this experiment")
    vm_ids = {item.id for item in items}
    web_ids = set(manifest.get("web_container_ids", []))
    by_id = {item.id: item for item in items}
    missing = []
    for identifier in web_ids:
        try:
            item = client.containers.get(identifier)
        except Exception as exc:
            from docker.errors import NotFound
            if not closing_now() or not isinstance(exc, NotFound):
                raise
            teardown = True
            missing.append(identifier)
            continue
        by_id[item.id] = item
    containers = []
    total_used = owned_containers = total_cap = 0
    for container in by_id.values():
        try:
            container.reload()
        except Exception as exc:
            from docker.errors import NotFound
            if not closing_now() or not isinstance(exc, NotFound):
                raise
            teardown = True
            missing.append(container.id)
            continue
        config, state = container.attrs["HostConfig"], container.attrs["State"]
        if container.id in vm_ids:
            if container.labels.get("ui-kobe.osworld.run") != run_id:
                raise RuntimeError("VM ownership label mismatch")
            cap, owned = 3 * GIB, True
        else:
            service = container.labels.get("com.docker.compose.service")
            if (container.labels.get("com.docker.compose.project") != "osworld-local-web"
                    or service not in WEB_CAPS):
                raise RuntimeError("Unexpected website container in experiment manifest")
            cap, owned = WEB_CAPS[service], manifest.get("web_owned") is True
        if config["Memory"] != cap or config["MemorySwap"] != cap:
            raise RuntimeError(f"Container memory cap changed: {container.name}")
        stats = container.stats(stream=False, one_shot=True).get("memory_stats", {}) if state["Running"] else {}
        used = stats["usage"] if state["Running"] else 0
        if isinstance(used, bool) or not isinstance(used, int) or used < 0:
            raise RuntimeError("Invalid Docker memory usage counter")
        total_cap += cap
        total_used += used
        owned_containers += used if owned else 0
        containers.append({"id": container.id, "name": container.name, "usage_bytes": used,
                           "limit_bytes": cap, "running": state["Running"], "owned_memory_credit": owned,
                           "oom_killed": state["OOMKilled"], "memory_stats": stats})
    measured_group_bytes = sum(item["usage_bytes"] for item in group_records)
    measured_caps = total_cap + sum(item["limit_bytes"] for item in group_records)
    if measured_caps >= 6 * GIB:
        raise RuntimeError("Experiment plus auxiliary hard limits reached 6 GiB")
    windows = adjusted_windows(raw_host_status(), measured_group_bytes + owned_containers)
    return {"memory_policy": POLICY, "windows": windows, "service_memory_bytes": primary["usage_bytes"],
            "service_memory_events": primary["memory_events"], "owned_cgroups": group_records,
            "aggregate_usage_bytes": primary["usage_bytes"] + total_used,
            "aggregate_usage_with_auxiliary_bytes": measured_group_bytes + total_used,
            "aggregate_hard_cap_bytes": int(5.75 * GIB), "measured_component_hard_caps_bytes": measured_caps,
            "containers": containers, "missing_during_teardown": missing, "teardown": teardown,
            "accounting_duration_s": round(time.monotonic() - started, 6)}


def reserve_ok(windows, startup=False):
    ram, disk_c, disk_d = (STARTUP_AVAILABLE_GIB, 45, 12) if startup else (RUNTIME_AVAILABLE_GIB, 35, 10)
    return (windows["available_excluding_experiment_gib"] >= ram
            and windows["c_free_gib"] >= disk_c and windows["d_free_gib"] >= disk_d)


class BudgetHostProbe:
    """Feed the same adjusted metric to the existing VM preflight and watcher.

The legacy hook requires the key available_ram_gib. Its original raw value is
kept separately, and every fresh observation has a full attribution receipt.
"""

    def __init__(self, manifest_path, raw_host_status):
        import docker
        self.manifest_path = Path(manifest_path)
        self.raw_host_status = raw_host_status
        self.client = docker.from_env(timeout=15)
        self.lock = threading.Lock()
        self.cached = None
        self.cached_at = 0
        atexit.register(self.client.close)

    def __call__(self):
        from datetime import datetime, timezone
        from scripts.osworld_task035_background import cgroup
        with self.lock:
            if self.cached is not None and time.monotonic() - self.cached_at < 2:
                return dict(self.cached)
            manifest = json.loads(self.manifest_path.read_text())
            record = {"time_utc": datetime.now(timezone.utc).isoformat(),
                      **sample(self.client, manifest, self.raw_host_status, cgroup())}
            with (self.manifest_path.parent / "vm-guard-memory.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps(record) + "\n")
            self.cached = {**record["windows"],
                "available_ram_gib": record["windows"]["available_excluding_experiment_gib"],
                "legacy_available_ram_key_semantics": "adjusted reserve; see raw_available_ram_gib for Windows free physical memory"}
            self.cached_at = time.monotonic()
            return dict(self.cached)
