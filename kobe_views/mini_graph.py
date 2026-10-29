"""Deterministic, episode-scoped identity index and bounded cross-view projections.

The original journal/catalog remain authoritative. No GUI actions, inference,
success certification, or model requests belong in this module.
"""
from copy import deepcopy
import hashlib

from .fixed_views import MAX_BYTES, PROFILE, REVISION, VIEW_IDS
from .model import dumps
from .keyboard_view import DATA, active_catalog

MODES = ('legacy', 'flat', 'linked')
ENV = 'UI_KOBE_MINI_GRAPH_MODE'
VERSION = 'mini_graph_v1'
ID_VERSION = 'mini_identity_v1'
PACKING = 'linked_cost_shared_selection_v1'
DELIVERY_PACKING = 'evidence_first_delivery_v2'
PACKING_ENV = 'UI_KOBE_MINI_GRAPH_PACKING'
DELIVERY_VERSION = 'mini_graph_delivery_v2'
LABEL = ('TaskViews graph: nodes share facts; record_refs=[node,facet]; sources resolve event seqs. '
         'Current means the current-view node and its original_input facet; artifact review refs stay numeric seqs. '
         'Links are evidence associations, never success/causality. Recipe matches prove parameters only. '
         'Unknown stays unverified; inspect missing evidence:')
REF_FIELDS = {'ref', 'before', 'after', 'current_ref', 'review_ref'}
DELIVERY_LABEL = (LABEL + ' V2: eN means journal seq N; sources[N]=[kind,base64 SHA256]; '
                  'fact is the single facet named in record_refs; links=[relation,target,[sources]]. '
                  'verification_from points to that node original_input.artifact.verification. '
                  'Recipe omissions count whole recipes. Copy key tokens exactly; verify app/focus.')


class GraphIntegrityError(RuntimeError):
    """An association or identity cannot be justified by original evidence."""


def sha(value):
    return hashlib.sha256(dumps(value).encode('utf-8')).hexdigest()


def mode(value):
    if value not in MODES:
        raise ValueError('Unknown Mini graph mode: ' + str(value))
    return value


def policy(value, packing=None):
    legacy = mode(value) == 'legacy'
    packing = packing or (REVISION if legacy else PACKING)
    if packing not in ((REVISION,) if legacy else (PACKING, DELIVERY_PACKING)):
        raise ValueError('Incompatible Mini graph packing strategy')
    return {'mode': value, 'schema_version': PROFILE if legacy else
            DELIVERY_VERSION if packing == DELIVERY_PACKING else VERSION,
            'id_version': 'journal_seq' if legacy else ID_VERSION,
            'packing': packing, 'max_bytes': MAX_BYTES, 'extra_model_calls': 0}


def plan_policy(plan):
    """Missing declarations mean the historical legacy path, never auto-upgrade."""
    value = mode(plan.get('mini_graph_mode', 'legacy'))
    declared = plan.get('mini_graph')
    expected = policy(value, declared.get('packing') if isinstance(declared, dict) else None)
    if (declared is not None and declared != expected) or (value != 'legacy' and declared is None):
        raise ValueError('Mini graph policy differs from frozen declaration')
    return expected


def arm_policy(plan, arm):
    return plan_policy(plan) if arm == 'taskviews' else policy('legacy')


def environment(plan, arm='taskviews'):
    selected = arm_policy(plan, arm)
    return {ENV: selected['mode'], PACKING_ENV: selected['packing']}


class GraphIndex:
    """Metadata-only incremental index, reconstructed from the same episode."""
    def __init__(self, episode_id, task_id):
        self.episode_id, self.task_id = episode_id, task_id
        self.cursor = 0
        self.events, self.by_id, self.identities, self.tasks = {}, {}, {}, {}

    def identity(self, alias, canonical, kind, **metadata):
        value = {'id': canonical, 'kind': kind, **metadata}
        if alias in self.identities and self.identities[alias] != value:
            raise GraphIntegrityError('Mini graph identity collision')
        self.identities[alias] = value
        return alias

    def sync(self, read):
        while True:
            rows = read('SELECT seq,id,payload FROM events WHERE seq>? ORDER BY seq LIMIT 256', (self.cursor,))
            if not rows:
                break
            for seq, event, digest in rows:
                if (seq != self.cursor + 1 or event.get('episode_id') != self.episode_id
                        or event.get('task_id') != self.task_id or event['id'] in self.by_id):
                    raise GraphIntegrityError('Mini graph journal identity or sequence differs')
                # References and matching metadata only; no screenshot, response, or receipt copies.
                keys = ('id', 'kind', 'time_utc', 'instruction', 'decision_id', 'command_index', 'source', 'target',
                        'observation', 'action', 'tool', 'commands', 'tools', 'dispatch_observed',
                        'command_alignment', 'gaps')
                item = {k: deepcopy(event[k]) for k in keys if k in event}
                item.update(seq=seq, sha256=digest)
                self.events[seq], self.by_id[event['id']] = item, seq
                alias = 'e' + str(seq)
                self.identity(alias, self.episode_id + ':' + event['id'],
                              'action' if event['kind'] == 'transition' else event['kind'],
                              seq=seq, sha256=digest, time_utc=event.get('time_utc'))
                self.cursor = seq
                instruction = event.get('instruction')
                if isinstance(instruction, str):
                    goal = self.goal(instruction)
                    self.tasks.setdefault(seq, set()).add(goal)
                    for field in ('source', 'target', 'observation'):
                        if event.get(field):
                            target = self.by_id.get(event[field])
                            if target is None or self.events[target]['kind'] != 'observation':
                                raise GraphIntegrityError('Mini graph observation endpoint is missing')
                            self.tasks.setdefault(target, set()).add(goal)

    def goal(self, instruction):
        digest = sha([self.task_id, hashlib.sha256(instruction.encode('utf-8')).hexdigest()])
        return self.identity('g' + digest[:12], 'goal:' + digest, 'goal')

    def event(self, seq, sources=None):
        if type(seq) is not int or seq not in self.events:
            raise GraphIntegrityError('Mini graph event reference is missing')
        item = self.events[seq]
        if sources is not None and str(seq) in sources:
            original = sources[str(seq)]
            if any(original.get(k) != item[k] for k in ('id', 'kind', 'sha256')):
                raise GraphIntegrityError('Mini graph source differs from original journal')
        return 'e' + str(seq)

    def action_context(self, seq):
        item = self.events[seq]
        if (item['kind'] != 'transition' or not item.get('dispatch_observed')
                or item.get('command_alignment') != 'matched' or item.get('gaps')):
            raise GraphIntegrityError('Mini graph action is not confirmed execution')
        decision_seq = self.by_id.get(item.get('decision_id'))
        decision = self.events.get(decision_seq, {})
        position = item.get('command_index')
        commands = decision.get('commands', [])
        if (decision.get('kind') != 'decision' or decision.get('instruction') != item.get('instruction')
                or type(position) is not int or not 0 <= position < len(commands)
                or commands[position] != item.get('action')
                or item.get('tool') not in decision.get('tools', [])):
            raise GraphIntegrityError('Mini graph decision/command binding differs')
        return decision_seq, self.by_id[item['source']], self.by_id[item['target']]

    def recipe(self, topic, recipe, toolsets=(), task_catalog=None):
        catalog = active_catalog(toolsets, task_catalog)
        if topic not in catalog or recipe not in catalog[topic]['recipes']:
            raise GraphIntegrityError('Mini graph recipe is outside the active selected topic')
        entry = catalog[topic]
        temporary = topic.startswith('task.')
        source_table = task_catalog['sources'] if temporary else DATA['sources']
        origin = task_catalog['identity'] if temporary else 'permanent'
        fields = {'namespace': origin, 'toolset': topic.rsplit('.', 1)[0] if '.' in topic else 'general',
                  'topic': topic, 'platform': DATA['runtime_platform'], 'scope': entry['scope'],
                  'recipe': recipe, 'sources': {key: source_table[key] for key in entry['sources']}}
        digest = sha(fields)
        return self.identity('k' + digest[:12], 'recipe:' + digest, 'recipe')

    def derived(self, kind, refs):
        digest = sha([VERSION, kind, sorted(self.identities[r]['id'] for r in set(refs))])
        return self.identity('d' + digest[:12], 'derived:' + digest, kind)

    def audit(self):
        return {'schema_version': VERSION, 'id_version': ID_VERSION, 'episode_id': self.episode_id,
                'journal_seq': self.cursor, 'identities': deepcopy(self.identities)}


def references(value):
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in REF_FIELDS and type(child) is int:
                found.add(child)
            elif key not in ('tool', 'sources'):
                found.update(references(child))
    elif isinstance(value, list):
        for child in value:
            found.update(references(child))
    return found


def normalize(raw, index, instruction, toolsets=(), task_catalog=None):
    """Compile one self-contained linked packet. All relation endpoints are included."""
    if raw['episode_id'] != index.episode_id:
        raise GraphIntegrityError('Mini graph projection belongs to another episode')
    if task_catalog is not None and task_catalog.get('instruction_sha256') != hashlib.sha256(
            instruction.encode('utf-8')).hexdigest():
        raise GraphIntegrityError('Mini graph temporary recipes belong to another task')
    goal = index.goal(instruction)
    nodes, links, sources = {goal: {'kind': 'goal', 'source': 'original_task'}}, set(), {}

    def edge(source, relation, target):
        links.add((source, relation, target))

    def event(seq):
        alias = index.event(seq, raw.get('sources'))
        item = index.events[seq]
        if goal not in index.tasks.get(seq, ()):
            raise GraphIntegrityError('Mini graph event belongs to another task instruction')
        if alias not in nodes:
            nodes[alias] = {'kind': index.identities[alias]['kind'], 'ref': seq}
            sources[str(seq)] = {'sha256': item['sha256'], 'kind': item['kind']}
            if goal in index.tasks.get(seq, ()):
                edge(alias, 'in_task', goal)
        return alias

    def converted(value):
        if isinstance(value, dict):
            return {k: event(v) if k in REF_FIELDS and type(v) is int else
                    deepcopy(v) if k in ('tool', 'sources') else converted(v) for k, v in value.items()}
        if isinstance(value, list):
            return [converted(v) for v in value]
        return value

    def facet(alias, name, body):
        node = nodes[alias]
        facets = node.setdefault('facets', {})
        if name in facets and facets[name] != body:
            raise GraphIntegrityError('Mini graph facet has conflicting payloads')
        facets[name] = body
        return [alias, name]

    def action(seq):
        alias = event(seq)
        decision, before, after = index.action_context(seq)
        edge(alias, 'issued_by', event(decision))
        edge(alias, 'before', event(before))
        edge(alias, 'after', event(after))
        return alias

    def record(row):
        body = deepcopy(row)
        grade = body.pop('grade')
        seq = body.pop('ref', None)
        if seq is not None:
            index.event(seq, raw.get('sources'))
            alias = action(seq) if index.events[seq]['kind'] == 'transition' else event(seq)
        else:
            refs = [event(r) for r in references(row)]
            identity_kind = grade + ':' + row['guide_id'] if grade == 'operation_guidance' else grade
            alias = index.derived(identity_kind, [goal, *refs])
            nodes.setdefault(alias, {'kind': grade})
        # Common operation fields are stored once; view-specific receipt/grade remain facets.
        if index.identities[alias]['kind'] == 'action':
            original = index.events[seq]
            if ('tool' in body and body['tool'] != original.get('tool')) or any(
                    field in body and body[field] != index.by_id[original[source]]
                    for field, source in (('before', 'source'), ('after', 'target'))):
                raise GraphIntegrityError('Mini graph projection differs from original action')
            for key in ('tool', 'before', 'after', 'effect_status'):
                if key in body:
                    value = body.pop(key)
                    if key in ('before', 'after'):
                        value = event(value)
                    if key in nodes[alias] and nodes[alias][key] != value:
                        raise GraphIntegrityError('Mini graph action facts disagree across views')
                    nodes[alias][key] = value
        body = converted(body)
        if 'followup' in body:
            edge(alias, 'followup', body['followup']['ref'])
        # Error facets already identify their action; before/after are action context,
        # not separate claims that the error report reviewed those screenshots.
        if grade in ('model_artifact_review', 'artifact_verification_state'):
            targets = [event(r) for r in references(row) if r != seq]
            for target in targets:
                edge(alias, 'reports_on', target)
        return facet(alias, grade, body)

    views = {}
    recipes, memories = [], []
    for name in VIEW_IDS:
        view = raw['views'][name]
        refs = []
        for row in view['records']:
            if name != 'keyboard' or row.get('grade') == 'operation_guidance':
                refs.append(record(row))
                continue
            root = deepcopy(row)
            grade = root.pop('grade')
            recipe_refs = []
            for recipe in root.pop('recipes'):
                alias = index.recipe(row['topic'], recipe, toolsets, task_catalog)
                nodes[alias] = {'kind': 'recipe', **deepcopy(recipe)}
                recipes.append((alias, recipe['tool']))
                recipe_refs.append(alias)
            memory_refs = []
            for memory in root.pop('memory'):
                data = deepcopy(memory)
                seq = data.pop('ref')
                alias = action(seq)
                memory_refs.append(facet(alias, 'key_memory', data))
                memories.append((seq, data))
            alias = index.derived('keyboard_reference', [goal, *recipe_refs, *(x[0] for x in memory_refs)])
            nodes[alias] = {'kind': 'keyboard_reference'}
            refs.append(facet(alias, grade, {**root, 'recipes': recipe_refs, 'memory': memory_refs}))
        views[name] = {'record_refs': refs, 'omitted_records': view['omitted_records']}
    # Complete literal parameters, not a claim that a recipe was used or applicable.
    corrections = {seq for seq, m in memories if m.get('key_status') != 'recorded_backend_tokens'
                   or m.get('effect_status') == 'key_not_emitted'}
    for alias, node in list(nodes.items()):
        if node['kind'] != 'action':
            continue
        seq = node['ref']
        args = (index.events[seq].get('tool') or {}).get('arguments')
        if seq not in corrections and isinstance(args, dict) and args.get('action') == 'key':
            for recipe_alias, params in recipes:
                if args == params:
                    edge(alias, 'matches_recipe', recipe_alias)
    if any(a not in nodes or b not in nodes for a, _, b in links):
        raise GraphIntegrityError('Mini graph contains a dangling link')
    return {'profile': PROFILE, 'schema_version': VERSION, 'mode': 'linked',
            'episode_id': raw['episode_id'], 'frame_id': raw['frame_id'],
            'nodes': nodes, 'views': views, 'links': [list(x) for x in sorted(links)], 'sources': sources}


def expand(packet):
    """Recover the admitted original projections for diagnostics, never extra context."""
    if packet.get('schema_version') == DELIVERY_VERSION:
        from .mini_delivery import unpack
        packet = unpack(packet)
    nodes = packet['nodes']

    def values(value):
        if isinstance(value, dict):
            return {k: nodes[v]['ref'] if k in REF_FIELDS and isinstance(v, str) and v in nodes
                    else deepcopy(v) if k == 'tool' else values(v) for k, v in value.items()}
        if isinstance(value, list):
            return [values(v) for v in value]
        return value

    def row(ref):
        alias, grade = ref
        node = nodes[alias]
        body = deepcopy(node['facets'][grade])
        if node['kind'] == 'action':
            body = {**{k: node[k] for k in ('tool', 'before', 'after', 'effect_status') if k in node}, **body}
        if 'ref' in node:
            body['ref'] = node['ref']
        body['grade'] = grade
        if node['kind'] == 'keyboard_reference':
            body['recipes'] = [{k: v for k, v in nodes[r].items() if k != 'kind'} for r in body['recipes']]
            body['memory'] = [memory(r) for r in body['memory']]
        return values(body)

    def memory(ref):
        alias, grade = ref
        return {**deepcopy(nodes[alias]['facets'][grade]), 'ref': nodes[alias]['ref']}

    return {**{k: packet[k] for k in ('profile', 'episode_id', 'frame_id', 'sources')},
            'views': {name: {'records': [row(r) for r in v['record_refs']], 'omitted_records': v['omitted_records']}
                      for name, v in packet['views'].items()}}


def materialize(*, index, instruction, graph_mode, frame_id, current, attempts, lessons, totals, max_bytes,
                keyboard=None, sources=None, toolsets=(), task_catalog=None, packing=PACKING):
    """Independent graph packer: both modes are selected using the linked wire cost."""
    policy(graph_mode, packing)
    if packing == DELIVERY_PACKING:
        from .mini_delivery import materialize as deliver
        return deliver(index=index, instruction=instruction, graph_mode=graph_mode, frame_id=frame_id,
                       current=current, attempts=attempts, lessons=lessons, totals=totals, max_bytes=max_bytes,
                       keyboard=keyboard, sources=sources, toolsets=toolsets, task_catalog=task_catalog)
    if mode(graph_mode) == 'legacy':
        raise ValueError('Legacy must use its original materializer')
    limit = min(MAX_BYTES, max_bytes)
    if type(limit) is not int or limit < 0:
        raise ValueError('Mini graph budget must be a nonnegative integer')
    rows = {'attempts': attempts, 'lessons': lessons}
    if any(type(totals.get(k)) is not int or totals[k] < len(rows[k]) for k in rows):
        raise ValueError('Mini graph eligible counts must include all candidates')
    raw = {'episode_id': index.episode_id, 'frame_id': frame_id,
           'sources': sources or {}, 'views': {k: {'records': [], 'omitted_records': totals.get(k, 0)} for k in VIEW_IDS}}
    raw['views']['current']['records'] = [deepcopy(current)]
    selected = {k: set() for k in rows}
    for i, row in enumerate(lessons):
        if row.get('grade') == 'artifact_verification_state':
            raw['views']['lessons']['records'].append(deepcopy(row))
            raw['views']['lessons']['omitted_records'] -= 1
            selected['lessons'].add(i)
    literal = raw['views']['current']['records'][0]
    lookup = literal.pop('keyboard_lookup', None)
    optional = {}
    for key in ('recent_repetition', 'interaction_contract'):
        if key in literal:
            optional[key] = literal.pop(key)
            literal[key + '_omitted'] = True

    def render(value):
        return normalize(value, index, instruction, toolsets, task_catalog)

    def fits(value):
        return len(dumps(render(value)).encode('utf-8')) <= limit

    if not fits(raw):
        return None

    def admit(key, i, ceiling):
        if i in selected[key]:
            return True
        candidate = deepcopy(raw)
        view = candidate['views'][key]
        view['records'].append(deepcopy(rows[key][i]))
        view['records'].sort(key=lambda r: r.get('seq', r.get('ref', 0)))
        view['omitted_records'] -= 1
        if len(dumps(view['records']).encode('utf-8')) > ceiling or not fits(candidate):
            return False
        raw.clear()
        raw.update(candidate)
        selected[key].add(i)
        return True

    if attempts:
        admit('attempts', 0, limit)
    for grade in ('execution_error_record', 'model_artifact_review'):
        for i, row in enumerate(lessons):
            if row.get('grade') == grade:
                if admit('lessons', i, limit) or grade == 'model_artifact_review':
                    break
    if keyboard is not None:
        candidate = deepcopy(raw)
        body = deepcopy(keyboard)
        candidate['views']['keyboard']['records'] = [body]
        while not fits(candidate) and body['memory']:
            body['memory'].pop()
            body['memory_omitted'] += 1
        if fits(candidate):
            raw = candidate
        else:
            raw['views']['keyboard']['omitted_records'] = 1

    def admit_current(key, value):
        candidate = deepcopy(raw)
        body = candidate['views']['current']['records'][0]
        body.pop(key + '_omitted', None)
        body[key] = deepcopy(value)
        if fits(candidate):
            raw.clear()
            raw.update(candidate)

    if 'recent_repetition' in optional:
        admit_current('recent_repetition', optional['recent_repetition'])
    for key, quota in (('attempts', 1200), ('lessons', 1000)):
        for i in range(len(rows[key])):
            admit(key, i, quota)
    for key in rows:
        for i in range(len(rows[key])):
            admit(key, i, limit)
    if 'interaction_contract' in optional:
        admit_current('interaction_contract', optional['interaction_contract'])
    if lookup is not None:
        admit_current('keyboard_lookup', lookup)
    packet = render(raw)
    if graph_mode == 'flat':
        packet['mode'], packet['links'] = 'flat', []
    return packet
