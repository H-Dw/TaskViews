"""Infrastructure-only resource caps around the original OSWorld-1 provider."""
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from scripts.native_resource_accounting import GIB, adjusted_windows, charged_group, outer_groups

LABEL = 'ui-kobe.verified.run'
ACTOR_LIMIT = 2 * GIB
LAUNCHER_LIMIT = 128 * 1024**2
VM_LIMIT = 3 * GIB


def resource_policy():
    return {'version': 'verified-physical-free2-owned-accounting-v1',
            'stop_metric': 'raw Windows available physical RAM',
            'minimum_free_ram_gib_exclusive': 2,
            'project_budget_metric': 'raw available RAM plus measured owned memory; audit only',
            'owned_sources': ['current bounded cgroup', 'verified launcher cgroup', 'exact run-label Docker VM'],
            'usage_not_hard_limits': True, 'exclude_unrelated_wsl': True,
            'checks': ['before guest startup', 'before each actor decision', 'before official evaluation'],
            'c_free_gib_min': 45, 'd_free_gib_min': 12, 'swap_bytes': 0}


def current_group(pid='self'):
    relative = Path(f'/proc/{pid}/cgroup').read_text().strip().split(':')[-1]
    return (Path('/sys/fs/cgroup') / relative.lstrip('/')).resolve()


def owned_memory(client, group, *, run_id=None, launcher=None):
    """Measure this run only, without charging whole WSL or crediting caps."""
    group = Path(group).resolve()
    cap = int((group / 'memory.max').read_text())
    if cap not in (ACTOR_LIMIT, LAUNCHER_LIMIT):
        raise RuntimeError('Verified accounting requires a bounded actor or helper scope')
    candidates = {group: cap}
    if launcher is not None:
        pid, declared_group = launcher
        declared_group = Path(declared_group).resolve()
        if current_group(pid) != declared_group:
            raise RuntimeError('Launcher process/cgroup ownership mismatch')
        candidates[declared_group] = LAUNCHER_LIMIT
    groups = [charged_group(item, candidates[item]) for item in outer_groups(candidates)]
    items = client.containers.list(all=True, filters={'label': f'{LABEL}={run_id}'}) if run_id else []
    by_id = {item.id: item for item in items}
    if len(by_id) > 1:
        raise RuntimeError('More than one VM belongs to this verified run')
    containers = []
    for item in by_id.values():
        item.reload()
        if item.labels.get(LABEL) != run_id:
            raise RuntimeError('Verified VM ownership label mismatch')
        config, state = item.attrs['HostConfig'], item.attrs['State']
        if config['Memory'] != VM_LIMIT or config['MemorySwap'] != VM_LIMIT:
            raise RuntimeError('Verified VM memory limits changed')
        memory = item.stats(stream=False, one_shot=True).get('memory_stats', {}) if state['Running'] else {}
        used = memory.get('usage') if state['Running'] else 0
        if isinstance(used, bool) or not isinstance(used, int) or used < 0:
            raise RuntimeError('Invalid verified VM actual memory counter')
        containers.append({'id': item.id, 'usage_bytes': used, 'limit_bytes': VM_LIMIT,
                           'running': state['Running'], 'oom_killed': state['OOMKilled']})
    total = sum(item['usage_bytes'] for item in groups) + sum(item['usage_bytes'] for item in containers)
    return {'owned_cgroups': groups, 'owned_containers': containers, 'owned_memory_bytes': total}


def check_headroom(raw, measured):
    windows = adjusted_windows(raw, measured['owned_memory_bytes'])
    passed = (windows['raw_available_ram_gib'] > 2
              and windows['c_free_gib'] >= 45 and windows['d_free_gib'] >= 12)
    return {'policy': resource_policy(), **measured, 'windows': windows, 'headroom_ok': passed}


class BoundedContainers:
    def __init__(self, original, plan):
        self.original, self.plan = original, plan

    def __getattr__(self, name):
        return getattr(self.original, name)

    def run(self, image, **kwargs):
        if image != 'happysixd/osworld-docker':
            raise RuntimeError('Unexpected upstream Docker image')
        kwargs.update(mem_limit=self.plan['vm_memory_bytes'], memswap_limit=self.plan['vm_memory_bytes'],
            nano_cpus=2_000_000_000, pids_limit=512,
            labels={LABEL: os.environ['OSWORLD_FULL_RUN_ID']})
        return self.original.run(self.plan['docker_image'], **kwargs)


class BoundedDockerClient:
    def __init__(self, original, plan):
        self.original = original
        # DockerClient.containers constructs a NEW collection on every access.
        # Keep the decorated collection on this proxy, not on a temporary object.
        self.containers = BoundedContainers(original.containers, plan)

    def __getattr__(self, name):
        return getattr(self.original, name)


def resource_guard(*, startup, audit_path=None, phase=None, decision=None):
    from scripts.osworld_native_experiment import host_status
    import docker
    if len(Path('/proc/swaps').read_text().splitlines()) != 1 or not Path('/dev/kvm').is_char_device():
        raise RuntimeError('This profile requires KVM and zero host swap')
    launcher = None
    if os.environ.get('OSWORLD_VERIFIED_LAUNCHER_PID'):
        launcher = (int(os.environ['OSWORLD_VERIFIED_LAUNCHER_PID']),
                    os.environ['OSWORLD_VERIFIED_LAUNCHER_CGROUP'])
    with closing(docker.from_env(timeout=15)) as client:
        measured = owned_memory(client, current_group(), run_id=os.environ.get('OSWORLD_FULL_RUN_ID'),
                                launcher=launcher)
        record = {'time_utc': datetime.now(timezone.utc).isoformat(), 'startup': startup,
                  'phase': phase or ('startup' if startup else 'before_predict'), 'decision': decision,
                  **check_headroom(host_status(), measured)}
        if audit_path is not None:
            with Path(audit_path).open('a', encoding='utf-8') as log:
                log.write(json.dumps(record, ensure_ascii=False) + '\n')
        if not record['headroom_ok']:
            raw = record['windows']
            raise RuntimeError('OSWorld-Verified resource headroom requires raw free RAM >2 GiB and C/D >=45/12 GiB; '
                f'startup={startup}, raw_available_ram_gib={raw["raw_available_ram_gib"]:.3f}, '
                f'owned_memory_bytes={raw["owned_memory_bytes"]}, '
                f'available_excluding_project_gib={raw["available_excluding_experiment_gib"]:.3f}, '
                f'c_free_gib={raw["c_free_gib"]:.3f}, d_free_gib={raw["d_free_gib"]:.3f}')
        if startup:
            for container in client.containers.list():
                if ('osworld' in str(container.attrs.get('Config', {}).get('Image', '')).lower()
                        or container.labels.get('osworld.local.owner')):
                    raise RuntimeError('Another OSWorld guest is running')
    return record


def install_provider(plan):
    from desktop_env.providers.docker.provider import DockerProvider
    from desktop_env.controllers.setup import SetupController
    original_init = DockerProvider.__init__
    original_setup = SetupController.setup

    def setup(self, *args, **kwargs):
        result = original_setup(self, *args, **kwargs)
        if result is not True:
            raise RuntimeError('Official setup did not succeed; stop before actor/evaluation')
        return result
    SetupController.setup = setup

    def initialize(self, region):
        original_init(self, region)
        self.environment.update(RAM_SIZE=plan['guest_ram'], CPU_CORES='2')
        self.client = BoundedDockerClient(self.client, plan)
    DockerProvider.__init__ = initialize
