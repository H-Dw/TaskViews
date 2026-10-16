"""Task isolation, sealed gold routing, evidence binding and review-only entry."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from scripts import verified_invoice as pair
from scripts import verified_media as media
from ui_kobe.osworld.verified_tasks import TASKS, asset_files, task_path


@pytest.fixture
def media_spec(monkeypatch):
    monkeypatch.setenv('SX_URL_SB', 'https://offline.example/v1')
    return lambda key: pair.specification('sx','SX_URL_SB','relative','sx-pair-max-high40',key)


@pytest.mark.parametrize('key', ['gimp','vlc'])
def test_media_pairs_share_actor_budget_but_keep_task_and_scoring_identity(media_spec,key):
    plan = media_spec(key)
    assert plan['arms'] == ['baseline','taskviews'] and plan['max_steps'] == 40
    assert plan['model'] == 'qwen3.8-max'
    assert plan['generation_fields'] == {'enable_thinking':True,'reasoning_effort':'high'}
    assert plan['task_id'] == TASKS[key]['id'] and plan['domain'] == key
    assert plan['snapshot'] == TASKS[key]['snapshot'] and plan['metric'] == TASKS[key]['metric']
    assert plan['arm_profiles']['baseline']['selector'] is None
    assert plan['arm_profiles']['taskviews']['view_ids'] == ['current','keyboard','attempts','lessons']
    assert plan['arm_profiles']['taskviews']['max_bytes'] == 3000
    assert plan['human_review_required'] and not plan['execution_authorized']
    other = media_spec('vlc' if key == 'gimp' else 'gimp')
    assert plan['cua_contract'] == other['cua_contract']
    with pytest.raises(ValueError,match='explicit baseline/Mini'):
        pair.specification('sx','SX_URL_SB','relative','sx-max-high40',key)


def test_vlc_single_mini_keeps_pair_contract_and_cannot_dispatch_baseline(media_spec):
    single = pair.specification('sx','SX_URL_SB','relative','sx-mini-max-high40','vlc')
    previous = media_spec('vlc')
    assert single['arms'] == ['taskviews']
    assert single['version'] == 'osworld-verified-vlc-mini-v4-v1'
    for field in previous.keys() - {'version', 'arms', 'arm_profiles', 'experiment'}:
        assert single[field] == previous[field], field
    assert single['arm_profiles'] == {'taskviews': previous['arm_profiles']['taskviews']}
    with pytest.raises(ValueError, match='explicit baseline/Mini'):
        pair.specification('sx','SX_URL_SB','relative','sx-mini-max-high40','gimp')


@pytest.mark.parametrize('key', ['gimp','vlc'])
def test_gold_is_cached_for_host_evaluator_and_never_added_to_guest_setup(tmp_path,media_spec,key):
    plan = media_spec(key)
    task = {'config':[{'type':'download','parameters':{'files':[
        {'url':'https://example/input','path':'/home/user/Desktop/input.png'}]}},
        {'type':'launch','parameters':{'command':['app','/home/user/Desktop/input.png']}}],
        'evaluator':{'expected':{'path':'https://example/gold','dest':'reference.png'}}}
    original = deepcopy(task)
    assets = tmp_path/'assets'
    assets.mkdir()
    (assets/'input.png').write_bytes(b'input')
    (assets/'reference.png').write_bytes(b'gold')
    plan['assets'] = str(assets)
    pair.stage_cache(plan,tmp_path/'arm',task)
    cache = tmp_path/'arm/cache'/TASKS[key]['id']
    inputs = list(cache.glob('*_input.png'))
    assert inputs == [cache/f'{uuid.uuid5(uuid.NAMESPACE_URL,"https://example/input")}_input.png']
    assert (cache/'reference.png').read_bytes() == b'gold'
    assert not list(cache.glob('*_reference.png')) and task == original
    assert [item['role'] for item in asset_files(task)] == ['official_input','evaluator_only']


def test_pinned_task_contract_rejects_gold_leak_or_postconfig_change(tmp_path,monkeypatch):
    meta = TASKS['gimp']
    task = {'id':meta['id'], 'snapshot':meta['snapshot'], 'config':[],
            'evaluator':{'func':meta['metric'], 'postconfig':[{'type':'sleep','parameters':{'seconds':1}}]}}
    path = tmp_path/task_path('gimp')
    pair.write(path,task)
    pair.write(tmp_path/'evaluation_examples/test_all.json',{'gimp':[meta['id']]})
    monkeypatch.setitem(meta,'sha256',pair.sha(path))
    assert pair.verify_task(tmp_path,'gimp') == task
    task['config'].append({'type':'download','parameters':{'files':[{'path':'/home/user/Desktop/gold.png'}]}})
    pair.write(path,task)
    with pytest.raises(ValueError,match='pinned task contract'):
        pair.verify_task(tmp_path,'gimp')


def test_gimp_integration_evidence_cannot_be_reused_for_vlc(tmp_path,monkeypatch,media_spec):
    plan = media_spec('gimp')
    identity = {'current':'source'}
    monkeypatch.setattr(pair,'project_identity',lambda:identity)
    for arm in plan['arms']:
        for case in ('limit','terminate','empty'):
            row = {k:plan[k] for k in ('model','base_url','cua_contract','generation_fields','max_steps',
                                      'experiment','task_key','task_id','domain')}
            row.update(passed=True,arm=arm,case=case,provider='sx',source_unchanged=True,
                project_source=identity,live_api_called=False,vm_started=False)
            pair.write(tmp_path/f'{arm}-{case}'/'validation.json',row)
    proof = {'passed':True, 'task_key':'gimp', 'official_metric_module':'desktop_env.evaluators.metrics.gimp',
        'original_evaluate_method_used':True, 'official_postconfig_preserved_but_mocked':True,
        'source_unchanged':True, 'project_source':identity, 'live_api_called':False, 'vm_started':False,
        'gui_actions':0, 'benchmark_score':None, 'official_task_assets_opened':False,
        'cases':[{'passed':True} for _ in range(4)]}
    pair.write(tmp_path/'metrics/validation.json',proof)
    assert len(pair.validation_evidence(tmp_path,'sx',plan['base_url'],plan['cua_contract'],plan)['sha256']) == 7
    with pytest.raises(ValueError,match='offline integration'):
        pair.validation_evidence(tmp_path,'sx',plan['base_url'],plan['cua_contract'],media_spec('vlc'))
    proof['official_metric_module'] = 'local_replacement'
    pair.write(tmp_path/'metrics/validation.json',proof)
    with pytest.raises(ValueError,match='synthetic metric/getter'):
        pair.validation_evidence(tmp_path,'sx',plan['base_url'],plan['cua_contract'],plan)


def test_review_scope_rejects_model_or_arm_drift_and_never_launches(tmp_path):
    config = media.configuration()
    path = tmp_path/'config.json'
    for key,value in [('model','qwen3.8-flash'),('max_steps',41),('arms',['taskviews']),('execution_authorized',True)]:
        bad = deepcopy(config)
        bad[key] = value
        pair.write(path,bad)
        with pytest.raises(ValueError,match='review scope'):
            media.configuration(path)
    with pytest.raises(PermissionError,match='review is pending'):
        media.launch(tmp_path/'nonexistent',False)
    assert not list(tmp_path.glob('**/state.json'))


@pytest.mark.parametrize('fail_first',[False,True])
def test_media_matrix_runs_serially_and_stops_after_pair_failure(tmp_path,monkeypatch,fail_first):
    from scripts import osworld_native_experiment
    monkeypatch.setattr(osworld_native_experiment,'require_scope',lambda limit:tmp_path)
    monkeypatch.setattr(media,'manifest',lambda root:{})
    monkeypatch.setattr(pair,'validate_plan',lambda root:{})
    qualified = []
    monkeypatch.setattr(pair,'require_live_provider_check',lambda root,plan:qualified.append(root.name))
    pair.write(tmp_path/'state.json',{'status':'prepared_not_started'})
    for key in media.TASKS:
        pair.write(tmp_path/key/'state.json',{'status':'prepared_not_started'})
    seen = []
    def run(command,check):
        assert qualified == ['gimp','vlc']
        root = Path(command[command.index('--root')+1])
        key = pair.read(tmp_path/'state.json')['active_task']
        assert root.name == key and key not in seen
        seen.append(key)
        pair.write(tmp_path/key/'state.json',{'status':'stopped_on_error' if fail_first else 'completed'})
        return SimpleNamespace(returncode=int(fail_first))
    monkeypatch.setattr(media.subprocess,'run',run)
    assert media.launch(tmp_path,True) == int(fail_first)
    assert seen == (['gimp'] if fail_first else ['gimp','vlc'])
    assert pair.read(tmp_path/'state.json')['status'] == ('stopped_on_error' if fail_first else 'completed')
    with pytest.raises(RuntimeError,match='already attempted'):
        media.launch(tmp_path,True)


def test_asset_format_checks_do_not_decode_gold_pixels(tmp_path):
    from scripts.prepare_verified_invoice_assets import verify_format
    for name,payload in [('image.png',b'\x89PNG\r\n\x1a\nheader'),('movie.mp4',b'\x00\x00\x00\x18ftypisom')]:
        path = tmp_path/name
        path.write_bytes(payload)
        verify_format(path)
        path.write_bytes(b'<html>not an asset</html>')
        with pytest.raises(ValueError,match='asset format'):
            verify_format(path)
