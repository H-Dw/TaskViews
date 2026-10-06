from types import SimpleNamespace

import pytest

from scripts import native_resource_accounting as policy


GIB = 1024**3


def test_previous_resource_stop_uses_own_actual_memory_credit():
    raw = {"available_ram_gib": 3.494335174560547, "c_free_gib": 146.2, "d_free_gib": 19.17}
    adjusted = policy.adjusted_windows(raw, 4193579008)
    assert adjusted["available_ram_gib"] == raw["available_ram_gib"]
    assert adjusted["raw_available_ram_gib"] < 4
    assert adjusted["available_excluding_experiment_gib"] == pytest.approx(7.3999, abs=0.001)
    assert policy.reserve_ok(adjusted)


def test_external_pressure_and_disk_limits_still_stop_the_experiment():
    raw = {"available_ram_gib": 1.9, "c_free_gib": 46, "d_free_gib": 13}
    assert not policy.reserve_ok(policy.adjusted_windows(raw, 2 * GIB))
    raw["available_ram_gib"] = 10
    for key, limit in [("c_free_gib", 35), ("d_free_gib", 10)]:
        assert not policy.reserve_ok(policy.adjusted_windows({**raw, key: limit - 0.001}, 2 * GIB))
    assert not policy.reserve_ok(policy.adjusted_windows({**raw, "available_ram_gib": 4.999}, 0), startup=True)


def test_startup_five_gib_boundary_preserves_runtime_and_disk_reserves():
    raw = {"available_ram_gib": 4, "c_free_gib": 45, "d_free_gib": 12}
    adjusted = policy.adjusted_windows(raw, GIB)
    assert policy.reserve_ok(adjusted, startup=True)
    assert not policy.reserve_ok(policy.adjusted_windows(raw, GIB - 1), startup=True)
    for key, value in [("c_free_gib", 44.999), ("d_free_gib", 11.999)]:
        assert not policy.reserve_ok({**adjusted, key: value}, startup=True)
    assert policy.reserve_ok(policy.adjusted_windows(raw, 0))
    assert not policy.reserve_ok(policy.adjusted_windows({**raw, "available_ram_gib": 3.999}, 0))


def test_vm_preflight_uses_five_for_native_and_keeps_legacy_default(tmp_path):
    from scripts.run_official_qwen_task035 import minimal_preflight
    kvm = tmp_path / "kvm"
    kvm.touch()
    status = {"available_ram_gib": 5, "c_free_gib": 45, "d_free_gib": 12}
    budget = SimpleNamespace(host_status=lambda: status, LABEL="owner", OWNER="native")
    client = SimpleNamespace(containers=SimpleNamespace(list=lambda **kwargs: []))
    assert minimal_preflight(client, budget, kvm, startup_available_gib=policy.STARTUP_AVAILABLE_GIB) == status
    with pytest.raises(RuntimeError, match="at least 6"):
        minimal_preflight(client, budget, kvm)
    status["available_ram_gib"] = 4.999
    with pytest.raises(RuntimeError, match="at least 5"):
        minimal_preflight(client, budget, kvm, startup_available_gib=policy.STARTUP_AVAILABLE_GIB)
    status.update(available_ram_gib=5, d_free_gib=11.999)
    with pytest.raises(RuntimeError, match="Disk reserve"):
        minimal_preflight(client, budget, kvm, startup_available_gib=policy.STARTUP_AVAILABLE_GIB)


@pytest.mark.parametrize("used", [-1, float("nan"), 5.75, True])
def test_invalid_measurement_cannot_become_memory_credit(used):
    with pytest.raises(ValueError):
        policy.adjusted_windows({"available_ram_gib": 1}, used)


def memory_group(path, used, cap=2 * GIB):
    path.mkdir(parents=True)
    for name, value in {"memory.max": cap, "memory.swap.max": 0, "memory.current": used,
                        "memory.events": "oom 0\noom_kill 0\n"}.items():
        (path / name).write_text(str(value))
    return path


class Container:
    def __init__(self, identifier, used, run_id=None, service=None):
        self.id = self.name = identifier
        self.used = used
        self.labels = ({"ui-kobe.osworld.run": run_id} if run_id else
                       {"com.docker.compose.project": "osworld-local-web", "com.docker.compose.service": service})
        cap = 3 * GIB if run_id else policy.WEB_CAPS[service]
        self.attrs = {"HostConfig": {"Memory": cap, "MemorySwap": cap},
                      "State": {"Running": True, "OOMKilled": False}}
        self.stats_calls = 0

    def reload(self):
        pass

    def stats(self, **kwargs):
        self.stats_calls += 1
        return {"memory_stats": {"usage": self.used}}


class Containers:
    def __init__(self, items):
        self.items = items

    def list(self, all, filters):
        key, value = filters["label"].split("=", 1)
        return [item for item in self.items if item.labels.get(key) == value]

    def get(self, identifier):
        return next(item for item in self.items if item.id == identifier)


def test_sampling_excludes_foreign_containers_and_counts_owned_memory_once(tmp_path, monkeypatch):
    group = memory_group(tmp_path / "service", GIB)
    nested = memory_group(group / "child", GIB // 4, policy.AUX_LIMIT)
    monkeypatch.setattr(policy, "auxiliary_groups", lambda: {nested})
    vm = Container("vm", 2 * GIB, run_id="current")
    foreign = Container("foreign", 3 * GIB, run_id="another")
    web = Container("web", 64 * 1024**2, service="caddy")
    client = SimpleNamespace(containers=Containers([vm, foreign, web]))
    manifest = {"run_id": "current", "cgroup": str(group), "web_container_ids": ["web", "web"], "web_owned": True}
    def raw():
        return {"available_ram_gib": 2.5, "c_free_gib": 100, "d_free_gib": 20}
    record = policy.sample(client, manifest, raw, group)
    assert record["windows"]["owned_memory_bytes"] == 3 * GIB + web.used
    assert len(record["owned_cgroups"]) == 1
    assert foreign.stats_calls == 0 and vm.stats_calls == web.stats_calls == 1
    assert record["windows"]["available_excluding_experiment_gib"] == 5.5625
    assert record["windows"]["available_excluding_experiment_gib"] != 2.5 + 5.75
    manifest["web_owned"] = False
    assert policy.sample(client, manifest, raw, group)["windows"]["owned_memory_bytes"] == 3 * GIB


def test_scope_startup_counts_actual_helper_usage_and_zero_swap(tmp_path, monkeypatch):
    group = memory_group(tmp_path / "auxiliary", 24 * 1024**2, policy.AUX_LIMIT)
    monkeypatch.setattr(policy, "auxiliary_groups", lambda: {group})
    client = SimpleNamespace(containers=Containers([]))
    def raw():
        return {"available_ram_gib": 6, "c_free_gib": 100, "d_free_gib": 20}
    record = policy.sample(client, {}, raw, group)
    assert record["windows"]["owned_memory_bytes"] == 24 * 1024**2
    (group / "memory.swap.max").write_text("1")
    with pytest.raises(RuntimeError, match="limits changed"):
        policy.sample(client, {}, raw, group)


def test_vm_guard_legacy_hook_preserves_raw_measurement(tmp_path, monkeypatch):
    import json
    import docker
    from scripts import osworld_task035_background as background
    group = memory_group(tmp_path / "service", GIB)
    monkeypatch.setattr(policy, "auxiliary_groups", lambda: set())
    monkeypatch.setattr(background, "cgroup", lambda: group)
    vm = Container("vm", 2 * GIB, run_id="current")
    client = SimpleNamespace(containers=Containers([vm]), close=lambda: None)
    monkeypatch.setattr(docker, "from_env", lambda **kwargs: client)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"run_id": "current", "cgroup": str(group)}))
    probe = policy.BudgetHostProbe(manifest, lambda: {"available_ram_gib": 3.2, "c_free_gib": 100, "d_free_gib": 20})
    result = probe()
    assert result["available_ram_gib"] == pytest.approx(6.2)
    assert result["raw_available_ram_gib"] == 3.2
    assert result["owned_memory_bytes"] == 3 * GIB
    receipt = json.loads((tmp_path / "vm-guard-memory.jsonl").read_text())
    assert receipt["windows"]["available_ram_gib"] == 3.2
    assert receipt["windows"]["available_excluding_experiment_gib"] == pytest.approx(6.2)


@pytest.mark.parametrize("closing", [False, True])
def test_docker_404_allowed_only_after_official_close_with_no_memory_credit(tmp_path, monkeypatch, closing):
    from docker.errors import NotFound
    from ui_kobe.osworld.lifecycle import write_phase
    group = memory_group(tmp_path / "service", GIB)
    monkeypatch.setattr(policy, "auxiliary_groups", lambda: set())
    vm = Container("vm", 2 * GIB, run_id="current")
    def gone():
        # Reproduce a list/reload race. The official close starts after listing.
        if closing:
            write_phase(tmp_path, "closing")
        raise NotFound("removed during shutdown")
    vm.reload = gone
    client = SimpleNamespace(containers=Containers([vm]))
    manifest = {"run_id": "current", "run_dir": str(tmp_path), "cgroup": str(group)}
    def raw():
        return {"available_ram_gib": 2, "c_free_gib": 100, "d_free_gib": 20}
    if not closing:
        with pytest.raises(NotFound):
            policy.sample(client, manifest, raw, group)
    else:
        record = policy.sample(client, manifest, raw, group)
        assert record["teardown"] and record["missing_during_teardown"] == ["vm"]
        assert record["windows"]["owned_memory_bytes"] == GIB
        assert record["windows"]["available_excluding_experiment_gib"] == 3
        assert record["containers"] == []  # No cap or previous/peak usage fabricated.
