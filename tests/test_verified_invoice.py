from types import SimpleNamespace

import pytest

from scripts.verified_invoice import (ARMS, execute_arm, launch, specification, stage_cache)
from ui_kobe.osworld.verified_runtime import reset_compatible


def test_coordinate_mode_is_explicit_frozen_and_keeps_all_budgets(monkeypatch):
    monkeypatch.setenv('SX_URL_SB', 'https://example.test/v1')
    pixel = specification('sx', 'SX_URL_SB')
    normalized = specification('sx', 'SX_URL_SB', 'relative')
    assert pixel['coordinate_type']==pixel['cua_contract']['coordinate_type']=='absolute'
    assert normalized['coordinate_type']==normalized['cua_contract']['coordinate_type']=='relative'
    assert normalized['mini_grounding_check_required'] is True
    for key in pixel['cua_contract']:
        if key!='coordinate_type':
            assert normalized['cua_contract'][key]==pixel['cua_contract'][key]
    assert normalized['cua_contract']['model_screen_width']==1920
    assert normalized['cua_contract']['model_screen_height']==1080
    assert normalized['max_steps']==35 and normalized['arms']==list(ARMS)
    with pytest.raises(ValueError,match='explicitly'):
        specification('sx','SX_URL_SB','auto')


def test_coordinate_declaration_cannot_disagree_with_frozen_contract(tmp_path):
    from scripts import verified_invoice as module
    plan=specification()
    plan['coordinate_type']='relative'
    module.write(tmp_path/'plan.json',plan)
    module.write(tmp_path/'plan.sha256.json',{'sha256':module.sha(tmp_path/'plan.json')})
    with pytest.raises(ValueError,match='cua_contract'):
        module.validate_plan(tmp_path)


def test_launch_evidence_requires_actual_mini_path_and_matching_units(tmp_path, monkeypatch):
    from copy import deepcopy
    from scripts import verified_invoice as module
    monkeypatch.setenv('SX_URL_SB','https://example.test/v1')
    plan=specification('sx','SX_URL_SB','relative')
    plan['project_source']={'test':'frozen'}
    fields={k:plan[k] for k in ('model','base_url','generation_fields','cua_contract','project_source')}
    provider={**fields,'complete':True,'checks':['text','vision_native_tool','tool_reply']}
    module.write(tmp_path/'live-provider-check.json',provider)
    with pytest.raises(FileNotFoundError):
        module.require_live_provider_check(tmp_path,plan)
    grounding={**deepcopy(fields),'kind':'synthetic_mini_grounding','complete':True,
               'source_unchanged':True,'live_api_called':True,'cases':[{'passed':True} for _ in range(4)],
               'vm_started':False,'gui_actions':0,'benchmark_score':None}
    module.write(tmp_path/'mini-grounding-check.json',grounding)
    module.require_live_provider_check(tmp_path,plan)
    for mutation in ('units','failed_case','source'):
        invalid=deepcopy(grounding)
        if mutation=='units':
            invalid['cua_contract']['coordinate_type']='absolute'
        elif mutation=='failed_case':
            invalid['cases'][1]['passed']=False
        else:
            invalid['project_source']={'test':'old'}
        module.write(tmp_path/'mini-grounding-check.json',invalid)
        with pytest.raises(ValueError,match='grounding evidence'):
            module.require_live_provider_check(tmp_path,plan)


def test_offline_evidence_cannot_qualify_a_different_coordinate_contract(tmp_path,monkeypatch):
    from copy import deepcopy
    from scripts import verified_invoice as module
    identity={'test':'source'}
    monkeypatch.setattr(module,'project_identity',lambda:identity)
    contract=specification()['cua_contract']
    for arm in ARMS:
        for case in ('limit','terminate','empty'):
            module.write(tmp_path/f'{arm}-{case}'/'validation.json',{
                'passed':True,'arm':arm,'case':case,'provider':'qwen',
                'project_source':identity,'source_unchanged':True,
                'live_api_called':False,'vm_started':False,'cua_contract':contract})
    module.validation_evidence(tmp_path,cua_contract=contract)
    other=deepcopy(contract)
    other['coordinate_type']='relative'
    with pytest.raises(ValueError,match='offline integration evidence'):
        module.validation_evidence(tmp_path,cua_contract=other)


def test_mini_evaluation_records_localization_misses_without_hiding_protocol_failures(tmp_path, monkeypatch):
    from copy import deepcopy
    from scripts import verified_invoice as module
    monkeypatch.setenv('SX_URL_SB','https://example.test/v1')
    plan=specification('sx','SX_URL_SB','relative','sx-mini-max-high40')
    plan['project_source']={'test':'frozen'}
    fields={k:plan[k] for k in ('model','base_url','generation_fields','cua_contract','project_source')}
    module.write(tmp_path/'live-provider-check.json',{**fields,'complete':True,
        'checks':['text','vision_native_tool','tool_reply']})
    evidence={**deepcopy(fields),'kind':'synthetic_mini_grounding','complete':True,
        'policy':'collect_all_record_accuracy','collection_complete':True,'all_targets_passed':False,
        'source_unchanged':True,'live_api_called':True,'vm_started':False,'gui_actions':0,'benchmark_score':None,
        'cases':[{'passed':False,'compiled_point_px':[1588,179],
                  'native_actions':[{'action':'mouse_move','coordinate':[827,166]}]} for _ in range(4)]}
    module.write(tmp_path/'mini-grounding-check.json',evidence)
    module.require_live_provider_check(tmp_path,plan)
    for mutation in ('missing','units','source','out_of_frame','wrong_tool','accuracy_falsified'):
        invalid=deepcopy(evidence)
        if mutation=='missing':
            invalid['cases'].pop()
        elif mutation=='units':
            invalid['cua_contract']['coordinate_type']='absolute'
        elif mutation=='source':
            invalid['source_unchanged']=False
        elif mutation=='out_of_frame':
            invalid['cases'][0]['compiled_point_px']=[1921,179]
        elif mutation=='wrong_tool':
            invalid['cases'][0]['native_actions'][0]['action']='terminate'
        else:
            invalid['all_targets_passed']=True
        module.write(tmp_path/'mini-grounding-check.json',invalid)
        with pytest.raises(ValueError,match='grounding evidence'):
            module.require_live_provider_check(tmp_path,plan)


def test_image_hash_releases_only_read_ranges_without_changing_digest(tmp_path, monkeypatch):
    import hashlib
    from scripts import verified_invoice as module
    payload = b'cache-proof' * 200000
    path = tmp_path / 'immutable-image.qcow2'
    path.write_bytes(payload)
    calls = []
    monkeypatch.setattr(module.os, 'POSIX_FADV_DONTNEED', 4, raising=False)
    monkeypatch.setattr(module.os, 'posix_fadvise', lambda fd, offset, length, advice:
                        calls.append((offset, length, advice)), raising=False)
    expected = hashlib.sha256(payload).hexdigest()
    assert module.sha(path) == expected and not calls
    assert module.sha(path, release_cache=True) == expected
    assert sum(length for _, length, _ in calls) == len(payload)
    assert [offset for offset, _, _ in calls] == list(range(0, len(payload), 1024 * 1024))
    assert all(advice == 4 for _, _, advice in calls)
    assert path.read_bytes() == payload


def test_unsupported_cache_hint_keeps_full_image_verification(tmp_path, monkeypatch):
    import hashlib
    from scripts import verified_invoice as module
    path = tmp_path / 'image'
    path.write_bytes(b'immutable')
    def unavailable(*args):
        raise OSError('unsupported')
    monkeypatch.setattr(module.os, 'posix_fadvise', unavailable, raising=False)
    monkeypatch.setattr(module.os, 'POSIX_FADV_DONTNEED', 4, raising=False)
    assert module.sha(path, release_cache=True) == hashlib.sha256(b'immutable').hexdigest()


def test_frozen_low35_comparison_has_no_implicit_execution():
    plan = specification()
    assert plan['arms'] == ['ui_kobe_like', 'taskviews']
    assert plan['max_steps'] == 35 and plan['model'] == 'qwen3.8-max'
    assert plan['generation_fields'] == {
        'enable_thinking': True, 'reasoning_effort': 'low', 'preserve_thinking': True}
    assert plan['request_policy']['stream'] is True
    assert plan['request_policy']['output_field'] == 'max_completion_tokens'
    assert plan['generation_profile']['max_completion_tokens'] == 16000
    assert plan['execution_authorized'] is False and plan['checkpoint_resume'] is False
    assert plan['controls_view'] == 'disabled'
    assert plan['arm_profiles']['taskviews']['view_ids'] == ['current', 'keyboard', 'attempts', 'lessons']
    assert all(plan['arm_profiles'][arm]['extra_role_requests'] == 0 for arm in ARMS)


@pytest.mark.parametrize('entry', [launch, execute_arm])
def test_unapproved_launch_rejected_before_plan_read_or_runtime_import(entry):
    with pytest.raises(PermissionError):
        entry(SimpleNamespace(execute_approved_plan=False))


def test_reset_adapter_does_not_change_predict_or_use_vm_ip():
    class Actor:
        def reset(self, logger=None):
            self.logger = logger
        def predict(self, instruction, obs):
            return instruction, obs
    wrapper = reset_compatible(Actor)
    instance = wrapper()
    instance.reset('logger', vm_ip='localhost:5000')
    assert instance.logger == 'logger' and wrapper.predict is Actor.predict


def test_original_asset_cache_names_and_evaluator_gold_are_outside_guest(tmp_path):
    import uuid
    from scripts.verified_invoice import TASK_ID
    assets = tmp_path / 'assets'
    assets.mkdir()
    (assets / 'input.pdf').write_bytes(b'%PDF-synthetic')
    task = {'config': [{'type':'download', 'parameters': {'files': [{'path': '/home/user/Desktop/input.pdf',
                                                'url': 'https://example.test/input.pdf'}]}}],
            'evaluator': {'expected': {'path': 'https://example.test/input.pdf', 'dest': 'gold.pdf'}}}
    stage_cache({'assets': str(assets)}, tmp_path / 'arm', task)
    cache = tmp_path / 'arm/cache' / TASK_ID
    assert (cache / f'{uuid.uuid5(uuid.NAMESPACE_URL, "https://example.test/input.pdf")}_input.pdf').is_file()
    assert (cache / 'gold.pdf').read_bytes() == b'%PDF-synthetic'
    assert len(task['config'][0]['parameters']['files']) == 1


def test_runtime_refuses_already_loaded_benchmark(monkeypatch):
    import sys
    import types
    from ui_kobe.osworld.verified_runtime import load_runtime
    monkeypatch.setitem(sys.modules, 'desktop_env', types.ModuleType('desktop_env'))
    with pytest.raises(RuntimeError, match='isolated interpreter'):
        load_runtime('/unused/osworld1', '/unused/osworld2')


@pytest.mark.parametrize('fail_first', [False, True])
def test_serial_dispatch_waits_for_cleanup_and_stops_on_failure(tmp_path, monkeypatch, fail_first):
    from scripts import verified_invoice as module
    from scripts import osworld_native_experiment
    monkeypatch.setattr(osworld_native_experiment, 'require_scope', lambda limit: tmp_path)
    monkeypatch.setattr(module, 'validate_plan', lambda root: specification())
    module.write(tmp_path / 'state.json', {'status': 'prepared_not_started'})
    called = []
    def run(command, check):
        arm = command[command.index('--arm') + 1]
        assert module.read(tmp_path / 'state.json')['active_arm'] == arm
        called.append(arm)
        module.write(tmp_path / arm / 'outcome.json', {
            'complete': not fail_first, 'source_unchanged': True})
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess, 'run', run)
    result = launch(SimpleNamespace(execute_approved_plan=True, root=tmp_path))
    assert called == (['ui_kobe_like'] if fail_first else list(ARMS))
    assert result == int(fail_first)
    with pytest.raises(RuntimeError, match='already attempted'):
        launch(SimpleNamespace(execute_approved_plan=True, root=tmp_path))


def test_changed_limit_rejected_even_with_recomputed_plan_digest(tmp_path):
    from scripts import verified_invoice as module
    plan = specification()
    plan['max_steps'] = 36
    module.write(tmp_path / 'plan.json', plan)
    module.write(tmp_path / 'plan.sha256.json', {'sha256': module.sha(tmp_path / 'plan.json')})
    with pytest.raises(ValueError, match='max_steps'):
        module.validate_plan(tmp_path)


def test_real_docker_sdk_collection_property_cannot_bypass_caps(monkeypatch):
    import docker
    from docker.models.containers import ContainerCollection
    from ui_kobe.osworld.verified_resources import BoundedDockerClient
    captured = []
    monkeypatch.setattr(ContainerCollection, 'run', lambda self, image, **kwargs: captured.append((image, kwargs)))
    monkeypatch.setenv('OSWORLD_FULL_RUN_ID', 'offline-resource-test')
    original = docker.DockerClient(base_url='unix:///unused-offline.sock', version='1.45')
    try:
        assert original.containers is not original.containers
        plan = specification()
        client = BoundedDockerClient(original, plan)
        for _ in range(2):
            client.containers.run('happysixd/osworld-docker', environment={'RAM_SIZE': '2G'})
        assert len(captured) == 2
        for image, kwargs in captured:
            assert image == plan['docker_image']
            assert kwargs['mem_limit'] == kwargs['memswap_limit'] == 3 * 1024**3
            assert kwargs['labels'] == {'ui-kobe.verified.run': 'offline-resource-test'}
        with pytest.raises(RuntimeError, match='Unexpected upstream'):
            client.containers.run('unexpected:latest')
    finally:
        original.close()
