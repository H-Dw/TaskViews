"""One explicit group contract for library workflows and catalog alternatives.

Directory order is never dependency information. Catalog lookups without a
specific action retain an explicit alternative set, admitted wholly or not at
all. Workflow dependencies are authored, not guessed from adjacent keys.
"""
from copy import deepcopy


def structure(entry):
    if entry.get('workflow'):
        return {'kind': 'workflow', 'dependencies': deepcopy(entry.get('dependencies', [])),
                'alternatives': deepcopy(entry.get('alternatives', []))}
    return {'kind': 'single_operation' if len(entry.get('bindings', [])) <= 1 else 'alternatives',
            'dependencies': [], 'alternatives': deepcopy(entry.get('alternatives', []))}


def catalog_alternatives(recipes):
    """Stable order for independent old bindings, no list-prefix selection."""
    return sorted(deepcopy(recipes), key=lambda r: r['id'])


def model_structure(value):
    result = {'group_kind': value['kind']}
    if value['dependencies']:
        result['dependencies'] = value['dependencies']
    # Existing cards already carry authored alternatives; avoid a second copy.
    return result


def validate_library(library):
    from .guidance_eligibility import GUIDE_OPS
    from .guidance_selection import BINDING_OPS
    if set(library['guides']) != set(GUIDE_OPS):
        raise ValueError('Guidance contracts must cover every authored card')
    for name, entry in library['guides'].items():
        if entry.get('operations') != GUIDE_OPS[name]:
            raise ValueError('Guidance operation contract mismatch: ' + name)
        bindings = entry['bindings']
        if len(bindings) != len(set(bindings)) or not set(bindings) <= library['bindings'].keys():
            raise ValueError('Invalid guidance binding set: ' + name)
        procedures = entry.get('procedure_operations')
        covered = set(entry['operations']).union(*(BINDING_OPS.get(b, set()) for b in bindings))
        if (not isinstance(procedures, list) or len(procedures) != len(set(procedures))
                or not set(procedures) <= covered
                or procedures and not bindings):
            raise ValueError('Invalid explicit operation procedure contract: ' + name)
        for pair in entry.get('dependencies', []):
            if (not isinstance(pair, list) or len(pair) != 2 or pair[0] == pair[1]
                    or not set(pair) <= set(bindings)):
                raise ValueError('Invalid explicit binding dependency: ' + name)
        if len(bindings) > 1 and entry.get('workflow') and not entry.get('dependencies'):
            raise ValueError('Multi-binding workflows must declare dependencies: ' + name)


def whole(record):
    """A shared guard for all new-mode cards, including imported old recipes."""
    if record.get('grade') != 'operation_guidance' or record.get('recipes_omitted', 0):
        raise ValueError('A guidance group cannot contain a recipe prefix')
    if not all(key in record for key in ('guide_id', 'scope', 'recipes', 'steps', 'source')):
        raise ValueError('Incomplete actionable guidance group')
    return deepcopy(record)
