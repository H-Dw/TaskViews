"""Opt-in evidence-first graph delivery; no new retrieval, inference or actions.

The codec removes reconstructible metadata, not facts. The old packer and old
keyboard selector remain untouched. Flat is obtained from the linked selection.
"""
from copy import deepcopy
import base64
import re

from . import mini_graph as graph
from .keyboard_view import PATTERNS, active_catalog
from .model import dumps


def lookup_guide(proposals, toolsets=(), task_catalog=None):
    """Small always-available menu; one exact group request reveals its topics.

    Enabled software is not inferred to be the foreground application. Invalid
    requests do not revive an older intent or activate a disabled directory.
    """
    catalog = active_catalog(toolsets, task_catalog)
    groups = sorted({topic.rsplit('.', 1)[0] if '.' in topic else 'general' for topic in catalog})
    text = proposals[0] if proposals and isinstance(proposals[0], str) else ''
    requests = re.findall(r'<key_lookup>([a-z0-9_.]+)</key_lookup>', text)
    valid = (text.count('<key_lookup') == text.count('<key_lookup>') == text.count('</key_lookup>') == 1
             and len(requests) == 1)
    group = requests[0] if valid and requests[0] in groups else None
    topics = [topic for topic in catalog if
              (topic.rsplit('.', 1)[0] if '.' in topic else 'general') == group] if group else [
                  topic for topic in catalog if '.' in topic or topic in {name for name, _ in PATTERNS}]
    return {'format': '<key_lookup>topic_or_group</key_lookup>', 'groups': groups,
            'topics': topics, 'topics_omitted': len(catalog) - len(topics),
            'check': 'Group lookup lists topics. Verify app/focus; enabled is not foreground.'}


def compact(packet):
    """Lossless v1 -> v2 codec. All original SHA256 bits and all links remain."""
    out = deepcopy(packet)
    out['schema_version'] = graph.DELIVERY_VERSION
    out['sources'] = {seq: [source['kind'], base64.b64encode(bytes.fromhex(source['sha256'])).decode('ascii')]
                      for seq, source in packet['sources'].items()}
    grouped = {}
    for source, relation, target in packet['links']:
        grouped.setdefault((relation, target), []).append(source)
    out['links'] = [[relation, target, sorted(origins)] for (relation, target), origins in sorted(grouped.items())]
    current_refs = packet['views']['current']['record_refs']
    current = current_refs[0][0] if current_refs else None
    verification = (packet['nodes'].get(current, {}).get('facets', {}).get('original_input', {})
                    .get('artifact', {}).get('verification'))
    for alias, node in out['nodes'].items():
        if alias.startswith('e') and alias[1:] in out['sources']:
            # Source kind and numeric seq identify these two fields exactly.
            node.pop('ref')
            node.pop('kind')
        for body in node.get('facets', {}).values():
            if (verification is not None and body.get('verification') == verification):
                body.pop('verification')
                body['verification_from'] = current
        if len(node.get('facets', {})) == 1:
            grade, body = next(iter(node.pop('facets').items()))
            node['fact'] = body  # Its grade is already present in record_refs or memory refs.
            if node.get('kind') == grade:
                node.pop('kind')
    return out


def unpack(packet):
    out = deepcopy(packet)
    out['schema_version'] = graph.VERSION
    if packet.get('source_encoding') == 'journal_seq_local_audit_v1':
        # Opt-in guidance v2 keeps hash verification in the pre-send index and
        # full mappings in local audit. Never invent a hash while expanding it.
        if any(not isinstance(v, list) or len(v) != 1 for v in packet['sources'].values()):
            raise ValueError('Invalid short journal source reference')
        out['sources'] = {seq: {'kind': v[0]} for seq, v in packet['sources'].items()}
    else:
        out['sources'] = {seq: {'kind': v[0], 'sha256': base64.b64decode(v[1], validate=True).hex()}
                          for seq, v in packet['sources'].items()}
    out['links'] = sorted([[source, relation, target] for relation, target, origins in packet['links'] for source in origins])
    grades = {alias: grade for view in packet['views'].values() for alias, grade in view['record_refs']}
    for node in packet['nodes'].values():
        for body in [node.get('fact', {}), *node.get('facets', {}).values()]:
            for alias, grade in body.get('memory', []):
                grades[alias] = grade
    for alias, node in out['nodes'].items():
        if 'fact' in node:
            grade = grades[alias]
            node['facets'] = {grade: node.pop('fact')}
            if not alias.startswith('e') and 'kind' not in node:
                node['kind'] = grade
    for alias, node in out['nodes'].items():
        if alias.startswith('e') and alias[1:] in out['sources']:
            kind = out['sources'][alias[1:]]['kind']
            node.update(ref=int(alias[1:]), kind='action' if kind == 'transition' else kind)
        for body in node.get('facets', {}).values():
            if 'verification_from' in body:
                source = body.pop('verification_from')
                body['verification'] = deepcopy(out['nodes'][source]['facets']['original_input']['artifact']['verification'])
    return out


def materialize(*, index, instruction, graph_mode, frame_id, current, attempts, lessons, totals, max_bytes,
                keyboard=None, sources=None, toolsets=(), task_catalog=None):
    limit = min(graph.MAX_BYTES, max_bytes)
    if type(limit) is not int or limit < 0:
        raise ValueError('Mini graph budget must be a nonnegative integer')
    rows = {'attempts': attempts, 'lessons': lessons}
    if any(type(totals.get(k)) is not int or totals[k] < len(rows[k]) for k in rows):
        raise ValueError('Mini graph eligible counts must include all candidates')
    raw = {'episode_id': index.episode_id, 'frame_id': frame_id, 'sources': sources or {},
           'views': {k: {'records': [], 'omitted_records': totals.get(k, 0)} for k in graph.VIEW_IDS}}
    literal = deepcopy(current)
    raw['views']['current']['records'] = [literal]
    lookup = literal.pop('keyboard_lookup', None)
    optional = {key: literal.pop(key) for key in ('recent_repetition', 'interaction_contract') if key in literal}
    for key in optional:
        literal[key + '_omitted'] = True
    selected = {k: set() for k in rows}
    for i, row in enumerate(lessons):
        if row.get('grade') == 'artifact_verification_state':
            raw['views']['lessons']['records'].append(deepcopy(row))
            raw['views']['lessons']['omitted_records'] -= 1
            selected['lessons'].add(i)

    def render(value):
        return compact(graph.normalize(value, index, instruction, toolsets, task_catalog))

    def accept(candidate):
        if len(dumps(render(candidate)).encode('utf-8')) > limit:
            return False
        raw.clear()
        raw.update(candidate)
        return True

    if not accept(deepcopy(raw)):
        return None

    def admit(key, i):
        if i in selected[key]:
            return True
        candidate = deepcopy(raw)
        view = candidate['views'][key]
        view['records'].append(deepcopy(rows[key][i]))
        view['records'].sort(key=lambda row: row.get('seq', row.get('ref', 0)))
        view['omitted_records'] -= 1
        if not accept(candidate):
            return False
        selected[key].add(i)
        return True

    def admit_current(key, value):
        candidate = deepcopy(raw)
        body = candidate['views']['current']['records'][0]
        body.pop(key + '_omitted', None)
        body[key] = deepcopy(value)
        return accept(candidate)

    # Critical evidence has precedence over advice; never cut errors or reviews.
    if attempts:
        admit('attempts', 0)
    for grade in ('execution_error_record', 'model_artifact_review'):
        for i, row in enumerate(lessons):
            if row.get('grade') == grade:
                if admit('lessons', i) or grade == 'model_artifact_review':
                    break

    # A recipe is an indivisible unit: retain scope/check/source and literal
    # parameters, report omissions, and never substitute a suggested key for
    # executed key memory. Prefer the complete topic when it fits.
    keyboard_admitted = False
    if keyboard is not None:
        for count in range(len(keyboard['recipes']), 0, -1):
            candidate = deepcopy(raw)
            body = deepcopy(keyboard)
            body['recipes'] = body['recipes'][:count]
            body['recipes_omitted'] = len(keyboard['recipes']) - count
            candidate['views']['keyboard']['records'] = [body]
            while True:
                if accept(candidate):
                    keyboard_admitted = True
                    break
                if not body['memory']:
                    break
                body['memory'].pop()
                body['memory_omitted'] += 1
            if keyboard_admitted:
                break
        if not keyboard_admitted:
            raw['views']['keyboard']['omitted_records'] = 1
    # Discovery must precede optional older prose/history, including when the
    # chosen recipe was too large. Do not leave the actor with a silent dead end.
    if lookup is not None and not keyboard_admitted:
        admit_current('keyboard_lookup', lookup)
    if 'recent_repetition' in optional:
        admit_current('recent_repetition', optional['recent_repetition'])
    for key in rows:
        for i in range(len(rows[key])):
            admit(key, i)
    if 'interaction_contract' in optional:
        admit_current('interaction_contract', optional['interaction_contract'])
    packet = render(raw)
    if graph_mode == 'flat':
        packet['mode'], packet['links'] = 'flat', []
    return packet
