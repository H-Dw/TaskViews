from copy import deepcopy
from io import BytesIO
import json
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

from ui_kobe.osworld.cua_contract import CUAContract, CUAFrame
from ui_kobe.osworld.kimi_native import KimiNativeAgent, official_compile
from ui_kobe.osworld.kimi_taskviews_native import KimiTaskViewsNativeAgent
from ui_kobe.osworld.native_history import compact
from ui_kobe.osworld.pointer_grounding import current_frame_content
from ui_kobe.osworld.pointer_checks import POINTER_CASES, rectangles, hit_target, grade_pointer_log, validate_case


def frame(step=1):
    return CUAFrame(SimpleNamespace(coordinate_type='absolute', original_width=1920, original_height=1080,
        model_width=1920, model_height=1080, data_url='data:image/png;base64,offline'), 'a'*64, step)


def test_mandatory_frame_contract_is_current_and_has_no_target_answer():
    first, second = current_frame_content(frame()), current_frame_content(frame(2))
    assert 'native-frame-0001' in first[0]['text'] and 'native-frame-0002' in second[0]['text']
    assert 'Actions use model-image pixels: x in 0..1920, y in 0..1080' in first[0]['text']
    assert 'do not normalize' in first[0]['text'] and 'one GUI action' in first[0]['text']
    assert all(label not in first[0]['text'] for label in ('Cobalt', 'Willow', 'Amber', '1711', '891'))
    assert first[1] == frame().image


@pytest.mark.parametrize('enabled', [False, True])
def test_only_opted_in_taskviews_changes_current_message(enabled):
    actor = KimiTaskViewsNativeAgent.__new__(KimiTaskViewsNativeAgent)
    actor.frame, actor.feedback_v10 = frame(), enabled
    value = actor.current_frame_content()
    assert value == (current_frame_content(frame()) if enabled else [frame().image])
    baseline = KimiNativeAgent.__new__(KimiNativeAgent)
    baseline.frame = frame()
    assert baseline.current_frame_content() == [frame().image]


def test_current_contract_survives_history_rescue_and_task_relocation():
    current = {'role':'user','content':current_frame_content(frame(9))}
    old = [[{'role':'user','content':[frame(8).image]},
            {'role':'assistant','content':'x'*9000}]]
    contract = CUAContract(context_max_text_chars=7000, context_reserve_chars=1000)
    _, omitted, _ = compact(old, step=9, folded=0, contract=contract,
        system={'role':'system','content':'Original system'}, current=current, instruction='Original task')
    assert omitted == 1 and not old
    assert current['content'][0]['text'].startswith('Trusted screenshot/coordinate contract:')
    assert 'Original task' in current['content'][-1]['text']


@pytest.mark.parametrize('point', [(891,45),(239,228),(319,720),(0,0),(1919,1079),(1711,49)])
def test_official_compiler_never_reinterprets_an_in_bounds_point(point):
    args = [{'action':'left_click','coordinate':list(point)}]
    original = deepcopy(args)
    batch = official_compile(args, frame())
    assert batch.commands == [f'pyautogui.click({point[0]}, {point[1]})'] and args == original


@pytest.mark.parametrize('point', [(-1,10),(1921,10),(10,1081)])
def test_invalid_coordinates_remain_official_failures(point):
    from mm_agents.qwen.actions import ActionValidationError
    with pytest.raises(ActionValidationError):
        official_compile([{'action':'left_click','coordinate':list(point)}],frame())


def qwen_actor(monkeypatch, tmp_path, responses):
    from ui_kobe.osworld.qwen_taskviews_native import QwenTaskViewsNativeAgent
    from ui_kobe.osworld import telemetry
    from ui_kobe.api.qwen_native import QwenNativeClient, MODEL, BASE_URL
    monkeypatch.setenv('QWEN_API_KEY','offline-only')
    monkeypatch.setenv('UI_KOBE_TELEMETRY_DIR',str(tmp_path))
    monkeypatch.setenv('UI_KOBE_TASK_ID','pointer-test')
    monkeypatch.setenv('UI_KOBE_TASKVIEWS_FEEDBACK_V10','1')
    actor=QwenTaskViewsNativeAgent(model=MODEL,base_url=BASE_URL,temperature=0,max_tokens=16000)
    actor.transport.close()
    sent=[]
    reads=[]
    def handler(request):
        sent.append(json.loads(request.content))
        args=responses[min(len(sent)-1,len(responses)-1)]
        return httpx.Response(200,json={'id':'offline-'+str(len(sent)),'model':MODEL,
            'choices':[{'index':0,'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
                'tool_calls':[{'id':'tool-'+str(len(sent)),'type':'function','function':{'name':'computer_use','arguments':json.dumps(args)}}]}}],
            'usage':{'prompt_tokens':20,'completion_tokens':10,'total_tokens':30}})
    client=QwenNativeClient(api_key='offline-only',budget=actor.budget,profile=actor.profile,
        emit=telemetry.emit,response_dir=tmp_path/'responses',
        client=httpx.Client(transport=httpx.MockTransport(handler)))
    actor.transport=actor.client.transport=client
    def optional(goal,obs):
        texts=[p.get('text','') for p in actor.actor_input_messages[-1]['content']]
        assert any('Trusted screenshot/coordinate contract:' in t for t in texts)
        reads.append(actor.total_steps)
        actor.view_trace={}
        return None
    actor.optional_context=optional
    image=BytesIO()
    Image.new('RGB',(1920,1080)).save(image,'PNG')
    return actor,{'screenshot':image.getvalue()},sent,reads


def test_actual_predict_delivers_current_contract_before_analysis_each_turn(monkeypatch,tmp_path):
    actor,obs,sent,reads=qwen_actor(monkeypatch,tmp_path,[{'action':'left_click','coordinate':[1711,49]}])
    try:
        for step in range(1,4):
            _,commands=actor.predict('Original exact task',obs)
            assert commands==['pyautogui.click(1711, 49)']
            current=next(m for m in reversed(sent[-1]['messages']) if m['role']=='user')
            assert f'native-frame-{step:04d}' in current['content'][0]['text']
            assert sent[-1]['tools'][0]['function']['description'].find('1920x1080')>=0
        assert reads==[1,2,3] and len(sent)==3
    finally:
        actor.close()


def test_native_repair_preserves_bad_point_and_mandatory_contract(monkeypatch,tmp_path):
    bad={'action':'left_click','coordinate':[99999,45]}
    good={'action':'left_click','coordinate':[1711,49]}
    actor,obs,sent,_=qwen_actor(monkeypatch,tmp_path,[bad,good])
    try:
        assert actor.predict('Original task',obs)[1]==['pyautogui.click(1711, 49)']
        assert len(sent)==2
        for payload in sent:
            assert any('Trusted screenshot/coordinate contract:' in p.get('text','')
                for m in payload['messages'] if isinstance(m.get('content'),list) for p in m['content'])
        rejected=next(m for m in sent[1]['messages'] if m['role']=='assistant')
        assert json.loads(rejected['tool_calls'][0]['function']['arguments'])==bad
    finally:
        actor.close()


def test_unadmitted_current_input_never_calls_optional_analysis(monkeypatch,tmp_path):
    actor,obs,sent,reads=qwen_actor(monkeypatch,tmp_path,[{'action':'left_click','coordinate':[1,1]}])
    actor.contract=CUAContract(context_max_text_chars=500,context_reserve_chars=0)
    try:
        with pytest.raises(ValueError,match='Current task/frame'):
            actor.predict('Original task',obs)
        assert not reads and not sent
    finally:
        actor.close()


TARGETS=[(kind,rev,label) for kind,spec in POINTER_CASES.items()
         for rev in range(len(spec['layouts'])) for label in spec['targets']]


@pytest.mark.parametrize('kind,revision,label',TARGETS)
def test_mouse_dataset_centers_match_current_layout(kind,revision,label):
    spec=POINTER_CASES[kind]
    validate_case(spec)
    box=rectangles(spec,revision)[label]
    point=[(box[0]+box[2])/2,(box[1]+box[3])/2]
    assert hit_target(spec,revision,point)==label


@pytest.mark.parametrize('kind,revision,label',TARGETS)
def test_normalized_numbers_are_not_silently_changed_to_pixels(kind,revision,label):
    spec=POINTER_CASES[kind]
    box=rectangles(spec,revision)[label]
    actual=[(box[0]+box[2])/2,(box[1]+box[3])/2]
    normalized=[actual[0]*1000/1920,actual[1]*1000/1080]
    original=list(normalized)
    assert hit_target(spec,revision,normalized)!=label and normalized==original


def mouse_log(spec):
    events=[]
    accepted=[]
    for label in spec['targets']:
        boxes=rectangles(spec,len(accepted))
        b=boxes[label]
        point=[(b[0]+b[2])/2,(b[1]+b[3])/2]
        events.append({'seq':len(events)+1,'kind':'mouse_release','button':1,'revision':len(accepted),
            'screen_point':point,'rectangles':boxes,'hit':label,'accepted':True})
        accepted.append(label)
    return {'case_id':spec['id'],'screen_size':[1920,1080],'window_origin':[0,0],
        'initial_accepted':[],'accepted':accepted,'events':events}


@pytest.mark.parametrize('kind',POINTER_CASES)
def test_mouse_grade_requires_real_ordered_points_and_native_terminal(tmp_path,kind):
    spec=POINTER_CASES[kind]
    path=tmp_path/'observer.json'
    path.write_text(json.dumps(mouse_log(spec)))
    assert grade_pointer_log(path,spec)['custom_score'] is None
    grade=grade_pointer_log(path,spec,terminal=True)
    assert grade['custom_score']==1 and grade['mouse_metrics']['precision']==1 and grade['official_score'] is None


@pytest.mark.parametrize('corruption',['normalized','stale-layout','reordered','fake-state','keyboard','wrong-case','nan','bool-point','out-of-frame'])
def test_pointer_evaluator_rejects_false_completion(tmp_path,corruption):
    spec=POINTER_CASES['pointer-relocation']
    log=mouse_log(spec)
    if corruption=='normalized':
        log['events'][0]['screen_point']=[100,100]
    elif corruption=='stale-layout':
        log['events'][1]['rectangles']=rectangles(spec,0)
    elif corruption=='reordered':
        log['events'].reverse()
    elif corruption=='fake-state':
        log['events']=[]
    elif corruption=='keyboard':
        log['events'][0]['kind']='key'
    elif corruption=='wrong-case':
        log['case_id']='other'
    elif corruption=='nan':
        log['events'][0]['screen_point']=[float('nan'),1]
    elif corruption=='bool-point':
        log['events'][0]['screen_point']=[True,1]
    elif corruption=='out-of-frame':
        log['events'][0]['screen_point']=[1921,1]
    path=tmp_path/'observer.json'
    path.write_text(json.dumps(log))
    assert grade_pointer_log(path,spec,terminal=True)['custom_score']==0


def test_fixture_is_input_only_and_has_no_keyboard_progress_binding():
    import ast
    from scripts.taskviews_pointer_fixture import pointer_setup_command
    for spec in POINTER_CASES.values():
        source=pointer_setup_command(spec)
        ast.parse(source)
        program=ast.literal_eval(ast.parse(source).body[2].value)
        tree=ast.parse(program)
        bindings=[node.args[0].value for node in ast.walk(tree) if isinstance(node,ast.Call)
            and isinstance(node.func,ast.Attribute) and node.func.attr=='bind']
        assert bindings==['<ButtonRelease-1>']
        assert "initial['events']" in source and 'pyautogui.click' not in source


def binding_module():
    from kobe_views.execution_modules import ExecutionModules
    module = ExecutionModules.__new__(ExecutionModules)
    last = {'transition_id': 'original-type-edge', 'target': 'original-type-post',
            'expected_change': {'kind': 'text', 'text': 'Visible text'},
            'evidence_capture_refs': [{'transition_id': 'capture-edge',
                                       'target_observation_id': 'newer-capture-post'}]}
    module.last_action = lambda: deepcopy(last)
    return module, last


def test_explicit_binding_keeps_operation_post_separate_from_later_capture():
    module, original = binding_module()
    binding = module.verification_binding('current-frame')
    assert binding == {'transition_id': 'original-type-edge',
                       'target_observation_id': 'original-type-post', 'frame_id': 'current-frame'}
    check = {**binding, 'assessment': 'unknown',
             'checks': [{'kind': 'text', 'assessment': 'unknown', 'quotes': []},
                        {'kind': 'focus', 'assessment': 'unknown', 'quotes': []}]}
    module.validate_action_check(check, frame='current-frame', visible_texts=[])
    assert module.last_action() == original


@pytest.mark.parametrize('field,value', [('target_observation_id', 'newer-capture-post'),
                                        ('frame_id', 'stale-frame')])
def test_bad_binding_stays_rejected_but_feedback_has_exact_expected_ids(field, value):
    module, _ = binding_module()
    check = {**module.verification_binding('current-frame'), 'assessment': 'unknown',
             'checks': [{'kind': 'text', 'assessment': 'unknown', 'quotes': []}]}
    check[field] = value
    original = deepcopy(check)
    with pytest.raises(ValueError) as failure:
        module.validate_action_check(check, frame='current-frame', visible_texts=[])
    assert 'Copy action_check_binding exactly' in str(failure.value)
    assert 'original-type-post' in str(failure.value) and 'current-frame' in str(failure.value)
    assert check == original


def test_no_operation_has_no_binding():
    module, _ = binding_module()
    module.last_action = lambda: None
    assert module.verification_binding('current-frame') is None


@pytest.mark.parametrize('coordinate_type', ['absolute', 'relative'])
def test_pixel_landmarks_match_only_the_declared_absolute_frame(coordinate_type):
    current = frame()
    current.screenshot.coordinate_type = coordinate_type
    text = current_frame_content(current)[0]['text']
    if coordinate_type == 'absolute':
        assert 'center [960, 540]' in text and 'last pixel [1919, 1079]' in text
        assert 'never target locations' in text
    else:
        assert 'Pixel landmarks' not in text


@pytest.mark.parametrize('operation,kind', [({'action': 'type', 'text': 'Requested text'}, 'text'),
    ({'action': 'left_click', 'coordinate': [10, 10]}, 'focus'),
    ({'action': 'key', 'keys': ['ctrl', 's']}, 'state')])
@pytest.mark.parametrize('capture', [False, True])
def test_wait_tail_keeps_real_operation_warning_and_all_original_edges(tmp_path, operation, kind, capture):
    from kobe_views.execution_modules import ExecutionModules
    from kobe_views.task_memory import TaskMemory
    from ui_kobe.osworld.transitions import TransitionJournal
    image = BytesIO()
    Image.new('RGB', (64, 48)).save(image, 'PNG')
    observation = {'screenshot': image.getvalue()}
    memory = TaskMemory('task', tmp_path / 'memory')
    memory.initialize('Save requested text')
    journal = TransitionJournal(tmp_path / 'events', task_id='task', run_id='run',
        contract=CUAContract(model_screen_width=64, model_screen_height=48))
    module = ExecutionModules(memory, journal)
    module.compare_state_v10 = True
    module.select('save', [{'purpose': 'save', 'anchors': ['task']}], frame='0', ref='ref')
    try:
        for step in (1, 2):
            journal.begin('Save', observation, step=step)
            commands = ['operate', 'WAIT'] + (['capture'] if capture else [])
            tools = [{'id': f'op-{step}', 'arguments': operation, 'command_indices': [0]},
                {'id': f'wait-{step}', 'arguments': {'action': 'wait', 'time': 1}, 'command_indices': [1]}]
            if capture:
                tools.append({'id': f'capture-{step}', 'arguments': {'action': 'screenshot'}, 'command_indices': [2]})
            journal.decide('original complete batch', commands, step=step, tools=tools)
            mutation = journal.result('operate', step=step, observation=observation, receipts=[{'returncode': 0}])
            delay = journal.result('WAIT', step=step, observation=observation, receipts=[])
            if capture:
                journal.result('capture', step=step, observation=observation, receipts=[{'returncode': 0}])
            module.sync()
            last = module.last_action()
            assert last['transition_id'] == mutation['id'] and last['expected_change']['kind'] == kind
            assert module.verification_binding(str(step))['target_observation_id'] == mutation['target']
            assert any(r['transition_id'] == delay['id'] and r['observation_kind'] == 'wait'
                       for r in last['evidence_capture_refs'])
            assert last['executed_tool_input']['parameters'] == operation
        assert module.actor_feedback()['original_parameters'] == operation
        assert module.actor_feedback()['unconfirmed_repetition_count'] == 2
        assert len(module.recent) == 2 * len(commands)
    finally:
        journal.close()
