"""Public, source-bound artifact reviews; model reports never certify facts."""
from copy import deepcopy
import json
import re

VERSION = 'mini_artifact_review_v3'
CHECKS = ('source_confirmed', 'content_previewed', 'name_correct', 'destination_confirmed')
LABEL = 'artifact_review'
MAX_REVIEW_BYTES = 2400
MAX_CANDIDATE_CHARS = 300
MAX_OBSERVED_CHARS = 160
MAX_REASON_CHARS = 240
GUIDANCE = (
    'Observation screenshots are not exports; timestamps/menu closure/returned are not content proof. '
    'Before success preview the candidate; follow current.artifact.review_schema in public content. '
    'Missing evidence: inspect, never invent. '
)


def tagged_review(value):
    """Serialize an explicit report/template; never supply missing evidence."""
    return f'<{LABEL}>' + json.dumps(value, ensure_ascii=False, separators=(',', ':')) + f'</{LABEL}>'


def review_schema():
    # One object to close. Pairs preserve each fact's own observation without
    # the applicable/checks/ref/observed wrappers in every generated report.
    example = {'candidate': 'PATH', **{key: [1, 'FACT'] for key in CHECKS}}
    return (
        'Success: assistant.content ONE tagged JSON + terminate; not reasoning/tool args. '
        'Replace ALL example values; 4 pairs=[same-task obs seq>=1,fact]; '
        'content_previewed[0]=current.ref. '
        f'No extra keys; candidate 1..{MAX_CANDIDATE_CHARS}, observed 1..{MAX_OBSERVED_CHARS} chars '
        f'; JSON<={MAX_REVIEW_BYTES} UTF8 bytes. '
        + tagged_review(example) + ' No-file tasks only: '
        + tagged_review({'no_artifact': 'WHY'})
        + f'; reason 1..{MAX_REASON_CHARS} chars.')


REVIEW_SCHEMA = review_schema()


class ReviewError(ValueError):
    """Bounded diagnostics contain field names/counts, never submitted prose."""

    def __init__(self, code, detail):
        self.code = code
        super().__init__(f'{code}: {detail}')


def unknown_checks():
    return dict.fromkeys(CHECKS, 'unknown')


def normalize_report(value):
    """Normalize explicit flat fields, never fill facts or repair malformed JSON.

    Strict v2 input remains readable for original journal records and older
    model responses. Only the flat form is advertised in new actor prompts.
    """
    if not isinstance(value, dict) or 'applicable' in value:
        return value
    if 'no_artifact' in value:
        if set(value) != {'no_artifact'}:
            raise ReviewError('report_fields', 'no-file report keys must be exactly no_artifact')
        return {'applicable': False, 'reason': value['no_artifact']}
    if not set(value) <= {'candidate', *CHECKS} or 'candidate' not in value:
        raise ReviewError('report_fields', 'Use candidate and only the 4 review keys')
    checks = {}
    for key in CHECKS:
        if key not in value:
            continue
        pair = value[key]
        if not isinstance(pair, list) or len(pair) != 2:
            raise ReviewError('report_fields', f'{key}: expected [observation seq, short fact]')
        checks[key] = {'ref': pair[0], 'observed': pair[1]}
    return {'applicable': True, 'candidate': value['candidate'], 'checks': checks}


def validate_review(text, *, final=False):
    """Validate without rewriting; diagnose every field error after JSON parses."""
    if not isinstance(text, str) or f'<{LABEL}>' not in text:
        raise ReviewError('missing_tag', 'Put one <artifact_review>...</artifact_review> in assistant.content')
    matches = re.findall(r'<artifact_review>(.*?)</artifact_review>', text, re.S)
    if len(matches) != 1 or text.count(f'<{LABEL}>') != 1 or text.count(f'</{LABEL}>') != 1:
        raise ReviewError('tag_count', 'Exactly one complete <artifact_review>...</artifact_review> is required')
    size = len(matches[0].encode('utf-8'))
    if size > MAX_REVIEW_BYTES:
        raise ReviewError('report_bytes', f'Inner JSON has {size} UTF8 bytes; maximum {MAX_REVIEW_BYTES}')
    try:
        value = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise ReviewError('invalid_json', f'{exc.msg} at line {exc.lineno}, column {exc.colno}; '
                          'return complete JSON with all objects closed') from exc
    except (ValueError, RecursionError) as exc:
        raise ReviewError('invalid_json', 'Return the shallow JSON object in review_schema') from exc
    value = normalize_report(value)
    if not isinstance(value, dict) or type(value.get('applicable')) is not bool:
        raise ReviewError('report_shape', 'Expected an object with boolean applicable')
    issues = []

    def bounded_text(item, field, limit):
        if not isinstance(item, str):
            issues.append(f'{field}: expected string of 1..{limit} chars')
        elif not 0 < len(item.strip()) <= limit:
            issues.append(f'{field}: {len(item.strip())} chars; allowed 1..{limit}')

    if value['applicable'] is False:
        if set(value) != {'applicable', 'reason'}:
            issues.append('no-file report keys must be exactly applicable,reason')
        bounded_text(value.get('reason'), 'reason', MAX_REASON_CHARS)
    else:
        if set(value) != {'applicable', 'candidate', 'checks'}:
            issues.append('artifact report keys must be exactly applicable,candidate,checks')
        bounded_text(value.get('candidate'), 'candidate', MAX_CANDIDATE_CHARS)
        checks = value.get('checks')
        if not isinstance(checks, dict):
            issues.append('checks: expected object with the 4 review keys')
        else:
            if not set(checks) <= set(CHECKS):
                issues.append('checks: unknown keys; use only the 4 review keys')
            if final and (missing := [key for key in CHECKS if key not in checks]):
                issues.append('checks missing: ' + ','.join(missing))
            for key in CHECKS:
                if key not in checks:
                    continue  # Partial reports can be recorded before success.
                check = checks[key]
                if not isinstance(check, dict) or set(check) != {'ref', 'observed'}:
                    issues.append(f'{key}: keys must be exactly ref,observed')
                    continue
                if type(check['ref']) is not int or check['ref'] < 1:
                    issues.append(f'{key}.ref: expected positive integer observation seq')
                bounded_text(check['observed'], f'{key}.observed', MAX_OBSERVED_CHARS)
    if issues:
        raise ReviewError('report_fields', '; '.join(issues))
    return deepcopy(value)


def parse_review(text):
    """Optional historical notes keep the original None-on-invalid interface."""
    try:
        return validate_review(text)
    except ReviewError:
        return None


def policy():
    return {'version': VERSION, 'checks': list(CHECKS), 'default': 'unknown',
            'model_reports': 'unverified, bound to same-episode observation references',
            'success_gate': 'public review of all checks; current-frame candidate-content review',
            'format_limits': {'json_utf8_bytes': MAX_REVIEW_BYTES, 'candidate_chars': MAX_CANDIDATE_CHARS,
                              'observed_chars': MAX_OBSERVED_CHARS, 'reason_chars': MAX_REASON_CHARS},
            'wire_format': 'flat candidate + 4 [observation seq, fact] pairs; or no_artifact reason',
            'legacy_read': 'strict v2 report; no malformed JSON rewriting',
            'recovery': 'Mini report feedback only; shared executor repair/time/output pool',
            'diagnostics': 'typed format/reference errors, separate from native tool errors',
            'semantic_certification': False, 'extra_role_requests': 0}
