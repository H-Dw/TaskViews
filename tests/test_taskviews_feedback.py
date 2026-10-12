from copy import deepcopy
from io import BytesIO
import hashlib
import json

from PIL import Image
import pytest

from kobe_views.execution_modules import ExecutionModules
from kobe_views.model import dumps, plain
from kobe_views.task_memory import TaskMemory
from scripts.taskviews_fast_fixture import run_fixture
from ui_kobe.osworld.actor_context import available_context_bytes, supplement
from ui_kobe.osworld.cua_contract import CUAContract
from ui_kobe.osworld.transitions import TransitionJournal
from ui_kobe.osworld.advisory_concurrency import AdvisoryJob, run_advisory_jobs


def prior_failure_module():
    module = ExecutionModules.__new__(ExecutionModules)
    module.active = 'import'
    module.recent = [{'transition_id': name, 'module_id': 'import', 'raw_ref': '/immutable/events#'+name}
                     for name in ('submit', 'dismiss', 'menu')]
    module.effects = {
        'submit': {'transition_id': 'submit', 'frame_id': 'error-frame', 'target_observation_id': 'error-post',
                   'assessment': 'not_observed', 'checks': [{'kind': 'submission', 'assessment': 'not_observed',
                                                            'quotes': ['Unsupported operation: ExampleCommand']}]},
        'dismiss': {'transition_id': 'dismiss', 'frame_id': 'closed-frame', 'target_observation_id': 'closed-post',
                    'assessment': 'not_observed', 'checks': [{'kind': 'object', 'assessment': 'not_observed',
                                                             'quotes': ['Empty Algebra']}]},
        'menu': {'assessment': 'observed', 'checks': [{'kind': 'state', 'assessment': 'observed',
                                                     'quotes': ['File']}]}}
    module.verification_intent = lambda row: {'text': 'Dismiss the error dialog' if row['transition_id'] == 'dismiss'
                                              else 'Submit ExampleCommand',
        'original_text_sha256': row['transition_id']+'-original-prose-sha', 'original_text_bytes': 24}
    return module


def test_prior_application_rejection_survives_dialog_dismissal_and_reaches_stateless_planner():
    from ui_kobe.osworld.taskviews_feedback import _planner_input
    module = prior_failure_module()
    original = deepcopy([module.recent, module.effects])
    prior = module.prior_action_evidence()
    feedback = {'last_action': {'checks': [{'quotes': ['Empty Algebra']}]}, 'prior_action_evidence': prior}
    packet = _planner_input({}, feedback, {'id': 'import'}, 'Import image', ['Error dialog now gone'], {}, 6000)
    rows = packet['action_feedback']['prior_action_evidence']['records']
    assert rows[0]['checks'][0]['quotes'] == ['Unsupported operation: ExampleCommand']
    assert rows[0]['frame_id'] == 'error-frame' and rows[0]['target_observation_id'] == 'error-post'
    assert rows[0]['original_feedback_sha256'] == hashlib.sha256(dumps(module.effects['submit']).encode()).hexdigest()
    assert rows[1]['original_intent']['text'] == 'Dismiss the error dialog'
    assert packet['visible_text'] == ['Error dialog now gone'] and prior['grade'] == 'model_proposal'
    assert [module.recent, module.effects] == original


@pytest.mark.parametrize('mode', ['other-subgoal', 'unknown', 'no-quote'])
def test_prior_failure_cannot_invent_rejected_evidence_or_cross_subgoals(mode):
    module = prior_failure_module()
    module.effects.pop('dismiss')
    if mode == 'other-subgoal':
        module.recent[0]['module_id'] = 'save'
    elif mode == 'unknown':
        module.effects['submit']['checks'][0]['assessment'] = 'unknown'
    else:
        module.effects['submit']['checks'][0]['quotes'] = []
    assert module.prior_action_evidence()['records'] == []


def test_prior_action_evidence_bounds_whole_quotes_refs_and_omission_counts():
    module = prior_failure_module()
    full = module.prior_action_evidence()
    limit = len(dumps(full).encode()) - 20
    bounded = module.prior_action_evidence(limit)
    assert len(dumps(bounded).encode()) <= limit and bounded['omitted_records'] == 1
    assert bounded['records'] == full['records'][:1]
    assert bounded['records'][0]['raw_transition_ref'] == '/immutable/events#submit'
    with pytest.raises(ValueError, match='omission metadata'):
        module.prior_action_evidence(1)


def test_long_prior_prose_is_wholly_omitted_without_truncating_literal_failure_evidence():
    module = prior_failure_module()
    module.verification_intent = lambda row: {'text': '长' * 200, 'original_text_sha256': 'original-sha',
                                              'original_text_bytes': 600}
    row = module.prior_action_evidence()['records'][0]
    assert row['original_intent'] == {'text': None, 'source_sha256': 'original-sha',
                                     'source_bytes': 600, 'whole_text_omitted': True}
    assert row['checks'][0]['quotes'] == ['Unsupported operation: ExampleCommand']


def test_submission_failure_outlives_recent_window_without_mutating_history():
    module = prior_failure_module()
    module.effects['submit'].update(module_id='import', raw_transition_ref='/immutable/events#submit')
    module.recent = module.recent[1:]
    before = deepcopy(module.effects)
    records = module.prior_action_evidence()['records']
    assert records[0]['transition_id'] == 'submit'
    assert records[0]['checks'][0]['quotes'] == ['Unsupported operation: ExampleCommand']
    assert module.effects == before
    module.effects['submit']['module_id'] = 'other-subgoal'
    assert all(row['transition_id'] != 'submit' for row in module.prior_action_evidence()['records'])


def test_actor_receives_retained_application_rejection_without_a_new_planner():
    from ui_kobe.osworld.taskviews_feedback import _admit_execution_feedback
    prior_module = prior_failure_module()
    prior_module.effects['submit'].update(module_id='import', raw_transition_ref='/immutable/events#submit')
    prior_module.recent = prior_module.recent[1:]
    original = deepcopy(prior_module.effects)
    evidence = prior_module.actor_prior_action_evidence()
    assert evidence['records'][0]['transition_id'] == 'submit'
    assert evidence['records'][0]['checks'][0]['quotes'] == ['Unsupported operation: ExampleCommand']
    assert evidence['records'][0]['original_feedback_sha256'] == hashlib.sha256(dumps(original['submit']).encode()).hexdigest()
    packet = _admit_execution_feedback(local_feedback_base(), [], duplicated_local_reference_module(),
                                       8000, strategy_review=False, prior_evidence=evidence)
    assert packet['prior_action_evidence'] == evidence and 'advisers' not in packet
    assert packet['prior_action_evidence']['scope'] == 'past_application_feedback_not_current_state_or_math'
    assert packet['current_visible_evidence']['summary'] == 'Visible editor'
    assert prior_module.effects == original


@pytest.mark.parametrize('mode', ['other-subgoal', 'unknown', 'observed', 'no-quote', 'focus'])
def test_actor_history_never_promotes_unknown_or_other_goal_checks_to_application_failure(mode):
    module = prior_failure_module()
    module.effects.pop('dismiss')
    if mode == 'other-subgoal':
        module.recent[0]['module_id'] = 'save'
    elif mode in {'unknown', 'observed'}:
        module.effects['submit']['assessment'] = mode
    elif mode == 'no-quote':
        module.effects['submit']['checks'][0]['quotes'] = []
    else:
        module.effects['submit']['checks'][0]['kind'] = 'focus'
    assert module.actor_prior_action_evidence()['records'] == []


def test_actor_history_keeps_whole_checks_and_exact_omission_counts_under_its_cap():
    module = prior_failure_module()
    original = deepcopy([module.effects, module.recent])
    full = module.actor_prior_action_evidence()
    assert len(full['records']) == 2 and len(dumps(full).encode()) <= 900
    limit = len(dumps(full).encode()) - 1
    bounded = module.actor_prior_action_evidence(limit)
    assert bounded['records'] == full['records'][:1] and bounded['omitted_records'] == 1
    assert bounded['records'][0]['raw_transition_ref'] == '/immutable/events#submit'
    assert [module.effects, module.recent] == original
    with pytest.raises(ValueError, match='omission metadata'):
        module.actor_prior_action_evidence(1)


def test_latest_execution_floor_outranks_optional_older_application_failure():
    from kobe_views.execution_modules import ExecutionPacketBudgetError
    from ui_kobe.osworld.taskviews_feedback import _admit_execution_feedback
    module, base = duplicated_local_reference_module(), local_feedback_base()
    prior = prior_failure_module().actor_prior_action_evidence()
    with pytest.raises(ExecutionPacketBudgetError) as raised:
        module.packet(max_bytes=1, include_modules=False, share_duplicate_refs=True, share_exact_refs=True)
    floor = raised.value.projection
    fixed = {**base, 'role_evidence': {'execution_modules': floor, 'strategy_review': False},
             'context_gaps': ['budget_omitted:prior_action_evidence']}
    limit = len(dumps(fixed).encode())
    packet = _admit_execution_feedback(base, [], module, limit, strategy_review=False, prior_evidence=prior)
    assert 'prior_action_evidence' not in packet and packet['context_gaps'] == fixed['context_gaps']
    assert packet['role_evidence']['execution_modules'] == floor
    assert packet['last_action_feedback'] == base['last_action_feedback']
    assert len(dumps(packet).encode()) <= limit


def test_old_focus_failure_does_not_displace_durable_application_rejection():
    module = prior_failure_module()
    module.effects['old-focus'] = {**deepcopy(module.effects['submit']), 'module_id': 'import',
        'raw_transition_ref': '/immutable/events#old-focus',
        'checks': [{'kind': 'focus', 'assessment': 'not_observed', 'quotes': ['Control']}]}
    module.effect_order = ['old-focus', 'submit', 'dismiss', 'menu']
    assert [row['transition_id'] for row in module.prior_action_evidence()['records']] == ['submit', 'dismiss']


def test_canonical_reload_recovers_accepted_reports_and_retains_chronological_effects(tmp_path):
    import sqlite3
    from types import SimpleNamespace
    path = tmp_path/'execution-modules.json'
    journal = SimpleNamespace(episode_id='episode', closed=False, db=sqlite3.connect(':memory:'))
    journal.db.execute('CREATE TABLE events (seq INTEGER, id TEXT, payload TEXT)')
    effects, claims = {}, {}
    identities = [f'{65-i:03}' for i in range(66)]
    for seq, identity in enumerate(identities):
        edge = {'id': identity, 'kind': 'transition', 'target': identity+'-post'}
        journal.db.execute('INSERT INTO events VALUES(?,?,?)', (seq, identity, dumps(edge)))
        effect = {'transition_id': identity, 'target_observation_id': edge['target'], 'frame_id': str(seq),
            'grade': 'model_proposal', 'module_id': 'import', 'assessment': 'not_observed',
            'checks': [{'kind': 'submission', 'assessment': 'not_observed', 'quotes': ['Rejected']}],
            'raw_transition_ref': '/immutable/events#'+identity}
        effects[identity] = effect
        claims[identity] = {'predicate': 'module_report.record', 'value': {'grade': 'model_proposal', 'report': effect}}
    # The old sorted-key cache dropped recent low IDs instead of old operations.
    path.write_text(dumps({'episode_id': 'episode', 'cursor': 0, 'active': 'import', 'modules': {},
                          'recent': [], 'effects': dict(list(effects.items())[:64])}))
    memory = SimpleNamespace(directory=tmp_path, snapshot=SimpleNamespace(claims=claims),
                             _atomic_json=TaskMemory._atomic_json)
    module = ExecutionModules(memory, journal)
    try:
        assert module.effect_order == identities[-64:]
        assert module.effects == {key: effects[key] for key in identities[-64:]}
        module.save()
        saved = json.loads(path.read_text())
        assert list(saved['effects']) == sorted(saved['effects'])
        assert saved['effect_order'] == identities[-64:]
        reopened = ExecutionModules(memory, journal)
        assert reopened.effect_order == module.effect_order and reopened.effects == module.effects
        # Rechecking an existing operation moves only that assessment to the end.
        row = {'transition_id': identities[2], 'raw_ref': effects[identities[2]]['raw_transition_ref'], 'module_id': 'import', 'error': None}
        reopened.last_effect_record = lambda: row
        reopened.report = lambda *args, **kwargs: None
        reopened.record_action_check({**effects[identities[2]], 'assessment': 'unknown'}, frame='latest')
        assert reopened.effect_order == identities[3:] + [identities[2]]
        assert len(reopened.effects) == 64
    finally:
        journal.db.close()


def durable_failure_fixture(tmp_path, count=82):
    import sqlite3
    from types import SimpleNamespace
    journal = SimpleNamespace(episode_id='durable-episode', closed=False, db=sqlite3.connect(':memory:'))
    journal.db.execute('CREATE TABLE events (seq INTEGER, id TEXT, payload TEXT)')
    reports, claims = {}, {}
    for seq in range(count):
        identity = f'operation-{count-seq:03}'
        edge = {'id': identity, 'kind': 'transition', 'target': identity+'-post'}
        journal.db.execute('INSERT INTO events VALUES(?,?,?)', (seq, identity, dumps(edge)))
        report = {'transition_id': identity, 'target_observation_id': edge['target'], 'frame_id': f'frame-{seq}',
            'grade': 'model_proposal', 'module_id': 'import',
            'assessment': 'not_observed' if seq == 0 else 'observed',
            'checks': [{'kind': 'submission' if seq == 0 else 'focus',
                        'assessment': 'not_observed' if seq == 0 else 'observed',
                        'quotes': ['Unsupported operation: ExampleCommand' if seq == 0 else 'Editor']}],
            'raw_transition_ref': '/immutable/events#'+identity}
        reports[identity] = report
        claims[identity] = {'predicate': 'module_report.record', 'value': {
            'grade': 'model_proposal', 'report': report}}
    # Deliberately reverse the graph/cache keys: IDs and JSON order are not time.
    claims = dict(reversed(list(claims.items())))
    identities = list(reports)[-64:]
    (tmp_path/'execution-modules.json').write_text(dumps({'episode_id': journal.episode_id,
        'cursor': 0, 'active': 'import', 'modules': {}, 'recent': [],
        'effects': {identity: reports[identity] for identity in identities}, 'effect_order': identities}))
    memory = SimpleNamespace(directory=tmp_path, snapshot=SimpleNamespace(claims=claims),
                             _atomic_json=TaskMemory._atomic_json)
    module = ExecutionModules(memory, journal)
    module.verification_intent = lambda record: {'text': 'Submit the requested operation',
        'original_text_sha256': 'c'*64, 'original_text_bytes': 30}
    return module, journal, reports, claims


def test_application_rejection_outlives_64_effects_and_reaches_actor_and_planner(tmp_path):
    from ui_kobe.osworld.taskviews_feedback import _admit_execution_feedback
    module, journal, reports, _ = durable_failure_fixture(tmp_path)
    try:
        oldest = next(iter(reports))
        original = deepcopy(module.effects)
        assert oldest not in module.effects and module.actor_prior_action_evidence()['records'] == []
        module.enable_application_failure_retention()
        actor = module.actor_prior_action_evidence()
        planner = module.prior_action_evidence()
        assert actor['records'][0]['transition_id'] == planner['records'][0]['transition_id'] == oldest
        assert actor['records'][0]['checks'] == reports[oldest]['checks']
        assert actor['records'][0]['raw_transition_ref'] == reports[oldest]['raw_transition_ref']
        assert actor['records'][0]['original_feedback_sha256'] == hashlib.sha256(dumps(reports[oldest]).encode()).hexdigest()
        assert len(dumps(actor).encode()) <= 900 and len(dumps(planner).encode()) <= 1600
        assert module.effects == original and len(module.effects) == 64
        delivered = _admit_execution_feedback(local_feedback_base(), [], duplicated_local_reference_module(),
            8000, strategy_review=False, prior_evidence=actor)
        assert delivered['prior_action_evidence'] == actor
        assert actor['scope'] == 'past_application_feedback_not_current_state_or_math'
    finally:
        journal.db.close()


def test_durable_failure_restore_uses_accepted_graph_and_does_not_rescan_every_frame(tmp_path):
    module, journal, reports, _ = durable_failure_fixture(tmp_path)
    try:
        module.enable_application_failure_retention()
        module.save()
        saved = json.loads(module.path.read_text())
        assert saved['application_failure_memory']['reports'] == [next(iter(reports.values()))]
        # Persisted cache is not authority: recover exact accepted graph values.
        saved['application_failure_memory']['reports'][0]['checks'][0]['quotes'] = ['Forged cache text']
        module.path.write_text(dumps(saved))
        reopened = ExecutionModules(module.memory, journal)
        reopened.enable_application_failure_retention()
        assert reopened.application_failure_memory == module.application_failure_memory
        reopened.memory.snapshot.claims = {}
        reopened.enable_application_failure_retention()
        assert reopened.application_failure_memory == module.application_failure_memory
        assert reopened.effects == module.effects
    finally:
        journal.db.close()


@pytest.mark.parametrize('invalid', ['unknown', 'observed', 'focus', 'no-quote', 'target', 'raw', 'grade', 'other-goal'])
def test_durable_migration_requires_accepted_application_checks_and_exact_binding(tmp_path, invalid):
    module, journal, reports, _ = durable_failure_fixture(tmp_path)
    try:
        report = next(iter(reports.values()))
        if invalid in {'unknown', 'observed'}:
            report['assessment'] = invalid
        elif invalid == 'focus':
            report['checks'][0]['kind'] = 'focus'
        elif invalid == 'no-quote':
            report['checks'][0]['quotes'] = []
        elif invalid == 'target':
            report['target_observation_id'] = 'wrong-post'
        elif invalid == 'raw':
            report['raw_transition_ref'] = '/different/events#wrong-edge'
        elif invalid == 'grade':
            report['grade'] = 'verified'
        else:
            report['module_id'] = 'save'
        module.enable_application_failure_retention()
        assert module.application_failure_memory['reports'] == []
        assert module.actor_prior_action_evidence()['records'] == []
    finally:
        journal.db.close()


def test_durable_reports_are_whole_bounded_and_repeated_literal_failures_keep_first_provenance(tmp_path):
    module, journal, reports, _ = durable_failure_fixture(tmp_path)
    try:
        for index, report in enumerate(reports.values()):
            report.update(assessment='not_observed', checks=[{'kind': 'submission', 'assessment': 'not_observed',
                'quotes': [f'Rejected operation {index % 10}']}])
        module.enable_application_failure_retention()
        retained = module.application_failure_memory
        assert len(retained['reports']) == 8 and retained['reports'] == list(reports.values())[:8]
        assert retained['omitted_reports'] > 0
        actor = module.actor_prior_action_evidence()
        # This fixture changes the accepted graph reports after loading its
        # recent cache; only the retained first eight reflect those failures.
        assert actor['records'][0]['transition_id'] == retained['reports'][-1]['transition_id']
        assert len(dumps(actor).encode()) <= 900
        reduced = module.actor_prior_action_evidence(len(dumps(actor).encode())-1)
        assert reduced['omitted_records'] > actor['omitted_records']
        assert all(row in actor['records'] for row in reduced['records'])
        assert retained['reports'] == list(reports.values())[:8]
        with pytest.raises(ValueError, match='omission metadata'):
            module.actor_prior_action_evidence(1)
    finally:
        journal.db.close()


def test_subgoal_change_rebuilds_only_that_goal_and_restores_earlier_goal_failure(tmp_path):
    module, journal, reports, _ = durable_failure_fixture(tmp_path)
    try:
        module.enable_application_failure_retention()
        original = deepcopy(module.application_failure_memory)
        module.active = 'save'
        module.enable_application_failure_retention()
        assert module.application_failure_memory['module_id'] == 'save'
        assert module.actor_prior_action_evidence()['records'] == []
        module.active = 'import'
        module.enable_application_failure_retention()
        assert module.application_failure_memory == original
        assert module.actor_prior_action_evidence()['records'][0]['transition_id'] == next(iter(reports))
    finally:
        journal.db.close()


def test_new_accepted_application_failure_is_persisted_without_extending_recent_cache(tmp_path):
    module, journal, reports, _ = durable_failure_fixture(tmp_path)
    try:
        module.enable_application_failure_retention()
        identity = list(reports)[-1]
        module.last_effect_record = lambda: {'transition_id': identity, 'module_id': 'import',
            'raw_ref': reports[identity]['raw_transition_ref'], 'error': None}
        module.transition_packet = lambda record: dict(record)
        module.report = lambda *args, **kwargs: None
        check = {**reports[identity], 'assessment': 'not_observed',
            'checks': [{'kind': 'object', 'assessment': 'not_observed', 'quotes': ['No requested object']}]}
        module.record_action_check(check, frame='new-frame')
        assert [row['transition_id'] for row in module.application_failure_memory['reports']] == [next(iter(reports)), identity]
        saved = json.loads(module.path.read_text())
        assert saved['application_failure_memory'] == module.application_failure_memory
        assert len(module.effects) == len(module.effect_order) == 64
        module.record_action_check({**check, 'assessment': 'observed'}, frame='later-frame')
        assert saved['application_failure_memory'] == module.application_failure_memory
    finally:
        journal.db.close()


def test_recent_route_error_outweighs_older_durable_rejection_in_small_briefs(tmp_path):
    module, journal, reports, _ = durable_failure_fixture(tmp_path)
    try:
        oldest, latest = list(reports)[0], list(reports)[-1]
        reports[latest].update(assessment='not_observed', checks=[
            {'kind': 'submission', 'assessment': 'not_observed', 'quotes': ['Selected resource could not be opened']},
            {'kind': 'object', 'assessment': 'not_observed', 'quotes': ['Selected resource could not be opened']}])
        module.effects[latest] = deepcopy(reports[latest])
        original = deepcopy([module.effects, module.recent, reports])
        module.enable_application_failure_retention()
        retained = deepcopy(module.application_failure_memory)
        for method, cap in ((module.actor_prior_action_evidence, 900), (module.prior_action_evidence, 1600)):
            full = method(10000)
            latest_row = full['records'][0]
            assert latest_row['transition_id'] == latest
            assert latest_row['original_feedback_sha256'] == hashlib.sha256(dumps(reports[latest]).encode()).hexdigest()
            assert latest_row['raw_transition_ref'] == reports[latest]['raw_transition_ref']
            bound = len(dumps({**full, 'records': [latest_row], 'omitted_records': len(full['records'])-1}).encode())
            assert bound <= cap
            short = method(bound)
            assert short['records'] == [latest_row] and short['omitted_records'] == len(full['records'])-1
            assert oldest in [row['transition_id'] for row in full['records']]
        assert module.application_failure_memory == retained
        assert [module.effects, module.recent, reports] == original
    finally:
        journal.db.close()


def test_failure_brief_order_survives_sorted_json_reload_and_dialog_dismissal(tmp_path):
    module, journal, reports, _ = durable_failure_fixture(tmp_path)
    try:
        latest = list(reports)[-2]
        reports[latest].update(assessment='not_observed', checks=[
            {'kind': 'object', 'assessment': 'not_observed', 'quotes': ['No imported object']}])
        module.effects[latest] = deepcopy(reports[latest])
        module.enable_application_failure_retention()
        expected = module.actor_prior_action_evidence()
        assert expected['records'][0]['transition_id'] == latest
        module.save()
        reopened = ExecutionModules(module.memory, journal)
        reopened.verification_intent = module.verification_intent
        reopened.enable_application_failure_retention()
        assert reopened.actor_prior_action_evidence() == expected
        assert reopened.prior_action_evidence()['records'][0]['transition_id'] == latest
        assert reopened.application_failure_memory == module.application_failure_memory
    finally:
        journal.db.close()


def test_priority_projection_skips_unknown_focus_and_other_goal_checks(tmp_path):
    module, journal, reports, _ = durable_failure_fixture(tmp_path)
    try:
        module.enable_application_failure_retention()
        oldest = next(iter(reports))
        # Recent records exist and have later sequences, but only the accepted
        # application response in this subgoal qualifies as route evidence.
        for index, invalid in enumerate(('unknown', 'focus', 'other-goal')):
            identity = list(reports)[-1-index]
            item = module.effects[identity]
            item.update(assessment='not_observed', checks=[
                {'kind': 'submission', 'assessment': 'not_observed', 'quotes': ['Unconfirmed']}])
            if invalid == 'unknown':
                item['assessment'] = 'unknown'
            elif invalid == 'focus':
                item['checks'][0]['kind'] = 'focus'
            else:
                item['module_id'] = 'other'
        assert module.actor_prior_action_evidence()['records'][0]['transition_id'] == oldest
        assert module.application_failure_memory['reports'][0] == reports[oldest]
    finally:
        journal.db.close()


def test_opt_in_failure_priority_requires_real_sequence_and_preserves_legacy_order(tmp_path):
    module, journal, reports, _ = durable_failure_fixture(tmp_path)
    try:
        module.enable_application_failure_retention()
        identity = next(iter(reports))
        journal.db.execute('DELETE FROM events WHERE id=?', (identity,))
        with pytest.raises(ValueError, match='original operation sequence'):
            module.actor_prior_action_evidence()
        legacy = prior_failure_module()
        assert [row['transition_id'] for row in legacy.actor_prior_action_evidence()['records']] == ['submit', 'dismiss']
    finally:
        journal.db.close()


def test_planner_separates_explicit_goal_targets_from_visible_math_hypotheses():
    from ui_kobe.osworld.taskviews_feedback import validate_planner_report
    args = {'visible_texts': ['Empty Algebra panel', 'Input:'],
            'original_task': 'Use GeoGebra to create P1 = (1, 2), then save.',
            'string_list': lambda values: isinstance(values, list) and all(isinstance(v, str) for v in values)}
    bad = {'advice': 'Enter the requested point', 'needed_evidence': [], 'math_hypotheses': [
        {'statement': 'P1 must be at (1, 2)', 'basis': ['create P1 = (1, 2)'], 'status': 'hypothesis'}]}
    with pytest.raises(ValueError, match='original_task_quote_matches') as error:
        validate_planner_report(bad, **args)
    assert 'candidate_index' in str(error.value) and len(str(error.value).encode()) < 6000
    good = {'advice': bad['advice'], 'needed_evidence': [], 'math_hypotheses': [],
            'goal_targets': [{'quote': 'create P1 = (1, 2)', 'status': 'requested'}]}
    validate_planner_report(good, **args)
    good['goal_targets'][0]['quote'] = 'create P1 = (517, 983)'
    with pytest.raises(ValueError, match='exact original_task'):
        validate_planner_report(good, **args)
    good['goal_targets'][0] = {'quote': 'create P1 = (1, 2)', 'status': 'observed'}
    with pytest.raises(ValueError, match='never a visible success'):
        validate_planner_report(good, **args)


def test_planner_goal_feedback_identifies_only_invalid_original_quote_without_rewriting():
    from ui_kobe.osworld.taskviews_feedback import validate_planner_report
    task = 'Open `sample.png` on the desktop. Import at default scale.'
    args = {'visible_texts': ['Open', 'File name:'], 'original_task': task,
            'string_list': lambda value: isinstance(value, list)}
    bad = {'advice': 'Observe the file field focus.', 'needed_evidence': ['Open'],
           'goal_targets': [{'quote': 'Import at default scale', 'status': 'requested'},
                            {'quote': 'sample.png on the desktop', 'status': 'requested'}]}
    original = deepcopy(bad)
    with pytest.raises(ValueError) as error:
        validate_planner_report(bad, **args)
    feedback = json.loads(str(error.value).split('claim: ', 1)[1])
    rejected = feedback['invalid_goal_targets']
    assert len(rejected) == 1 and rejected[0]['candidate_index'] == 1
    assert rejected[0]['reasons'] == ['quote_not_exact_original_task_substring']
    assert rejected[0]['provided_target'] == bad['goal_targets'][1]
    assert 'optional' in feedback['repair'] and 'backticks' in feedback['repair']
    assert bad == original
    for candidate in ({k: v for k, v in bad.items() if k != 'goal_targets'},
                      {**bad, 'goal_targets': [{'quote': '`sample.png` on the desktop',
                                               'status': 'requested'}]}):
        validate_planner_report(candidate, **args)


@pytest.mark.parametrize('target,reason', [
    ({'quote': 'Save', 'status': 'observed'}, 'status_must_be_requested'),
    ({'quote': 'Save', 'status': 'requested', 'source': 'image'}, 'fields_must_be_exactly_quote_status'),
    ({'status': 'requested'}, 'quote_must_be_string'),
    (['Save'], 'target_must_be_object')])
def test_planner_goal_feedback_preserves_strict_schema_and_exact_sources(target, reason):
    from ui_kobe.osworld.taskviews_feedback import validate_planner_report
    report = {'advice': 'Check dialog.', 'needed_evidence': [], 'goal_targets': [target]}
    with pytest.raises(ValueError) as error:
        validate_planner_report(report, visible_texts=['Save'], original_task='Save the document.',
                                string_list=lambda value: isinstance(value, list))
    payload = json.loads(str(error.value).split('claim: ', 1)[1])
    assert reason in payload['invalid_goal_targets'][0]['reasons']
    assert payload['invalid_goal_targets'][0]['provided_target'] == target


def test_planner_goal_error_wholly_omits_large_malformed_target_with_full_digest():
    from ui_kobe.osworld.taskviews_feedback import validate_planner_report
    target = {'quote': 'Save', 'status': 'requested', 'extra': '秘密' * 350}
    encoded = dumps(target).encode()
    with pytest.raises(ValueError) as error:
        validate_planner_report({'advice': '', 'needed_evidence': [], 'goal_targets': [target]},
                                visible_texts=[], original_task='Save',
                                string_list=lambda value: isinstance(value, list))
    row = json.loads(str(error.value).split('claim: ', 1)[1])['invalid_goal_targets'][0]
    assert row['provided_target'] is None and row['whole_target_omitted'] is True
    assert row['original_target_bytes'] == len(encoded)
    assert row['original_target_sha256'] == hashlib.sha256(encoded).hexdigest()
    assert len(str(error.value).encode()) < 6000 and '秘密' not in str(error.value)


def test_repeated_unconfirmed_strategy_detects_interleaved_input_submit_cycle():
    from types import SimpleNamespace
    module = ExecutionModules.__new__(ExecutionModules)
    module.recent = [{'transition_id': 'c1', 'module_id': 'input', 'action_fingerprint': 'click'},
                     {'transition_id': 't1', 'module_id': 'input', 'action_fingerprint': 'type'},
                     {'transition_id': 'k1', 'module_id': 'input', 'action_fingerprint': 'submit'},
                     {'transition_id': 'c2', 'module_id': 'input', 'action_fingerprint': 'click'}]
    module.effects = {'c1': {'assessment': 'not_observed'}, 'c2': {'assessment': 'unknown'}}
    module.last_action = lambda: dict(module.recent[-1])
    assert module.feedback()['repetition_count'] == 2 and module.feedback()['strategy_review']
    module.effects['c1'] = {'assessment': 'observed'}
    assert module.feedback()['repetition_count'] == 1 and not module.feedback()['strategy_review']
    module.memory = SimpleNamespace()


def pointer_history(parameters, assessments=None):
    """Old geometry-free hashes must not merge different original pointers."""
    from types import SimpleNamespace
    module = ExecutionModules.__new__(ExecutionModules)
    module.active = 'stable-subgoal'
    module.recent = [{'transition_id': f'edge-{i}', 'module_id': module.active,
                      'action_fingerprint': 'old-geometry-free-click'} for i in range(len(parameters))]
    edges = {row['transition_id']: {'tool': {'arguments': value}}
             for row, value in zip(module.recent, parameters)}
    module.journal = SimpleNamespace(closed=False)
    module.event = lambda identity: deepcopy(edges[identity])
    module.effects = {row['transition_id']: {'assessment': (assessments or ['unknown'] * len(parameters))[i],
        'state_comparison': {'shared_field_keys': ['focus', 'input'], 'changed_field_keys': []}}
        for i, row in enumerate(module.recent)}
    module.last_action = lambda: deepcopy(module.recent[-1])
    return module


def destination_cycle(tmp_path, *, first_prose='Open the requested menu', batch=False):
    memory = TaskMemory('task', tmp_path / 'memory')
    memory.initialize('Open the requested menu')
    journal = TransitionJournal(tmp_path / 'events', task_id='task', run_id='run',
        contract=CUAContract(model_screen_width=64, model_screen_height=48))
    module = ExecutionModules(memory, journal)
    module.compare_state_v10 = module.intent_verification_v12 = module.returned_page_intent_v12 = True
    click = {'action': 'left_click', 'coordinate': [3, 4]}
    recovery = {'action': 'key', 'keys': ['alt', 'tab']}
    failed = []
    for step, parameters in enumerate([click, recovery, click, recovery], 1):
        is_click = parameters == click
        before = 'Editor' if is_click else 'Other application'
        after = 'Other application' if is_click else 'Editor'
        journal.begin('Open the requested menu', image(), step=step)
        journal.annotate(journal.current['id'], logical_page='editor' if is_click else 'other',
            state_schema={'active_window': before, 'menu': 'closed'}, evidence_ref=f'before-{step}.png')
        commands = ['operation', 'capture'] if batch and step == 1 else ['operation']
        journal.decide(first_prose if step == 1 else 'Open menu' if is_click else 'Return to the editor',
            commands, step=step, tools=[{'id': f'tool-{step}', 'arguments': parameters, 'command_indices': [0]}])
        edge = journal.result('operation', step=step, observation=image(), receipts=[{'returncode': 0}])
        module.sync()
        assessment = 'not_observed' if is_click else 'observed'
        check = {'transition_id': edge['id'], 'target_observation_id': edge['target'], 'frame_id': str(step),
            'assessment': assessment, 'checks': [
                {'kind': 'focus' if is_click else 'state', 'assessment': assessment, 'quotes': [after]},
                {'kind': 'intent', 'assessment': assessment, 'quotes': [after], 'state_keys': ['active_window']}]}
        state = {'page_id': 'other' if is_click else 'editor', 'fields': {'active_window': after, 'menu': 'closed'}}
        module.validate_action_check(check, frame=str(step), visible_texts=[after], current_state=state)
        module.record_action_check(check, frame=str(step), current_state=state)
        journal.annotate(journal.current['id'], logical_page=state['page_id'], state_schema=state['fields'],
            evidence_ref=f'after-{step}.png')
        module.sync()
        if is_click:
            failed.append(edge['id'])
    return memory, journal, module, click, failed


def focus_review_step(module, journal, step, parameters, *, before='Editor', after='Editor'):
    journal.begin('Focus the input control', image(), step=step)
    before_fields = {'window': before, 'input': 'original text', 'focus': None}
    journal.annotate(journal.current['id'], logical_page=before, state_schema=before_fields,
                     evidence_ref=f'before-{step}.png')
    journal.decide('Focus the input' if before == after else 'Switch windows', ['operation'],
                   step=step, tools=[{'id': f'tool-{step}', 'arguments': parameters, 'command_indices': [0]}])
    edge = journal.result('operation', step=step, observation=image(), receipts=[{'returncode': 0}])
    module.sync()
    assessment = 'unknown' if before == after else 'observed'
    check = {'transition_id': edge['id'], 'target_observation_id': edge['target'], 'frame_id': str(step),
             'assessment': assessment, 'checks': [
                 {'kind': 'focus' if before == after else 'state', 'assessment': assessment, 'quotes': [after]},
                 {'kind': 'intent', 'assessment': assessment, 'quotes': [after],
                  'state_keys': ['focus'] if before == after else ['window']}]}
    expected = module.last_action()['expected_change']['kind']
    if expected not in {item['kind'] for item in check['checks']}:
        check['checks'].append({'kind': expected, 'assessment': assessment, 'quotes': [after]})
    state = {'page_id': after, 'fields': {**before_fields, 'window': after}}
    module.validate_action_check(check, frame=str(step), visible_texts=[after], current_state=state)
    module.record_action_check(check, frame=str(step), current_state=state)
    journal.annotate(journal.current['id'], logical_page=after, state_schema=state['fields'],
                     evidence_ref=f'after-{step}.png')
    module.sync()
    return edge['id']


def focus_review_cycle(tmp_path):
    memory = TaskMemory('task', tmp_path/'memory')
    memory.initialize('Focus the input control')
    journal = TransitionJournal(tmp_path/'events', task_id='task', run_id='run',
                                contract=CUAContract(model_screen_width=64, model_screen_height=48))
    module = ExecutionModules(memory, journal)
    module.compare_state_v10 = module.intent_verification_v12 = module.subgoal_state_review_v12 = True
    module.returned_page_pointer_review_v12 = True
    ids = [focus_review_step(module, journal, step, {'action': action, 'coordinate': [3, 4]})
           for step, action in enumerate(['left_click', 'triple_click', 'double_click'], 1)]
    keys = {'action': 'key', 'keys': ['alt', 'tab']}
    focus_review_step(module, journal, 4, keys, after='Other')
    focus_review_step(module, journal, 5, keys, before='Other')
    return memory, journal, module, ids


def test_unconfirmed_focus_survives_window_return_without_merging_click_commands(tmp_path):
    memory, journal, module, ids = focus_review_cycle(tmp_path)
    try:
        original = deepcopy([module.recent, module.effects])
        assert module._stalled_actions({'left_click', 'double_click'}) == []
        review = module.unconfirmed_state_review()
        assert review['reason'] == 'same_source_point_unconfirmed_focus'
        assert review['transition_ids'] == list(reversed(ids))
        assert review['comparison_field_keys'] == ['input', 'window']
        assert review['grade'] == 'model_proposal' and module.feedback()['strategy_review']
        assert [module.recent, module.effects] == original
        assert [module.original_parameters(row)['action'] for row in module.recent[:3]] == [
            'left_click', 'triple_click', 'double_click']
        restored = ExecutionModules(memory, journal)
        restored.subgoal_state_review_v12 = restored.returned_page_pointer_review_v12 = True
        restored.intent_verification_v12 = True
        assert restored.unconfirmed_state_review() == review
        restored.returned_page_pointer_review_v12 = False
        assert restored.unconfirmed_state_review() is None
    finally:
        journal.close()
        memory.close()


@pytest.mark.parametrize('mode', ['other-page', 'different-state', 'unknown-state', 'changed-geometry',
                                'no-focus-check', 'observed-focus', 'changed-effect', 'other-goal',
                                'omitted-intent', 'different-position', 'missing-position'])
def test_returned_focus_review_requires_original_comparable_unconfirmed_evidence(tmp_path, mode):
    memory, journal, module, ids = focus_review_cycle(tmp_path)
    try:
        if mode in {'other-page', 'different-state', 'unknown-state', 'changed-geometry'}:
            if mode == 'changed-geometry':
                journal.contract = CUAContract(model_screen_width=128, model_screen_height=48)
            journal.begin('Focus input', image(), step=6)
            journal.annotate(journal.current['id'], logical_page='Other' if mode == 'other-page' else 'Editor',
                state_schema={'window': 'Editor', 'input': None if mode == 'unknown-state' else
                              'changed text' if mode == 'different-state' else 'original text'},
                evidence_ref='latest.png')
        elif mode == 'no-focus-check':
            module.effects[ids[-1]]['checks'][0]['kind'] = 'state'
        elif mode == 'observed-focus':
            module.effects[ids[-1]]['checks'][0]['assessment'] = 'observed'
        elif mode == 'changed-effect':
            module.effects[ids[-1]]['state_comparison']['changed_field_keys'] = ['input']
        elif mode == 'other-goal':
            module.recent[2]['module_id'] = 'other-goal'
        elif mode == 'omitted-intent':
            original = module.verification_intent
            module.verification_intent = lambda row: {**original(row), 'text_omitted': True}
        else:
            original = module.original_parameters
            module.original_parameters = lambda row: {**original(row), 'coordinate':
                None if mode == 'missing-position' else [10, 12]} \
                if row['transition_id'] == ids[-1] else original(row)
        assert module.unconfirmed_state_review() is None
    finally:
        journal.close()
        memory.close()


def test_returned_focus_review_requires_three_new_attempts_after_completed_review(tmp_path):
    memory, journal, module, _ = focus_review_cycle(tmp_path)
    try:
        module.record_uncertainty_review(module.unconfirmed_state_review())
        assert module.unconfirmed_state_review() is None
        for step, action in enumerate(['left_click', 'triple_click', 'double_click'], 6):
            focus_review_step(module, journal, step, {'action': action, 'coordinate': [3, 4]})
            if step < 8:
                assert module.unconfirmed_state_review() is None
        assert module.unconfirmed_state_review()['unconfirmed_operation_count'] == 3
    finally:
        journal.close()
        memory.close()


def test_return_to_source_page_preserves_failed_intention_without_coordinate_rewrite(tmp_path):
    memory, journal, module, click, failed = destination_cycle(tmp_path)
    try:
        original = deepcopy([module.recent, module.effects])
        assert module._stalled_actions({'left_click'}) == []  # The old recovery boundary loses both failures.
        rows = module.stalled_pointer_actions()
        assert rows[0]['parameters'] == click and set(rows[0]['transition_ids']) == set(failed)
        assert rows[0]['reason'] == 'failed_intent_after_return_to_source_page'
        assert rows[0]['matched_intent_state_keys'] == ['active_window']
        assert module.stalled_keyboard_actions() == []
        assert [module.recent, module.effects] == original
        # A checkpoint reload preserves the original evidence, with explicit opt-in at the caller.
        restored = ExecutionModules(memory, journal)
        restored.intent_verification_v12 = restored.returned_page_intent_v12 = True
        assert restored.stalled_pointer_actions() == rows
        restored.returned_page_intent_v12 = False
        assert restored.stalled_pointer_actions() == []
    finally:
        journal.close()
        memory.close()


@pytest.mark.parametrize('mode', ['other-page', 'unknown-state', 'changed-state', 'changed-geometry',
                                'unknown-intent', 'missing-quote', 'other-subgoal', 'later-success',
                                'incomparable-intent-fields'])
def test_destination_cycle_warning_requires_matching_evidence_and_releases_after_success(tmp_path, mode):
    memory, journal, module, _, failed = destination_cycle(tmp_path)
    try:
        if mode in {'other-page', 'unknown-state', 'changed-state', 'changed-geometry'}:
            if mode == 'changed-geometry':
                journal.contract = CUAContract(model_screen_width=128, model_screen_height=48)
            journal.begin('Open the requested menu', image(), step=5)
            journal.annotate(journal.current['id'], logical_page='other' if mode == 'other-page' else 'editor',
                state_schema={'active_window': None if mode == 'unknown-state' else
                              'Different editor' if mode == 'changed-state' else 'Editor'}, evidence_ref='current.png')
        elif mode == 'other-subgoal':
            module.recent[-2]['module_id'] = 'other-goal'
        else:
            intent = module.effects[failed[-1]]['checks'][-1]
            if mode == 'unknown-intent':
                intent['assessment'] = 'unknown'
            elif mode == 'missing-quote':
                intent['quotes'] = []
            elif mode == 'incomparable-intent-fields':
                intent['state_keys'] = ['menu']
            else:
                intent['assessment'] = 'observed'
        assert module.stalled_pointer_actions() == []
    finally:
        journal.close()
        memory.close()


@pytest.mark.parametrize('prose,batch', [('x' * 1201, False), ('Open the requested menu', True)])
def test_destination_cycle_does_not_attribute_omitted_or_batch_prose_to_one_command(tmp_path, prose, batch):
    memory, journal, module, _, _ = destination_cycle(tmp_path, first_prose=prose, batch=batch)
    try:
        assert module.stalled_pointer_actions() == []
    finally:
        journal.close()
        memory.close()


def test_alternating_positions_count_exact_original_parameters_and_retain_both_failures():
    a = {'action': 'left_click', 'coordinate': [239, 228]}
    b = {'action': 'left_click', 'coordinate': [891, 45]}
    module = pointer_history([a, b, a, b])
    original = deepcopy([module.recent, module.effects])
    assert module.feedback()['repetition_count'] == 2
    stalled = module.stalled_pointer_actions()
    assert {tuple(row['parameters']['coordinate']) for row in stalled} == {(239, 228), (891, 45)}
    assert all(len(row['transition_ids']) == 2 for row in stalled)
    assert [module.recent, module.effects] == original
    module.recent[-1]['module_id'] = 'different-subgoal'
    assert len(module.stalled_pointer_actions()) == 1


@pytest.mark.parametrize('assessment,shared,changed,expected', [
    ('unknown', [], [], 0), ('unknown', ['focus'], [], 1),
    ('not_observed', [], [], 1), ('observed', ['focus'], [], 0),
    ('unknown', ['focus'], ['focus'], 0)])
def test_pointer_guard_requires_actual_effect_evidence_and_clears_after_state_change(
        assessment, shared, changed, expected):
    point = {'action': 'left_click', 'coordinate': [239, 228]}
    module = pointer_history([point, point], [assessment, assessment])
    for effect in module.effects.values():
        effect['state_comparison'] = {'shared_field_keys': shared, 'changed_field_keys': changed}
    assert len(module.stalled_pointer_actions()) == expected


def test_confirmed_intervening_change_clears_older_pointer_cycle():
    point = {'action': 'left_click', 'coordinate': [239, 228]}
    module = pointer_history([point, point, {'action': 'key', 'keys': ['alt', 'f']}, point])
    module.effects['edge-2']['state_comparison']['changed_field_keys'] = ['menu']
    assert module.stalled_pointer_actions() == []


def varying_state_history():
    parameters = [{'action': 'left_click', 'coordinate': [100 + i * 30, 80]} for i in range(6)]
    module = pointer_history(parameters)
    module.subgoal_state_review_v12 = True
    module.uncertainty_reviews = {}
    module.save = lambda: None
    return module


@pytest.mark.parametrize('assessment', ['unknown', 'not_observed'])
def test_native_triple_click_has_exact_existing_pointer_guard_when_opted_in(assessment):
    from ui_kobe.osworld.pointer_grounding import validate_pointer_strategy
    from ui_kobe.api.kimi_stream import StreamProtocolError
    parameters = {'action': 'triple_click', 'coordinate': [20, 30]}
    module = pointer_history([parameters] * 3, [assessment] * 3)
    original = deepcopy([module.recent, module.effects])
    assert module.stalled_pointer_actions() == []
    module.returned_page_pointer_review_v12 = True
    stalled = module.stalled_pointer_actions()
    assert stalled[0]['parameters'] == parameters
    assert stalled[0]['transition_ids'] == ['edge-2', 'edge-1', 'edge-0']
    assert stalled[0]['assessments'] == [assessment] * 3
    with pytest.raises(StreamProtocolError) as caught:
        validate_pointer_strategy([parameters], stalled, frame_id='current', keyboard_recovery=True)
    assert caught.value.code == 'repeated_unconfirmed_pointer'
    assert [module.recent, module.effects] == original


@pytest.mark.parametrize('boundary', ['observed', 'changed', 'uncomparable'])
def test_native_triple_guard_keeps_existing_effect_boundaries(boundary):
    parameters = {'action': 'triple_click', 'coordinate': [20, 30]}
    module = pointer_history([parameters] * 3)
    module.returned_page_pointer_review_v12 = True
    if boundary == 'observed':
        module.effects['edge-2']['assessment'] = 'observed'
    elif boundary == 'changed':
        module.effects['edge-2']['state_comparison']['changed_field_keys'] = ['input']
    else:
        for report in module.effects.values():
            report['state_comparison']['shared_field_keys'] = []
    assert module.stalled_pointer_actions() == []


def test_native_triple_groups_do_not_alias_other_click_counts_or_positions():
    from ui_kobe.osworld.pointer_grounding import validate_pointer_strategy
    first = {'action': 'triple_click', 'coordinate': [20, 30]}
    second = {'action': 'triple_click', 'coordinate': [50, 60]}
    module = pointer_history([first, first, second])
    module.returned_page_pointer_review_v12 = True
    stalled = module.stalled_pointer_actions()
    assert len(stalled) == 1 and stalled[0]['parameters'] == first
    for action in [second, {'action': 'left_click', 'coordinate': [20, 30]},
                   {'action': 'double_click', 'coordinate': [20, 30]}, {'action': 'key', 'keys': ['tab']}]:
        validate_pointer_strategy([action], stalled, frame_id='current', keyboard_recovery=True)


def test_native_triple_is_a_real_interaction_in_existing_continuous_review():
    module = varying_state_history()
    module.recent = module.recent[:3]
    prior = module.event
    module.event = lambda identity: {'tool': {'arguments': {'action': 'triple_click', 'coordinate': [20, 30]}}}
    assert module.unconfirmed_state_review() is None
    module.returned_page_pointer_review_v12 = True
    review = module.unconfirmed_state_review()
    assert review['transition_ids'] == ['edge-2', 'edge-1', 'edge-0']
    assert review['unconfirmed_operation_count'] == 3 and 'reason' not in review
    module.event = prior


def test_varying_parameters_request_state_review_without_merging_exact_pointer_guard():
    from ui_kobe.osworld.taskviews_feedback import feedback_analysis_triggers
    module = varying_state_history()
    module.subgoals, module.selected_needs, module.page_id = {'goal': {}}, [{'consumer': 'executor'}], 'editor'
    original = deepcopy([module.recent, module.effects])
    feedback = module.feedback()
    assert feedback['repetition_count'] == 1 and feedback['strategy_review']
    assert feedback['state_review']['unconfirmed_operation_count'] == 6
    assert feedback['state_review']['comparison_field_keys'] == ['focus', 'input']
    assert feedback['state_review']['transition_ids'] == [f'edge-{i}' for i in reversed(range(6))]
    assert feedback['state_review']['grade'] == 'model_proposal'
    assert module.stalled_pointer_actions() == []  # Exact-parameter execution guard is unchanged.
    raw = {'ui_state': {'page_id': 'editor'}, 'subgoal_review': None}
    assert feedback_analysis_triggers(module, raw, feedback, False) == ['consecutive_unconfirmed_state']
    assert [module.recent, module.effects] == original
    module.subgoal_state_review_v12 = False
    assert not module.feedback()['strategy_review'] and 'state_review' not in module.feedback()
    assert feedback['state_review']['module_id'] == module.active


@pytest.mark.parametrize('boundary', ['changed', 'observed', 'uncomparable', 'clock', 'subgoal'])
def test_state_review_requires_three_unconfirmed_operations_in_comparable_subgoal(boundary):
    module = varying_state_history()
    module.recent = module.recent[:3]
    if boundary == 'changed':
        module.effects['edge-1']['state_comparison']['changed_field_keys'] = ['input']
    elif boundary == 'observed':
        module.effects['edge-1']['assessment'] = 'observed'
    elif boundary == 'uncomparable':
        module.effects['edge-1']['state_comparison']['shared_field_keys'] = []
    elif boundary == 'clock':
        for effect in module.effects.values():
            effect['state_comparison']['shared_field_keys'] = ['clock']
    else:
        module.recent[1]['module_id'] = 'other-subgoal'
    assert module.unconfirmed_state_review() is None
    assert not module.feedback()['strategy_review']


def test_completed_state_review_cooldown_requires_three_new_operations_not_each_frame():
    module = varying_state_history()
    all_records = deepcopy(module.recent)
    module.recent = all_records[:3]
    review = module.unconfirmed_state_review()
    module.record_uncertainty_review(review)
    assert module.uncertainty_reviews == {module.active: 'edge-2'}
    assert module.unconfirmed_state_review() is None
    for count in (4, 5):
        module.recent = all_records[:count]
        assert module.unconfirmed_state_review() is None
    module.recent = all_records
    assert module.unconfirmed_state_review()['transition_ids'] == ['edge-5', 'edge-4', 'edge-3']


def test_state_review_captures_do_not_count_as_failed_actions_or_replace_review_marker():
    module = varying_state_history()
    module.recent = module.recent[:2]
    capture = {'transition_id': 'capture', 'module_id': module.active}
    prior_event = module.event
    module.event = lambda identity: ({'tool': {'arguments': {'action': 'screenshot'}}}
                                     if identity == 'capture' else prior_event(identity))
    module.recent.append(capture)
    module.effects['capture'] = {'assessment': 'unknown',
        'state_comparison': {'shared_field_keys': ['focus', 'input'], 'changed_field_keys': []}}
    assert module.unconfirmed_state_review() is None
    assert module.effects['capture']['assessment'] == 'unknown'


def test_state_review_checkpoint_roundtrip_preserves_marker_and_legacy_missing_field(tmp_path):
    memory, log, module, _ = intent_operation(tmp_path, 'Focus the editor')
    try:
        assert 'uncertainty_reviews' not in json.loads(module.path.read_text())
        module.record_uncertainty_review({'module_id': 'stable', 'transition_ids': ['original-edge']})
        restored = ExecutionModules(memory, log)
        assert restored.uncertainty_reviews == {'stable': 'original-edge'}
        assert json.loads(module.path.read_text())['uncertainty_reviews'] == restored.uncertainty_reviews
    finally:
        log.close()


def test_nullable_optional_review_completes_full_offline_flow_without_local_read_exception(tmp_path):
    result = run_fixture(tmp_path / 'nullable-review', null_subgoal_review=True)
    assert result['terminal'] and not result['paused'] and result['fixture_score'] == 1
    assert result['official_score'] is None and result['all_actor_packets_delivered']


def test_current_recovery_advice_precedes_optional_graph_and_is_not_promoted_to_command():
    from ui_kobe.osworld.taskviews_feedback import _admit
    module, _ = repeated_warning_module()
    protected = {'last_action_feedback': module.actor_feedback(), 'next_strategy': {
        'subgoal': {'id': 'save', 'label': 'Save requested document', 'dependencies': []},
        'advice': 'Re-observe the Name field before entering text; confirm the visible filename.',
        'frame_id': 'current', 'grade': 'model_proposal'}}
    packet = _admit(protected, [('assigned_views', 'x' * 6000), ('advisers', 'x' * 3000)], 2600)
    assert packet['next_strategy'] == protected['next_strategy']
    assert packet['last_action_feedback'] == protected['last_action_feedback']
    assert packet['context_gaps'] == ['budget_omitted:assigned_views', 'budget_omitted:advisers']


def repeated_warning_module(assessment='unknown', parameters=None, quotes=None):
    module = ExecutionModules.__new__(ExecutionModules)
    module.recent = [{'transition_id': 'edge-' + str(i), 'module_id': 'input',
                      'action_fingerprint': 'same-exact-parameters'} for i in range(4)]
    module.effects = {row['transition_id']: {'assessment': assessment} for row in module.recent}
    last = {**module.recent[-1], 'target': 'post-4', 'raw_ref': '/immutable/events.sqlite#edge-3',
            'executed_tool_input': {'tool_call_id': 'original-tool-4',
                'parameters': parameters or {'action': 'left_click', 'coordinate': [504, 987]}},
            'expected_change': {'kind': 'focus'}, 'action_check': {'assessment': assessment,
                'checks': [{'kind': 'focus', 'assessment': assessment, 'quotes': quotes or []}]}}
    module.last_action = lambda: deepcopy(last)
    return module, last


def test_protected_warning_retains_actual_repetition_count_and_parameters():
    module, last = repeated_warning_module()
    original = deepcopy(last)
    warning = module.actor_feedback()
    assert warning['unconfirmed_repetition_count'] == 4 and warning['strategy_review']
    assert warning['original_parameters'] == {'action': 'left_click', 'coordinate': [504, 987]}
    assert warning['assessment'] == 'unknown' and warning['expected_change'] == 'focus'
    assert warning['tool_call_id'] == 'original-tool-4' and warning['raw_transition_ref'].endswith('#edge-3')
    assert warning['grade'] == 'model_proposal' and 'current image' in warning['decision_guidance']
    assert last == original


def test_protected_warning_does_not_promote_receipt_or_unknown_to_observed():
    module, _ = repeated_warning_module('not_observed', quotes=['Input is empty'])
    warning = module.actor_feedback()
    assert warning['assessment'] == 'not_observed' and warning['checks'][0]['quotes'] == ['Input is empty']
    module.effects['edge-3'] = {'assessment': 'observed'}
    module.last_action = lambda: {**repeated_warning_module('observed')[1]}
    warning = module.actor_feedback()
    assert warning['unconfirmed_repetition_count'] == 0 and not warning['strategy_review']
    assert warning['assessment'] == 'observed' and warning['grade'] == 'model_proposal'


def test_protected_warning_keeps_whole_quotes_and_raw_large_parameter_reference():
    module, _ = repeated_warning_module(parameters={'complete_parameters_ref': '/immutable/full-type-input'},
        quotes=['Full visible quote ' + 'a' * 200] * 4)
    warning = module.actor_feedback()
    assert warning['original_parameters']['complete_parameters_ref'] == '/immutable/full-type-input'
    assert warning['checks'][0]['quotes'] == ['Full visible quote ' + 'a' * 200]
    assert len(dumps(warning).encode()) <= 1800


def test_optional_long_advice_cannot_evict_protected_warning():
    from ui_kobe.osworld.taskviews_feedback import _admit
    module, _ = repeated_warning_module()
    warning = module.actor_feedback()
    base = {'last_action_feedback': warning, 'current_frame_id': 'current'}
    packet = _admit(base, [('advisers', {'planner': 'x' * 4000}), ('views', ['y' * 4000])], 1500)
    assert packet['last_action_feedback'] == warning
    assert set(packet['context_gaps']) == {'budget_omitted:advisers', 'budget_omitted:views'}


def test_no_previous_dispatch_has_no_protected_action_warning():
    module = ExecutionModules.__new__(ExecutionModules)
    module.last_action = lambda: None
    assert module.actor_feedback() is None


def test_optional_field_cannot_consume_later_omission_report_reserve():
    from ui_kobe.osworld.taskviews_feedback import _admit
    base = {'last_action_feedback': {'transition_id': 'original-edge',
        'assessment': 'not_observed', 'raw_transition_ref': '/immutable/edge'}}
    optional = [('visible', 'v' * 200), ('advisers', 'a' * 4000)]
    # The old loop admitted visible exactly at the boundary, then overflowed
    # when it added the required advisers omission after rejecting that value.
    limit = len(dumps({**base, 'context_gaps': [], 'visible': optional[0][1]}).encode())
    packet = _admit(base, optional, limit)
    assert packet['last_action_feedback'] == base['last_action_feedback']
    assert packet['context_gaps'] == ['budget_omitted:visible', 'budget_omitted:advisers']
    assert len(dumps(packet).encode()) <= limit
    assert base.keys() == {'last_action_feedback'}


def test_admission_reserves_utf8_gap_names_and_json_escaping():
    from ui_kobe.osworld.taskviews_feedback import _admit
    base = {'last_action_feedback': {'assessment': 'unknown', 'quote': '输入栏为空'}}
    optional = [('中文字段', '\\"' * 500), ('advisers', 'x' * 5000)]
    limit = len(dumps({**base, 'context_gaps': ['budget_omitted:' + k for k, _ in optional]}).encode())
    packet = _admit(base, optional, limit)
    assert len(dumps(packet).encode()) == limit
    assert packet['last_action_feedback'] == base['last_action_feedback']
    assert packet['context_gaps'] == ['budget_omitted:中文字段', 'budget_omitted:advisers']


def test_omission_envelope_failure_never_deletes_protected_feedback():
    from ui_kobe.osworld.taskviews_feedback import _admit
    base = {'last_action_feedback': {'assessment': 'not_observed', 'transition_id': 'original'}}
    original = deepcopy(base)
    limit = len(dumps({**base, 'context_gaps': []}).encode())
    with pytest.raises(ValueError, match='Protected current-action evidence and omission metadata'):
        _admit(base, [('advisers', 'x' * 4000)], limit)
    assert base == original


def quote_check_module():
    module = ExecutionModules.__new__(ExecutionModules)
    module.last_action = lambda: {'transition_id': 'save-key', 'target': 'post-save-key',
                                  'expected_change': {'kind': 'state'}}
    check = {'transition_id': 'save-key', 'target_observation_id': 'post-save-key',
             'frame_id': 'current', 'assessment': 'observed',
             'checks': [{'kind': 'state', 'assessment': 'observed',
                         'quotes': ['Save', 'Name', 'Untitled Document 1']}]}
    return module, check


def test_save_dialog_missing_literal_is_specific_and_original_candidate_unchanged():
    import json
    module, check = quote_check_module()
    original = deepcopy(check)
    with pytest.raises(ValueError, match='missing_visible_quotes') as error:
        module.validate_action_check(check, frame='current',
                                     visible_texts=['Save', 'Untitled Document 1', 'Desktop', 'Cancel'])
    detail = json.loads(str(error.value).partition(': ')[2])
    assert detail['missing_visible_quotes'] == ['Name'] and detail['check_index'] == 0
    assert detail['kind'] == 'state' and 'current image' in detail['repair']
    assert check == original and len(str(error.value).encode()) < 1800
    # A regenerated source-consistent candidate is admitted; the validator
    # never silently deletes or adds quotes to the rejected one.
    regenerated = deepcopy(check)
    regenerated['checks'][0]['quotes'] = ['Save', 'Untitled Document 1']
    module.validate_action_check(regenerated, frame='current',
                                 visible_texts=['Save', 'Untitled Document 1', 'Desktop', 'Cancel'])


def test_quote_repair_does_not_relax_missing_source_or_transition_binding():
    module, check = quote_check_module()
    with pytest.raises(ValueError, match='missing_visible_quotes'):
        module.validate_action_check(check, frame='current', visible_texts=['Save'])
    check['transition_id'] = 'another-action'
    with pytest.raises(ValueError, match='bind the last transition'):
        module.validate_action_check(check, frame='current', visible_texts=['Save', 'Name', 'Untitled Document 1'])


def test_quote_diagnostic_does_not_echo_oversized_or_malformed_values():
    module, check = quote_check_module()
    check['checks'][0]['quotes'] = ['x' * 257]
    with pytest.raises(ValueError, match='bounded visible quotes') as error:
        module.validate_action_check(check, frame='current', visible_texts=['x' * 257])
    assert 'x' * 257 not in str(error.value)
    check['checks'][0]['quotes'] = [None]
    with pytest.raises(ValueError, match='bounded visible quotes'):
        module.validate_action_check(check, frame='current', visible_texts=['Save'])


def test_uncertain_visual_effect_can_stay_unknown_without_fabricated_quote():
    module, check = quote_check_module()
    check['assessment'] = check['checks'][0]['assessment'] = 'unknown'
    check['checks'][0]['quotes'] = []
    module.validate_action_check(check, frame='current', visible_texts=['Save'])
    check['assessment'] = check['checks'][0]['assessment'] = 'observed'
    with pytest.raises(ValueError, match='bounded visible quotes'):
        module.validate_action_check(check, frame='current', visible_texts=['Save'])


def before_after_module(before=None):
    module, check = quote_check_module()
    module.compare_state_v10 = True
    module.last_action = lambda: {'transition_id': 'save-key', 'target': 'post-save-key',
        'expected_change': {'kind': 'focus'}, 'before_state': before}
    check['checks'] = [{'kind': 'focus', 'assessment': 'observed', 'quotes': ['Name']}]
    return module, check


def test_preexisting_focus_is_not_certified_as_an_action_change():
    before = {'observation_id': 'pre-click', 'fields': {'focus': 'Name', 'location': 'Home'},
              'evidence_ref': '/original/pre.png'}
    module, check = before_after_module(before)
    current = {'fields': {'focus': 'Name', 'location': 'Home'}}
    original = deepcopy(check)
    with pytest.raises(ValueError, match='Pre-existing focus'):
        module.validate_action_check(check, frame='current', visible_texts=['Name', 'Home'], current_state=current)
    assert check == original
    check['assessment'] = check['checks'][0]['assessment'] = 'unknown'
    module.validate_action_check(check, frame='current', visible_texts=['Name', 'Home'], current_state=current)


def test_missing_prior_state_does_not_become_positive_from_a_visible_label():
    module, check = before_after_module()
    with pytest.raises(ValueError, match='source_observation_id'):
        module.validate_action_check(check, frame='current', visible_texts=['Name'], current_state={'fields': {'focus': 'Name'}})
    assert module.state_comparison({'fields': {'focus': 'Name'}})['changed_field_keys'] == []


def test_real_field_delta_is_a_model_proposal_but_clock_or_key_rename_is_not():
    before = {'observation_id': 'pre', 'fields': {'location': 'Home', 'clock': '01:00'}, 'evidence_ref': '/original/pre.png'}
    module, check = before_after_module(before)
    for fields in ({'location': 'Home', 'clock': '01:01'}, {'directory': 'Desktop'}):
        with pytest.raises(ValueError, match='before/after state evidence'):
            module.validate_action_check(check, frame='current', visible_texts=['Name'], current_state={'fields': fields})
    current = {'fields': {'location': 'Desktop', 'clock': '01:01'}}
    module.validate_action_check(check, frame='current', visible_texts=['Name'], current_state=current)
    comparison = module.state_comparison(current)
    assert comparison['changed_field_keys'] == ['location'] and comparison['grade'] == 'model_proposal'


def test_legacy_observed_click_without_state_delta_cannot_reset_repeat_feedback():
    module, _ = repeated_warning_module('observed')
    module.compare_state_v10 = True
    for row in module.recent:
        row['action_semantics'] = {'action': 'left_click'}
    assert module.feedback()['repetition_count'] == 4 and module.feedback()['strategy_review']
    module.effects['edge-3']['state_comparison'] = {'changed_field_keys': ['location']}
    assert module.feedback()['repetition_count'] == 0


def test_before_state_comes_from_exact_source_observation_annotation(tmp_path):
    memory = TaskMemory('task', tmp_path / 'memory')
    memory.initialize('Save the requested text')
    log = TransitionJournal(tmp_path / 'events', task_id='task', run_id='run', contract=CUAContract(model_screen_width=64, model_screen_height=48))
    module = ExecutionModules(memory, log)
    module.compare_state_v10 = True
    try:
        log.begin('Save', image(), step=1)
        source = log.current['id']
        log.annotate(source, logical_page='dialog', state_schema={'focus': 'Name', 'location': 'Home'}, evidence_ref='/original/pre.png')
        module.sync()
        log.decide('click', ['click'], step=1, tools=[{'id': 'original-call', 'arguments': {'action': 'left_click', 'coordinate': [3, 4]}, 'command_indices': [0]}])
        log.result('click', step=1, observation=image())
        module.sync()
        last = module.last_action()
        assert last['before_state']['observation_id'] == source
        assert last['before_state']['fields'] == {'focus': 'Name', 'location': 'Home'}
        assert last['before_state']['grade'] == 'model_proposal'
        assert last['executed_tool_input']['parameters']['coordinate'] == [3, 4]
    finally:
        log.close()
        memory.close()


def image():
    buffer = BytesIO()
    Image.new('RGB', (64, 48), 'white').save(buffer, 'PNG')
    return {'screenshot': buffer.getvalue()}


def test_budget_retains_last_action_receipt_images_and_unresolved_failure(tmp_path, monkeypatch):
    log = TransitionJournal(tmp_path / 'events', task_id='task', run_id='run',
                            contract=CUAContract(model_screen_width=64, model_screen_height=48))
    memory = TaskMemory('task', tmp_path / 'memory')
    memory.initialize('Save a requested result')
    modules = ExecutionModules(memory, log)
    try:
        for step in range(1, 10):
            log.begin('Save a requested result', image(), step=step)
            modules.sync()
            modules.select('stage-' + str(step), [{'purpose': 'request', 'anchors': ['task']}], frame=str(step), ref='image')
            log.decide('intent', ['click'], step=step, tools=[{'id': 'tool-' + str(step),
                'arguments': {'action': 'left_click', 'coordinate': [1, 2]}, 'command_indices': [0]}])
            row = log.result('click', step=step, observation=image(), receipts=[{'returncode': 0}])
            modules.sync()
            modules.record_action_check({'transition_id': row['id'], 'target_observation_id': row['target'],
                'frame_id': str(step), 'assessment': 'not_observed',
                'checks': [{'kind': 'focus', 'assessment': 'not_observed', 'quotes': ['Focus: canvas']}]}, frame=str(step))
            modules.report('planner', {'advice': 'A' * 6000, 'needed_evidence': ['E' * 2000]}, frame=str(step))
        monkeypatch.setattr(log, 'export_ui_kobe', lambda: pytest.fail('Whole trajectory export on hot path'))
        packet = modules.packet()
        assert len(dumps(packet).encode()) <= 6000
        assert packet['recent_transitions'][-1]['transition_id'] == row['id']
        latest = packet['recent_transitions'][-1]
        assert latest['raw_ref'] == latest['controller_receipt_ref'] == log.reference(row)
        assert latest['before_image']['sha256'] == latest['after_image']['sha256']
        assert latest['executed_tool_input']['parameters'] == {'action': 'left_click', 'coordinate': [1, 2]}
        assert latest['executed_tool_input']['source_frame']['model_size'] == [64, 48]
        assert packet['unresolved_failures'][-1]['transition_id'] == row['id']
        assert any('module' in key for key in packet['projection_omissions'])
    finally:
        # Restore the export before the immutable journal close/export.
        monkeypatch.undo()
        log.close()
        memory.close()


def test_stable_subgoal_survives_stage_role_anchor_changes_and_replay(tmp_path):
    memory = TaskMemory('task', tmp_path / 'memory')
    memory.initialize('Import, sample, fit, compute and save the requested result')
    log = TransitionJournal(tmp_path / 'events', task_id='task', run_id='run', contract=CUAContract())
    modules = ExecutionModules(memory, log)
    plan = [{'id': 'import', 'label': 'Import input', 'dependencies': []},
            {'id': 'sample', 'label': 'Sample points', 'dependencies': ['import']},
            {'id': 'fit', 'label': 'Fit the requested model', 'dependencies': ['sample']},
            {'id': 'volume', 'label': 'Compute the requested volume', 'dependencies': ['fit']},
            {'id': 'save', 'label': 'Save the result', 'dependencies': ['volume']}]
    try:
        modules.register_subgoals(plan)
        first = modules.select('execution', [{'purpose': 'one', 'anchors': ['task']}], frame='f1', ref='r', subgoal_id='sample')
        modules.report('planner', {'needed_evidence': ['Failed input focus']}, frame='f1')
        second = modules.select('execution planning', [{'purpose': 'two', 'anchors': ['task']},
            {'purpose': 'inspect', 'anchors': ['task']}], frame='f2', ref='r', subgoal_id='sample')
        assert first == second and len(modules.modules) == 1
        replay = ExecutionModules(memory, log)
        replay.validate_subgoals(list(replay.subgoals.values()))
        assert replay.subgoals == modules.subgoals and replay.modules[first]['needed_evidence'] == ['Failed input focus']
        changed = deepcopy(plan)
        changed[1]['label'] = 'Drifting goal'
        with pytest.raises(ValueError, match='immutable'):
            replay.validate_subgoals(changed)
        with pytest.raises(ValueError, match='Unknown'):
            replay.select('other', [], frame='f3', ref='r', subgoal_id='invented')
    finally:
        log.close()
        memory.close()


def math_claim():
    return {'id': 'point-claim', 'subject': 'task', 'predicate': 'coordinates', 'locator': 'P1 = (1, 2)',
        'value': {'kind': 'application_math', 'space': 'cartesian', 'object_label': 'P1',
                  'coordinates': [1, 2], 'visible_text': 'P1 = (1, 2)'}}


def test_visible_math_coordinates_have_a_distinct_provenance_contract(tmp_path):
    memory = TaskMemory('math', tmp_path)
    try:
        memory.initialize('Read the visible algebra point')
        proposal = {'entities': [], 'claims': [math_claim()]}
        TaskMemory.validate_proposal_content(proposal, visible_texts=['P1 = (1, 2)'])
        admitted = memory.observe('frame', image()['screenshot'], {'summary': 'Algebra object',
            'elements': [{'text': 'P1 = (1, 2)', 'role': 'math_object'}]}, proposals=proposal)
        assert admitted['semantic_proposals']['accepted'] and not admitted['semantic_proposals']['rejected']
        claim = memory.snapshot.claims['point-claim']
        assert plain(claim['value']) == math_claim()['value']
        assert claim['evidence']['source'] == 'visual-extractor'
    finally:
        memory.close()


@pytest.mark.parametrize('change,reason', [
    ({'space': 'screen'}, 'invalid_application_math_contract'),
    ({'coordinates': [517, 983]}, 'disagrees_with_visible_source'),
    ({'visible_text': 'P1 = (3, 4)'}, 'requires_current_visible_source'),
    ({'bbox': [1, 2, 3, 4]}, 'invalid_application_math_contract')])
def test_math_discriminant_does_not_bypass_screen_or_source_checks(change, reason):
    claim = math_claim()
    claim['value'].update(change)
    with pytest.raises(ValueError, match=reason):
        TaskMemory.validate_proposal_content({'entities': [], 'claims': [claim]}, visible_texts=['P1 = (1, 2)'])
    with pytest.raises(ValueError, match='current_frame_geometry_only'):
        TaskMemory.validate_proposal_content({'entities': [], 'claims': [
            {**math_claim(), 'value': {'x': 517, 'y': 983}}]}, visible_texts=['P1 = (1, 2)'])


def test_preallocation_admits_unicode_quoted_packet_without_changing_actor_history():
    contract = CUAContract(context_max_text_chars=10000, context_max_payload_chars=11000,
                           taskviews_context_bytes=6000)
    messages = [{'role': 'user', 'content': [{'type': 'text', 'text': 'original goal ' + 'x' * 7000}]}]
    original = deepcopy(messages)
    budget = available_context_bytes(messages, label='TaskViews', contract=contract)
    text = ('中"\\\n' * 100)[:budget // 4]
    prepared = supplement(messages, text, label='TaskViews', contract=contract)
    assert prepared is not messages and messages == original
    assert 0 < budget < 6000


def test_logical_text_capacity_is_not_halved_for_payload_escaping():
    from ui_kobe.osworld.native_history import context_size
    contract = CUAContract(context_max_text_chars=32000, context_max_payload_chars=2000000,
                           context_rough_text_token_budget=12000, taskviews_context_bytes=8000)
    messages = [{'role': 'user', 'content': [{'type': 'text', 'text': 'x' * 21716}]}]
    original = deepcopy(messages)
    budget = available_context_bytes(messages, label='TaskViews', contract=contract)
    assert budget == 8000  # The packet cap remains fixed; 10273 logical characters are free.
    packet = dumps({'raw_ref': '/original/receipt', 'effect_status': 'unknown', 'detail': 'x' * 7800})
    prepared = supplement(messages, packet, label='TaskViews', contract=contract)
    assert prepared is not messages and messages == original
    payload, chars = context_size(prepared)
    assert chars <= 32000 and payload <= 2000000 and (chars + 3) // 4 <= 12000
    assert prepared[-1]['content'][-1]['text'] == 'TaskViews\n' + packet


@pytest.mark.parametrize('character', ['\x00', '\n', '"', '\\', '中'])
def test_payload_escaping_reserve_prevents_admitted_context_being_dropped(character):
    from ui_kobe.osworld.native_history import context_size
    contract = CUAContract(context_max_text_chars=32000, context_max_payload_chars=1600,
                           context_rough_text_token_budget=12000, taskviews_context_bytes=8000)
    messages = [{'role': 'user', 'content': [{'type': 'text', 'text': 'Original goal'}]}]
    original = deepcopy(messages)
    budget = available_context_bytes(messages, label='TaskViews', contract=contract)
    text = character * (budget // len(character.encode('utf-8')))
    prepared = supplement(messages, text, label='TaskViews', contract=contract)
    assert prepared is not messages and messages == original
    assert context_size(prepared)[0] <= 1600


@pytest.mark.parametrize('text_cap,rough_cap,expected', [(100, 1000, 91), (1000, 25, 91), (8, 1000, 0)])
def test_context_admission_keeps_logical_text_and_rough_token_limits(text_cap, rough_cap, expected):
    contract = CUAContract(context_max_text_chars=text_cap, context_max_payload_chars=2000000,
                           context_rough_text_token_budget=rough_cap, taskviews_context_bytes=8000)
    messages = [{'role': 'user', 'content': [{'type': 'text', 'text': '12345'}]}]
    assert available_context_bytes(messages, label='tag', contract=contract) == expected


def test_complete_native_fixture_closes_focus_input_submit_save_and_grade(tmp_path):
    result = run_fixture(tmp_path / 'complete')
    assert result['test_kind'].startswith('offline_fixture') and result['official_score'] is None
    assert result['terminal'] and not result['paused'] and result['fixture_score'] == 1
    assert result['controller_actions'] == 6 and result['native_decisions'] == result['compiler_checks'] == 7
    assert result['module_count'] == 1 and result['all_actor_packets_delivered'] and result['all_actor_packets_local']
    assert result['recent_feedback_packets'] == 6
    assert result['roles']['perception'] == result['roles']['executor'] == 7
    assert result['roles']['view_controller'] == result['roles']['planner'] == 2
    assert result['requests'] == 18  # Single failed click stays local; repeated failure still replans.
    assert result['latest_checkpoint']['completed_steps'] == result['latest_checkpoint']['command_count'] == 6
    for pools in result['pool_checks']:
        assert pools['actor']['output_limit'] == pools['analysis']['output_limit'] == 32000
        assert pools['actor']['charged_output'] <= 32000 and pools['analysis']['charged_output'] <= 16000


def test_reader_receives_current_frame_claim_namespace_through_complete_loop(tmp_path, monkeypatch):
    from ui_kobe.osworld.taskviews_context import TaskViewsContextMixin
    original = TaskViewsContextMixin.role
    frames = []

    def capture(self, name, prompt, context, image, deadline, validator):
        if name == 'perception':
            frame = context['frame']['frame_id']
            assert dumps('claim_' + frame + '_') in prompt
            assert 'Omit unchanged task/static facts' in prompt
            assert 'Entity IDs stay stable' in prompt
            frames.append(frame)
        return original(self, name, prompt, context, image, deadline, validator)

    monkeypatch.setattr(TaskViewsContextMixin, 'role', capture)
    result = run_fixture(tmp_path / 'frame-claim-loop')
    assert result['terminal'] and not result['paused']
    assert result['official_score'] is None and result['fixture_score'] == 1
    assert result['all_actor_packets_delivered'] and result['controller_actions'] == 6
    assert len(frames) == len(set(frames)) == result['roles']['perception'] == 7


def repair_capacity_owner(packet, messages, *, spare):
    from types import SimpleNamespace
    from ui_kobe.osworld.taskviews_context import TaskViewsContextMixin
    from ui_kobe.osworld.native_history import context_size

    owner = TaskViewsContextMixin()
    owner.feedback_v10 = owner.checkpoint_reads = True
    owner.modules = None
    owner.frame = SimpleNamespace(metadata={'frame_id': packet['frame_id']})
    owner.context_label = 'TaskViews evidence'
    owner.cached_context = dumps(packet)
    owner.view_trace = {'executor_context': deepcopy(packet), 'available_actor_context_bytes': 8000}
    original = deepcopy(messages)
    original[-1]['content'].append({'type': 'text', 'text': owner.context_label + '\n' + owner.cached_context})
    owner.contract = CUAContract(context_max_text_chars=context_size(original)[1] + spare)
    return owner


def test_repair_readmission_changes_only_fixed_policy_and_keeps_original_tool_history():
    from types import SimpleNamespace
    from ui_kobe.osworld.actor_context import ContextClient
    from ui_kobe.osworld.taskviews_feedback import LOCAL_EXECUTION, LOCAL_EXECUTION_COMPACT
    packet = {**local_feedback_base(), 'execution_boundary': LOCAL_EXECUTION,
              'role_evidence': {'execution_modules': {'recent_transitions': [{'transition_id': 'original-edge',
                  'raw_ref': '/original/receipt', 'before_image': {'sha256': 'a'*64},
                  'after_image': {'sha256': 'b'*64}}]}, 'strategy_review': True},
              'context_gaps': ['budget_omitted:prior_action_evidence']}
    messages = [{'role': 'user', 'content': [{'type': 'text', 'text': 'Original task and image'}]},
        {'role': 'assistant', 'content': 'Original rejected prose', 'tool_calls': [{'id': 'original-id',
            'type': 'function', 'function': {'name': 'computer_use', 'arguments': '{"action":"left_click"}'}}]},
        {'role': 'tool', 'tool_call_id': 'original-id', 'content': dumps({'error': 'Complete original error ' * 40})},
        {'role': 'user', 'content': [{'type': 'text', 'text': 'Regenerate the complete candidate'}]}]
    owner = repair_capacity_owner(packet, messages, spare=-200)
    original = deepcopy(messages)
    requests = []
    wire = SimpleNamespace(create=lambda **request: requests.append(request), last_timing={})
    ContextClient(owner, wire).create(messages=messages, tools=['original-tool-schema'])
    assert len(requests) == 1 and requests[0]['tools'] == ['original-tool-schema'] and messages == original
    assert requests[0]['messages'][:-1] == original[:-1]
    assert requests[0]['messages'][-1]['content'][:-1] == original[-1]['content']
    current = json.loads(owner.cached_context)
    assert current['execution_boundary'] == LOCAL_EXECUTION_COMPACT
    assert current['execution_boundary_original_sha256'] == hashlib.sha256(LOCAL_EXECUTION.encode()).hexdigest()
    assert {key: value for key, value in current.items() if key not in {'execution_boundary',
        'execution_boundary_variant', 'execution_boundary_original_sha256'}} == {
        key: value for key, value in packet.items() if key != 'execution_boundary'}
    assert owner.view_trace['actor_context_readmissions'][0]['original_context'] == packet
    assert len(owner.cached_context.encode()) <= owner.view_trace['available_actor_context_bytes']


@pytest.mark.parametrize('mode', ['foreign-policy', 'already-compact', 'stale-frame', 'still-too-small'])
def test_repair_readmission_never_changes_foreign_policy_frame_or_exceeds_capacity(mode):
    from types import SimpleNamespace
    from ui_kobe.osworld.actor_context import ContextClient
    from ui_kobe.osworld.checkpoints import ReadAnomaly
    from ui_kobe.osworld.taskviews_feedback import LOCAL_EXECUTION, LOCAL_EXECUTION_COMPACT
    packet = {**local_feedback_base(), 'execution_boundary': LOCAL_EXECUTION}
    if mode == 'foreign-policy':
        packet['execution_boundary'] = 'Foreign instruction that must not change'
    if mode == 'already-compact':
        packet['execution_boundary'] = LOCAL_EXECUTION_COMPACT
    messages = [{'role': 'user', 'content': [{'type': 'text', 'text': 'Original complete error and history'}]}]
    owner = repair_capacity_owner(packet, messages, spare=-200 if mode != 'still-too-small' else -1900)
    if mode == 'stale-frame':
        owner.frame.metadata['frame_id'] = 'other-frame'
    original_context, original_trace = owner.cached_context, deepcopy(owner.view_trace)
    calls = []
    wire = SimpleNamespace(create=lambda **request: calls.append(request), last_timing={})
    with pytest.raises(ReadAnomaly, match='cannot fit'):
        ContextClient(owner, wire).create(messages=messages)
    assert not calls and owner.cached_context == original_context and owner.view_trace == original_trace


def test_wrong_last_action_binding_repairs_then_pauses_before_next_dispatch(tmp_path):
    result = run_fixture(tmp_path / 'bad-binding', bad_action_binding=True)
    assert result['paused'] and not result['terminal'] and result['fixture_score'] is None
    assert result['controller_actions'] == result['native_decisions'] == 1
    assert result['roles']['perception'] == 4  # First read + rejected read + two bounded repairs.
    assert result['latest_checkpoint']['completed_steps'] == result['latest_checkpoint']['command_count'] == 1


def test_parallel_jobs_keep_two_real_ids_one_shared_output_pool_and_stable_result_order():
    from scripts.benchmark_taskviews_advisory import benchmark_mock
    result = benchmark_mock(2, delay=0.01)
    assert result['mock_only'] and result['requests'] == 2
    ledger = result['ledger']
    assert ledger['known_usage']['total_tokens'] == 220 and ledger['charged_output'] == 20
    assert ledger['output_limit'] == 32000 and ledger['unknown_usage_requests'] == 0


@pytest.mark.parametrize('mode', ['executor', 'different-frame', 'shared-transport'])
def test_concurrency_rejects_gui_roles_stale_frames_or_shared_mutable_transport(mode):
    transport = object()
    jobs = [AdvisoryJob('planner', 'f', 1, transport, lambda: {}),
            AdvisoryJob('executor' if mode == 'executor' else 'verifier',
                        'other' if mode == 'different-frame' else 'f', 1,
                        transport if mode == 'shared-transport' else object(), lambda: {})]
    with pytest.raises(ValueError, match='Independent'):
        run_advisory_jobs(jobs, concurrency=2)


def test_parallel_repairs_cannot_each_obtain_a_new_two_repair_budget():
    from concurrent.futures import ThreadPoolExecutor
    import time
    from ui_kobe.api.kimi_budget import ConcurrentAdvisoryLedger
    from ui_kobe.api.qwen_native import QwenGenerationProfile
    ledger = ConcurrentAdvisoryLedger(QwenGenerationProfile(), time.monotonic() + 60, lambda *_a, **_k: None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        granted = list(pool.map(lambda _n: ledger.regenerate('planner', 0), range(10)))
    assert sum(granted) == ledger.snapshot()['repair_counts']['advisory'] == 2


def test_no_late_context_omission_is_needed_when_analysis_has_no_actor_room(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from ui_kobe.osworld.taskviews_feedback import build_feedback_views
    from ui_kobe.osworld import telemetry
    events = []
    monkeypatch.setattr(telemetry, 'emit', lambda kind, **data: events.append((kind, data)))
    contract = CUAContract(context_max_text_chars=2100)
    owner = SimpleNamespace(control=None, execution_journal=None, actor_input_messages=[
        {'role': 'user', 'content': [{'type': 'text', 'text': 'Original task ' + 'x' * 2000}]}],
        contract=contract, context_label='TaskViews', view_trace={})
    assert build_feedback_views(owner, 99999) is None
    assert owner.view_trace['analysis_skipped'] == 'actor_input_admission'
    assert events[0][0] == 'taskviews_analysis_skipped'


def test_unknown_parallel_usage_remains_cap_charged_and_null():
    from concurrent.futures import ThreadPoolExecutor
    import time
    from ui_kobe.api.kimi_budget import ConcurrentAdvisoryLedger
    from ui_kobe.api.qwen_native import QwenGenerationProfile
    ledger = ConcurrentAdvisoryLedger(QwenGenerationProfile(), time.monotonic() + 60, lambda *_a, **_k: None)
    def attempt(identity):
        ledger.reserve(identity, 'planner', 4000)
        ledger.settle(identity, None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(attempt, ['actual-mock-id-a', 'actual-mock-id-b']))
    snapshot = ledger.snapshot()
    assert snapshot['charged_output'] == 8000 and snapshot['unknown_usage_requests'] == 2
    assert all(r['usage'] is None for r in ledger.requests.values())


def test_recording_can_copy_the_concurrent_ledger_without_copying_its_live_lock():
    import time
    from ui_kobe.api.kimi_budget import ConcurrentAdvisoryLedger
    from ui_kobe.api.qwen_native import QwenGenerationProfile
    ledger = ConcurrentAdvisoryLedger(QwenGenerationProfile(), time.monotonic() + 60, lambda *_a, **_k: None)
    ledger.reserve('actual-id', 'planner', 4000)
    copy = deepcopy(ledger)
    copy.settle('actual-id', None)
    assert not ledger.requests['actual-id']['settled'] and copy.requests['actual-id']['settled']
    assert copy._lock is not ledger._lock


def test_math_display_unicode_minus_preserves_the_original_quote_and_value():
    claim = math_claim()
    claim['locator'] = claim['value']['visible_text'] = 'P1 = (1, \u22122)'
    claim['value']['coordinates'] = [1, -2]
    original = deepcopy(claim)
    TaskMemory.validate_proposal_content({'entities': [], 'claims': [claim]}, visible_texts=['P1 = (1, \u22122)'])
    assert claim == original


def test_cannot_execute_blindly_when_checkpoint_read_cannot_reach_actor(monkeypatch):
    from types import SimpleNamespace
    from ui_kobe.osworld.taskviews_feedback import build_feedback_views
    owner = SimpleNamespace(control=None, execution_journal=None, checkpoint_reads=True,
        actor_input_messages=[{'role': 'user', 'content': [{'type': 'text', 'text': 'x' * 2000}]}],
        contract=CUAContract(context_max_text_chars=2100), context_label='TaskViews', view_trace={})
    with pytest.raises(ValueError, match='preserve checkpoint before dispatch'):
        build_feedback_views(owner, 99999)


@pytest.mark.parametrize('keys', ['Return', 'Enter', ['Return'], ['ENTER'], ['enter']])
def test_last_action_check_cannot_substitute_old_objects_for_new_input(tmp_path, keys):
    memory = TaskMemory('task', tmp_path / 'memory')
    memory.initialize('Create requested point')
    log = TransitionJournal(tmp_path / 'events', task_id='task', run_id='run',
                            contract=CUAContract(model_screen_width=64, model_screen_height=48))
    modules = ExecutionModules(memory, log)
    try:
        modules.select('create', [{'purpose': 'create P1', 'anchors': ['task']}], frame='0', ref='r')
        for step, args in enumerate(({'action': 'type', 'text': 'P1 = (1, 2)'},
                                    {'action': 'key', 'keys': keys}), 1):
            log.begin('Create requested point', image(), step=step)
            modules.sync()
            log.decide('intent', ['action'], step=step, tools=[{'id': 't' + str(step), 'arguments': args,
                                                             'command_indices': [0]}])
            row = log.result('action', step=step, observation=image())
            modules.sync()
        last = modules.last_action()
        assert last['expected_change']['requested_object_label'] == 'P1'
        check = {'transition_id': row['id'], 'target_observation_id': row['target'], 'frame_id': 'current',
            'assessment': 'observed', 'checks': [
                {'kind': 'submission', 'assessment': 'observed', 'quotes': ['Objects: A, B']},
                {'kind': 'object', 'assessment': 'observed', 'quotes': ['Objects: A, B']}]}
        with pytest.raises(ValueError, match='exact previous request'):
            modules.validate_action_check(check, frame='current', visible_texts=['Objects: A, B'])
        for item in check['checks']:
            item.update(assessment='not_observed')
        check['assessment'] = 'not_observed'
        modules.validate_action_check(check, frame='current', visible_texts=['Objects: A, B'])
    finally:
        log.close()
        memory.close()


@pytest.mark.parametrize('keys', [['ctrl', 'Return'], ['ctrl', 's']])
def test_modified_keys_are_not_falsely_classified_as_bare_submission(keys):
    module = ExecutionModules.__new__(ExecutionModules)
    original = {'transition_id': 'key', 'module_id': 'input',
                'action_semantics': {'action': 'key', 'keys': keys}, 'raw_ref': '/immutable/key'}
    module.recent = [deepcopy(original)]
    module.transition_packet = lambda record: deepcopy(record)
    assert module.last_action()['expected_change']['kind'] == 'state'
    assert module.recent == [original]


@pytest.mark.parametrize('malformed', [False, True])
def test_submission_repairs_identify_separate_object_check_without_rewriting_candidate(malformed):
    module = ExecutionModules.__new__(ExecutionModules)
    module.last_action = lambda: {'transition_id': 'submit', 'target': 'post',
                                  'expected_change': {'kind': 'submission'}}
    check = {'transition_id': 'submit', 'target_observation_id': 'post', 'frame_id': 'current',
             'assessment': 'not_observed', 'checks': [
                 {'kind': 'submission', 'assessment': 'not_observed', 'quotes': ['Empty results']}]}
    if malformed:
        check['checks'][0].update(object='requested-object', result='not_created')
    original = deepcopy(check)
    with pytest.raises(ValueError) as error:
        module.validate_action_check(check, frame='current', visible_texts=['Empty results'])
    assert check == original and len(str(error.value).encode()) < 6000
    if malformed:
        detail = json.loads(str(error.value).split(': ', 1)[1])
        assert detail['extra_fields'] == ['object', 'result']
        assert detail['required_fields'] == ['assessment', 'kind', 'quotes']
        assert detail['provided_check'] == original['checks'][0]
    else:
        assert 'separate kind:object' in str(error.value)
    regenerated = {**original, 'checks': [
        {'kind': 'submission', 'assessment': 'not_observed', 'quotes': ['Empty results']},
        {'kind': 'object', 'assessment': 'unknown', 'quotes': []}]}
    module.validate_action_check(regenerated, frame='current', visible_texts=['Empty results'])
    assert regenerated['checks'][1]['assessment'] == 'unknown' and check == original


@pytest.mark.parametrize('arguments,kind', [
    ({'action': 'left_click', 'coordinate': [3, 4]}, 'focus'),
    ({'action': 'type', 'text': 'Requested text'}, 'text'),
    ({'action': 'key', 'keys': ['ctrl', 's']}, 'state')])
def test_trailing_capture_cannot_mask_last_actual_operation_or_receive_its_effect(tmp_path, arguments, kind):
    memory = TaskMemory('task', tmp_path / 'memory')
    memory.initialize('Save the requested text')
    log = TransitionJournal(tmp_path / 'events', task_id='task', run_id='run',
                            contract=CUAContract(model_screen_width=64, model_screen_height=48))
    module = ExecutionModules(memory, log)
    module.compare_state_v10 = True
    try:
        module.select('save', [{'purpose': 'save', 'anchors': ['task']}], frame='0', ref='r')
        for step in (1, 2):
            log.begin('Save', image(), step=step)
            source = log.current['id']
            log.annotate(source, logical_page='dialog', state_schema={'focus': 'Name'}, evidence_ref='/original/pre.png')
            log.decide('operation and evidence', ['operate', 'capture'], step=step, tools=[
                {'id': f'op-{step}', 'arguments': arguments, 'command_indices': [0]},
                {'id': f'capture-{step}', 'arguments': {'action': 'screenshot'}, 'command_indices': [1]}])
            operation = log.result('operate', step=step, observation=image(), receipts=[{'returncode': 0}])
            capture = log.result('capture', step=step, observation=image(), receipts=[{'returncode': 0}])
            module.sync()
            last = module.last_action()
            assert last['transition_id'] == operation['id'] and last['expected_change']['kind'] == kind
            assert last['before_state']['observation_id'] == source
            assert last['executed_tool_input']['tool_call_id'] == f'op-{step}'
            assert last['evidence_capture_refs'][-1]['transition_id'] == capture['id']
            checks = [{'kind': kind, 'assessment': 'unknown', 'quotes': []}]
            if kind == 'text':
                checks.append({'kind': 'focus', 'assessment': 'unknown', 'quotes': []})
            check = {'transition_id': operation['id'], 'target_observation_id': operation['target'],
                     'frame_id': str(step), 'assessment': 'unknown', 'checks': checks}
            module.validate_action_check(check, frame=str(step), visible_texts=[], current_state={'fields': {'focus': 'Name'}})
            module.record_action_check(check, frame=str(step), current_state={'fields': {'focus': 'Name'}})
            assert operation['id'] in module.effects and capture['id'] not in module.effects
            with pytest.raises(ValueError):
                module.record_action_check({**check, 'transition_id': capture['id']}, frame=str(step))
        warning = module.actor_feedback()
        assert warning['original_parameters'] == arguments
        assert warning['unconfirmed_repetition_count'] == 2 and warning['strategy_review']
        assert warning['latest_evidence_capture_ref'] == log.reference(capture)
        module.report('planner', {'advice': 'x' * 8000}, frame='2')
        packet = module.packet(max_bytes=6000)
        retained = {r['transition_id']: r for r in packet['recent_transitions']}
        assert {operation['id'], capture['id']} <= retained.keys()
        assert retained[operation['id']]['raw_ref'] == log.reference(operation)
        assert retained[capture['id']]['raw_ref'] == log.reference(capture)
        assert retained[operation['id']]['after_image']['sha256'] == retained[capture['id']]['after_image']['sha256']
        assert len(dumps(packet).encode()) <= 6000
        assert len(module.recent) == 4  # No original capture, command or receipt was deleted.
    finally:
        log.close()
        memory.close()


def test_capture_only_has_evidence_but_no_claimed_ui_action_effect(tmp_path):
    memory = TaskMemory('task', tmp_path / 'memory')
    memory.initialize('Inspect the current application')
    log = TransitionJournal(tmp_path / 'events', task_id='task', run_id='run',
                            contract=CUAContract(model_screen_width=64, model_screen_height=48))
    module = ExecutionModules(memory, log)
    module.compare_state_v10 = True
    try:
        log.begin('Inspect', image(), step=1)
        log.decide('capture only', ['capture'], step=1, tools=[
            {'id': 'original-capture', 'arguments': {'action': 'screenshot'}, 'command_indices': [0]}])
        capture = log.result('capture', step=1, observation=image(), receipts=[{'returncode': 0}])
        module.sync()
        assert module.last_action() is None and module.actor_feedback() is None
        module.validate_action_check(None, frame='1', visible_texts=[])
        module.record_action_check(None, frame='1')
        assert not module.effects
        assert module.packet()['recent_transitions'][-1]['transition_id'] == capture['id']
    finally:
        log.close()
        memory.close()


def test_verification_projection_bounds_large_state_without_mutating_original_or_claiming_change(tmp_path):
    memory = TaskMemory('task', tmp_path / 'memory')
    memory.initialize('Save text')
    log = TransitionJournal(tmp_path / 'events', task_id='task', run_id='run',
                            contract=CUAContract(model_screen_width=64, model_screen_height=48))
    module = ExecutionModules(memory, log)
    module.compare_state_v10 = True
    fields = {'focus': 'Name', **{f'detail-{i}': 'x' * 180 for i in range(15)}}
    try:
        log.begin('Save text', image(), step=1)
        log.annotate(log.current['id'], logical_page='dialog', state_schema=fields, evidence_ref='/original/before.png')
        log.decide('focus', ['click'], step=1, tools=[{'id': 'real-call',
            'arguments': {'action': 'left_click', 'coordinate': [3, 4]}, 'command_indices': [0]}])
        row = log.result('click', step=1, observation=image(), receipts=[{'returncode': 0}])
        module.sync()
        original = module.last_action()
        bounded = module.verification_action(max_bytes=2200)
        assert len(dumps(bounded).encode()) <= 2200
        assert bounded['before_state']['fields']['focus'] == 'Name'
        assert bounded['omitted_before_state_keys']
        assert bounded['executed_tool_input']['parameters'] == {'action': 'left_click', 'coordinate': [3, 4]}
        assert bounded['raw_ref'] == log.reference(row) and bounded['complete_model_feedback_ref'].endswith(row['id'])
        assert module.last_action() == original and original['before_state']['fields'] == fields
        assert module.state_comparison({'fields': fields})['changed_field_keys'] == []
    finally:
        log.close()
        memory.close()


def test_planner_large_visible_text_is_optional_after_actual_action_feedback():
    from ui_kobe.osworld.taskviews_feedback import _planner_input
    module, _ = repeated_warning_module('not_observed')
    warning = {'last_action': module.actor_feedback(), 'repetition_count': 4, 'strategy_review': True}
    core = {'task': 'Save original requested result'}
    result = _planner_input(core, warning, {'id': 'save'}, 'Original task',
                            ['A visible long row ' + 'x' * 8000], {'needs': []}, 2500)
    assert len(dumps(result).encode()) <= 2500
    assert result['action_feedback'] == warning and result['original_task'] == 'Original task'
    assert 'visible_text' not in result and 'budget_omitted:visible_text' in result['context_gaps']
    assert result['mandatory_core'] == core

def bounded_reference_module():
    from types import SimpleNamespace
    module = ExecutionModules.__new__(ExecutionModules)
    def record(identity):
        return {'transition_id': identity, 'source': 'before-' + identity, 'target': 'after-' + identity,
                'raw_ref': '/immutable/' + identity + '/' + 'p' * 200,
                'controller_receipt_ref': '/immutable/' + identity + '/' + 'p' * 200,
                'action_semantics': {'action': 'left_click', 'advice': 'a' * 1500},
                'action_check': {'assessment': 'not_observed'}, 'effect_status': 'unknown',
                'before_image': {'ref': '/image/pre-' + identity, 'sha256': '1' * 64, 'bytes': 123456},
                'after_image': {'ref': '/image/post-' + identity, 'sha256': '2' * 64, 'bytes': 123456},
                'expected_change': {'kind': 'focus', 'description': 'Confirm this exact effect ' * 8},
                'evidence_capture_refs': [], 'omitted_older_capture_refs': 0}
    module.recent = [record('failed'), record('latest')]
    module.unresolved = [deepcopy(module.recent[0])]
    module.modules = {}
    module.active = None
    module.previous_revision = None
    module.new_events = []
    module.gaps = []
    module.memory = SimpleNamespace(snapshot=SimpleNamespace(revision='original'))
    module.transition_packet = lambda row: deepcopy(row)
    module.last_action = lambda: deepcopy(module.recent[-1])
    return module


def test_packet_preserves_two_distinct_edges_when_optional_reference_metadata_exceeds_budget():
    module = bounded_reference_module()
    original = deepcopy((module.recent, module.unresolved))
    minimal = module.packet(max_bytes=20000)
    minimal['recent_transitions'] = minimal['recent_transitions'][-1:]
    for row in minimal['recent_transitions'] + minimal['unresolved_failures']:
        row.pop('action_semantics')
        row.pop('action_check')
    minimal['projection_omissions'] = {'older_transition': 1, 'transition_details_at_raw_ref': 2}
    budget = len(dumps(minimal).encode()) - 1
    packet = module.packet(max_bytes=budget)
    assert len(dumps(packet).encode()) <= budget
    assert packet['projection_omissions']['optional_transition_metadata'] >= 1
    assert {r['transition_id'] for r in packet['recent_transitions']} == {'latest'}
    assert {r['transition_id'] for r in packet['unresolved_failures']} == {'failed'}
    for row in packet['recent_transitions'] + packet['unresolved_failures']:
        source = next(r for r in original[0] if r['transition_id'] == row['transition_id'])
        assert row['raw_ref'] == row['controller_receipt_ref'] == source['raw_ref']
        assert (row['source'], row['target'], row['effect_status']) == (source['source'], source['target'], 'unknown')
        for key in ('before_image', 'after_image'):
            assert row[key]['ref'] == source[key]['ref'] and row[key]['sha256'] == source[key]['sha256']
        assert row['expected_change']['kind'] == 'focus'
    assert (module.recent, module.unresolved) == original


def test_packet_optional_metadata_stays_with_room_and_impossible_budget_still_fails():
    module = bounded_reference_module()
    packet = module.packet(max_bytes=20000)
    latest = packet['recent_transitions'][-1]
    assert latest['expected_change']['description'] == module.recent[-1]['expected_change']['description']
    assert latest['before_image']['bytes'] == 123456
    assert 'optional_transition_metadata' not in packet['projection_omissions']
    with pytest.raises(ValueError, match='latest action and unresolved failure references'):
        module.packet(max_bytes=1)


@pytest.mark.parametrize('controller_error', [None, 'original controller failure'])
def test_reference_floor_keeps_real_errors_and_ids_when_derived_metadata_no_longer_fits(controller_error):
    module = bounded_reference_module()
    for row in module.recent + module.unresolved:
        row.update(action_fingerprint='f' * 24, error=controller_error,
                   tool_call_id='original-tool-' + row['transition_id'], module_id='original-module')
    original = deepcopy((module.recent, module.unresolved))
    minimal = module.packet(max_bytes=20000)
    minimal['recent_transitions'] = minimal['recent_transitions'][-1:]
    for row in minimal['recent_transitions'] + minimal['unresolved_failures']:
        row.pop('action_semantics')
        row.pop('action_check')
        row['before_image'].pop('bytes')
        row['after_image'].pop('bytes')
        row['expected_change'].pop('description')
        row.pop('evidence_capture_refs')
        row.pop('omitted_older_capture_refs')
    minimal['projection_omissions'] = {'older_transition': 1, 'transition_details_at_raw_ref': 2,
                                      'optional_transition_metadata': 2}
    budget = len(dumps(minimal).encode()) - 1
    packet = module.packet(max_bytes=budget)
    assert len(dumps(packet).encode()) <= budget
    assert packet['projection_omissions']['derived_transition_metadata'] >= 1
    assert {r['transition_id'] for r in packet['recent_transitions']} == {'latest'}
    assert {r['transition_id'] for r in packet['unresolved_failures']} == {'failed'}
    for row in packet['recent_transitions'] + packet['unresolved_failures']:
        source = next(r for r in original[0] if r['transition_id'] == row['transition_id'])
        for key in ('source', 'target', 'raw_ref', 'controller_receipt_ref', 'effect_status',
                    'tool_call_id', 'module_id', 'before_image', 'after_image'):
            if key in ('before_image', 'after_image'):
                assert row[key]['ref'] == source[key]['ref'] and row[key]['sha256'] == source[key]['sha256']
            else:
                assert row[key] == source[key]
        if controller_error is not None:
            assert row['error'] == controller_error
    assert (module.recent, module.unresolved) == original


def test_derived_metadata_remains_in_a_wide_packet_and_strict_reference_floor_still_fails():
    module = bounded_reference_module()
    for row in module.recent + module.unresolved:
        row.update(action_fingerprint='original fingerprint', error=None)
    packet = module.packet(max_bytes=20000)
    assert all(row['action_fingerprint'] == 'original fingerprint' and row['error'] is None
               for row in packet['recent_transitions'] + packet['unresolved_failures'])
    assert 'derived_transition_metadata' not in packet['projection_omissions']
    with pytest.raises(ValueError, match='latest action and unresolved failure references'):
        module.packet(max_bytes=1)


@pytest.mark.parametrize('assessment,shared,changed,expected', [
    ('unknown', [], [], 0), ('unknown', ['window_state'], [], 1),
    ('not_observed', [], [], 1), ('observed', ['window_state'], [], 0),
    ('unknown', ['window_state'], ['window_state'], 0)])
def test_repeated_keys_need_action_bound_evidence_and_clear_on_actual_state_change(
        assessment, shared, changed, expected):
    keys = {'action': 'key', 'keys': ['command', 'up']}
    module = pointer_history([keys, keys], [assessment, assessment])
    original = deepcopy([module.recent, module.effects])
    for effect in module.effects.values():
        effect['state_comparison'] = {'shared_field_keys': shared, 'changed_field_keys': changed}
    original = deepcopy([module.recent, module.effects])
    assert len(module.stalled_keyboard_actions()) == expected
    assert module.stalled_pointer_actions() == []
    assert [module.recent, module.effects] == original


def test_recovery_requires_planner_assignment_but_ordinary_event_free_reuse_does_not():
    from ui_kobe.osworld.taskviews_feedback import validate_recovery_consumers
    needs = [{'consumer': 'executor'}]
    with pytest.raises(ValueError, match='Assign a planner view'):
        validate_recovery_consumers(needs, required=True)
    validate_recovery_consumers(needs, required=False)
    validate_recovery_consumers(needs + [{'consumer': 'planner'}], required=True)
    assert needs == [{'consumer': 'executor'}]


def test_local_execution_does_not_inherit_an_observers_wrong_pointer_geometry():
    from ui_kobe.osworld.taskviews_feedback import local_visible_evidence
    raw = {'summary': 'Input is empty', 'elements': [
        {'text': 'Input:', 'role': 'textbox', 'bbox': [313, 766, 339, 784]}],
        'semantics': {'claims': [{'value': 'historical graph locator'}]}}
    original = deepcopy(raw)
    packet = local_visible_evidence(raw)
    assert packet['elements'] == [{'text': 'Input:', 'role': 'textbox'}]
    assert packet['summary'] == raw['summary'] and not packet['summary_omitted']
    assert packet['pointer_source'] == 'current_original_screenshot' and packet['grade'] == 'model_proposal'
    assert 'bbox' not in dumps(packet) and 'claims' not in packet
    assert raw == original  # The complete original evidence stays unchanged.


def test_local_labels_stay_whole_under_utf8_budget_without_fabricated_locators():
    from ui_kobe.osworld.taskviews_feedback import local_visible_evidence
    raw = {'summary': '长观察' * 1000, 'elements': [
        {'text': '文件名' * 400, 'role': 'textbox', 'bbox': [1, 2, 3, 4]},
        {'text': '另存为', 'role': 'button', 'bbox': [5, 6, 7, 8]}]}
    original = deepcopy(raw)
    packet = local_visible_evidence(raw, max_bytes=300)
    assert len(dumps(packet).encode()) <= 300
    assert packet['elements'] == [{'text': '另存为', 'role': 'button'}]
    assert packet['omitted_elements'] == 1 and packet['summary_omitted'] and 'summary' not in packet
    assert raw == original
    with pytest.raises(ValueError, match='envelope'):
        local_visible_evidence(raw, max_bytes=1)


def test_single_failed_attempt_keeps_local_feedback_without_another_global_plan():
    from types import SimpleNamespace
    from ui_kobe.osworld.taskviews_feedback import feedback_analysis_triggers
    module = SimpleNamespace(subgoals={'goal': {}}, selected_needs=[{'consumer': 'executor'}], page_id='editor')
    raw = {'ui_state': {'page_id': 'editor'}, 'action_check': {'assessment': 'not_observed'},
           'subgoal_review': None}
    original = deepcopy(raw)
    assert feedback_analysis_triggers(module, raw, {'strategy_review': False}, False) == []
    assert feedback_analysis_triggers(module, raw, {'strategy_review': True}, False) == ['repeated_unconfirmed_strategy']
    assert feedback_analysis_triggers(module, raw, {'strategy_review': False}, True) == ['persistent_pointer_uncertainty']
    assert raw == original
    raw['ui_state']['page_id'] = 'save-dialog'
    assert feedback_analysis_triggers(module, raw, {'strategy_review': False}, False) == ['page_change']
    raw['subgoal_review'] = {'change_needed': True}
    assert feedback_analysis_triggers(module, raw, {'strategy_review': False}, False) == ['page_change', 'subgoal_review']


def test_local_actor_module_projection_preserves_operation_receipts_and_unresolved_failure(tmp_path):
    from types import SimpleNamespace
    module = ExecutionModules.__new__(ExecutionModules)
    module.memory = SimpleNamespace(snapshot=SimpleNamespace(revision='current'))
    module.modules = {'stable': {'id': 'stable', 'reports': {'planner': 'Never execute this old plan' * 100}}}
    module.active, module.previous_revision = 'stable', 'previous'
    module.new_events, module.gaps = [], []
    recent = {'transition_id': 'actual-edge', 'raw_ref': '/raw.sqlite#actual-edge',
              'controller_receipt_ref': '/raw.sqlite#actual-edge', 'receipt_count': 1,
              'before_image': {'ref': '/before.png', 'sha256': 'before'},
              'after_image': {'ref': '/after.png', 'sha256': 'after'}, 'effect_status': 'unknown'}
    module.recent, module.unresolved = [recent], [{**recent, 'transition_id': 'failed-edge'}]
    module.transition_packet = lambda record: deepcopy(record)
    module.last_action = lambda: deepcopy(recent)
    original = deepcopy([module.modules, module.recent, module.unresolved])
    packet = module.packet(max_bytes=2000, include_modules=False)
    assert packet['modules'] == [] and packet['omitted_modules'] == 1 and packet['active_module'] == 'stable'
    assert packet['recent_transitions'] == [recent] and packet['unresolved_failures'] == module.unresolved
    assert 'Never execute' not in dumps(packet)
    assert [module.modules, module.recent, module.unresolved] == original


def intent_operation(tmp_path, response, *, capture=False):
    memory = TaskMemory('task', tmp_path / 'memory')
    memory.initialize('Perform the requested operation')
    log = TransitionJournal(tmp_path / 'events', task_id='task', run_id='run',
                            contract=CUAContract(model_screen_width=64, model_screen_height=48))
    module = ExecutionModules(memory, log)
    module.compare_state_v10 = module.intent_verification_v12 = True
    log.begin('Perform the requested operation', image(), step=1)
    log.annotate(log.current['id'], logical_page='editor',
        state_schema={'window_state': 'normal', 'menu': 'open', 'focus': 'menu', 'clock': '1'}, evidence_ref='before.png')
    tools = [{'id': 'original-click', 'arguments': {'action': 'left_click', 'coordinate': [3, 4]},
              'command_indices': [0]}]
    if capture:
        tools.append({'id': 'original-capture', 'arguments': {'action': 'screenshot'}, 'command_indices': [1]})
    log.decide(response, ['click'] + (['capture'] if capture else []), step=1, tools=tools)
    row = log.result('click', step=1, observation=image(), receipts=[{'returncode': 0}])
    if capture:
        log.result('capture', step=1, observation=image(), receipts=[{'returncode': 0}])
    module.sync()
    return memory, log, module, row


def intent_check(module, row, assessment, *, key='window_state', quote='Window: normal'):
    return {'transition_id': row['id'], 'target_observation_id': row['target'], 'frame_id': '2',
        'assessment': assessment, 'checks': [
            {'kind': 'focus', 'assessment': 'observed', 'quotes': ['Focus: editor']},
            {'kind': 'intent', 'assessment': assessment,
             'quotes': [] if assessment == 'unknown' else [quote], 'state_keys': [key]}]}


def test_intent_prevents_menu_change_from_certifying_requested_maximization(tmp_path):
    prose = 'Click Maximize to maximize the editor window.'
    memory, log, module, row = intent_operation(tmp_path, prose)
    state = {'fields': {'window_state': 'normal', 'menu': 'closed', 'focus': 'editor', 'clock': '2'}}
    visible = ['Focus: editor', 'Window: normal']
    try:
        intent = module.verification_action()['actor_intent']
        assert intent['text'] == prose and intent['original_field'] == 'response'
        assert intent['decision_ref'] == row['decision_ref'] and intent['command_index'] == 0
        check = intent_check(module, row, 'observed')
        with pytest.raises(ValueError, match='changed before/current'):
            module.validate_action_check(check, frame='2', visible_texts=visible, current_state=state)
        generic = deepcopy(check)
        generic['checks'].pop()
        with pytest.raises(ValueError, match='original actor intent separately'):
            module.validate_action_check(generic, frame='2', visible_texts=visible, current_state=state)
        failure = intent_check(module, row, 'not_observed')
        module.validate_action_check(failure, frame='2', visible_texts=visible, current_state=state)
        module.record_action_check(failure, frame='2', current_state=state)
        warning = module.actor_feedback()
        assert warning['assessment'] == 'not_observed' and warning['unconfirmed_repetition_count'] == 1
        assert warning['checks'][1]['state_keys'] == ['window_state']
        assert module.event(row['decision_id'])['response'] == prose
        assert module.event(row['id'])['tool']['arguments']['coordinate'] == [3, 4]
    finally:
        log.close()
        memory.close()


@pytest.mark.parametrize('current_menu', [None, {'status': 'absent'}])
def test_visible_absence_is_known_but_null_remains_unknown_with_exact_repair_feedback(tmp_path, current_menu):
    memory, log, module, row = intent_operation(tmp_path, 'Close the menu by pressing Escape.')
    before = module.last_action()
    before['before_state']['fields']['open_menu'] = 'File'
    before['before_state']['fields']['focus'] = 'editor'
    module.last_action = lambda: deepcopy(before)
    state = {'fields': {'focus': 'editor', 'open_menu': current_menu}}
    check = intent_check(module, row, 'observed', key='open_menu', quote='No menu is open')
    try:
        original = deepcopy(state)
        if current_menu is None:
            with pytest.raises(ValueError, match='changed before/current') as error:
                module.validate_action_check(check, frame='2', visible_texts=['Focus: editor', 'No menu is open'], current_state=state)
            detail = json.loads(str(error.value).split('established: ', 1)[1])
            assert detail['unknown_or_missing_state_keys'] == ['open_menu']
            assert detail['provided_state_keys'] == ['open_menu'] and detail['changed_field_keys'] == []
            assert not detail['actor_prose_omitted'] and 'Do not copy actor prose' in detail['repair']
        else:
            module.validate_action_check(check, frame='2', visible_texts=['Focus: editor', 'No menu is open'], current_state=state)
            assert module.state_comparison(state)['changed_field_keys'] == ['open_menu']
        assert state == original
        before['before_state']['fields']['open_menu'] = None
        with pytest.raises(ValueError, match='changed before/current'):
            module.validate_action_check(check, frame='2', visible_texts=['Focus: editor', 'No menu is open'], current_state=state)
    finally:
        log.close()
        memory.close()


def test_absence_claim_does_not_allow_actor_prose_as_visible_evidence(tmp_path):
    prose = 'Close the menu by pressing Escape.'
    memory, log, module, row = intent_operation(tmp_path, prose)
    before = module.last_action()
    before['before_state']['fields']['open_menu'] = 'File'
    module.last_action = lambda: deepcopy(before)
    try:
        check = intent_check(module, row, 'observed', key='open_menu', quote=prose)
        with pytest.raises(ValueError, match='missing_visible_quotes'):
            module.validate_action_check(check, frame='2', visible_texts=['Focus: editor', 'No menu is open'],
                current_state={'fields': {'open_menu': {'status': 'absent'}}})
    finally:
        log.close()
        memory.close()


def test_observed_intent_requires_relevant_known_state_change_not_clock_or_new_keys(tmp_path):
    memory, log, module, row = intent_operation(tmp_path, 'Maximize this window.')
    try:
        state = {'fields': {'window_state': 'maximized', 'menu': 'closed', 'focus': 'editor', 'clock': '2'}}
        check = intent_check(module, row, 'observed', quote='Window: maximized')
        module.validate_action_check(check, frame='2', visible_texts=['Focus: editor', 'Window: maximized'], current_state=state)
        for key in ('clock', 'renamed_window_state'):
            bad = intent_check(module, row, 'observed', key=key, quote='Window: maximized')
            with pytest.raises(ValueError, match='changed before/current'):
                module.validate_action_check(bad, frame='2', visible_texts=['Focus: editor', 'Window: maximized'], current_state=state)
        ambiguous = intent_check(module, row, 'unknown')
        module.validate_action_check(ambiguous, frame='2', visible_texts=['Focus: editor'], current_state=state)
        ambiguous['assessment'] = 'observed'
        with pytest.raises(ValueError, match='agree with its individual checks'):
            module.validate_action_check(ambiguous, frame='2', visible_texts=['Focus: editor'], current_state=state)
    finally:
        log.close()
        memory.close()


def test_intent_omits_whole_oversized_prose_without_inventing_success_or_mutating_history(tmp_path):
    import hashlib
    prose = '原始执行意图' * 100
    memory, log, module, row = intent_operation(tmp_path, prose)
    try:
        value = module.verification_action(max_bytes=4000)
        intent = value['actor_intent']
        assert intent['text'] is None and intent['text_omitted']
        assert intent['original_text_bytes'] == len(prose.encode())
        assert intent['original_text_sha256'] == hashlib.sha256(prose.encode()).hexdigest()
        assert len(dumps(value).encode()) <= 4000 and module.event(row['decision_id'])['response'] == prose
        check = intent_check(module, row, 'observed', quote='Window: maximized')
        state = {'fields': {'window_state': 'maximized', 'focus': 'editor'}}
        with pytest.raises(ValueError, match='exact admitted actor prose'):
            module.validate_action_check(check, frame='2', visible_texts=['Focus: editor', 'Window: maximized'], current_state=state)
        module.validate_action_check(intent_check(module, row, 'unknown'), frame='2',
            visible_texts=['Focus: editor'], current_state=state)
    finally:
        log.close()
        memory.close()


def test_batch_intent_remains_decision_scoped_and_capture_does_not_replace_operation(tmp_path):
    prose = 'Click the control, then capture evidence of its effect.'
    memory, log, module, row = intent_operation(tmp_path, prose, capture=True)
    try:
        value = module.verification_action()
        assert value['transition_id'] == row['id'] and value['actor_intent']['command_count'] == 2
        assert value['actor_intent']['command_index'] == 0
        assert value['actor_intent']['scope'] == 'whole_decision_model_proposal_not_verified_effect'
        assert value['actor_intent']['text'] == prose and value['latest_evidence_capture']['transition_id'] != row['id']
    finally:
        log.close()
        memory.close()


def test_serialized_native_message_without_prose_does_not_invent_intent(tmp_path):
    response = dumps({'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'original-click'}]})
    memory, log, module, row = intent_operation(tmp_path, response)
    try:
        assert 'actor_intent' not in module.verification_action()
        check = intent_check(module, row, 'unknown')
        check['checks'].pop()
        check['assessment'] = 'observed'
        module.validate_action_check(check, frame='2', visible_texts=['Focus: editor'],
            current_state={'fields': {'window_state': 'normal', 'focus': 'editor'}})
        assert module.event(row['decision_id'])['response'] == response
    finally:
        log.close()
        memory.close()


def test_verification_shares_exact_source_image_before_dropping_known_state_or_intent(tmp_path):
    prose = 'Focus the application before opening its File menu. ' * 20
    memory, log, module, row = intent_operation(tmp_path, prose)
    try:
        full = module.verification_action(max_bytes=20000)
        original_event = deepcopy(module.event(row['id']))
        budget = len(dumps(full).encode()) - 1
        projected = module.verification_action(max_bytes=budget)
        assert len(dumps(projected).encode()) <= budget
        reference = projected['executed_tool_input']['source_frame_evidence_ref']
        assert reference == {'record_ref': '#/before_image'}
        resolved = deepcopy(projected)
        resolved['executed_tool_input']['source_frame_evidence_ref'] = deepcopy(projected['before_image'])
        assert resolved == full
        assert projected['before_state'] == full['before_state']
        assert projected['actor_intent']['text'] == prose
        assert projected['omitted_before_state_keys'] == []
        assert module.event(row['id']) == original_event
        assert module.event(row['decision_id'])['response'] == prose
    finally:
        log.close()
        memory.close()


def test_wide_and_legacy_verification_packets_keep_full_source_frame_reference(tmp_path):
    memory, log, module, row = intent_operation(tmp_path, 'Focus this application.')
    try:
        wide = module.verification_action(max_bytes=20000)
        assert wide['executed_tool_input']['source_frame_evidence_ref'] == wide['before_image']
        assert 'record_ref' not in wide['executed_tool_input']['source_frame_evidence_ref']
        module.intent_verification_v12 = False
        legacy = module.verification_action(max_bytes=20000)
        assert 'actor_intent' not in legacy
        assert legacy['executed_tool_input']['source_frame_evidence_ref'] == legacy['before_image']
        legacy['before_state']['fields'] = {}
        legacy['omitted_before_state_keys'] = list(wide['before_state']['fields'])
        with pytest.raises(ValueError, match='exact current-action verification references'):
            module.verification_action(max_bytes=len(dumps(legacy).encode()) - 1)
    finally:
        log.close()
        memory.close()


def test_shared_verification_frame_does_not_truncate_native_parameters_or_bypass_capacity(tmp_path):
    memory, log, module, row = intent_operation(tmp_path, 'Enter the original text.')
    try:
        original = module.last_action()
        original['executed_tool_input']['parameters'] = {'action': 'type', 'text': 'literal input ' * 500}
        module.last_action = lambda: deepcopy(original)
        with pytest.raises(ValueError, match='exact current-action verification references'):
            module.verification_action(max_bytes=4000)
        assert module.last_action()['executed_tool_input']['parameters'] == original['executed_tool_input']['parameters']
        with pytest.raises(ValueError, match='exact current-action verification references'):
            module.verification_action(max_bytes=1)
    finally:
        log.close()
        memory.close()


@pytest.mark.parametrize('intent_assessment,provided,required', [
    ('unknown', 'observed', 'unknown'), ('not_observed', 'observed', 'not_observed'),
    ('observed', 'unknown', 'observed')])
def test_aggregate_repair_feedback_names_exact_marks_without_rewriting_them(
        tmp_path, intent_assessment, provided, required):
    memory, log, module, row = intent_operation(tmp_path, 'Maximize this window.')
    try:
        quote = 'Window: maximized' if intent_assessment == 'observed' else 'Window: normal'
        state = {'fields': {'window_state': 'maximized' if intent_assessment == 'observed' else 'normal',
                            'menu': 'closed', 'focus': 'editor'}}
        candidate = intent_check(module, row, intent_assessment, quote=quote)
        candidate['assessment'] = provided
        original = deepcopy(candidate)
        with pytest.raises(ValueError, match='agree with its individual checks: ') as error:
            module.validate_action_check(candidate, frame='2', visible_texts=['Focus: editor', quote],
                                         current_state=state)
        detail = json.loads(str(error.value).split(': ', 1)[1])
        assert detail['provided_assessment'] == provided and detail['required_assessment'] == required
        assert detail['individual_checks'] == [{'kind': c['kind'], 'assessment': c['assessment']}
                                               for c in candidate['checks']]
        assert 'not the whole task' in detail['rule'] and len(str(error.value).encode()) < 1000
        assert candidate == original and module.effects == {}
        regenerated = deepcopy(candidate)
        regenerated['assessment'] = required
        module.validate_action_check(regenerated, frame='2', visible_texts=['Focus: editor', quote],
                                     current_state=state)
        assert candidate == original
    finally:
        log.close()
        memory.close()


@pytest.mark.parametrize('candidate', [
    {'action': 'click', 'coordinate': [674, 253]},
    {'action_check': {'frame_id': 'frame'}, 'last_action': {}, 'frame': {},
     'mandatory_core': {}, 'entity_records': [], 'semantic_schema': {}}])
def test_perception_envelope_repairs_actor_output_and_input_echo_with_exact_fields(candidate):
    from ui_kobe.osworld.taskviews_feedback import validate_feedback_envelope
    original = deepcopy(candidate)
    with pytest.raises(ValueError, match='response envelope invalid') as error:
        validate_feedback_envelope(candidate)
    detail = json.loads(str(error.value).split(': ', 1)[1])
    assert set(detail['missing_root_fields']) == {'summary', 'elements', 'semantics', 'ui_state'} | (
        {'action_check'} if 'action_check' not in candidate else set())
    assert set(detail['unexpected_root_fields']) == set(candidate) - {'action_check'}
    assert 'perception, not the GUI actor' in detail['repair'] and candidate == original


def test_perception_envelope_error_bounds_whole_names_and_preserves_strict_guard():
    from ui_kobe.osworld.taskviews_feedback import validate_feedback_envelope
    raw = {('长' * 100) + str(i): i for i in range(50)}
    with pytest.raises(ValueError) as error:
        validate_feedback_envelope(raw)
    assert len(str(error.value).encode()) < 2000 and '"omitted_received_field_names":50' in str(error.value)
    good = {'summary': '', 'elements': [], 'semantics': {'entities': [], 'claims': []},
            'ui_state': {'page_id': None, 'fields': {}}, 'action_check': None}
    validate_feedback_envelope(good)
    validate_feedback_envelope({**good, 'subgoal_review': None})
    with pytest.raises(ValueError):
        validate_feedback_envelope({**good, 'last_action': {}})


def test_perception_wrong_role_and_echo_repair_complete_full_fixture_with_original_limit(tmp_path):
    result = run_fixture(tmp_path/'schema-repair', bad_perception_envelopes=2)
    assert result['terminal'] and not result['paused'] and result['fixture_score'] == 1.0
    assert result['official_score'] is None and not result['model_ability_measured']
    assert result['compiler_checks'] == 7 and result['roles']['perception'] == 9


def duplicated_local_reference_module():
    from types import SimpleNamespace
    module = ExecutionModules.__new__(ExecutionModules)
    module.memory = SimpleNamespace(snapshot=SimpleNamespace(revision='current'))
    module.modules = {'stable': {'id': 'stable'}}
    module.active, module.previous_revision = 'stable', 'previous'
    module.new_events, module.gaps = [], []
    prefix = '/saved-original/' + 'p' * 280
    record = {'transition_id': 'edge', 'source': 'before', 'target': 'after',
              'raw_ref': prefix + '/events.sqlite#edge', 'module_id': 'stable',
              'controller_receipt_ref': prefix + '/events.sqlite#edge', 'receipt_count': 1,
              'before_image': {'ref': prefix + '/before.png', 'sha256': 'a' * 64},
              'after_image': {'ref': prefix + '/after.png', 'sha256': 'b' * 64},
              'effect_status': 'unknown'}
    module.recent = [{**record, 'expected_change': {'kind': 'state'}}]
    module.unresolved = [{**record, 'error': 'Original unresolved failure'}]
    module.transition_packet = lambda record: deepcopy(record)
    module.last_action = lambda: deepcopy(module.recent[-1])
    return module


def resolve_projection_value(packet, value):
    if isinstance(value, dict) and set(value) == {'value_ref'}:
        target = packet
        for key in value['value_ref'].removeprefix('#/').split('/'):
            target = target[int(key)] if isinstance(target, list) else target[key]
        # References must terminate at an original concrete value, never a loop.
        assert not isinstance(target, dict) or set(target) != {'value_ref'}
        return deepcopy(target)
    if isinstance(value, dict):
        return {key: resolve_projection_value(packet, item) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_projection_value(packet, item) for item in value]
    return deepcopy(value)


def local_feedback_base():
    return {'protocol': 'taskviews-feedback-v10', 'frame_id': 'current-frame',
            'last_action_feedback': {'transition_id': 'edge', 'assessment': 'unknown'},
            'active_subgoal': {'id': 'stable', 'label': 'Create the requested object'},
            'next_strategy': {'advice': 'Locate the current control and verify its effect.'},
            'current_visible_evidence': {'elements': [{'text': 'Menu', 'role': 'button'}],
                'summary': 'Visible editor', 'omitted_elements': 0, 'summary_omitted': False,
                'grade': 'model_proposal', 'pointer_source': 'current_original_screenshot'}}


def test_actor_reference_sharing_retains_exact_distinct_edges_and_feedback():
    from kobe_views.execution_modules import ExecutionPacketBudgetError
    from ui_kobe.osworld.taskviews_feedback import _admit_execution_feedback
    module, base = duplicated_local_reference_module(), local_feedback_base()
    base['last_action_feedback']['raw_transition_ref'] = module.recent[0]['raw_ref']
    module.unresolved[0].update(transition_id='other-edge', raw_ref='/other/original#other-edge')
    original = deepcopy([base, module.recent, module.unresolved])
    with pytest.raises(ExecutionPacketBudgetError) as raised:
        module.packet(max_bytes=1, include_modules=False, share_duplicate_refs=True, share_exact_refs=True)
    floor = raised.value.projection
    # This envelope cannot fit even after whole visible labels yield. Its long
    # latest raw path is already concrete in protected actor feedback.
    minimal = deepcopy(base['current_visible_evidence'])
    minimal.pop('summary')
    minimal.update(elements=[], omitted_elements=1, summary_omitted=True)
    fixed = {**base, 'current_visible_evidence': minimal,
             'role_evidence': {'execution_modules': floor, 'strategy_review': True}, 'context_gaps': []}
    limit = len(dumps(fixed).encode()) - 80
    packet = _admit_execution_feedback(base, [], module, limit, strategy_review=True)
    projected = packet['role_evidence']['execution_modules']
    alias = projected['recent_transitions'][0]['raw_ref']
    assert alias == {'actor_packet_ref': '#/last_action_feedback/raw_transition_ref'}
    assert packet['last_action_feedback']['raw_transition_ref'] == original[1][0]['raw_ref']
    # A module-local receipt alias may terminate at the actor-root raw alias.
    receipt = projected['recent_transitions'][0]['controller_receipt_ref']
    assert receipt == {'value_ref': '#/recent_transitions/0/raw_ref'}
    assert projected['unresolved_failures'][0]['raw_ref'] == '/other/original#other-edge'
    assert projected['unresolved_failures'][0]['transition_id'] == 'other-edge'
    assert projected['unresolved_failures'][0]['error'] == original[2][0]['error']
    assert packet['last_action_feedback'] == base['last_action_feedback']
    assert packet['next_strategy'] == base['next_strategy'] and len(dumps(packet).encode()) <= limit
    assert [base, module.recent, module.unresolved] == original
    wide = _admit_execution_feedback(base, [], module, 20000, strategy_review=True)
    assert 'actor_packet_ref_scope' not in wide
    assert wide['role_evidence']['execution_modules']['recent_transitions'][0]['raw_ref'] == original[1][0]['raw_ref']
    with pytest.raises(ExecutionPacketBudgetError):
        _admit_execution_feedback(base, [], module, 1, strategy_review=True)


@pytest.mark.parametrize('mode', ['different-id', 'different-ref', 'short-ref', 'missing-id', 'already-aliased'])
def test_actor_reference_sharing_requires_exact_identity_and_concrete_profitable_value(mode):
    from ui_kobe.osworld.taskviews_feedback import _share_actor_action_reference
    projection = {'recent_transitions': [{'transition_id': 'edge', 'raw_ref': '/' + 'a' * 240}],
                  'unresolved_failures': []}
    feedback = {'transition_id': 'edge', 'raw_transition_ref': projection['recent_transitions'][0]['raw_ref']}
    if mode == 'different-id':
        feedback['transition_id'] = 'other'
    elif mode == 'different-ref':
        feedback['raw_transition_ref'] += '-different'
    elif mode == 'short-ref':
        projection['recent_transitions'][0]['raw_ref'] = feedback['raw_transition_ref'] = '/short'
    elif mode == 'missing-id':
        feedback.pop('transition_id')
    else:
        projection['recent_transitions'][0]['raw_ref'] = {'value_ref': '#/previous'}
    original = deepcopy([projection, feedback])
    result, shared = _share_actor_action_reference(projection, feedback)
    assert not shared and result == projection and [projection, feedback] == original


def test_reference_floor_error_exposes_exact_reduced_projection_without_mutating_history():
    from kobe_views.execution_modules import ExecutionPacketBudgetError
    module = duplicated_local_reference_module()
    original = deepcopy([module.recent, module.unresolved])
    with pytest.raises(ExecutionPacketBudgetError, match='latest action and unresolved failure') as raised:
        module.packet(max_bytes=1, include_modules=False, share_duplicate_refs=True, share_exact_refs=True)
    projection = raised.value.projection
    assert projection['recent_transitions'][0]['transition_id'] == original[0][0]['transition_id']
    assert projection['unresolved_failures'][0]['error'] == original[1][0]['error']
    assert [module.recent, module.unresolved] == original


@pytest.mark.parametrize('label,summary', [('Label ' * 50, 'Summary ' * 100),
                                         ('可见控件' * 60, '原始观察' * 150),
                                         ('Menu', 'Original summary ' * 120)])
def test_execution_identity_outlives_large_whole_labels_and_summary(label, summary):
    from kobe_views.execution_modules import ExecutionPacketBudgetError
    from ui_kobe.osworld.taskviews_feedback import _admit_execution_feedback
    module = duplicated_local_reference_module()
    failure = module.unresolved[0]
    failure.update(transition_id='different-failure', raw_ref=failure['raw_ref'] + '-failure',
                   controller_receipt_ref=failure['raw_ref'] + '-failure')
    base = local_feedback_base()
    base['current_visible_evidence'].update(elements=[{'text': label, 'role': 'button'},
                                                     {'text': 'Current input', 'role': 'textbox'}],
                                           summary=summary, omitted_elements=3)
    original = deepcopy([base, module.recent, module.unresolved])
    with pytest.raises(ExecutionPacketBudgetError) as raised:
        module.packet(max_bytes=1, include_modules=False, share_duplicate_refs=True, share_exact_refs=True)
    floor = raised.value.projection
    fixed = {**base, 'current_visible_evidence': None,
             'role_evidence': {'execution_modules': floor, 'strategy_review': True},
             'context_gaps': ['budget_omitted:input_policy']}
    limit = len(dumps(fixed).encode()) - len('null') + 300
    packet = _admit_execution_feedback(base, [('input_policy', 'Optional advice ' * 80)],
                                       module, limit, strategy_review=True)
    assert len(dumps(packet).encode()) <= limit
    projected = packet['role_evidence']['execution_modules']
    assert projected == floor
    decoded = resolve_projection_value(projected, projected)
    for collection, expected in zip(('recent_transitions', 'unresolved_failures'), original[1:], strict=True):
        row = decoded[collection][0]
        assert row['transition_id'] == expected[0]['transition_id']
        for key in ('raw_ref', 'controller_receipt_ref', 'before_image', 'after_image', 'effect_status'):
            assert row[key] == expected[0][key]
    assert decoded['unresolved_failures'][0]['error'] == 'Original unresolved failure'
    assert packet['last_action_feedback'] == base['last_action_feedback']
    assert packet['next_strategy'] == base['next_strategy'] and packet['active_subgoal'] == base['active_subgoal']
    visible = packet['current_visible_evidence']
    assert visible['summary_omitted'] and 'summary' not in visible
    assert all(item in base['current_visible_evidence']['elements'] for item in visible['elements'])
    assert visible['omitted_elements'] + len(visible['elements']) == 5
    assert visible['pointer_source'] == 'current_original_screenshot'
    assert [base, module.recent, module.unresolved] == original


def test_execution_admission_keeps_wide_packet_identical_and_real_floor_strict():
    from ui_kobe.osworld.taskviews_feedback import _admit, _admit_execution_feedback
    module, base = duplicated_local_reference_module(), local_feedback_base()
    optional = [('input_policy', 'Optional advice')]
    expected = _admit({**base, 'role_evidence': {'execution_modules': module.packet(
        max_bytes=6000, include_modules=False, share_duplicate_refs=True, share_exact_refs=True),
        'strategy_review': False}}, optional, 20000)
    assert _admit_execution_feedback(base, optional, module, 20000, strategy_review=False) == expected
    with pytest.raises(ValueError, match='latest action and unresolved failure'):
        _admit_execution_feedback(base, optional, module, 700, strategy_review=False)
    base['last_action_feedback']['must_keep'] = 'Original mandatory warning' * 300
    with pytest.raises(ValueError, match='latest action and unresolved failure'):
        _admit_execution_feedback(base, optional, module, 2000, strategy_review=False)


def test_execution_admission_does_not_convert_unrelated_module_errors_to_label_omission():
    from types import SimpleNamespace
    from ui_kobe.osworld.taskviews_feedback import _admit_execution_feedback
    def broken(**kwargs):
        raise ValueError('Original missing execution identity')
    with pytest.raises(ValueError, match='Original missing execution identity'):
        _admit_execution_feedback(local_feedback_base(), [], SimpleNamespace(packet=broken),
                                  8000, strategy_review=False)


def test_reference_floor_uses_compact_own_policy_before_dropping_actual_evidence():
    import hashlib
    from kobe_views.execution_modules import ExecutionPacketBudgetError
    from ui_kobe.osworld.taskviews_feedback import _admit_execution_feedback, LOCAL_EXECUTION, LOCAL_EXECUTION_COMPACT
    module, base = duplicated_local_reference_module(), local_feedback_base()
    module.unresolved[0].update(transition_id='different', raw_ref=module.unresolved[0]['raw_ref']+'-other',
                                controller_receipt_ref=module.unresolved[0]['raw_ref']+'-other')
    base['execution_boundary'] = LOCAL_EXECUTION
    base['stalled_pointer_actions'] = [{'parameters': {'action': 'left_click', 'coordinate': [20, 30]},
                                       'transition_ids': ['edge', 'different'], 'assessment': 'unknown'}]
    original = deepcopy([base, module.recent, module.unresolved])
    with pytest.raises(ExecutionPacketBudgetError) as raised:
        module.packet(max_bytes=1, include_modules=False, share_duplicate_refs=True, share_exact_refs=True)
    fixed = {**base, 'current_visible_evidence': None,
             'role_evidence': {'execution_modules': raised.value.projection, 'strategy_review': True},
             'context_gaps': []}
    limit = len(dumps(fixed).encode()) - 300
    packet = _admit_execution_feedback(base, [], module, limit, strategy_review=True)
    assert len(dumps(packet).encode()) <= limit
    assert packet['execution_boundary'] == LOCAL_EXECUTION_COMPACT
    assert packet['execution_boundary_original_sha256'] == hashlib.sha256(LOCAL_EXECUTION.encode()).hexdigest()
    for key in ('last_action_feedback', 'active_subgoal', 'next_strategy', 'stalled_pointer_actions'):
        assert packet[key] == base[key]
    projected = packet['role_evidence']['execution_modules']
    decoded = resolve_projection_value(projected, projected)
    for key, records in zip(('recent_transitions', 'unresolved_failures'), original[1:], strict=True):
        for field in ('transition_id', 'raw_ref', 'controller_receipt_ref', 'before_image', 'after_image', 'effect_status'):
            assert decoded[key][0][field] == records[0][field]
    assert [base, module.recent, module.unresolved] == original


def test_execution_boundary_wide_packet_keeps_original_policy_and_no_variant():
    from ui_kobe.osworld.taskviews_feedback import _admit_execution_feedback, LOCAL_EXECUTION
    module, base = duplicated_local_reference_module(), local_feedback_base()
    base['execution_boundary'] = LOCAL_EXECUTION
    packet = _admit_execution_feedback(base, [], module, 20000, strategy_review=False)
    assert packet['execution_boundary'] == LOCAL_EXECUTION and 'execution_boundary_variant' not in packet


def test_execution_admission_never_compacts_arbitrary_instruction_or_warning():
    from ui_kobe.osworld.taskviews_feedback import _admit_execution_feedback
    module, base = duplicated_local_reference_module(), local_feedback_base()
    base['execution_boundary'] = 'Original unrecognized instruction' * 300
    with pytest.raises(ValueError, match='latest action and unresolved failure'):
        _admit_execution_feedback(base, [], module, 4000, strategy_review=False)


def test_exact_value_refs_keep_distinct_latest_and_failure_edges_under_budget():
    module = duplicated_local_reference_module()
    failure = module.unresolved[0]
    failure.update(transition_id='older-failure', source='earlier', target='earlier-post',
                   raw_ref=failure['raw_ref'] + '-older',
                   controller_receipt_ref=failure['raw_ref'] + '-older')
    failure['after_image'] = deepcopy(module.recent[0]['before_image'])
    original = deepcopy([module.recent, module.unresolved])
    full = module.packet(max_bytes=20000, include_modules=False)
    budget = len(dumps(full).encode()) - 500
    with pytest.raises(ValueError, match='latest action and unresolved failure'):
        module.packet(max_bytes=budget, include_modules=False, share_duplicate_refs=True)
    packet = module.packet(max_bytes=budget, include_modules=False,
                           share_duplicate_refs=True, share_exact_refs=True)
    assert len(dumps(packet).encode()) <= budget
    decoded = resolve_projection_value(packet, packet)
    for collection in ('recent_transitions', 'unresolved_failures'):
        for actual, expected in zip(decoded[collection], full[collection], strict=True):
            for key in ('transition_id', 'source', 'target', 'raw_ref', 'controller_receipt_ref',
                        'receipt_count', 'before_image', 'after_image', 'effect_status'):
                assert actual[key] == expected[key]
    assert decoded['unresolved_failures'][0]['error'] == 'Original unresolved failure'
    assert decoded['recent_transitions'][0]['transition_id'] != decoded['unresolved_failures'][0]['transition_id']
    assert packet['projection_omissions']['shared_exact_reference_values'] >= 2
    assert [module.recent, module.unresolved] == original
    with pytest.raises(ValueError, match='latest action and unresolved failure'):
        module.packet(max_bytes=1, include_modules=False, share_duplicate_refs=True, share_exact_refs=True)
    assert [module.recent, module.unresolved] == original


def test_exact_value_sharing_keeps_wide_and_legacy_packets_unchanged():
    module = duplicated_local_reference_module()
    original = module.packet(max_bytes=20000, include_modules=False)
    assert module.packet(max_bytes=20000, include_modules=False,
                         share_duplicate_refs=True, share_exact_refs=True) == original
    assert 'value_ref' not in dumps(original)


@pytest.mark.parametrize('different', ['ref', 'sha256', 'bytes'])
def test_exact_image_sharing_never_merges_nonidentical_evidence(different):
    before = {'ref': '/original/' + 'p' * 200, 'sha256': 'a' * 64, 'bytes': 100}
    after = deepcopy(before)
    after[different] = 101 if different == 'bytes' else after[different] + '-different'
    packet = {'recent_transitions': [{'transition_id': 'one', 'before_image': before}],
              'unresolved_failures': [{'transition_id': 'two', 'after_image': after}]}
    original = deepcopy(packet)
    assert not ExecutionModules._share_packet_reference(packet)
    assert packet == original


def test_shared_image_resolves_to_concrete_value_without_changing_either_edge():
    image = {'ref': '/original/' + 'p' * 200, 'sha256': 'a' * 64}
    packet = {'recent_transitions': [{'transition_id': 'one', 'before_image': deepcopy(image)}],
              'unresolved_failures': [{'transition_id': 'two', 'after_image': deepcopy(image)}]}
    original = deepcopy(packet)
    assert ExecutionModules._share_packet_reference(packet)
    assert packet['unresolved_failures'][0]['after_image'] == {
        'value_ref': '#/recent_transitions/0/before_image'}
    assert resolve_projection_value(packet, packet) == original
    assert not ExecutionModules._share_packet_reference(packet)


def test_local_failure_shared_refs_reconstruct_exact_fields_without_copying_optional_differences():
    module = duplicated_local_reference_module()
    original = deepcopy([module.recent, module.unresolved])
    full = module.packet(max_bytes=20000, include_modules=False)
    budget = len(dumps(full).encode()) - 400
    with pytest.raises(ValueError, match='latest action and unresolved failure'):
        module.packet(max_bytes=budget, include_modules=False)
    packet = module.packet(max_bytes=budget, include_modules=False, share_duplicate_refs=True)
    assert len(dumps(packet).encode()) <= budget
    alias = packet['unresolved_failures'][0]
    assert alias['record_ref'] == '#/recent_transitions/0' and alias['transition_id'] == 'edge'
    shared = packet['recent_transitions'][0]
    resolved = {key: deepcopy(shared[key]) for key in alias['shared_fields']}
    resolved.update({key: value for key, value in alias.items() if key not in {'record_ref', 'shared_fields'}})
    assert resolved == full['unresolved_failures'][0]
    assert 'expected_change' not in resolved and resolved['error'] == 'Original unresolved failure'
    assert packet['projection_omissions']['shared_duplicate_reference_fields'] == 1
    assert [module.recent, module.unresolved] == original
    assert module.packet(max_bytes=20000, include_modules=False) == full
    with pytest.raises(ValueError, match='latest action and unresolved failure'):
        module.packet(max_bytes=1, include_modules=False, share_duplicate_refs=True)


@pytest.mark.parametrize('mismatch', ['transition_id', 'controller_receipt_ref', 'before_image'])
def test_local_reference_sharing_rejects_different_identity_image_or_receipt(mismatch):
    module = duplicated_local_reference_module()
    if mismatch == 'before_image':
        module.unresolved[0][mismatch] = {**module.unresolved[0][mismatch], 'sha256': 'different'}
    else:
        module.unresolved[0][mismatch] = 'different-original-value'
    original = deepcopy([module.recent, module.unresolved])
    full = module.packet(max_bytes=20000, include_modules=False)
    with pytest.raises(ValueError, match='latest action and unresolved failure'):
        module.packet(max_bytes=len(dumps(full).encode()) - 400, include_modules=False, share_duplicate_refs=True)
    assert [module.recent, module.unresolved] == original
