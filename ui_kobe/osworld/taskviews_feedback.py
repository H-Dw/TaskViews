"""Event-driven TaskViews with last-action evidence ahead of optional advice.

The original actor is the only GUI writer. All semantic/action assessments in
this projection are model proposals, never official scores or checkpoint gates.
"""
from __future__ import annotations

import base64
import hashlib

from kobe_views.model import dumps, plain
from . import telemetry
from .actor_context import available_context_bytes
from .agent import bounded_visual_evidence
from .task_control import SEMANTIC_PERCEPTION, CONTROLLER, ADVISER


ACTION_READ = """Also return action_check=null when no last_action is supplied. Otherwise return
action_check={transition_id,target_observation_id,frame_id,assessment,checks}, copying
the three IDs from action_check_binding exactly. assessment is observed|not_observed|unknown.
action_check_binding.target_observation_id is the verified operation's post
observation (last_action.target). latest_evidence_capture.target_observation_id
belongs to a later screenshot and is evidence only: never substitute its ID.
Use the supplied binding's current frame_id while assessing the original operation.
checks is 1..4 {kind:focus|text|submission|object|state,assessment,quotes:[literal
visible text]}. Verify the LAST ACTION's expected change, not all remaining goals.
last_action selects the last executed operation excluding wait and screenshot.
A subsequent wait/screenshot is later observation, not a new GUI input or task progress; retain its
original refs, and verify the supplied operation against the current image.
A click does not prove focus; typing does not prove submission; Return does not
prove an object exists. Describe the intended control/focus, exact input and
submitted object separately when visible. Use unknown when the screenshot cannot
establish the effect. Never turn controller return codes or clock changes into
visual success. observed/not_observed require visible quotes. Every quote must
occur literally in this same response's summary or elements; report only text
actually visible in the current image. A dialog/control label omitted from your
elements/summary is not a usable quote. Use unknown for a visually unclear effect,
never invent a label or report a receipt as proof. Include the supplied expected_change.kind;
Also return ui_state={page_id,fields} with concise current control/focus, input,
location, selected item, visible result and document title when visible; unknown
values are null. Visible absence is different from unknown: when this current
image establishes that a menu/dialog/object is absent, use {status:'absent'} as
that field's whole value and describe the absence in summary. Do not convert
uncertainty to absence. Copy supplied before_state field keys when still relevant.
For a click/key/submission to be observed, at least one known field must actually
change from before_state. An already selected filename or static label is not
evidence this click worked. When no source state exists or nothing demonstrably
changed, use unknown/not_observed; never rename keys or invent a change.
executed_tool_input contains the original parameters and their original frame
contract, not suggested new pointer coordinates. Re-ground the intended control
in the current screenshot; never interpret those screen pixels as app mathematics.
Its source_frame_evidence_ref may be {record_ref:'#/before_image'}: that exact
same-packet reference resolves to last_action.before_image, not another frame.
text checks also require focus. For submission, include a separate kind:'object'
check for the resulting object, with exactly kind, assessment, quotes. Do not add
object/result fields to a kind:'submission' check; unknown object evidence stays unknown.
When last_action.actor_intent is supplied, include exactly one additional check
{kind:'intent',assessment,quotes:[literal visible text],state_keys:[ui_state field keys]}.
Read the original actor prose as a decision-level proposal, not a verified effect.
Identify the intended result attributable to this specific command. A batch's
whole intention is not a per-command promise; use unknown if attribution is unclear.
Check that result separately from focus/menu changes. For example, closing a menu
does not establish that the intended window state changed. Observed intent must
name 1..4 keys whose known values changed from supplied before_state to current
ui_state, specifically measuring the intended result, not an unrelated change.
Copy existing keys; do not fabricate or rename a key to manufacture success.
Use unknown when the original prose was wholly omitted, or the relevant before
state/result is unavailable. not_observed requires actual evidence of failed effect.
Other checks retain their original three fields. Aggregate intent with all checks:
an observed focus with unconfirmed intent must not become overall observed.
Compute action_check.assessment from ALL individual checks: any not_observed
means not_observed; otherwise any unknown means unknown; otherwise observed.
This is this operation's assessment, not whether the entire task is finished.
Optional subgoal_review={subgoal_id,
change_needed:bool,quotes:[visible text]} requests a fresh plan only when the
current subgoal needs review; it does not certify task completion.
Visible application mathematics may use a typed application_math value; image
pixels and GUI reference handles do not establish a mathematical constraint.
For a literally visible algebra object use value={kind:'application_math',
space:'cartesian',object_label:'P1',coordinates:[...],visible_text:'P1 = (...)'}.
visible_text must exactly match an element's displayed text and the claim locator;
the numeric components must match that text. Do not derive an axis from this type,
or use it for screen/pointer coordinates. All accepted math remains a proposal."""

FEEDBACK_RESPONSE = """You are the perception reader, not the GUI executor.
Return a NEW evidence response whose root fields are exactly summary, elements,
semantics, ui_state, action_check; only subgoal_review is optional.
summary is a concise current-image description, elements are its literal visible
labels/boxes, semantics={entities,claims}, ui_state={page_id,fields}, and
action_check follows the supplied binding and check rules below. Unknown state
is null. Do not emit action/coordinate commands: you have no GUI execution tools.
The user message is READ-ONLY INPUT CONTEXT, not an output template. Do not echo
frame, mandatory_core, entity_records, semantic_schema, last_action, actor_intent,
context_gaps, or image references as root response fields. Preserve the input
IDs only inside the specified evidence/check fields. A rejected response is
not accepted evidence; regenerate the complete response in this output schema."""


def validate_feedback_envelope(raw):
    """Keep the strict schema, but tell a repairing reader exactly what failed."""
    required = {'summary', 'elements', 'semantics', 'action_check', 'ui_state'}
    allowed = required | {'subgoal_review'}
    if isinstance(raw, dict) and required <= set(raw) <= allowed:
        return
    keys = list(raw) if isinstance(raw, dict) else []
    named = [key for key in keys if isinstance(key, str) and len(key.encode()) <= 80][:16]
    detail = {'required_root_fields': sorted(required), 'optional_root_fields': ['subgoal_review'],
        'missing_root_fields': sorted(required - set(keys)),
        'unexpected_root_fields': sorted(key for key in named if key not in allowed),
        'omitted_received_field_names': len(keys) - len(named),
        'received_type': type(raw).__name__,
        'repair': 'Return NEW current-image summary/elements/semantics/ui_state/action_check. '
                  'This is perception, not the GUI actor. Do not issue action/coordinate commands '
                  'or echo the read-only input packet. Regenerate the complete required response; '
                  'do not silently delete fields or treat input context as newly observed evidence.'}
    raise ValueError('Feedback perception response envelope invalid: ' + dumps(detail))

STABLE_PLAN = """For this protocol return stage, needs, subgoal_id and, on the first
plan only, subgoals:[{id,label,dependencies:[earlier goal IDs]}]. Derive 1..8 small
subgoals and their dependencies from the original user goal, not screen anchors
or role names. Copy immutable IDs/labels/dependencies on later plans. Select an
existing subgoal_id. Role/anchor changes do not create another subgoal. Do not
mark a goal complete from a receipt or a model proposal. Prefer one executor
need; request planner only at initial planning, a stage change, or an unresolved
action/focus failure. Last-action verification is already part of perception;
do not request another global verifier on each step. When analysis_triggers includes
consecutive_unconfirmed_state, assign a planner need for one fresh strategy and
visible verification; varying native parameters alone do not establish progress."""

PLANNING = """Plan a short next strategy for this stable subgoal and its most recent
action checks. Repeated unconfirmed input/clicks require re-observing the control,
focus and input contents before another blind attempt. Give no pointer coordinates
without the current image.
When pointer grounding remains uncertain, consider the application's normal
keyboard navigation/shortcuts from its visible state, rather than another guess.
When pointer_recovery_required is true, plan one normal keyboard recovery
operation and its visible verification; further pointer guesses are rejected
until an observed state change clears the earlier cycle. Do not guess a shortcut.
Establish application focus before a dependent shortcut. A visible window alone
does not prove focus. Use the visible guest desktop's keyboard conventions.
If failed_keyboard_actions is present, do not repeat those exact keys; plan a
different ordinary application recovery and verify its effect first.
failed_pointer_actions are original parameters, not new target locations.
A failed_intent_after_return_to_source_page warning retains failed destination
operations even when a window recovery was observed. Returning to the source
application does not make that earlier menu/control click valid. Re-ground a
different ordinary route and verify its intended result, not just a window change.
When a folder click has no visible effect, consider normal dialog keyboard
location/full-requested-path navigation. Verify the resulting folder and filename
before confirmation; do not substitute a guessed pointer coordinate.
For an uncertain click, plan a single operation followed by a fresh observation
before dependent typing/submission. A save dialog has separate filename, folder
and confirmation effects; do not certify all three from one unchanged label.
Distinguish GUI image handles, mathematical objects,
and the task's stated constraints; do not infer an axis from image corners.
If using a mathematical inference, also return math_hypotheses:[{statement,
basis:[literal visible text],status:'hypothesis'}]. Each basis must be quoted
from the current visible evidence. A hypothesis is not a verified fact or an
instruction to bypass missing evidence. An explicitly requested future point or
formula is NOT a visible hypothesis. Keep such original task requirements in
goal_targets:[{quote:literal substring of original_task,status:'requested'}].
Use math_hypotheses=[] for a GUI input/save plan with no mathematical inference.
Do not claim a requested goal is already visible or mathematically verified.
When state_review is supplied, its shared field names describe comparable state
schemas, not known unchanged values. Several operations remain unconfirmed in the
same subgoal despite varying parameters. Re-observe the actual control and focus;
choose one different ordinary route with visible verification. Do not claim the
uncertainty proves failure or keep slightly offsetting a stale pointer guess.
prior_action_evidence contains literal checks from earlier frames in this same
subgoal, with immutable refs and fallible original intent. Keep an application's
earlier rejection in mind after its dialog disappears. Closing that dialog does
not make the rejected operation valid. Do not retry the same rejected route
unless new visible evidence addresses its cause; choose another ordinary route.
The native-key expected_change is generic: Return can dismiss a dialog rather
than submit text. Interpret original intent and before/current state together;
an absent object alone does not prove a failed dialog dismissal. Historical
quotes are not current visible math sources or verified facts."""

RECOVERY_PLAN = """Keep advice within 900 UTF-8 bytes. Give one next recovery
operation and its visible verification, without re-telling the whole task.
This concise advice is protected in the actor packet; longer supporting
evidence remains in the original report. Give only the immediate operation,
not a chain of focus, typing, submission and saving in one instruction. The actor
grounds its parameters in the current original screenshot; observer boxes and
old graph locators do not supply pointer targets. After ineffective preparatory
operations, consider a different ordinary route to the original task's next
deliverable, without dropping any original requirement. Do not supply a guessed
location or insist on repeating the failed preparation."""


LOCAL_EXECUTION = """Local execution boundary: the current original screenshot
is the source for locating controls. TaskViews classifications and observer
descriptions are model proposals, not pointer targets or executable plans.
Use the original task, current image, and the latest actual operation/effect
evidence to choose the next operation. Re-ground all parameters yourself.
Keep view classification and long graph reasoning outside this action loop.
Hover/tooltip text alone does not establish foreground focus or an overlapping
window. Distinguish application controls from the desktop launcher in the current
image; a window switch is not evidence that the intended menu opened.
An observed return to the source window does not validate an earlier failed
destination click; retained same-page failed-intent warnings still apply.
Verify uncertain focus/state changes before dependent operations. The original
native actor alone decides actions and termination. Do not let optional window
preparation become a prerequisite forever: after failed preparation, consider a
direct ordinary route to the requested deliverable in the accessible current UI.
Preserve every original requirement; do not claim an unobserved preparation worked.
Keep any prose before the tool call concise, describing this operation's intended
effect within 1200 UTF-8 bytes. The original tool arguments remain unchanged.
Longer prose is retained in history but wholly omitted from bounded verification;
that omission prevents the next reader from confirming your intended effect.
In execution_modules, {value_ref:'#/...'} resolves an identical receipt/image
value within that execution_modules object; distinct operation IDs remain distinct.
prior_action_evidence is earlier application feedback, not the current screenshot.
Dismissal or an empty current dialog does not validate the earlier rejected input;
reassess that evidence before repeating a submission. It does not choose an action."""

LOCAL_EXECUTION_COMPACT = """Locate controls only in the current original image.
Use the task/image/recent operations and effects; re-ground native parameters.
Classifications, observer text and old parameters are fallible, not locators or
plans. Keep long classification/graph reasoning outside this loop. Distinguish
app controls from the launcher. Tooltip/window returns do not prove focus,
menus or earlier destination effects. Observe uncertain focus/state before
dependent operations. Only the native actor acts/ends. Preserve every original
requirement including first preparation; never claim unseen success or let
failed preparation indefinitely delay accessible deliverables.
Intent prose <=1200 UTF-8 bytes; longer stays in history, wholly omitted from
verification, so intent is unknown. Original tool arguments stay unchanged.
In execution_modules, {value_ref:'#/...'} resolves an identical value within
that object; operation IDs stay distinct. prior_action_evidence is historical,
not current image/math, verified facts or an action choice. Dismissing a dialog
does not validate rejected input; reassess before repeating."""


def feedback_analysis_triggers(modules, raw, feedback, pointer_recovery):
    """A single unobserved action stays in the local actor/effect loop.

    Classification/planning is refreshed for initial needs, actual proposed
    page/subgoal changes, or repeated unconfirmed strategies. Last-action
    feedback is always delivered independently of this expensive refresh.
    """
    reasons = []
    if not modules or not modules.subgoals or not modules.selected_needs:
        reasons.append('initial_plan')
    page = raw.get('ui_state', {}).get('page_id')
    if modules and page is not None and modules.page_id is not None and page != modules.page_id:
        reasons.append('page_change')
    if (raw.get('subgoal_review') or {}).get('change_needed'):
        reasons.append('subgoal_review')
    if feedback.get('state_review'):
        reasons.append('consecutive_unconfirmed_state')
    elif feedback['strategy_review']:
        reasons.append('repeated_unconfirmed_strategy')
    if pointer_recovery:
        reasons.append('persistent_pointer_uncertainty')
    return reasons


def local_visible_evidence(raw, *, max_bytes=1600):
    """Project original labels as fallible evidence, never observer geometry.

    Full response, boxes, semantics and classification remain in the original
    telemetry/memory. Nothing here rescales or corrects a coordinate.
    """
    packet = {'elements': [], 'omitted_elements': len(raw['elements']), 'summary_omitted': True,
              'grade': 'model_proposal', 'pointer_source': 'current_original_screenshot'}
    for element in raw['elements']:
        label = {k: element[k] for k in ('text', 'role')}
        candidate = {**packet, 'elements': [*packet['elements'], label],
                     'omitted_elements': packet['omitted_elements'] - 1}
        if len(dumps(candidate).encode()) <= max_bytes:
            packet = candidate
    candidate = {**packet, 'summary': raw['summary'], 'summary_omitted': False}
    if len(dumps(candidate).encode()) <= max_bytes:
        packet = candidate
    if len(dumps(packet).encode()) > max_bytes:
        raise ValueError('Local visible-evidence envelope exceeds its budget')
    return packet


def validate_planner_report(report, *, visible_texts, original_task, string_list):
    if (not isinstance(report, dict) or not {'advice', 'needed_evidence'} <= set(report)
            or set(report) - {'advice', 'needed_evidence', 'math_hypotheses', 'goal_targets'}
            or not isinstance(report['advice'], str) or not string_list(report['needed_evidence'])
            or len(dumps(report).encode()) > 3000):
        raise ValueError('Invalid bounded stage planner report')
    targets = report.get('goal_targets', [])
    if not isinstance(targets, list) or len(targets) > 4:
        raise ValueError('Bound explicit requested goal targets')
    for target in targets:
        if (not isinstance(target, dict) or set(target) != {'quote', 'status'}
                or target['status'] != 'requested' or not isinstance(target['quote'], str)
                or not 1 <= len(target['quote']) <= 256 or target['quote'] not in original_task):
            raise ValueError('Requested future state requires an exact original_task quote, never a visible success claim')
    hypotheses = report.get('math_hypotheses', [])
    if not isinstance(hypotheses, list) or len(hypotheses) > 4:
        raise ValueError('Bound mathematical hypotheses')
    for index, claim in enumerate(hypotheses):
        if (not isinstance(claim, dict) or set(claim) != {'statement', 'basis', 'status'}
                or not isinstance(claim['statement'], str) or claim['status'] != 'hypothesis'
                or not string_list(claim['basis']) or not claim['basis']):
            raise ValueError('Mathematical hypotheses require statement/basis/status=hypothesis')
        missing = [q for q in claim['basis'] if not any(q in text for text in visible_texts)]
        if missing:
            # Give the model the specific rejected source and its proper source
            # category; retain the complete original assistant for regeneration.
            payload = {'candidate_index': index, 'missing_visible_basis': missing,
                'original_task_quote_matches': [q for q in missing if q in original_task],
                'reason': 'Requested future state is not a visible mathematical hypothesis',
                'repair': 'For exact original_task requirements use goal_targets/status=requested; '
                          'math_hypotheses needs actual current visible sources. Do not change numbers or bypass the guard.'}
            packed = dumps(payload)
            if len(packed.encode()) > 6000:
                payload['omitted_original_task_quote_matches'] = len(payload.pop('original_task_quote_matches'))
                packed = dumps(payload)
            raise ValueError('Mathematical source mismatch: ' + packed)


def _admit(base, optional, limit):
    """Reserve omission reports before admitting whole optional values."""
    optional = list(optional)
    result = plain(base)
    result['context_gaps'] = []
    if len(dumps(result).encode()) > limit:
        raise ValueError('Protected current-action evidence exceeds its admitted input budget')
    result['context_gaps'] = ['budget_omitted:' + key for key, _ in optional]
    if len(dumps(result).encode()) > limit:
        raise ValueError('Protected current-action evidence and omission metadata exceed its admitted input budget')
    for key, value in optional:
        gaps = list(result['context_gaps'])
        gaps.remove('budget_omitted:' + key)
        candidate = {**result, key: plain(value), 'context_gaps': gaps}
        if len(dumps(candidate).encode()) <= limit:
            result = candidate
    return result


def _visible(raw):
    return [raw['summary'], *(e['text'] for e in raw['elements'])]


def _admit_execution_feedback(protected, optional, modules, limit, *, strategy_review, prior_evidence=None):
    """Reserve execution identity before supplementary current-frame labels.

    The current screenshot remains the pointer source. Only whole literal
    labels/summary can yield to the already reduced operation/receipt/image
    floor; mandatory warnings, subgoal and fresh strategy stay unchanged.
    """
    from kobe_views.execution_modules import ExecutionPacketBudgetError

    optional = list(optional)
    if prior_evidence and prior_evidence['records']:
        try:
            return _admit_execution_feedback({**protected, 'prior_action_evidence': prior_evidence},
                optional, modules, limit, strategy_review=strategy_review)
        except ExecutionPacketBudgetError:
            # Latest action/receipt/images outrank even earlier application
            # failures. Keep truthful whole-value omission when both cannot fit.
            optional.insert(0, ('prior_action_evidence', prior_evidence))
    gaps = ['budget_omitted:' + key for key, _ in optional]

    def envelope(projection):
        return {**protected, 'role_evidence': {'execution_modules': projection,
                'strategy_review': strategy_review}, 'context_gaps': gaps}

    budget = min(6000, limit - len(dumps(envelope(None)).encode()) + len('null'))
    try:
        projection = modules.packet(max_bytes=max(0, budget), include_modules=False,
                                    share_duplicate_refs=True, share_exact_refs=True)
    except ExecutionPacketBudgetError as exc:
        # No new capacity: redistribute the same admitted actor packet. This
        # projection is exposed only after all older/optional module detail and
        # exact duplicate values have already yielded to protected references.
        projection = exc.projection
        if len(dumps(projection).encode()) > 6000:
            raise
        fixed = {**envelope(projection), 'current_visible_evidence': None}
        visible_budget = limit - len(dumps(fixed).encode()) + len('null')
        original = protected['current_visible_evidence']
        visible = {key: plain(value) for key, value in original.items()
                   if key not in {'elements', 'summary'}}
        visible.update(elements=[], omitted_elements=original['omitted_elements'] + len(original['elements']),
                       summary_omitted=True)
        if len(dumps(visible).encode()) > visible_budget:
            if protected.get('execution_boundary') == LOCAL_EXECUTION:
                # Compact our fixed policy, never user/model evidence. Retain
                # complete warnings/advice and the real reference floor before
                # asking the actor to consume a redundant verbose instruction.
                return _admit_execution_feedback({**protected,
                    'execution_boundary': LOCAL_EXECUTION_COMPACT,
                    'execution_boundary_variant': 'compact_same_policy',
                    'execution_boundary_original_sha256': hashlib.sha256(LOCAL_EXECUTION.encode()).hexdigest()},
                    optional, modules, limit, strategy_review=strategy_review)
            raise
        for label in original['elements']:
            candidate = {**visible, 'elements': [*visible['elements'], plain(label)],
                         'omitted_elements': visible['omitted_elements'] - 1}
            if len(dumps(candidate).encode()) <= visible_budget:
                visible = candidate
        if 'summary' in original:
            candidate = {**visible, 'summary': original['summary'], 'summary_omitted': False}
            if len(dumps(candidate).encode()) <= visible_budget:
                visible = candidate
        protected = {**protected, 'current_visible_evidence': visible}
    return _admit({**protected, 'role_evidence': {'execution_modules': projection,
                  'strategy_review': strategy_review}}, optional, limit)


def _planner_input(core, feedback, subgoal, instruction, visible, assigned, limit):
    return _admit({'mandatory_core': core, 'action_feedback': feedback,
                   'subgoal': subgoal, 'original_task': instruction},
                  [('visible_text', visible), ('assigned_views', assigned)], limit)


def validate_recovery_consumers(needs, *, required):
    if required and not any(need['consumer'] == 'planner' for need in needs):
        raise ValueError('Assign a planner view for stalled-operation recovery before another executor proposal')


def build_feedback_views(owner, deadline):
    control, journal = owner.control, getattr(owner, 'execution_journal', None)
    limit = available_context_bytes(owner.actor_input_messages, label=owner.context_label,
                                    contract=owner.contract)
    # Avoid four expensive reads for a packet that cannot reach the actor.
    if limit < 2048:
        telemetry.emit('taskviews_analysis_skipped', reason='actor_input_admission', available_bytes=limit)
        owner.view_trace = {'protocol': 'taskviews-feedback-v10', 'analysis_skipped': 'actor_input_admission',
                            'available_actor_context_bytes': limit}
        if getattr(owner, 'checkpoint_reads', False):
            raise ValueError('Actor input cannot admit protected TaskViews feedback; preserve checkpoint before dispatch')
        return None
    if journal is not None and control.memory is None:
        control.directory = journal.directory / 'task-memory' / journal.episode_id
    control.initialize(owner.instruction)
    owner.sync_execution()
    modules = getattr(owner, 'modules', None)
    if modules:
        modules.compare_state_v10 = True
        modules.intent_verification_v12 = True
        modules.subgoal_state_review_v12 = True
        modules.returned_page_intent_v12 = True
    core, inventory = control._core(), control.inventory()
    frame = owner.frame.metadata['frame_id']
    last = modules.verification_action() if modules else None
    image = owner.frame.image
    screenshot = owner.frame.screenshot
    model_bytes = base64.b64decode(screenshot.data_url.split(',', 1)[1])
    protected = {'mandatory_core': core, 'frame': owner.frame.metadata, 'last_action': last,
                 'action_check_binding': modules.verification_binding(frame) if modules else None}
    request = _admit(protected, [('entity_records', inventory['entities']),
        ('semantic_schema', inventory['schema'])], min(control.budget, 14000))
    request['inventory_omissions_do_not_create_new_ids'] = True

    def validate_read(raw):
        validate_feedback_envelope(raw)
        bounded_visual_evidence({k: raw[k] for k in ('summary', 'elements')},
                                screenshot.model_width, screenshot.model_height)
        semantics = raw['semantics']
        if (not isinstance(semantics, dict) or set(semantics) != {'entities', 'claims'}
                or not isinstance(semantics['entities'], list) or len(semantics['entities']) > 32
                or not isinstance(semantics['claims'], list) or len(semantics['claims']) > 64):
            raise ValueError('Semantics requires <=32 entities and <=64 claims')
        control.memory.validate_proposal_identity(raw['semantics'])
        control.memory.validate_proposal_content(raw['semantics'], visible_texts=[e['text'] for e in raw['elements']])
        if modules:
            modules.validate_action_check(raw['action_check'], frame=frame, visible_texts=_visible(raw),
                                          current_state=raw['ui_state'])
        elif raw['action_check'] is not None:
            raise ValueError('No journal action to verify')
        if 'ui_state' in raw:
            state = raw['ui_state']
            from kobe_views.task_memory import _contains_geometry, _credential_safe
            if (not isinstance(state, dict) or set(state) != {'page_id', 'fields'}
                    or state['page_id'] is not None and (not isinstance(state['page_id'], str) or len(state['page_id']) > 256)
                    or not isinstance(state['fields'], dict) or len(state['fields']) > 32
                    or len(dumps(state).encode()) > 3000 or _contains_geometry(state)):
                raise ValueError('Invalid bounded semantic UI state')
            _credential_safe(state)
        review = raw.get('subgoal_review')
        if review is not None and (not isinstance(review, dict)
                or set(review) != {'subgoal_id', 'change_needed', 'quotes'}
                or not modules or review['subgoal_id'] not in modules.subgoals
                or type(review['change_needed']) is not bool or not control._strings(review['quotes'])
                or len(dumps(review).encode()) > 1000
                or review['change_needed'] and not review['quotes']
                or any(not any(q in text for text in _visible(raw)) for q in review['quotes'])):
            raise ValueError('Subgoal review requires an existing ID and visible evidence')

    prompt = (SEMANTIC_PERCEPTION + '\n' + FEEDBACK_RESPONSE + '\nFor this protocol action_check is required. '
        'Existing entity IDs/type/label and claim IDs are immutable. Inventories may omit older records; '
        'repair conflicts using the original records or omit redeclaration. A changed observation is new '
        'evidence, not an edit to an old claim ID. Identity repair lists conflicting_claim_records and '
        'changed_identity_fields; unchanged facts need not be redeclared. Never invent another identity '
        'for an unchanged fact to bypass a conflict or status. Keep <=8 entities/12 claims.\n'
        + ACTION_READ + '\n' + owner.frame.instruction)
    raw = owner.role('perception', prompt, request, image, deadline, validate_read)
    evidence, normalization = bounded_visual_evidence({k: raw[k] for k in ('summary', 'elements')},
                                                       screenshot.model_width, screenshot.model_height)
    core = control.observe(owner.instruction, frame, model_bytes, raw, evidence)
    admitted = control.observation_meta.get('semantic_proposals', {})
    if not admitted.get('accepted') or admitted.get('rejected'):
        raise ValueError('Current-frame feedback evidence rejected')
    if modules:
        modules.record_action_check(raw['action_check'], frame=frame, current_state=raw['ui_state'])
    if journal is not None and journal.current:
        state = raw['ui_state']
        journal.annotate(journal.current['id'], logical_page=state['page_id'], state_schema=state['fields'],
                         evidence_ref=control.observation_meta['screenshot_ref'], grade='model_proposal')
        owner.sync_execution()
    snapshot = control.memory.read()
    feedback = modules.feedback() if modules else {'strategy_review': False}
    page = raw.get('ui_state', {}).get('page_id')
    failed_keys = modules.stalled_keyboard_actions()
    pointer_recovery = len(modules.stalled_pointer_actions()) >= 2 or bool(failed_keys)
    reasons = feedback_analysis_triggers(modules, raw, feedback, pointer_recovery)
    if modules and page is not None:
        modules.page_id = page
        modules.save()

    def validate_plan(proposed):
        fields = {'stage', 'needs', 'subgoal_id'}
        if not isinstance(proposed, dict) or not fields <= set(proposed) or set(proposed) - fields - {'subgoals'}:
            raise ValueError('Stable controller requires stage, needs, subgoal_id')
        if not isinstance(proposed['stage'], str) or not 1 <= len(proposed['stage']) <= 256:
            raise ValueError('Invalid bounded stage')
        if modules is None:
            raise ValueError('Feedback protocol requires an execution journal')
        goals = proposed.get('subgoals', list(modules.subgoals.values()))
        modules.validate_subgoals(goals)
        if proposed['subgoal_id'] not in {g['id'] for g in goals}:
            raise ValueError('Select an existing stable subgoal')
        needs, _ = control._resolve_core_anchors(snapshot, core, proposed['needs'])
        control.views.validate_needs(snapshot, needs)
        if not any(n['consumer'] == 'executor' for n in needs):
            raise ValueError('Assign the executor')
        validate_recovery_consumers(needs, required=pointer_recovery or bool(feedback.get('state_review')))

    if reasons:
        short_feedback = {'last_action': modules.actor_feedback(),
            'repetition_count': feedback['repetition_count'], 'strategy_review': feedback['strategy_review'],
            'pointer_recovery_required': pointer_recovery,
            'failed_keyboard_actions': failed_keys,
            'failed_pointer_actions': modules.stalled_pointer_actions(),
            'prior_action_evidence': modules.prior_action_evidence(),
            'state_review': feedback.get('state_review'),
            'guidance': feedback.get('guidance')}
        controller_input = {'mandatory_core': core,
            'consumer_allowed_anchors': control.views.allowed_anchor_inventory(snapshot, limit=16),
            'frame': owner.frame.metadata, 'subgoals': list(modules.subgoals.values()) if modules else [],
            'action_feedback': short_feedback, 'analysis_triggers': reasons}
        proposed = owner.role('view_controller', CONTROLLER + '\n' + STABLE_PLAN,
                              controller_input, image, deadline, validate_plan)
        if 'subgoals' in proposed:
            modules.register_subgoals(proposed['subgoals'])
        needs, resolutions = control._resolve_core_anchors(snapshot, core, proposed['needs'])
        module = modules.select(proposed['stage'], needs, frame=frame,
                                ref=control.observation_meta['screenshot_ref'], subgoal_id=proposed['subgoal_id'])
    else:
        needs, resolutions = control._resolve_core_anchors(snapshot, core, modules.selected_needs)
        module = modules.active
        proposed = {'stage': modules.modules[module]['stage'], 'needs': needs,
                    'subgoal_id': modules.modules[module]['subgoal_id'], 'reused': True}
    # Reserve the protected feedback first, then materialize optional graph views.
    view_budget = max(512, min(8000, limit // 2))
    compiled = control.views.compile(snapshot, needs, view_budget, compact_purposes=True)
    control.views.dispatch(compiled)
    changes = modules.view_changes(compiled)
    advisers = {}
    planner_packet = control.views.packet_for('planner')
    if reasons and planner_packet['needs']:
        context = _planner_input(core, short_feedback, modules.subgoals[proposed['subgoal_id']],
                                 owner.instruction, _visible(raw), planner_packet, min(control.budget, 14000))
        def validate_planner(report):
            validate_planner_report(report, visible_texts=_visible(raw), original_task=owner.instruction,
                                    string_list=control._strings)
            if len(report['advice'].encode()) > 900:
                raise ValueError('Keep recovery advice within 900 UTF-8 bytes; provide one next operation and verification')
        report = owner.role('planner', ADVISER + '\n' + PLANNING + '\n' + RECOVERY_PLAN,
                            context, image, deadline, validate_planner)
        advisers['planner'] = {'report': report, 'grade': 'model_proposal', 'frame_id': frame}
        modules.report('planner', report, frame=frame)
        if 'assigned_views' in context:
            control.views.acknowledge('planner', compiled['dispatch_id'], snapshot.revision)
    # Verification is an action-bound part of the one current-frame read. It is
    # not another provider request and cannot mark a subgoal or episode complete.
    protected = {'protocol': 'taskviews-feedback-v10',
        'mandatory_core_ref': hashlib.sha256(dumps(core).encode()).hexdigest(),
        'last_action_feedback': modules.actor_feedback(),
        'frame_id': frame, 'grade': 'model_proposal', 'execution_boundary': LOCAL_EXECUTION,
        'active_subgoal': modules.subgoals[proposed['subgoal_id']],
        'current_visible_evidence': local_visible_evidence(raw)}
    # Failed-strategy advice must reach the actor before bulky graph/module
    # detail. Keep whole original advice, exact goal identity and current frame;
    # this neither chooses an action nor promotes a hypothesis to an effect.
    if reasons and 'planner' in advisers:
        protected['next_strategy'] = {'subgoal': modules.subgoals[proposed['subgoal_id']],
            'advice': advisers['planner']['report']['advice'], 'frame_id': frame,
            'grade': 'model_proposal', 'full_report_ref':
                str(modules.path) + '#modules/' + module + '/reports/planner'}
    stalls = modules.stalled_pointer_actions()
    if stalls:
        protected['stalled_pointer_actions'] = stalls
    if failed_keys:
        protected['stalled_keyboard_actions'] = failed_keys
    if pointer_recovery:
        protected['pointer_recovery'] = {
            'required': True, 'grade': 'model_proposal', 'guidance':
                'Multiple distinct pointer locations repeatedly produced no established state change. '
                'Choose one normal application keyboard recovery operation, then inspect its effect. '
                'Do not try another pointer location or dependent text until a known state change clears this warning.'}
    # Classified views still drive task/role selection and remain in the trace.
    # The actor receives a local brief plus real execution references. Auxiliary
    # bbox/graph locators and duplicate long adviser reports are not action input.
    optional = [('input_policy', feedback.get('guidance'))]
    executor = _admit_execution_feedback(protected, optional, modules, limit,
                                        strategy_review=feedback['strategy_review'],
                                        prior_evidence=modules.actor_prior_action_evidence())
    if feedback.get('state_review') and 'planner' in advisers:
        modules.record_uncertainty_review(feedback['state_review'])
    owner.view_trace = {'protocol': 'taskviews-feedback-v10', 'frame': owner.frame.metadata,
        'stage': proposed['stage'], 'controller': proposed, 'anchor_resolutions': resolutions,
        'normalization': normalization, 'analysis_triggers': reasons,
        'dispatch': compiled, 'executor_context': executor, 'advisers': advisers,
        'action_check': raw['action_check'], 'module_id': module, 'view_changes': changes,
        'actor_projection': 'local_execution_labels_and_native_feedback_no_observer_boxes',
        'state_review': feedback.get('state_review'),
        'available_actor_context_bytes': limit}
    telemetry.emit('taskviews_feedback_admission', packet_bytes=len(dumps(executor).encode()), available_bytes=limit,
                   analysis_triggers=reasons, merged_action_verification=True)
    return dumps(executor)
