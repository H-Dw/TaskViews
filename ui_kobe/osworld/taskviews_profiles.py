"""Explicit profile selection, without merging full and Mini instruction sets."""
from kobe_views.fixed_views import PROFILE as MINI_PROFILE, profile_contract

FULL_PROFILE = 'full_checkpoint'
UI_KOBE_PROFILE = 'ui_kobe_like_native_v1'


def mini_cua_contract():
    from .cua_contract import CUAContract
    return CUAContract(history_n=20, image_max=1, fold_size=1,
        context_max_payload_chars=2000000, context_max_text_chars=32000,
        context_rough_text_token_budget=12000, context_reserve_chars=10000,
        taskviews_context_bytes=8000).snapshot()


def frozen_profile(arm):
    if arm == 'taskviews':
        return profile_contract()
    if arm == 'ui_kobe_like':
        return {'profile': UI_KOBE_PROFILE, 'selector': 'recent_execution_edges',
                'recent_edges': 8, 'extra_role_requests': 0}
    if arm == 'baseline':
        return {'profile': 'osworld_native_llm_baseline_v1', 'selector': None,
                'extra_role_requests': 0, 'passive_transition_audit': True,
                'mandatory_frame_guidance': False}
    raise ValueError('Mini comparison supports taskviews or ui_kobe_like only')


def validate_profile(plan):
    profile = plan.get('taskviews_profile', FULL_PROFILE)
    if profile == FULL_PROFILE:
        if plan.get('mini_profile') is not None or plan.get('mini_controls_view') is not None:
            raise ValueError('Full TaskViews cannot carry a Mini profile')
        return profile
    arms = plan.get('arms', [])
    if (profile != MINI_PROFILE or plan.get('agent_interface') != 'qwen-native'
            or len(arms) != 1 or arms[0] not in ('taskviews', 'ui_kobe_like')
            or plan.get('taskviews_feedback', False) is not False
            or plan.get('mini_profile') != frozen_profile(arms[0])
            or plan.get('cua_contract') != mini_cua_contract()
            or plan.get('source_branch') != 'mini'):
        raise ValueError('Mini requires one explicit frozen profile on the mini branch, without full feedback')
    if plan.get('mini_controls_view') is not None:
        from kobe_views.controls_view import policy
        if arms != ['taskviews'] or plan['mini_controls_view'] != policy():
            raise ValueError('Controls view requires its exact declared Mini extension')
    return profile


def checkpoint_profile(manifest):
    profile = manifest.get('taskviews_profile', FULL_PROFILE)
    if profile == MINI_PROFILE:
        return frozen_profile(manifest['arm'])['profile']
    if profile != FULL_PROFILE:
        raise ValueError('Unknown checkpoint actor profile')
    return FULL_PROFILE
