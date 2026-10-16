from copy import deepcopy
from dataclasses import replace
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from scripts import verified_invoice as invoice
from scripts import verified_invoice_matrix as matrix
from ui_kobe.api.kimi_budget import StepLedger
from ui_kobe.api.qwen_native import QwenTransportBudget
from ui_kobe.api.sx_native import (GENERATION, MAX_GENERATIONS, SXNativeClient,
    generation_profile, generation_request_fields, model_for_profile)


@pytest.mark.parametrize('name,effort', list(MAX_GENERATIONS.items()))
def test_max_profiles_preserve_model_and_exact_wire_reasoning(tmp_path, monkeypatch, name, effort):
    from test_sx_native import stream, MODEL
    monkeypatch.setenv('SX_URL_SB','https://fixture.example/v1')
    profile = generation_profile(name)
    assert model_for_profile(profile) == 'qwen3.8-max'
    assert generation_request_fields(profile) == {'enable_thinking':True,'reasoning_effort':effort}
    requests = []
    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload['model'] == 'qwen3.8-max' and payload['enable_thinking'] is True
        assert payload['reasoning_effort'] == effort and payload['max_tokens'] == 16000
        assert payload['stream'] is True
        return httpx.Response(200,headers={'content-type':'text/event-stream'},
                              content=stream().replace(MODEL.encode(), b'qwen3.8-max'))
    client = SXNativeClient(url_env='SX_URL_SB',api_key='offline-only',profile=profile,
        budget=QwenTransportBudget(attempts=1),emit=lambda *a,**k:None,response_dir=tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(handler)))
    ledger = StepLedger(profile,time.monotonic()+930,lambda *a,**k:None)
    try:
        with pytest.raises(ValueError,match='exact model'):
            client.create(model=MODEL,messages=[],max_tokens=16000,deadline=ledger.deadline,
                          step_ledger=ledger,budget_role='executor')
        assert not requests
        response=client.create(model='qwen3.8-max',messages=[],max_tokens=16000,
                              deadline=ledger.deadline,step_ledger=ledger,budget_role='executor')
        assert response.model_dump()['model']=='qwen3.8-max' and len(requests)==1
        with pytest.raises(ValueError,match='frozen bounds'):
            generation_request_fields(replace(profile,max_completion_tokens=16001))
    finally:
        client.close()


def test_flash_low_remains_a_separate_frozen_profile():
    profile=generation_profile(GENERATION)
    assert model_for_profile(profile)=='qwen3.8-flash'
    assert generation_request_fields(profile)=={'reasoning_effort':'low'}


@pytest.mark.parametrize('effort',['medium','low'])
def test_reasoning_pairs_have_only_baseline_and_current_mini_with_same_budgets(monkeypatch,effort):
    monkeypatch.setenv('SX_URL_SB','https://fixture.example/v1')
    plan=invoice.specification('sx','SX_URL_SB','relative','sx-max-'+effort+'40')
    high=invoice.specification('sx','SX_URL_SB','relative','sx-mini-max-high40')
    assert plan['model']=='qwen3.8-max' and plan['max_steps']==40
    assert plan['arms']==['baseline','taskviews']
    assert plan['generation_fields']=={'enable_thinking':True,'reasoning_effort':effort}
    assert plan['arm_profiles']['baseline']['selector'] is None
    assert plan['arm_profiles']['taskviews']==high['arm_profiles']['taskviews']
    for key in ('cua_contract','resource_policy','vm_memory_bytes','service_memory_bytes','swap_bytes',
                'mini_grounding_check_policy','transport_policy','request_policy'):
        assert plan[key]==high[key]
    assert {k:v for k,v in plan['generation_profile'].items() if k not in ('name','reasoning_effort')}=={
        k:v for k,v in high['generation_profile'].items() if k not in ('name','reasoning_effort')}


def matrix_fixture(tmp_path,monkeypatch):
    monkeypatch.setenv('SX_URL_SB','https://fixture.example/v1')
    monkeypatch.setattr(matrix,'project_identity',lambda:{'frozen':'source'})
    plans={}
    for effort in matrix.ORDER:
        plan=invoice.specification('sx','SX_URL_SB','relative','sx-max-'+effort+'40')
        plan.update(sources={'fixture':'pinned'},asset_identity={'fixture':'hash'},task_sha256='task-hash')
        plans[effort]=plan
        invoice.write(tmp_path/effort/'plan.json',plan)
        invoice.write(tmp_path/effort/'state.json',{'status':'prepared_not_started'})
    monkeypatch.setattr(matrix,'validate_plan',lambda pair:deepcopy(plans[pair.name]))
    cfg={'version':'verified-invoice-max-medium-low40-v1','order':['medium','low'],
         'arms':['baseline','taskviews'],'max_steps':40,'project_source':{'frozen':'source'},
         'plan_sha256':{effort:invoice.sha(tmp_path/effort/'plan.json') for effort in matrix.ORDER}}
    invoice.write(tmp_path/'matrix.json',cfg)
    invoice.write(tmp_path/'matrix.sha256.json',{'sha256':invoice.sha(tmp_path/'matrix.json')})
    invoice.write(tmp_path/'state.json',{'status':'prepared_not_started'})
    return plans,cfg


@pytest.mark.parametrize('fail',[None,'medium','low'])
def test_matrix_dispatches_each_pair_once_and_stops_on_failure(tmp_path,monkeypatch,fail):
    from scripts import osworld_native_experiment
    matrix_fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(osworld_native_experiment,'require_scope',lambda limit:None)
    seen=[]
    def run(command,check):
        pair=command[command.index('--root')+1]
        effort=Path(pair).name
        assert invoice.read(tmp_path/'state.json')['active_effort']==effort
        seen.append(effort)
        invoice.write(tmp_path/effort/'state.json',{'status':'stopped_on_error' if fail==effort else 'completed'})
        return SimpleNamespace(returncode=int(fail==effort))
    from pathlib import Path
    monkeypatch.setattr(matrix.subprocess,'run',run)
    assert matrix.launch(tmp_path,True)==int(fail is not None)
    assert seen==(['medium'] if fail=='medium' else ['medium','low'])
    with pytest.raises(RuntimeError,match='already attempted'):
        matrix.launch(tmp_path,True)


@pytest.mark.parametrize('mutation',['digest','order','source','model','reasoning','task','budget'])
def test_matrix_rejects_mismatched_contracts_before_dispatch(tmp_path,monkeypatch,mutation):
    plans,cfg=matrix_fixture(tmp_path,monkeypatch)
    if mutation in ('digest','order','source'):
        cfg['order']=['low','medium'] if mutation=='order' else cfg['order']
        if mutation=='source':
            cfg['project_source']={'changed':'source'}
        invoice.write(tmp_path/'matrix.json',cfg|{'note':'changed'})
        if mutation!='digest':
            invoice.write(tmp_path/'matrix.sha256.json',{'sha256':invoice.sha(tmp_path/'matrix.json')})
    else:
        key,value={'model':('model','qwen3.8-flash'),
            'reasoning':('generation_fields',{'enable_thinking':True,'reasoning_effort':'high'}),
            'task':('task_sha256','other-task'), 'budget':('vm_memory_bytes',1)}[mutation]
        plans['low'][key]=value
    with pytest.raises(ValueError):
        matrix.manifest(tmp_path)
