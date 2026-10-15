from types import SimpleNamespace

import pytest

from ui_kobe.osworld import verified_resources as resource


GIB = 1024**3


def group(path, used, cap):
    path.mkdir(parents=True)
    for name, value in {'memory.max': cap, 'memory.swap.max': 0, 'memory.current': used,
                        'memory.events': 'oom 0\noom_kill 0\n'}.items():
        (path / name).write_text(str(value))
    return path


class Container:
    def __init__(self, run_id, used, identifier='vm'):
        self.id = identifier
        self.labels = {resource.LABEL: run_id}
        self.used, self.stats_calls = used, 0
        self.attrs = {'HostConfig': {'Memory': 3 * GIB, 'MemorySwap': 3 * GIB},
                      'State': {'Running': True, 'OOMKilled': False}}

    def reload(self):
        pass

    def stats(self, **kwargs):
        self.stats_calls += 1
        return {'memory_stats': {'usage': self.used}}


def client_for(items):
    def listing(all=True, filters=None):
        if filters:
            key, value = filters['label'].split('=', 1)
            return [item for item in items if item.labels.get(key) == value]
        return items
    return SimpleNamespace(containers=SimpleNamespace(list=listing), close=lambda: None)


def test_ownership_uses_actual_memory_and_excludes_foreign_containers(tmp_path, monkeypatch):
    actor = group(tmp_path / 'actor', GIB // 2, 2 * GIB)
    launcher = group(tmp_path / 'launcher', 24 * 1024**2, resource.LAUNCHER_LIMIT)
    monkeypatch.setattr(resource, 'current_group', lambda pid='self': launcher)
    vm, foreign = Container('current', GIB), Container('foreign', 3 * GIB, 'foreign')
    measured = resource.owned_memory(client_for([vm, foreign]), actor, run_id='current', launcher=(123, launcher))
    assert measured['owned_memory_bytes'] == GIB + GIB // 2 + 24 * 1024**2
    assert vm.stats_calls == 1 and foreign.stats_calls == 0
    assert len(measured['owned_cgroups']) == 2
    assert measured['owned_containers'][0]['usage_bytes'] == GIB
    assert measured['owned_memory_bytes'] < 3 * GIB  # Caps cannot become usage credits.


def test_nested_cgroups_and_duplicate_vm_ids_cannot_be_counted_twice(tmp_path, monkeypatch):
    launcher = group(tmp_path / 'launcher', 40 * 1024**2, resource.LAUNCHER_LIMIT)
    child = group(launcher / 'child', 10 * 1024**2, 2 * GIB)
    monkeypatch.setattr(resource, 'current_group', lambda pid='self': launcher)
    vm = Container('current', GIB)
    measured = resource.owned_memory(client_for([vm, vm]), child, run_id='current', launcher=(123, launcher))
    assert measured['owned_memory_bytes'] == GIB + 40 * 1024**2
    assert len(measured['owned_cgroups']) == 1 and vm.stats_calls == 1


def test_launcher_pid_must_still_belong_to_declared_group(tmp_path, monkeypatch):
    actor = group(tmp_path / 'actor', GIB // 2, 2 * GIB)
    monkeypatch.setattr(resource, 'current_group', lambda pid='self': tmp_path / 'foreign')
    with pytest.raises(RuntimeError, match='ownership mismatch'):
        resource.owned_memory(client_for([]), actor, launcher=(123, tmp_path / 'launcher'))


@pytest.mark.parametrize('free', [3.736, 3.821, 2.000001])
def test_previous_false_stops_now_pass_without_recharging_project_memory(free):
    result = resource.check_headroom({'available_ram_gib': free, 'c_free_gib': 46, 'd_free_gib': 13},
        {'owned_memory_bytes': 3 * GIB})
    assert result['headroom_ok']
    assert result['windows']['raw_available_ram_gib'] == free
    assert result['windows']['available_excluding_experiment_gib'] == pytest.approx(free + 3)


@pytest.mark.parametrize('free', [2.0, 1.9, 0])
def test_actual_two_gib_floor_cannot_be_hidden_by_project_memory_credit(free):
    result = resource.check_headroom({'available_ram_gib': free, 'c_free_gib': 46, 'd_free_gib': 13},
        {'owned_memory_bytes': 5 * GIB})
    assert not result['headroom_ok'] and result['windows']['available_excluding_experiment_gib'] > 2


def test_disk_and_scope_limits_remain_enforced(tmp_path):
    actor = group(tmp_path / 'actor', 20 * 1024**2, 2 * GIB)
    (actor / 'memory.swap.max').write_text('1')
    with pytest.raises(RuntimeError, match='limits changed'):
        resource.owned_memory(client_for([]), actor)
    for values in ({'c_free_gib': 44.99, 'd_free_gib': 13}, {'c_free_gib': 46, 'd_free_gib': 11.99}):
        assert not resource.check_headroom({'available_ram_gib': 10, **values}, {'owned_memory_bytes': 0})['headroom_ok']


@pytest.mark.parametrize('used', [None, True, -1])
def test_invalid_docker_usage_does_not_become_budget_credit(tmp_path, used):
    actor = group(tmp_path / 'actor', 20 * 1024**2, 2 * GIB)
    with pytest.raises(RuntimeError, match='actual memory counter'):
        resource.owned_memory(client_for([Container('current', used)]), actor, run_id='current')


def test_guard_failure_saves_raw_and_owned_metrics_before_stopping(tmp_path, monkeypatch):
    import docker
    import json
    from scripts import osworld_native_experiment
    actor = group(tmp_path / 'actor', GIB // 2, 2 * GIB)
    monkeypatch.setattr(resource, 'current_group', lambda pid='self': actor)
    monkeypatch.setattr(docker, 'from_env', lambda **kwargs: client_for([Container('current', GIB)]))
    monkeypatch.setenv('OSWORLD_FULL_RUN_ID', 'current')
    monkeypatch.delenv('OSWORLD_VERIFIED_LAUNCHER_PID', raising=False)
    monkeypatch.setattr(osworld_native_experiment, 'host_status', lambda: {
        'available_ram_gib': 1.9, 'c_free_gib': 68.1, 'd_free_gib': 46.3})
    original_read = resource.Path.read_text
    monkeypatch.setattr(resource.Path, 'read_text', lambda path, *a, **kw:
        'Filename\tType\tSize\tUsed\tPriority\n' if str(path) == '/proc/swaps' else original_read(path, *a, **kw))
    monkeypatch.setattr(resource.Path, 'is_char_device', lambda path: str(path) == '/dev/kvm')
    log = tmp_path / 'memory.jsonl'
    with pytest.raises(RuntimeError, match='raw_available_ram_gib=1.900'):
        resource.resource_guard(startup=False, audit_path=log, decision=10)
    saved = json.loads(log.read_text())
    assert saved['decision'] == 10 and saved['windows']['raw_available_ram_gib'] == 1.9
    assert saved['windows']['available_excluding_experiment_gib'] == 3.4
    assert saved['owned_memory_bytes'] == GIB + GIB // 2
