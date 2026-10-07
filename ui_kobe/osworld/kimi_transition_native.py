"""UI-KOBE-like graph retrieval on the same native actor as the other arms."""
from .kimi_native import KimiNativeAgent
from .transition_context import TransitionContext
from . import telemetry


class KimiTransitionNativeAgent(KimiNativeAgent):
    experiment_arm = 'ui_kobe_like'
    transition_recording = True
    context_label = TransitionContext.label

    def reset(self, _logger=None):
        super().reset(_logger)
        self.context_provider = TransitionContext(self)

    def optional_context(self, instruction, obs):
        self.context_provider.cached = None
        try:
            return self.context_provider.context(instruction, self.frame.screenshot)
        except Exception as exc:
            telemetry.emit('transition_memory_failure', error_type=type(exc).__name__, error=str(exc))
            return None
