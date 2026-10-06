"""Execution receipt callback for the project adapter, without upstream edits."""
from contextvars import ContextVar
import functools


action_owner = ContextVar("taskviews_action_owner", default=None)


def effect_feedback(verifier, before_trace, observation, controller_result):
    """Build attested feedback only from a trusted adapter callback.

    A callback may read captured evidence or a permitted state probe; it must not
    dispatch GUI actions. Model output never enters this callable boundary.
    Raw controller receipts and screenshots cannot be replaced by its report.
    """
    payload = {"controller_result": controller_result, "screenshot": observation.get("screenshot")}
    if verifier is not None:
        if not callable(verifier):
            raise ValueError("Effect verifier must be a trusted callable")
        report = verifier(before_trace, observation, controller_result)
        allowed = {"verified_state", "effect_verified", "compensation", "checkpoint", "recovery_checkpoint_verified"}
        if not isinstance(report, dict) or set(report) - allowed:
            raise ValueError("Invalid adapter effect attestation")
        payload.update(report)
    return payload


def install_feedback_hooks(env_type=None, controller_type=None):
    if env_type is None:
        from desktop_env.desktop_env import DesktopEnv
        env_type = DesktopEnv
    if controller_type is None:
        from desktop_env.controllers.python import PythonController
        controller_type = PythonController
    if not getattr(controller_type, "_taskviews_feedback", False):
        original_execute = controller_type.execute_python_command

        @functools.wraps(original_execute)
        def execute(self, command):
            owner = action_owner.get()
            try:
                result = original_execute(self, command)
            except Exception:
                if owner is not None:
                    owner._execution_result = None
                raise
            if owner is not None:
                owner._execution_result = result
            return result

        controller_type.execute_python_command = execute
        controller_type._taskviews_feedback = True
    if not getattr(env_type, "_taskviews_feedback", False):
        original_step = env_type.step

        @functools.wraps(original_step)
        def step(self, action, *args, **kwargs):
            owner = action_owner.get()
            try:
                obs, reward, done, info = original_step(self, action, *args, **kwargs)
            except Exception:
                if owner is not None:
                    action_owner.set(None)
                    owner.worker.feedback({"controller_result": owner._execution_result,
                                           "error": "execution_failed_or_unconfirmed"})
                raise
            if owner is not None:
                action_owner.set(None)
                payload = effect_feedback(getattr(owner, "feedback_verifier", None),
                                          getattr(owner, "last_trace", {}), obs, owner._execution_result)
                owner.worker.feedback({**payload, "done": done})
            return obs, reward, done, info

        env_type.step = step
        env_type._taskviews_feedback = True
