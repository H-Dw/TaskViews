"""Prepare/check an OSWorld-1 invoice comparison; execution is explicit opt-in.

Prepare/check never produce VM/GUI actions or an official score. Prepare can
make separately logged research requests only with --keyboard-research.
Each approved arm runs in a new interpreter and a fresh official Docker guest.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import uuid

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from ui_kobe.osworld.verified_tasks import (TASKS, asset_files, download_files, expected_asset_name, task_path)  # noqa: E402
TASK_ID = '337d318b-aa07-4f4f-b763-89d9a2dd013f'
TASK_PATH = f'evaluation_examples/examples/multi_apps/{TASK_ID}.json'
BENCHMARK_COMMIT = 'b138d348256078fa634fc3b73567a7337c793e6b'
COMPILER_COMMIT = '3d778a3c9a34a079316f70df023b166700445792'
IMAGE_REVISION = 'a5d9c3eaae98eebf6e3a0beb84e7e47cf72ae133'
IMAGE_ZIP_SHA256 = 'b795b6cd4c69b252c1b4f10150a347795555032501b60fd031751ed09b896712'
DOCKER_IMAGE = 'happysixd/osworld-docker@sha256:0e6497a9295647cf05bf2b2af522fdd79bdeba2737595259cab310a3bcf6baa9'
ARMS = ('ui_kobe_like', 'taskviews')
ALL_ARMS = ('ui_kobe_like', 'baseline', 'taskviews')
MAX40_EXPERIMENTS = {
    'sx-max-high40': ('high', ALL_ARMS),
    'sx-mini-max-high40': ('high', ('taskviews',)),
    'sx-max-medium40': ('medium', ('baseline', 'taskviews')),
    'sx-max-low40': ('low', ('baseline', 'taskviews')),
    'sx-pair-max-high40': ('high', ('baseline', 'taskviews')),
}
EXPERIMENTS = ('legacy-low35', *MAX40_EXPERIMENTS)
GENERATION = 'qwen-sse-low-total16k'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def sha(path, *, release_cache=False):
    result = hashlib.sha256()
    with Path(path).open('rb') as handle:
        offset = 0
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
            # Large immutable VM images should not displace guest/host memory
            # merely because their bytes were verified. This is a cache hint,
            # never a write, and is only enabled at image verification sites.
            if release_cache and hasattr(os, 'posix_fadvise'):
                try:
                    os.posix_fadvise(handle.fileno(), offset, len(block), os.POSIX_FADV_DONTNEED)
                except OSError:
                    pass  # Unsupported cache hints do not change the digest.
            offset += len(block)
    return result.hexdigest()


def source_identity(repo, commit, paths):
    repo = Path(repo).resolve()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()
    if git('rev-parse', 'HEAD') != commit:
        raise ValueError('Unexpected upstream commit: ' + str(repo))
    if git('status', '--porcelain', '--untracked-files=all', '--', *paths):
        raise ValueError('Upstream source has local changes: ' + str(repo))
    names = git('ls-files', '--', *paths).splitlines()
    if not names:
        raise ValueError('Missing upstream sources')
    return {'repo': str(repo), 'commit': commit, 'sha256': {name: sha(repo / name) for name in names}}


def sources(benchmark, compiler, task_key='invoice'):
    return {
        'benchmark': source_identity(benchmark, BENCHMARK_COMMIT,
            ['desktop_env', 'lib_run_single.py', 'lib_results_logger.py', 'mm_agents/os_symphony', task_path(task_key),
             'evaluation_examples/test_all.json']),
        'actor_compiler': source_identity(compiler, COMPILER_COMMIT, ['mm_agents/qwen']),
    }


def project_identity():
    paths = [path for folder in ('ui_kobe', 'kobe_views', 'scripts')
             for path in (PROJECT / folder).rglob('*.py')]
    paths.extend((PROJECT / 'kobe_views/key_tools').glob('*.json'))
    return {str(path.relative_to(PROJECT)): sha(path) for path in sorted(paths)}


def specification(provider='qwen', sx_url_env='SX_URL', coordinate_type='absolute', experiment='legacy-low35',
                  task_key='invoice', *, keyboard_task=None, keyboard_mode='task_names', keyboard_toolsets=()):
    task_spec = TASKS[task_key]
    single_vlc_mini = task_key == 'vlc' and experiment == 'sx-mini-max-high40'
    if task_key != 'invoice' and experiment != 'sx-pair-max-high40' and not single_vlc_mini:
        raise ValueError('GIMP/VLC require the explicit baseline/Mini Max/high40 experiment')
    max40 = experiment in MAX40_EXPERIMENTS
    if experiment not in EXPERIMENTS or (max40 and provider != 'sx'):
        raise ValueError('Unknown experiment or provider incompatible with frozen experiment')
    if coordinate_type not in ('absolute', 'relative'):
        raise ValueError('Coordinate type must be explicitly absolute or relative')
    if provider == 'qwen':
        from ui_kobe.api import qwen_native as api
        generation, key_env = GENERATION, 'QWEN_API_KEY'
    elif provider == 'tinker':
        from ui_kobe.api import tinker_native as api
        generation, key_env = api.GENERATION, 'TINKER_API_KEY'
    elif provider == 'openrouter':
        from ui_kobe.api import openrouter_native as api
        generation, key_env = api.GENERATION, 'OPENROUTER_LTY_API_KEY'
    elif provider == 'sx':
        from ui_kobe.api import sx_native as api
        generation, key_env = api.GENERATION, 'SX_QWEN_API_KEY'
    else:
        raise ValueError('Unknown invoice provider')
    if max40:
        effort = MAX40_EXPERIMENTS[experiment][0]
        generation = getattr(api, 'MAX_' + effort.upper() + '_GENERATION')
    profile = api.generation_profile(generation)
    arms = MAX40_EXPERIMENTS[experiment][1] if max40 else ARMS
    max_steps = 40 if max40 else 35
    from ui_kobe.osworld.taskviews_profiles import frozen_profile, mini_cua_contract
    from kobe_views.keyboard_selection import task_keyboard_policy
    keyboard = task_keyboard_policy(keyboard_task if keyboard_task is not None else {},
                                    mode=keyboard_mode, requested=keyboard_toolsets)
    contract = mini_cua_contract()
    contract['coordinate_type'] = coordinate_type
    if provider == 'sx':
        # One full lossless frame can exceed 2M base64 characters. Allow the
        # existing 8MiB PNG transport bound, without increasing text/history,
        # image count, view bytes or output tokens in either comparison arm.
        contract['context_max_payload_chars'] = 12_000_000
    from ui_kobe.osworld.verified_resources import resource_policy
    return {'version': ('osworld-verified-invoice-v5' if task_key == 'invoice' else
                        'osworld-verified-vlc-mini-v4-v1' if single_vlc_mini else 'osworld-verified-media-v1'),
        'provider': provider, 'experiment': experiment,
        'interface': provider + '-native', 'benchmark': 'OSWorld-Verified (OSWorld-1)',
        'task_key': task_key, 'task_id': task_spec['id'], 'domain': task_spec['domain'],
        'snapshot': task_spec['snapshot'], 'metric': task_spec['metric'], 'arms': list(arms), 'max_steps': max_steps,
        'round_unit': 'actor.predict calls, including empty decisions; repair/API/GUI counts reported separately',
        'model': api.model_for_profile(profile) if provider == 'sx' else api.MODEL,
        'base_url': api.resolve_base_url(sx_url_env) if provider == 'sx' else api.BASE_URL,
        'base_url_env': sx_url_env if provider == 'sx' else None, 'generation_profile': profile.__dict__,
        'request_policy': api.request_policy(profile),
        'generation_fields': api.generation_request_fields(profile),
        'transport_policy': api.transport_policy(), 'api_key_env': key_env,
        'live_provider_check_required': provider in ('tinker', 'openrouter', 'sx'),
        'mini_grounding_check_required': provider == 'sx', 'coordinate_type': coordinate_type,
        'mini_grounding_check_policy': ('collect_all_record_accuracy' if experiment in
                                       ('sx-mini-max-high40', 'sx-max-medium40', 'sx-max-low40', 'sx-pair-max-high40')
                                        else 'all_targets_within30px'),
        'cua_contract': contract, 'taskviews_profile': 'mini_fixed_v1',
        'arm_profiles': {arm: frozen_profile(arm) for arm in arms},
        'controls_view': 'disabled', 'full_taskviews_feedback': False,
        **keyboard,
        'official_runner': 'lib_run_single.run_single_example', 'sleep_after_execution': 3,
        'evaluation': f'original DesktopEnv.evaluate after explicit terminal action or {max_steps} decisions',
        'score_threshold': None, 'checkpoint_resume': False,
        'isolation': 'new process, new Docker writable layer, new agent and journal per arm',
        'docker_image': DOCKER_IMAGE, 'guest_ram': '2G', 'vm_memory_bytes': 3 * 1024**3,
        'service_memory_bytes': 2 * 1024**3, 'swap_bytes': 0,
        'resource_policy': resource_policy(),
        'human_review_required': True, 'execution_authorized': False}


def verify_task(repo, task_key='invoice'):
    spec = TASKS[task_key]
    path = Path(repo) / task_path(task_key)
    task = read(path)
    if (task.get('id') != spec['id'] or task.get('snapshot') != spec['snapshot']
            or task.get('evaluator', {}).get('func') != spec['metric']
            or ('sha256' in spec and sha(path) != spec['sha256'])):
        raise ValueError('Unexpected pinned task contract: ' + task_key)
    if task_key == 'invoice' and ([item['type'] for item in task['config']] != ['download']
                                or len(download_files(task)) != 4):
        raise ValueError('Unexpected invoice task contract')
    if spec['id'] not in read(Path(repo) / 'evaluation_examples/test_all.json')[spec['domain']]:
        raise ValueError('Task is absent from official task list')
    return task


def prepare(args):
    root = args.root.resolve()
    if root.exists():
        raise FileExistsError('Use a new plan directory; existing plans are immutable')
    task_key = getattr(args, 'task', 'invoice')
    task = verify_task(args.benchmark_repo, task_key)
    spec = specification(args.provider, args.sx_url_env, args.coordinate_type, args.experiment, task_key,
                         keyboard_task=task, keyboard_mode=getattr(args, 'keyboard_mode', 'task_names'),
                         keyboard_toolsets=getattr(args, 'keyboard_toolset', ()))
    evidence = validation_evidence(args.validation_dir, args.provider, spec['base_url'], spec['cua_contract'], spec)
    plan = spec | {'sources': sources(args.benchmark_repo, args.compiler_repo, task_key),
        'project_source': project_identity(), 'image': str(args.image.resolve()),
        'image_proof': str(args.image_proof.resolve()), 'assets': str(args.assets.resolve()),
        'task_sha256': sha(args.benchmark_repo / task_path(task_key)), 'validation': evidence,
        'project_commit': subprocess.check_output(['git','-C',str(PROJECT),'rev-parse','HEAD'],text=True).strip(),
        'run_ids': {arm: f'{root.name}-{arm}-{uuid.uuid4().hex}' for arm in spec['arms']}}
    if args.image_proof.is_file():
        proof = read(args.image_proof)
        if proof['archive_sha256'] != IMAGE_ZIP_SHA256 or proof['image_sha256'] != sha(args.image, release_cache=True):
            raise ValueError('Image proof differs from official archive or extracted image')
        plan['image_identity'] = proof
    plan['asset_identity'] = {item['name']: sha(args.assets / item['name']) for item in asset_files(task)}
    root.mkdir(parents=True)
    from kobe_views.keyboard_research import prepare_research
    prepare_research(plan, task, root, enabled=getattr(args, 'keyboard_research', False),
                     config_path=getattr(args, 'keyboard_research_config', None))
    write(root / 'plan.json', plan)
    write(root / 'plan.sha256.json', {'sha256': sha(root / 'plan.json')})
    write(root / 'state.json', {'status': 'prepared_not_started', 'completed_arms': [],
                              'model_calls': 0, 'vm_starts': 0, 'evaluations': 0,
                              **({'research_model_calls': plan['mini_keyboard_research']['request_count']}
                                 if plan.get('mini_keyboard_research') else {})})
    print(json.dumps({'status': 'prepared_not_started', 'root': str(root), 'max_steps': spec['max_steps']}))


def validate_plan(root):
    plan = read(root / 'plan.json')
    if sha(root / 'plan.json') != read(root / 'plan.sha256.json')['sha256']:
        raise ValueError('Plan changed after preparation')
    for key, value in specification(plan.get('provider', 'qwen'), plan.get('base_url_env') or 'SX_URL',
                                    plan.get('coordinate_type', 'absolute'), plan.get('experiment','legacy-low35'),
                                    plan.get('task_key','invoice')).items():
        if key in ('mini_keyboard_tools', 'mini_keyboard_selection'):
            continue  # Recomputed below against the verified public task fields.
        if plan.get(key) != value:
            raise ValueError('Frozen comparison differs from implementation: ' + key)
    if project_identity() != plan['project_source']:
        raise ValueError('Project code changed; revalidate and prepare a fresh plan')
    run_ids = plan.get('run_ids')
    if (not isinstance(run_ids,dict) or set(run_ids) != set(plan['arms'])
            or any(not isinstance(v,str) or not v for v in run_ids.values())
            or len(set(run_ids.values())) != len(run_ids)):
        raise ValueError('Each arm requires a unique frozen run ownership label')
    if validation_evidence(Path(plan['validation']['directory']), plan['provider'], plan['base_url'],
                           plan['cua_contract'], plan) != plan['validation']:
        raise ValueError('Offline validation evidence changed')
    task_key = plan.get('task_key', 'invoice')
    actual = sources(plan['sources']['benchmark']['repo'], plan['sources']['actor_compiler']['repo'], task_key)
    if actual != plan['sources']:
        raise ValueError('Upstream source changed')
    task = verify_task(plan['sources']['benchmark']['repo'], task_key)
    if sha(Path(plan['sources']['benchmark']['repo']) / task_path(task_key)) != plan['task_sha256']:
        raise ValueError('Task identity differs from frozen plan')
    from kobe_views.keyboard_selection import validate_task_keyboard
    validate_task_keyboard(plan, task)
    from kobe_views.task_keyboard import validate_plan_research
    validate_plan_research(plan, task)
    if set(plan['asset_identity']) != {item['name'] for item in asset_files(task)}:
        raise ValueError('Task assets differ from frozen plan')
    for item in asset_files(task):
        name = item['name']
        if sha(Path(plan['assets']) / name) != plan['asset_identity'][name]:
            raise ValueError('Task asset changed')
    return plan


def validation_evidence(directory, provider='qwen', base_url=None, cua_contract=None, plan=None):
    if directory is None:
        raise ValueError('--validation-dir with all declared arms and passing offline cases is required')
    directory = Path(directory).resolve()
    evidence = {}
    identity = project_identity()
    for arm in plan['arms'] if plan is not None else ARMS:
        for case in ('limit', 'terminate', 'empty'):
            path = directory / f'{arm}-{case}' / 'validation.json'
            value = read(path)
            if (value.get('passed') is not True or value.get('arm') != arm or value.get('case') != case
                    or value.get('provider') != provider
                    or (base_url is not None and value.get('base_url') != base_url)
                    or (cua_contract is not None and value.get('cua_contract') != cua_contract)
                    or (plan is not None and any(value.get(k) != plan[k] for k in
                        ('model','generation_fields','max_steps','experiment',
                         'mini_keyboard_tools','mini_keyboard_selection')))
                    or (plan is not None and plan.get('task_key','invoice') != 'invoice'
                        and any(value.get(k) != plan[k] for k in ('task_key','task_id','domain')))
                    or value.get('project_source') != identity or value.get('source_unchanged') is not True
                    or value.get('live_api_called') is not False or value.get('vm_started') is not False):
                raise ValueError('Current source lacks passing offline integration evidence: ' + str(path))
            evidence[str(path)] = sha(path)
    if plan is not None and plan.get('task_key','invoice') != 'invoice':
        path = directory / 'metrics' / 'validation.json'
        value = read(path)
        if (value.get('passed') is not True or value.get('task_key') != plan['task_key']
                or value.get('official_metric_module') != 'desktop_env.evaluators.metrics.' + plan['task_key']
                or value.get('original_evaluate_method_used') is not True
                or value.get('official_postconfig_preserved_but_mocked') is not True
                or value.get('source_unchanged') is not True or value.get('project_source') != identity
                or value.get('live_api_called') is not False or value.get('vm_started') is not False
                or value.get('gui_actions') != 0 or value.get('benchmark_score') is not None
                or value.get('official_task_assets_opened') is not False
                or len(value.get('cases',[])) != 4 or not all(case.get('passed') is True for case in value['cases'])):
            raise ValueError('Current source lacks passing synthetic metric/getter integration: ' + str(path))
        evidence[str(path)] = sha(path)
    return {'directory': str(directory), 'sha256': evidence}


def check(args):
    plan = validate_plan(args.root)
    from ui_kobe.osworld.verified_runtime import load_runtime
    env, runner, qwen = load_runtime(plan['sources']['benchmark']['repo'], plan['sources']['actor_compiler']['repo'],
                                     plan.get('task_key','invoice'))
    from desktop_env.evaluators import metrics
    metric = getattr(metrics, plan['metric'])
    proof = read(plan['image_proof']) if Path(plan['image_proof']).is_file() else None
    image_ok = bool(proof and proof == plan.get('image_identity')
                    and proof.get('archive_sha256') == IMAGE_ZIP_SHA256
                    and Path(plan['image']).is_file() and sha(plan['image'], release_cache=True) == proof['image_sha256'])
    import docker
    with closing(docker.from_env()) as client:
        docker_id = client.images.get(DOCKER_IMAGE).id
    report = {'status': 'ready_for_user_review' if image_ok else 'image_not_ready',
        'image_verified': image_ok, 'docker_image_id': docker_id,
        'imports': {'environment': env.__file__, 'runner': runner.__file__, 'actor_helpers': qwen.__file__,
                    'metric': metric.__code__.co_filename},
        'task_key': plan['task_key'], 'task_id': plan['task_id'], 'domain': plan['domain'],
        'model': plan['model'], 'reasoning': plan['generation_fields'], 'max_steps': plan['max_steps'],
        'arms': plan['arms'], 'key_present': bool(os.environ.get(plan['api_key_env'])),
        'model_endpoint_probed': False, 'vm_started': False, 'official_score_computed': False,
        'execution_authorized': False, 'checkpoint_resume': False}
    # A missing runtime credential is distinct from a code or asset failure.
    report['launch_prerequisites'] = [] if report['key_present'] else [f"Export {plan['api_key_env']} in Linux before launch"]
    if plan['live_provider_check_required']:
        try:
            require_live_provider_check(args.root, plan)
            report['live_provider_check_passed'] = True
        except (ValueError, OSError):
            report['live_provider_check_passed'] = False
            report['launch_prerequisites'].append('Matching provider and required Mini grounding evidence needed')
            report['status'] = 'provider_not_ready' if image_ok else report['status']
    write(args.root / 'preflight.json', report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if image_ok and not report['launch_prerequisites'] else 1


def require_live_provider_check(root, plan):
    if not plan['live_provider_check_required']:
        return
    proof = read(root / 'live-provider-check.json')
    if (proof.get('complete') is not True or proof.get('project_source') != plan['project_source']
            or any(proof.get(k) != plan[k] for k in ('model', 'base_url', 'generation_fields', 'cua_contract'))
            or proof.get('checks') != ['text', 'vision_native_tool', 'tool_reply']):
        raise ValueError('Live provider compatibility check is missing or incomplete; no VM may start')
    if plan.get('mini_grounding_check_required'):
        grounding = read(root / 'mini-grounding-check.json')
        diagnostic = plan.get('mini_grounding_check_policy') == 'collect_all_record_accuracy'
        cases = grounding.get('cases', [])
        if diagnostic:
            width, height = plan['cua_contract']['model_screen_width'], plan['cua_contract']['model_screen_height']
            compatible = (grounding.get('policy') == 'collect_all_record_accuracy'
                and grounding.get('collection_complete') is True
                and grounding.get('all_targets_passed') == all(c.get('passed') is True for c in cases)
                and all(type(c.get('passed')) is bool and isinstance(c.get('compiled_point_px'), list)
                    and len(c['compiled_point_px']) == 2
                    and all(type(v) in (int, float) and 0 <= v < bound
                            for v, bound in zip(c['compiled_point_px'], (width, height)))
                    and len(c.get('native_actions', [])) == 1
                    and c['native_actions'][0].get('action') == 'mouse_move' for c in cases))
        else:
            compatible = all(case.get('passed') is True for case in cases)
        if (grounding.get('kind') != 'synthetic_mini_grounding' or grounding.get('complete') is not True
                or grounding.get('live_api_called') is not True
                or grounding.get('source_unchanged') is not True
                or grounding.get('project_source') != plan['project_source']
                or any(grounding.get(k) != plan[k] for k in ('model', 'base_url', 'generation_fields', 'cua_contract'))
                or len(cases) != 4 or not compatible
                or grounding.get('vm_started') is not False or grounding.get('gui_actions') != 0
                or grounding.get('benchmark_score') is not None):
            raise ValueError('Mini actual-predict grounding evidence is incomplete or differs from the frozen plan')


def stage_cache(plan, stage, task):
    cache = stage / 'cache' / plan.get('task_id', TASK_ID)
    cache.mkdir(parents=True, exist_ok=False)
    for item in download_files(task):
        name = Path(item['path']).name
        target = f"{uuid.uuid5(uuid.NAMESPACE_URL, item['url'])}_{name}"
        shutil.copyfile(Path(plan['assets']) / name, cache / target)
    # Gold is evaluator-only, outside the guest and actor input.
    expected = task['evaluator']['expected']
    shutil.copyfile(Path(plan['assets']) / expected_asset_name(task), cache / expected['dest'])


def execute_arm(args):
    if not args.execute_approved_plan:
        raise PermissionError('Execution requires a new explicit user instruction and --execute-approved-plan')
    plan = validate_plan(args.root)
    state = read(args.root / 'state.json')
    if state.get('status') != 'running' or state.get('active_arm') != args.arm:
        raise RuntimeError('Use the serial launch command; this arm was not dispatched')
    require_live_provider_check(args.root, plan)
    if not os.environ.get(plan['api_key_env']):
        raise RuntimeError(plan['api_key_env'] + ' is missing in the Linux runtime')
    if os.environ.get('OSWORLD_VM_SECRET_MOUNTS'):
        raise RuntimeError('Unexpected guest secret mounts')
    if (read(plan['image_proof']) != plan.get('image_identity')
            or sha(plan['image'], release_cache=True) != plan['image_identity']['image_sha256']):
        raise ValueError('Official OSWorld-1 image is not verified')
    from scripts.osworld_native_experiment import require_scope
    require_scope(plan['service_memory_bytes'])
    from ui_kobe.osworld.verified_runtime import load_runtime, reset_compatible
    env_module, runner, qwen = load_runtime(plan['sources']['benchmark']['repo'],
                                          plan['sources']['actor_compiler']['repo'], plan.get('task_key','invoice'))
    from scripts.run_official_native_tasks import agent_class
    from ui_kobe.osworld.verified_resources import install_provider, resource_guard
    from ui_kobe.osworld import telemetry
    stage = args.root / args.arm
    stage.mkdir(exist_ok=False)
    task = verify_task(plan['sources']['benchmark']['repo'], plan.get('task_key','invoice'))
    stage_cache(plan, stage, task)
    from kobe_views.task_keyboard import environment
    os.environ.update(environment(plan, arm=args.arm))
    os.environ.update(UI_KOBE_TASKVIEWS_PROFILE='mini_fixed_v1', UI_KOBE_MINI_CONTROLS_VIEW='disabled',
        UI_KOBE_MINI_KEYBOARD_TOOLS=json.dumps(
            plan['mini_keyboard_tools']['enabled_toolsets'][1:] if args.arm == 'taskviews' else []),
        UI_KOBE_TASKVIEWS_FEEDBACK_V10='0', UI_KOBE_GENERATION_PROFILE=plan['generation_profile']['name'],
        UI_KOBE_CUA_CONTRACT_JSON=json.dumps(plan['cua_contract']), UI_KOBE_TASK_ID=plan['task_id'],
        UI_KOBE_TELEMETRY_DIR=str(stage / 'telemetry'), OSWORLD_FULL_RUN_ID=plan['run_ids'][args.arm])
    if plan['provider'] == 'sx':
        os.environ['UI_KOBE_SX_URL_ENV'] = plan['base_url_env']
    selected = reset_compatible(agent_class(plan['interface'], args.arm, 'mini_fixed_v1'))
    qwen.QwenAgent = selected
    install_provider(plan)
    telemetry.install(stage / 'telemetry')
    # Check resource headroom before every actor call without adding model context.
    original_predict = selected.predict
    def guarded_predict(self, instruction, obs):
        resource_guard(startup=False, audit_path=stage / 'resource-monitor.jsonl',
                       phase='before_predict', decision=self.total_steps + 1)
        return original_predict(self, instruction, obs)
    selected.predict = guarded_predict
    original_evaluate = env_module.DesktopEnv.evaluate
    def guarded_evaluate(self, *args, **kwargs):
        resource_guard(startup=False, audit_path=stage / 'resource-monitor.jsonl', phase='before_evaluation')
        return original_evaluate(self, *args, **kwargs)
    env_module.DesktopEnv.evaluate = guarded_evaluate
    result_dir = stage / 'official' / plan['domain'] / plan['task_id']
    result_dir.mkdir(parents=True)
    actor = selected(model=plan['model'], base_url=plan['base_url'], temperature=0, max_tokens=16000,
                     api_key=os.environ[plan['api_key_env']])
    env, scores = None, []
    error, closed, cleanup_ok = None, False, False
    try:
        resource_guard(startup=True, audit_path=stage / 'resource-monitor.jsonl')
        env = env_module.DesktopEnv(provider_name='docker', path_to_vm=plan['image'],
            snapshot_name=task['snapshot'], action_space='pyautogui', cache_dir=str(stage / 'cache'),
            screen_size=(1920, 1080), headless=True, require_a11y_tree=False, require_terminal=False)
        runner.run_single_example(actor, env, task, plan['max_steps'], task['instruction'],
            SimpleNamespace(sleep_after_execution=3, result_dir=str(stage / 'official')),
            str(result_dir), scores)
    except BaseException as exc:
        error = {'type': type(exc).__name__, 'message': telemetry.safe(str(exc))}
        raise
    finally:
        try:
            if env is not None:
                env.close()
            else:
                actor.close()
            closed = True
            import docker
            with closing(docker.from_env()) as client:
                cleanup_ok = not client.containers.list(all=True,
                    filters={'label': 'ui-kobe.verified.run=' + os.environ['OSWORLD_FULL_RUN_ID']})
        finally:
            write(stage / 'outcome.json', {'official_score': scores[-1] if scores else None,
                'decisions': actor.total_steps, 'max_steps': plan['max_steps'], 'run_id': os.environ['OSWORLD_FULL_RUN_ID'],
                'error': error, 'closed': closed,
                'cleanup_ok': cleanup_ok, 'complete': error is None and bool(scores) and closed and cleanup_ok,
                'no_retry_or_resume': True, 'source_unchanged': sources(
                    plan['sources']['benchmark']['repo'], plan['sources']['actor_compiler']['repo'],
                    plan.get('task_key','invoice')) == plan['sources']
                    and project_identity() == plan['project_source']})


def launch(args):
    if not args.execute_approved_plan:
        raise PermissionError('User review is pending; no evaluation was started')
    import fcntl
    with (args.root / 'launch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = validate_plan(args.root)
        require_live_provider_check(args.root, plan)
        from scripts.osworld_native_experiment import require_scope
        from ui_kobe.osworld.verified_resources import LAUNCHER_LIMIT
        group = require_scope(LAUNCHER_LIMIT)
        os.environ.update(OSWORLD_VERIFIED_LAUNCHER_PID=str(os.getpid()),
                          OSWORLD_VERIFIED_LAUNCHER_CGROUP=str(group.resolve()))
        state = read(args.root / 'state.json')
        arms = tuple(plan['arms'])
        if state['status'] != 'prepared_not_started' or any((args.root / arm).exists() for arm in arms):
            raise RuntimeError('Plan was already attempted; no implicit resume or replay')
        write(args.root / 'state.json', {'status': 'running', 'completed_arms': [],
                                       'execution_authorized_by_explicit_cli': True})
        for index, arm in enumerate(arms):
            write(args.root / 'state.json', {'status': 'running', 'active_arm': arm,
                'completed_arms': list(arms[:index]), 'execution_authorized_by_explicit_cli': True})
            command = ['systemd-run', '--user', '--scope', '--quiet', '--property=MemoryMax=2G',
                '--property=MemorySwapMax=0', sys.executable, str(Path(__file__).resolve()),
                '_run-arm', '--root', str(args.root), '--arm', arm, '--execute-approved-plan']
            result = subprocess.run(command, check=False)
            if plan.get('run_ids'):
                from ui_kobe.osworld.verified_resources import cleanup_owned_run
                try:
                    cleanup = cleanup_owned_run(plan, plan['run_ids'][arm])
                except Exception as exc:
                    write(args.root / f'cleanup-{arm}.json', {'cleanup_ok':False,
                        'error':{'type':type(exc).__name__,'message':str(exc)}})
                    write(args.root/'state.json',{'status':'stopped_on_error','arm':arm,'reason':'cleanup_error'})
                    return 1
                write(args.root / f'cleanup-{arm}.json', cleanup)
                if not cleanup['cleanup_ok']:
                    write(args.root/'state.json',{'status':'stopped_on_error','arm':arm,'reason':'cleanup_failed'})
                    return 1
            outcome_path = args.root / arm / 'outcome.json'
            outcome = read(outcome_path) if outcome_path.exists() else {}
            if not outcome:
                outcome = {'official_score':None,'complete':False,'max_steps':plan['max_steps'],
                    'error':{'type':'ArmProcessExited','returncode':result.returncode},
                    'cleanup_ok':bool(plan.get('run_ids')) and cleanup['cleanup_ok']}
                write(outcome_path,outcome)
            if result.returncode or not outcome.get('complete') or not outcome.get('source_unchanged'):
                write(args.root / 'state.json', {'status': 'stopped_on_error', 'arm': arm,
                                                'returncode': result.returncode})
                return 1
            write(args.root / 'state.json', {'status': 'completed' if index == len(arms)-1 else 'running',
                'completed_arms': list(arms[:index + 1])})
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'check', 'launch', '_run-arm'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--benchmark-repo', type=Path, default=Path.home() / 'osworld-verified/OSWorld')
    parser.add_argument('--compiler-repo', type=Path, default=Path.home() / 'osworld2/OSWorld-V2')
    parser.add_argument('--assets', type=Path, default=PROJECT.parent / 'osworld_verified_setup/assets')
    parser.add_argument('--image', type=Path, default=Path.home() / 'osworld-verified/images/Ubuntu.qcow2')
    parser.add_argument('--image-proof', type=Path, default=PROJECT.parent / 'osworld_verified_setup/image-proof.json')
    parser.add_argument('--validation-dir', type=Path)
    parser.add_argument('--provider', choices=('qwen', 'tinker', 'openrouter', 'sx'), default='qwen',
                        help='Used by prepare; later commands use the frozen plan provider')
    parser.add_argument('--sx-url-env', choices=('SX_URL', 'SX_URL_SB'), default='SX_URL')
    parser.add_argument('--coordinate-type', choices=('absolute', 'relative'), default='absolute',
                        help='Prepare only: freeze one coordinate mode for both arms; never auto-switch')
    parser.add_argument('--experiment', choices=EXPERIMENTS, default='legacy-low35')
    parser.add_argument('--task', choices=tuple(TASKS), default='invoice', help='Prepare only; later commands use plan')
    parser.add_argument('--keyboard-mode', choices=('task_names', 'manual'), default='task_names',
                        help='Prepare only: match public task names, or use only explicitly selected directories')
    parser.add_argument('--keyboard-toolset', action='append', default=[],
                        help='Prepare only: add an exact directory ID to general and any task matches')
    parser.add_argument('--keyboard-research', action='store_true',
                        help='Prepare only: research and archive task-scoped keyboard references before any CUA action')
    parser.add_argument('--keyboard-research-config', type=Path,
                        help='Optional research endpoint/model/budget JSON; requires --keyboard-research')
    parser.add_argument('--arm', choices=ALL_ARMS)
    parser.add_argument('--execute-approved-plan', action='store_true')
    args = parser.parse_args()
    args.root = args.root.resolve()
    if args.command == '_run-arm' and not args.arm:
        parser.error('--arm is required')
    return {'prepare': prepare, 'check': check, 'launch': launch, '_run-arm': execute_arm}[args.command](args)


if __name__ == '__main__':
    raise SystemExit(main())
