"""Regressions for v5 empty receipts, unit ambiguity and silent repeat loops."""
from copy import deepcopy

import pytest

from kobe_views.fixed_views import REVISION, materialize, profile_contract
from ui_kobe.osworld.checkpoints import ReadAnomaly
from ui_kobe.osworld.cua_contract import CUAContract
from ui_kobe.osworld.mini_taskviews_native import FRAME_CONTRACT_PREFIX
from test_mini_taskviews import make_actor, original_event, packet, predict


@pytest.mark.parametrize('error', [None, '', ' ', '\t\r\n', False, {}, []])
def test_successful_official_receipts_do_not_enter_error_lessons(monkeypatch, tmp_path, error):
    actor, obs, transport = make_actor(monkeypatch, tmp_path)
    commands = predict(actor, obs, dispatch=False)
    receipts = [{'command': commands[0], 'result': {'status': 'success', 'returncode': 0,
                                                 'error': error, 'output': ''}}]
    actor.execution_journal.result(commands[0], step=1, observation=obs, receipts=receipts, error=error)
    actor.record_execution(commands[0], receipts=receipts, error=error)
    predict(actor, obs)
    value = packet(transport)
    assert not any(r['grade']=='execution_error_record' for r in value['views']['lessons']['records'])
    assert any(r['grade']=='model_intent_proposal' for r in value['views']['lessons']['records'])
    assert original_event(actor, value, value['views']['attempts']['records'][0])['controller_receipts'] == receipts
    actor.close()


@pytest.mark.parametrize('result', [
    {'status': 'failure', 'error': ''}, {'status': 'success', 'returncode': 2, 'error': ''},
    {'status': 'success', 'success': False, 'error': ''},
    {'status': 'success', 'error': 'actual failure'}, {'error': {'message': 'actual failure'}}])
def test_failure_signals_survive_empty_message_fix(monkeypatch, tmp_path, result):
    actor, obs, transport = make_actor(monkeypatch, tmp_path)
    commands = predict(actor, obs, dispatch=False)
    receipts = [{'command': commands[0], 'result': result}]
    actor.execution_journal.result(commands[0], step=1, observation=obs, receipts=receipts)
    actor.record_execution(commands[0], receipts=receipts)
    predict(actor, obs)
    errors = [r for r in packet(transport)['views']['lessons']['records'] if r['grade']=='execution_error_record']
    assert len(errors)==1 and original_event(actor, packet(transport), errors[0])['controller_receipts']==receipts
    actor.close()


@pytest.mark.parametrize('relative,point,expected', [
    (False, [1830, 920], 'pyautogui.click(1830, 920)'),
    (False, [17, 560], 'pyautogui.click(17, 560)'),
    (True, [950, 800], 'pyautogui.click(1824, 864)'),
])
def test_actual_predict_declares_units_and_only_official_compiler_projects(monkeypatch, tmp_path, relative, point, expected):
    contract = CUAContract(coordinate_type='relative' if relative else 'absolute',
                          model_screen_width=1920, model_screen_height=1080,
                          history_n=20, image_max=1, fold_size=1)
    actor, obs, transport = make_actor(monkeypatch, tmp_path, contract=contract,
                                      actions=[{'action':'left_click', 'coordinate':point}]*2)
    for step in (1,2):
        assert predict(actor, obs)==[expected]
        current=transport.requests[-1]['messages'][-1]['content']
        text=next(p['text'] for p in current if p.get('text','').startswith('Trusted screenshot/coordinate contract:'))
        assert len(text)<700  # Keep the final native assistant/tool pair even at the 500-step prefix boundary.
        assert f'native-frame-{step:04d}' in text
        assert ('Use normalized 0..1000' if relative else 'Use absolute pixels') in text
        assert ('center is (500,500)' if relative else 'center is (960,540)') in text
        assert 'Verify the expected visible change' in text
        assert sum(p['type']=='image_url' for p in current)==1
        assert actor.last_trace['native_action']['coordinate']==point
    assert len(transport.requests)==2
    actor.close()


def test_only_old_generated_coordinate_annotations_are_removed(monkeypatch, tmp_path):
    actor, obs, transport = make_actor(monkeypatch, tmp_path)
    predict(actor, obs, error='Original controller error')
    original = deepcopy(actor.turns[0][1])
    user_text = {'type':'text', 'text':'Original extra observation'}
    actor.turns[0][0]['content'].append(user_text)
    predict(actor, obs)
    messages = transport.requests[-1]['messages']
    annotations = [part['text'] for message in messages if isinstance(message.get('content'), list)
                   for part in message['content'] if part.get('text','').startswith(FRAME_CONTRACT_PREFIX)]
    assert len(annotations)==1 and 'native-frame-0002' in annotations[0]
    assert any(user_text in m['content'] for m in messages if isinstance(m.get('content'),list))
    assert original in messages
    receipt = next(m for m in messages if m.get('tool_call_id')=='original-1')
    assert 'Original controller error' in receipt['content']
    actor.close()


def test_default_repeat_evidence_with_official_receipts_is_not_a_false_error(monkeypatch, tmp_path):
    monkeypatch.setenv('UI_KOBE_MINI_CONTROLS_VIEW','disabled')
    actor, obs, transport=make_actor(monkeypatch,tmp_path,actions=[{'action':'left_click','coordinate':[17,560]}]*4)
    for _ in range(3):
        commands=predict(actor,obs,dispatch=False)
        receipts=[{'command':commands[0],'result':{'status':'success','returncode':0,'error':''}}]
        actor.execution_journal.result(commands[0],step=actor.total_steps,observation=obs,receipts=receipts)
        actor.record_execution(commands[0],receipts=receipts)
    predict(actor,obs)
    value=packet(transport)
    repeated=value['views']['current']['records'][0]['recent_repetition']
    assert repeated['repeat_count']==repeated['same_image_count']==3
    assert repeated['effect_status']=='unknown'
    assert not any(r['grade']=='execution_error_record' for r in value['views']['lessons']['records'])
    assert len(transport.requests)==4 and actor.mini_context.trace['packet_bytes']<=3000
    actor.close()


def test_oversized_repeat_record_can_be_omitted_without_controls():
    result=materialize(episode_id='e',frame_id='f',current={'recent_repetition':{'action':'x'*4000}},
                       attempts=[],lessons=[],totals={'attempts':0,'lessons':0},max_bytes=3000)
    assert result['views']['current']['records']==[{'recent_repetition_omitted':True}]


def test_old_checkpoint_cannot_silently_gain_new_actor_semantics(monkeypatch,tmp_path):
    actor,obs,_=make_actor(monkeypatch,tmp_path)
    predict(actor,obs)
    state=actor.checkpoint_state()
    assert state['contract']['implementation_revision']==REVISION==profile_contract()['implementation_revision']
    old=deepcopy(state)
    old['contract'].pop('implementation_revision')
    with pytest.raises(ReadAnomaly,match='profile differs'):
        actor.restore_checkpoint_state(old)
    actor.restore_checkpoint_state(state)
    actor.close()


@pytest.mark.parametrize('mode', ['absolute', 'relative'])
@pytest.mark.parametrize('box', [(1580,140,1660,220), (180,820,260,900), (1720,880,1800,960)])
def test_probe_uses_real_mini_predict_and_checks_compiled_screen_point(monkeypatch,tmp_path,mode,box):
    from scripts.probe_mini_grounding import inspect_candidate, synthetic_image
    center=[(box[0]+box[2])/2,(box[1]+box[3])/2]
    point=center if mode=='absolute' else [center[0]*1000/1920,center[1]*1000/1080]
    contract=CUAContract(coordinate_type=mode,model_screen_width=1920,model_screen_height=1080)
    actor,_,transport=make_actor(monkeypatch,tmp_path,contract=contract,
                               actions=[{'action':'mouse_move','coordinate':point}])
    result=inspect_candidate(actor,synthetic_image(box),box)
    assert result['passed'] and result['compiled_point_px']==center
    assert not result['gui_dispatched'] and result['journal_decision_unexecuted']
    assert actor.execution_journal.position==0 and len(transport.requests)==1
    assert sum(p['type']=='image_url' for p in transport.requests[-1]['messages'][-1]['content'])==1
    actor.close()


def test_probe_rejects_normalized_coordinates_misread_as_pixels(monkeypatch,tmp_path):
    from scripts.probe_mini_grounding import inspect_candidate, synthetic_image
    box=(1720,880,1800,960)
    actor,_,transport=make_actor(monkeypatch,tmp_path,actions=[{'action':'mouse_move','coordinate':[917,852]}])
    result=inspect_candidate(actor,synthetic_image(box),box)
    assert not result['passed'] and result['compiled_point_px']==[917,852]
    assert len(transport.requests)==1 and actor.execution_journal.position==0
    actor.close()


def test_provider_diagnostic_releases_large_frame_buffers_with_identical_pixels():
    from scripts.probe_native_provider import vision_frame
    contract=CUAContract(coordinate_type='relative',model_screen_width=1920,model_screen_height=1080)
    frame, size=vision_frame(contract,large=True)
    assert frame.original_sha256=='51442cde6d4195b868597dffeccaabf226fca2556f3f5c6d20d76f960c862842'
    assert size==4387662 and len(frame.image['image_url']['url'])>2_000_000
    assert frame.metadata['original_size']==frame.metadata['model_size']==[1920,1080]
