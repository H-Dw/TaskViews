"""Public, source-bound artifact reviews; model reports never certify facts."""
from copy import deepcopy
import json
import re

VERSION = 'mini_artifact_review_v1'
CHECKS = ('source_confirmed', 'content_previewed', 'name_correct', 'destination_confirmed')
LABEL = 'artifact_review'
GUIDANCE = (
    'Observation screenshots are not exports; timestamps/menu closure/returned are not content proof. '
    'Before success preview the candidate and emit artifact_review per current.artifact.review_schema; reports stay unverified. '
)
REVIEW_SCHEMA = ('<artifact_review>{"applicable":true,"candidate":"path",'
    '"checks":{"CHECK":{"ref":SEQ,"observed":"evidence"}}}</artifact_review>; '
    'CHECK=each verification key; preview ref=current.ref. No artifact: {"applicable":false,"reason":"why"}.')


def unknown_checks():
    return dict.fromkeys(CHECKS, 'unknown')


def parse_review(text):
    """Accept one bounded public note, not prose, booleans or claimed truth grades."""
    if not isinstance(text, str):
        return None
    matches = re.findall(r'<artifact_review>(.*?)</artifact_review>', text, re.S)
    if len(matches) != 1 or len(matches[0].encode()) > 2400:
        return None
    try:
        value = json.loads(matches[0])
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or type(value.get('applicable')) is not bool:
        return None
    if value['applicable'] is False:
        reason = value.get('reason')
        return value if (set(value) == {'applicable', 'reason'} and isinstance(reason, str)
                         and 0 < len(reason.strip()) <= 240) else None
    if set(value) != {'applicable', 'candidate', 'checks'}:
        return None
    if not isinstance(value['candidate'], str) or not 0 < len(value['candidate'].strip()) <= 300:
        return None
    checks = value['checks']
    if not isinstance(checks, dict) or not set(checks) <= set(CHECKS):
        return None
    for check in checks.values():
        if (not isinstance(check, dict) or set(check) != {'ref', 'observed'}
                or type(check['ref']) is not int or check['ref'] < 1
                or not isinstance(check['observed'], str) or not 0 < len(check['observed'].strip()) <= 160):
            return None
    return deepcopy(value)


def policy():
    return {'version': VERSION, 'checks': list(CHECKS), 'default': 'unknown',
            'model_reports': 'unverified, bound to same-episode observation references',
            'success_gate': 'public review of all checks; current-frame candidate-content review',
            'semantic_certification': False, 'extra_role_requests': 0}
