"""A project micro-task specification and artifact-only custom evaluator.

This is not an official OSWorld benchmark task/score. The evaluator is never
included in the actor's input and cannot drive actions or terminate the actor.
"""
from __future__ import annotations

import math
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
import zlib


GEOGEBRA_POINT = {
    'id': 'taskviews-quick-geogebra-point-v10',
    'test_kind': 'project_custom_cua_smoke',
    'instruction': ('Use the GeoGebra GUI to create P1 = (1, 2). Confirm that P1 appears in the algebra panel. '
                    'Save the construction as tv_quick.ggb on the Desktop, verify it is saved, then finish.'),
    'initial_state': 'Fresh local GeoGebra blank construction; no external image/PDF/website',
    'expected_guest_artifact': '/home/user/Desktop/tv_quick.ggb',
    'diagnostic_pause_after_decisions': 20,
    'native_decision_limit': 500,
    'evaluation_trigger': 'explicit native terminate or original cumulative decision limit',
    'official_benchmark_score': None,
}

TEXT_SAVE = {**GEOGEBRA_POINT,
    'id': 'taskviews-quick-text-save-v10',
    'instruction': ('In the blank text editor, type exactly TaskViews quick check. '
                    'Confirm that the text appears. Save it as tv_quick.txt on the Desktop, '
                    'verify it is saved, then finish.'),
    'initial_state': 'Blank local text editor; no external data and no pre-created target file',
    'expected_guest_artifact': '/home/user/Desktop/tv_quick.txt'}

TEXT_KEYBOARD_SAVE = {**TEXT_SAVE,
    'id': 'taskviews-quick-keyboard-text-save-v10',
    'instruction': ('Using only keyboard controls in the blank text editor, type exactly TaskViews quick check. '
                    'Confirm the text, save it to /home/user/Desktop/tv_quick.txt through the application GUI, '
                    'verify it is saved, then finish. Do not use terminal, console or scripting.'),
    'module_under_test': 'keyboard input, file-save and native-terminal pipeline; excludes pointer localization'}

TEXT_EDIT_SAVE = {**TEXT_SAVE,
    'id': 'taskviews-quick-edit-open-document-v10',
    'instruction': ('In the already opened empty document tv_input.txt, type exactly TaskViews quick check. '
                    'Confirm the text, save this current document through the editor GUI, '
                    'verify it is saved, then finish. Do not use terminal, console or scripting.'),
    'initial_state': 'Existing zero-byte document supplied as test input; no requested answer content',
    'expected_guest_artifact': '/home/user/Desktop/tv_input.txt',
    'module_under_test': 'edit existing document, save current file, native terminal; excludes Save As dialog',
    'initial_input_expected_bytes': 0}


def grade_saved_text(path, *, terminal=False, cumulative_limit=False):
    result = {'test_kind': 'project_custom_cua_smoke', 'official_score': None,
              'custom_score': None, 'checks': {}, 'evaluation_started': terminal or cumulative_limit}
    if not result['evaluation_started']:
        return result
    path = Path(path)
    checks = {'saved_file': path.is_file(), 'exact_requested_text': False}
    try:
        if path.stat().st_size > 4096:
            raise ValueError('Text artifact exceeds bounded micro-test size')
        # Editors may add their final newline; other differences stay failures.
        checks['exact_requested_text'] = path.read_text(encoding='utf-8-sig').removesuffix('\n') == 'TaskViews quick check'
    except (OSError, ValueError, UnicodeError):
        pass
    result.update(checks=checks, custom_score=float(all(checks.values())))
    return result


def grade_saved_point(path, *, terminal=False, cumulative_limit=False):
    """Inspect only the delivered ZIP/XML after the runner's real terminal event."""
    result = {'test_kind': 'project_custom_cua_smoke', 'official_score': None,
              'custom_score': None, 'checks': {}, 'evaluation_started': terminal or cumulative_limit}
    if not result['evaluation_started']:
        return result
    path = Path(path)
    checks = {'saved_file': path.is_file(), 'valid_construction': False, 'point_P1': False}
    try:
        if path.stat().st_size > 2 * 1024**2:
            raise ValueError('Delivered artifact exceeds bounded evaluation size')
        with zipfile.ZipFile(path) as archive:
            entries = [entry for entry in archive.infolist() if entry.filename == 'geogebra.xml']
            if len(entries) != 1:
                raise ValueError('Construction entry must be unique')
            entry = entries[0]
            if entry.file_size > 2 * 1024**2:
                raise ValueError('Construction XML exceeds bounded evaluation size')
            xml = archive.read(entry).decode('utf-8-sig')
        if '<!doctype' in xml.casefold() or '<!entity' in xml.casefold():
            raise ValueError('Construction XML must not declare DTD/entities')
        root = ET.fromstring(xml)
        constructions = root.findall('construction')
        checks['valid_construction'] = root.tag == 'geogebra' and len(constructions) == 1
        if checks['valid_construction']:
            points = [element for element in constructions[0].findall('element') if element.get('label') == 'P1']
            if len(points) != 1 or points[0].get('type') != 'point':
                raise ValueError('Delivered P1 must be one unambiguous point')
            coordinates = points[0].findall('coords')
            if len(coordinates) != 1:
                raise ValueError('Point coordinates must be unique')
            coords = coordinates[0]
            x, y, z = (float(coords.get(key, 'nan')) for key in ('x', 'y', 'z'))
            checks['point_P1'] = all(math.isfinite(n) for n in (x, y, z)) and z != 0 and (
                math.isclose(x / z, 1, abs_tol=1e-9) and math.isclose(y / z, 2, abs_tol=1e-9))
    except (OSError, KeyError, ValueError, UnicodeError, RuntimeError, NotImplementedError,
            zlib.error, zipfile.BadZipFile, ET.ParseError):
        pass
    result.update(checks=checks, custom_score=float(all(checks.values())))
    return result
