"""Max/high three-arm contracts, wire identity, baseline and serial lifecycle."""
from copy import deepcopy
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from scripts import verified_invoice as module
from ui_kobe.api.kimi_budget import StepLedger
from ui_kobe.api.qwen_native import QwenTransportBudget
from ui_kobe.api.sx_native import MAX_HIGH_GENERATION, SXNativeClient, generation_profile


def spec(monkeypatch):
    monkeypatch.setenv('SX_URL_SB','https://sx.example/v1')
    return module.specification('sx','SX_URL_SB','relative','sx-max-high40')


def test_max_high40_changes_only_declared_model_reasoning_rounds_and_arms(monkeypatch):
    plan=spec(monkeypatch)
    previous=module.specification('sx','SX_URL_SB','relative')
    assert plan['arms']==['ui_kobe_like','baseline','taskviews'] and plan['max_steps']==40
    assert plan['model']=='qwen3.8-max'
    assert plan['generation_fields']=={'enable_thinking':True,'reasoning_effort':'high'}
    assert plan['generation_profile']['max_completion_tokens']==16000
    assert plan['generation_profile']['step_output_tokens']==32000
    for key in ('cua_contract','vm_memory_bytes','service_memory_bytes','swap_bytes','resource_policy'):
        assert plan[key]==previous[key]
    assert plan['transport_policy']['upload_timeout_s']==120
    assert plan['transport_policy']['outer_deadlines_unchanged'] is True
    assert plan['arm_profiles']['baseline']['selector'] is None
    assert all(v['extra_role_requests']==0 for v in plan['arm_profiles'].values())
    with pytest.raises(ValueError,match='provider incompatible'):
        module.specification('qwen',experiment='sx-max-high40')


def test_mini_only_high40_freezes_exactly_one_arm_with_unchanged_budgets(monkeypatch):
    comparison=spec(monkeypatch)
    mini=module.specification('sx','SX_URL_SB','relative','sx-mini-max-high40')
    assert mini['arms']==['taskviews'] and set(mini['arm_profiles'])=={'taskviews'}
    for key in comparison:
        if key not in ('arms','arm_profiles','experiment'):
            assert mini[key]==comparison[key]
    with pytest.raises(ValueError,match='provider incompatible'):
        module.specification('qwen',experiment='sx-mini-max-high40')


def test_max_high_wire_cannot_silently_send_flash_or_low(tmp_path,monkeypatch):
    plan=spec(monkeypatch)
    from test_sx_native import stream, MODEL
    raw=stream().replace(MODEL.encode(),plan['model'].encode())
    requests=[]
    def handler(request):
        requests.append(json.loads(request.content))
        assert requests[-1]['model']==plan['model']
        assert requests[-1]['enable_thinking'] is True and requests[-1]['reasoning_effort']=='high'
        assert request.extensions['timeout']['write']==120
        return httpx.Response(200,headers={'content-type':'text/event-stream'},content=raw)
    profile=generation_profile(MAX_HIGH_GENERATION)
    client=SXNativeClient(url_env='SX_URL_SB',api_key='offline-only',profile=profile,
        budget=QwenTransportBudget(attempts=1),emit=lambda *a,**k:None,response_dir=tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        ledger=StepLedger(profile,time.monotonic()+930,lambda *a,**k:None)
        with pytest.raises(ValueError,match='exact model'):
            client.create(model=MODEL,messages=[],max_tokens=16000,deadline=ledger.deadline,
                          step_ledger=ledger,budget_role='executor')
        assert not requests
        response=client.create(model=plan['model'],messages=[],max_tokens=16000,deadline=ledger.deadline,
                               step_ledger=ledger,budget_role='executor')
        assert response.model_dump()['model']==plan['model'] and len(requests)==1
    finally:
        client.close()


def test_three_actors_share_projection_but_baseline_reads_no_extra_context(tmp_path,monkeypatch):
    plan=spec(monkeypatch)
    from scripts.run_official_native_tasks import agent_class
    from scripts.probe_mini_grounding import synthetic_image
    from test_mini_taskviews import OfflineTransport
    from ui_kobe.osworld.kimi_native import KimiNativeAgent
    from ui_kobe.osworld.sx_native import SXNativeProvider
    from ui_kobe.osworld.transitions import TransitionJournal,decision_tools
    obs=synthetic_image((1720,880,1800,960))
    for arm in plan['arms']:
        monkeypatch.setenv('UI_KOBE_GENERATION_PROFILE',MAX_HIGH_GENERATION)
        monkeypatch.setenv('UI_KOBE_SX_URL_ENV','SX_URL_SB')
        monkeypatch.setenv('UI_KOBE_TASKVIEWS_PROFILE','mini_fixed_v1')
        monkeypatch.setenv('UI_KOBE_MINI_CONTROLS_VIEW','disabled')
        monkeypatch.setenv('UI_KOBE_TELEMETRY_DIR',str(tmp_path/arm))
        monkeypatch.setenv('UI_KOBE_CUA_CONTRACT_JSON',json.dumps(plan['cua_contract']))
        transport=OfflineTransport([{'action':'left_click','coordinate':[500,500]}]*2)
        monkeypatch.setattr(SXNativeProvider,'provider_transport',lambda *a:transport)
        actor=agent_class('sx-native',arm,'mini_fixed_v1')(model=plan['model'],base_url=plan['base_url'],
                                                        temperature=0,max_tokens=16000)
        actor.execution_journal=TransitionJournal(tmp_path/arm/'journal',task_id='synthetic',run_id=arm,contract=actor.contract)
        for step in (1,2):
            actor.execution_journal.begin('Synthetic task',obs,step=step)
            response,commands=actor.predict('Synthetic task',obs)
            assert commands==['pyautogui.click(960, 540)']
            actor.execution_journal.decide(response,commands,step=step,tools=decision_tools(actor))
            receipts=[{'command':commands[0],'result':{'status':'success','returncode':0,'error':''}}]
            actor.execution_journal.result(commands[0],step=step,observation=obs,receipts=receipts)
            actor.record_execution(commands[0],receipts=receipts)
        assert len(transport.requests)==2 and actor.model_name==plan['model']
        if arm=='baseline':
            assert actor.optional_context.__func__ is KimiNativeAgent.optional_context
            assert actor.cached_context is None and not hasattr(actor,'mini_context') and not hasattr(actor,'context_provider')
            text=json.dumps(transport.requests[-1]['messages'])
            assert 'Fixed TaskViews' not in text and 'Trusted screenshot/coordinate contract:' not in text
            assert any(m.get('tool_call_id')=='original-1' for m in transport.requests[-1]['messages'])
        actor.close()


@pytest.mark.parametrize('experiment,stop_arm',[
    ('sx-max-high40',None),('sx-max-high40','ui_kobe_like'),('sx-max-high40','baseline'),
    ('sx-mini-max-high40',None),('sx-mini-max-high40','taskviews')])
def test_three_arm_dispatch_never_marks_complete_or_skips_cleanup_early(tmp_path,monkeypatch,experiment,stop_arm):
    spec(monkeypatch)
    plan=module.specification('sx','SX_URL_SB','relative',experiment)
    from scripts import osworld_native_experiment
    monkeypatch.setattr(osworld_native_experiment,'require_scope',lambda limit:tmp_path)
    monkeypatch.setattr(module,'validate_plan',lambda root:plan)
    monkeypatch.setattr(module,'require_live_provider_check',lambda *a:None)
    module.write(tmp_path/'state.json',{'status':'prepared_not_started'})
    seen=[]
    def run(command,check):
        arm=command[command.index('--arm')+1]
        state=module.read(tmp_path/'state.json')
        assert state['status']=='running' and state['active_arm']==arm
        assert state['completed_arms']==seen
        seen.append(arm)
        module.write(tmp_path/arm/'outcome.json',{'complete':arm!=stop_arm,'source_unchanged':True})
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess,'run',run)
    code=module.launch(SimpleNamespace(execute_approved_plan=True,root=tmp_path))
    count=plan['arms'].index(stop_arm)+1 if stop_arm else len(plan['arms'])
    assert seen==plan['arms'][:count] and code==bool(stop_arm)
    assert module.read(tmp_path/'state.json')['status']==('stopped_on_error' if stop_arm else 'completed')


@pytest.mark.parametrize('experiment,count,corrupt_arm',[
    ('sx-max-high40',9,'baseline'),('sx-mini-max-high40',3,'taskviews')])
def test_high40_requires_all_nine_cases_with_current_generation(tmp_path,monkeypatch,experiment,count,corrupt_arm):
    spec(monkeypatch)
    plan=module.specification('sx','SX_URL_SB','relative',experiment)
    identity={'fixture':'source'}
    monkeypatch.setattr(module,'project_identity',lambda:identity)
    for arm in plan['arms']:
        for case in ('limit','terminate','empty'):
            row={k:deepcopy(plan[k]) for k in ('model','base_url','cua_contract','generation_fields','max_steps','experiment')}
            row.update(passed=True,arm=arm,case=case,provider='sx',source_unchanged=True,
                       project_source=identity,live_api_called=False,vm_started=False)
            module.write(tmp_path/f'{arm}-{case}'/'validation.json',row)
    args=(tmp_path,'sx',plan['base_url'],plan['cua_contract'],plan)
    assert len(module.validation_evidence(*args)['sha256'])==count
    path=tmp_path/f'{corrupt_arm}-limit'/'validation.json'
    row=module.read(path)
    row['generation_fields']={'reasoning_effort':'low'}
    module.write(path,row)
    with pytest.raises(ValueError,match='offline integration'):
        module.validation_evidence(*args)


@pytest.mark.parametrize('mismatch',[None,'image','label','memory'])
def test_cleanup_only_removes_exact_owned_frozen_guest(monkeypatch,mismatch):
    import docker
    from ui_kobe.osworld.verified_resources import cleanup_owned_run, LABEL
    plan=spec(monkeypatch)
    calls=[]
    class Guest:
        id='owned-id'
        removed=False
        labels={LABEL:'owned-run' if mismatch!='label' else 'foreign-run'}
        attrs={'HostConfig':{'Memory':plan['vm_memory_bytes'] if mismatch!='memory' else 1,
                             'MemorySwap':plan['vm_memory_bytes']},
               'Config':{'Image':plan['docker_image'] if mismatch!='image' else 'foreign:latest'},
               'State':{'Running':True}}
        def reload(self):
            pass
        def stop(self,timeout):
            calls.append('stop')
        def remove(self):
            calls.append('remove')
            self.removed=True
    guest=Guest()
    class Client:
        containers=None
        def list(self,all,filters):
            assert filters=={'label':f'{LABEL}=owned-run'}
            return [] if guest.removed else [guest]
        def close(self):
            pass
    client=Client()
    client.containers=client
    monkeypatch.setattr(docker,'from_env',lambda **kwargs:client)
    if mismatch:
        with pytest.raises(RuntimeError,match='Refuse cleanup'):
            cleanup_owned_run(plan,'owned-run')
        assert not calls
    else:
        assert cleanup_owned_run(plan,'owned-run')['cleanup_ok']
        assert calls==['stop','remove']
