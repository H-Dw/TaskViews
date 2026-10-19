"""Offline admission of saved failed requests, never an episode/API/GUI replay."""
import argparse
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def saved_case(root):
    from kobe_views.artifact_view import ReviewError, validate_review
    from ui_kobe.api.kimi_stream import StreamProtocolError
    from ui_kobe.osworld.actor_context import repair_messages
    from ui_kobe.osworld.cua_contract import CUAContract
    from ui_kobe.osworld.mini_recovery import admit_request, check_tool_pairs, report_feedback
    from ui_kobe.osworld.native_history import context_size

    fixtures = json.loads((PROJECT/'tests/fixtures/mini_recovery_failures.json').read_text())
    plan = json.loads((root/'plan.json').read_text())
    case = next(row for row in fixtures.values() if isinstance(row,dict) and row.get('commit')==plan['project_commit'])
    files = sorted((root/'taskviews/telemetry').glob('events-*.jsonl'))
    assert len(files)==1 and sha(files[0])==case['events_sha256']
    events = []
    for line in files[0].open():
        row = json.loads(line)
        if row.get('step')==case['step']:
            events.append(row)
    requests = [row for row in events if row['event']=='api_request']
    replies = {row['request_id']:row['response'] for row in events if row['event']=='api_response'}
    rejections = [row for row in events if row['event']=='candidate_rejected']
    assert len(rejections)==len(case['responses'])
    request = {'messages':deepcopy(requests[0]['payload']['messages']), 'tools':requests[0]['payload']['tools']}
    context, label = None, None
    for message in request['messages']:
        if isinstance(message.get('content'),list):
            parts = []
            for part in message['content']:
                if part.get('text','').startswith('TaskViews:'):
                    assert context is None
                    label, context = part['text'].split('\n',1)
                else:
                    parts.append(part)
            message['content']=parts
    assert context is not None and context_size(request['messages'])[1]==case['base_native_text_chars']
    # This VLC history contains closed user/assistant/tool turns, no ask-user
    # messages. Infer and check these recorded boundaries before testing them.
    lengths, position = [], 1
    while position<len(request['messages'])-1:
        messages=request['messages']
        assert messages[position]['role']=='user' and messages[position+1]['role']=='assistant'
        end=position+2
        while end<len(messages)-1 and messages[end]['role']=='tool':
            end+=1
        lengths.append(end-position)
        position=end
    assert position==len(request['messages'])-1
    transport=next(row for row in events if row['event']=='qwen_image_transport')
    observation=next(row for row in events if row['event']=='observation')
    image=root/'taskviews/telemetry'/observation['screenshot']['image']
    assert sha(image)==observation['screenshot']['sha256']
    assert transport['changed'] is False
    url='data:image/png;base64,'+base64.b64encode(image.read_bytes()).decode()
    assert len(url)==transport['wire_data_url_chars']
    current=request['messages'][-1]
    images=[part for part in current['content'] if part.get('type')=='image_url']
    assert len(images)==1
    images[0]['image_url']['url']=url
    original=deepcopy(request)
    contract=CUAContract(**plan['cua_contract'])
    short, short_lengths=deepcopy(request),list(lengths)
    full=deepcopy(request)
    report_admissions=[]
    for index,rejection in enumerate(rejections):
        response=replies[rejection['request_id']]
        message=response['choices'][0]['message']
        item=case['responses'][index]
        assert len(message.get('content') or '')==item['content_chars']
        assert len(message.get('reasoning_content') or '')==item['reasoning_chars']
        response_event=next(row for row in events if row['event']=='api_response' and row['request_id']==rejection['request_id'])
        assert response_event['raw_response_sha256']==item['raw_sse_sha256']
        assert sha(Path(response_event['raw_sse_path']))==item['raw_sse_sha256']
        try:
            validate_review(message.get('content'),final=True)
        except ReviewError as error:
            assert error.code==item['failure']
            short=report_feedback(short,error)
        else:
            raise AssertionError('Expected the saved unmodified invalid report')
        short,short_lengths,trace=admit_request(short,short_lengths,contract=contract,context=context,label=label)
        report_admissions.append(trace)
        full=repair_messages(full,response,StreamProtocolError(rejection['error'],code=rejection['error_code']),role='executor')
    assert context_size(full['messages'])[1]==case['old_blocked_text_chars']
    fixed,remaining,trace=admit_request(full,lengths,contract=contract,context=context,label=label)
    assert trace['old_turns_removed']>0
    # No field of a rejected assistant or corresponding tool receipt is lost.
    suffix_index=1+sum(lengths)
    admitted_suffix_index=1+sum(remaining)
    assert fixed['messages'][admitted_suffix_index+1:]==full['messages'][suffix_index+1:]
    check_tool_pairs(short['messages'])
    check_tool_pairs(fixed['messages'])
    assert request==original
    assert sha(files[0])==case['events_sha256']
    return {'project_commit_of_saved_run':plan['project_commit'],'step':case['step'],
        'saved_native_text_chars':case['base_native_text_chars'],
        'old_full_repair_native_text_chars':case['old_blocked_text_chars'],
        'mini_report_feedback_admissions':report_admissions,
        'full_native_repair_readmission':trace,
        'saved_image_sha256':observation['screenshot']['sha256'],
        'saved_events_sha256':case['events_sha256'], 'original_evidence_unchanged':True,
        'required_native_replies_preserved':True,
        'limitation':'Saved inputs and failed replies only; no new model response or task score'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result={'kind':'offline_saved_failure_admission','live_model_requests':0,'gui_actions':0,
            'official_evaluations':0,'official_score':None,'cases':[saved_case(path) for path in args.run]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__':
    main()
