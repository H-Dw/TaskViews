"""M0 fixed TaskViews on the unchanged shared native actor and compiler."""
import os

from kobe_views.fixed_views import PROFILE, profile_contract
from .checkpoints import ReadAnomaly
from .kimi_native import KimiNativeAgent
from .mini_taskviews_context import LABEL, MiniTaskViewsContext
from .qwen_native_base import QwenNativeProvider


class MiniTaskViewsNativeAgent(KimiNativeAgent):
    experiment_arm = 'taskviews'
    transition_recording = True
    taskviews_profile = PROFILE
    checkpoint_profile = PROFILE
    context_label = LABEL
    strict_native_input = True

    def __init__(self, **options):
        if (os.environ.get('UI_KOBE_TASKVIEWS_PROFILE', PROFILE) != PROFILE
                or os.environ.get('UI_KOBE_TASKVIEWS_FEEDBACK_V10', '0') != '0'):
            raise ValueError('Mini requires its own declared profile, without full feedback workflow')
        super().__init__(**options)

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

    def flush_execution(self):
        if self.execution_journal is not None:
            self.mini_context.boundary()
        elif self.total_steps:
            raise ReadAnomaly('Mini lost its journal after inference')

    def checkpoint_ready(self):
        return hasattr(self, 'mini_context')

    def checkpoint_state(self):
        return {'contract': profile_contract(), 'delivery': self.mini_context.snapshot()}

    def restore_checkpoint_state(self, value):
        if not isinstance(value, dict) or set(value) != {'contract', 'delivery'} or value['contract'] != profile_contract():
            raise ReadAnomaly('Mini checkpoint profile differs from implementation')
        self.mini_context.restore(value['delivery'])
        self.cached_context = None


class QwenMiniTaskViewsNativeAgent(QwenNativeProvider, MiniTaskViewsNativeAgent):
    """Frozen non-stream Qwen protocol; no additional analysis ledger or roles."""
