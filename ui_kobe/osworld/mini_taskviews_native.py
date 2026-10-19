"""Mini views and bounded recovery on the shared native predict/compiler."""
import json
import os

from kobe_views.fixed_views import PROFILE, profile_contract
from kobe_views.controls_view import VERSION, matched_bindings, parse_note, policy
from . import telemetry
from .checkpoints import ReadAnomaly
from .kimi_native import KimiNativeAgent
from .mini_taskviews_context import LABEL, CONTROLS_LABEL, MiniTaskViewsContext
from .qwen_native_base import QwenNativeProvider
from .mini_interaction import validate_keys
from kobe_views.artifact_view import GUIDANCE as ARTIFACT_GUIDANCE
from kobe_views.keyboard_view import normalize_toolsets, policy as keyboard_policy
from .mini_recovery import generate_candidate as generate_mini_candidate


FRAME_CONTRACT_PREFIX = 'Trusted screenshot/coordinate contract: '


class MiniTaskViewsNativeAgent(KimiNativeAgent):
    experiment_arm = 'taskviews'
    transition_recording = True
    taskviews_profile = PROFILE
    checkpoint_profile = PROFILE
    context_label = LABEL
    strict_native_input = True

    def __init__(self, **options):
        self.keyboard_toolsets = normalize_toolsets(json.loads(os.environ.get('UI_KOBE_MINI_KEYBOARD_TOOLS', '[]')))
        if (os.environ.get('UI_KOBE_TASKVIEWS_PROFILE', PROFILE) != PROFILE
                or os.environ.get('UI_KOBE_TASKVIEWS_FEEDBACK_V10', '0') != '0'):
            raise ValueError('Mini requires its own declared profile, without full feedback workflow')
        control_version = os.environ.get('UI_KOBE_MINI_CONTROLS_VIEW', 'disabled')
        if control_version not in ('disabled', VERSION):
            raise ValueError('Unknown Mini controls view')
        self.controls_view_enabled = control_version == VERSION
        if self.controls_view_enabled and self.keyboard_toolsets:
            raise ValueError('Scoped keyboard tools cannot use the legacy controls-only packet')
        self.native_parameter_repair_feedback = self.controls_view_enabled
        self.context_label = CONTROLS_LABEL if self.controls_view_enabled else LABEL
        super().__init__(**options)

    def validate_actor_candidate(self, response):
        result = super().validate_actor_candidate(response)
        validate_keys(result[0], response)
        if result[1].terminal_status == 'success':
            self.mini_context.require_final_review(response.model_dump()['choices'][0]['message'].get('content'))
        if self.controls_view_enabled:
            content = response.model_dump()['choices'][0]['message'].get('content')
            telemetry.emit('mini_controls_candidate', frame_id=self.frame.metadata['frame_id'],
                note=parse_note(content), matched_bindings=matched_bindings(result[0]),
                view_delivered=self.mini_context.trace.get('delivered', False),
                effect_status='unknown', extra_role_requests=0)
        return result

    def generate_candidate(self, transport, role, deadline, request, validator):
        if role != 'executor':
            return super().generate_candidate(transport, role, deadline, request, validator)
        return generate_mini_candidate(self, transport, role, deadline, request, validator)

    def current_frame_content(self):
        # Mandatory before history admission; an optional view being omitted
        # must not remove the coordinate contract. The compiler remains the
        # sole projection authority; never infer units from a candidate.
        # Only the current frame needs this generated annotation. Retaining a
        # copy per old frame needlessly evicts native assistant/tool pairs.
        # Original task text, model replies and controller receipts stay intact.
        for turn in self.turns:
            turn[0]['content'] = [part for part in turn[0]['content']
                                  if not part.get('text', '').startswith(FRAME_CONTRACT_PREFIX)]
        s = self.frame.screenshot
        if s.coordinate_type == 'absolute':
            units = (f'Use absolute pixels of the {s.model_width}x{s.model_height} image, NOT normalized 0..1000. '
                     f'The center is ({s.model_width // 2},{s.model_height // 2}). ')
        else:
            units = ('Use normalized 0..1000 on EACH axis, not image pixels. '
                     'The center is (500,500); the compiler converts to desktop pixels. ')
        geometry = {key: self.frame.metadata[key] for key in
                    ('frame_id', 'coordinate_type', 'original_size', 'model_size')}
        text = (FRAME_CONTRACT_PREFIX + json.dumps(geometry, separators=(',', ':')) + '\n'
                + units + 'Verify the expected visible change; if absent, re-ground. Confirm focus before typing. '
                + ARTIFACT_GUIDANCE)
        return [*super().current_frame_content(),
                {'type': 'text', 'text': text}]

    def reset(self, _logger=None):
        super().reset(_logger)
        self.mini_context = MiniTaskViewsContext(self)

    def optional_context(self, instruction, obs):
        return self.mini_context.context(instruction)

    def context_delivered(self):
        self.mini_context.delivered()

    def context_omitted(self, reason):
        self.mini_context.omitted(reason)

    def context_trace(self):
        self.last_trace['taskviews_mini'] = self.mini_context.trace
        self.last_trace['mini_recovery'] = self.mini_recovery_trace

    def flush_execution(self):
        if self.execution_journal is not None:
            self.mini_context.boundary()
        elif self.total_steps:
            raise ReadAnomaly('Mini lost its journal after inference')

    def checkpoint_ready(self):
        return hasattr(self, 'mini_context')

    def checkpoint_state(self):
        value = {'contract': profile_contract(), 'delivery': self.mini_context.snapshot(),
                 'keyboard_tools': keyboard_policy(self.keyboard_toolsets)}
        if self.controls_view_enabled:
            value['controls_view'] = policy()
        return value

    def restore_checkpoint_state(self, value):
        if (not isinstance(value, dict) or set(value) not in ({'contract', 'delivery', 'keyboard_tools'},
                {'contract', 'delivery', 'keyboard_tools', 'controls_view'}) or value['contract'] != profile_contract()
                or value['keyboard_tools'] != keyboard_policy(self.keyboard_toolsets)):
            raise ReadAnomaly('Mini checkpoint profile differs from implementation')
        if 'controls_view' in value and (not self.controls_view_enabled or value['controls_view'] != policy()):
            raise ReadAnomaly('Mini controls checkpoint extension is incompatible')
        # Explicitly enabling this read-only extension on an M0 checkpoint needs no replay or state migration.
        self.mini_context.restore(value['delivery'])
        self.cached_context = None


class QwenMiniTaskViewsNativeAgent(QwenNativeProvider, MiniTaskViewsNativeAgent):
    """Frozen non-stream Qwen protocol; no additional analysis ledger or roles."""
