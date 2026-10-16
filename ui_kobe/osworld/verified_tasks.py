"""Pinned OSWorld-Verified task metadata and host-only asset routing."""
from pathlib import Path


TASKS = {
    'invoice': {
        'id': '337d318b-aa07-4f4f-b763-89d9a2dd013f', 'domain': 'multi_apps',
        'snapshot': 'libreoffice_calc', 'metric': 'compare_pdfs',
    },
    'gimp': {
        'id': '2a729ded-3296-423d-aec4-7dd55ed5fbb3', 'domain': 'gimp',
        'snapshot': 'gimp', 'metric': 'check_structure_sim',
        'sha256': 'a2972fc8a5b955c570b84e4a2a689b74d7a73bc999ac4ee97d3c8379fcb6bd7c',
    },
    'vlc': {
        'id': 'fba2c100-79e8-42df-ae74-b592418d54f4', 'domain': 'vlc',
        'snapshot': 'base_setup', 'metric': 'compare_images',
        'sha256': '1da8403e299e71fdf0aaebac9197ca29887007556a872a128c45bd2a57d76a4d',
    },
}


def task_path(key='invoice'):
    task = TASKS[key]
    return f"evaluation_examples/examples/{task['domain']}/{task['id']}.json"


def download_files(task):
    return [item for config in task['config'] if config['type'] == 'download'
            for item in config['parameters']['files']]


def expected_asset_name(task):
    expected = task['evaluator']['expected']
    matching = next((item for item in download_files(task) if item['url'] == expected['path']), None)
    return Path(matching['path']).name if matching else expected['dest']


def asset_files(task):
    """Gold may share an official input (invoice), or be host-only (GIMP/VLC)."""
    inputs = download_files(task)
    result = [{'name': Path(item['path']).name, 'url': item['url'], 'role': 'official_input'} for item in inputs]
    if not any(item['url'] == task['evaluator']['expected']['path'] for item in inputs):
        result.append({'name': expected_asset_name(task), 'url': task['evaluator']['expected']['path'],
                       'role': 'evaluator_only'})
    if len({item['name'] for item in result}) != len(result):
        raise ValueError('Task asset names collide')
    return result
