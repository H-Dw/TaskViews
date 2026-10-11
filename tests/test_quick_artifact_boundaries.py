"""Artifact grading boundaries; these fixtures never invoke an Agent or a VM."""
import zipfile
import zlib

import pytest

from ui_kobe.osworld.quick_checks import grade_saved_point


GOOD_POINT = '<element type="point" label="P1"><coords x="1" y="2" z="1"/></element>'
WRONG_POINT = '<element type="point" label="P1"><coords x="9" y="8" z="1"/></element>'


def save_xml(path, xml):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('geogebra.xml', xml)


def assert_rejected_artifact(path):
    result = grade_saved_point(path, terminal=True)
    assert result['evaluation_started'] is True
    assert result['checks']['saved_file'] is True
    assert result['custom_score'] == 0
    assert result['official_score'] is None


@pytest.mark.parametrize('coords', [(1, 2, 1), (2, 4, 2)])
def test_unique_direct_construction_is_scored_only_after_terminal(tmp_path, coords):
    path = tmp_path / 'valid.ggb'
    x, y, z = coords
    point = f'<element type="point" label="P1"><coords x="{x}" y="{y}" z="{z}"/></element>'
    save_xml(path, f'<geogebra><construction>{point}</construction></geogebra>')

    pending = grade_saved_point(path)
    assert pending['evaluation_started'] is False
    assert pending['custom_score'] is None and pending['checks'] == {}
    for trigger in ({'terminal': True}, {'cumulative_limit': True}):
        result = grade_saved_point(path, **trigger)
        assert result['custom_score'] == 1 and all(result['checks'].values())
        assert result['official_score'] is None


@pytest.mark.parametrize('body', [
    f'<metadata><construction>{GOOD_POINT}</construction></metadata>',
    f'<construction>{GOOD_POINT}</construction><construction/>',
    f'<metadata>{GOOD_POINT}</metadata>',
], ids=['nested_fake_construction', 'duplicate_direct_construction', 'no_construction'])
def test_only_one_direct_construction_can_define_the_delivered_point(tmp_path, body):
    path = tmp_path / 'ambiguous.ggb'
    save_xml(path, f'<geogebra>{body}</geogebra>')
    assert_rejected_artifact(path)


@pytest.mark.parametrize('points', [
    WRONG_POINT + GOOD_POINT,
    GOOD_POINT + WRONG_POINT,
], ids=['wrong_then_correct', 'correct_then_wrong'])
def test_duplicate_point_labels_are_rejected_in_both_orders(tmp_path, points):
    path = tmp_path / 'duplicate-point.ggb'
    save_xml(path, f'<geogebra><construction>{points}</construction></geogebra>')
    assert_rejected_artifact(path)


@pytest.mark.parametrize('points', [
    [WRONG_POINT, GOOD_POINT],
    [GOOD_POINT, WRONG_POINT],
], ids=['wrong_then_correct', 'correct_then_wrong'])
def test_duplicate_construction_entries_are_rejected_in_both_orders(tmp_path, points):
    path = tmp_path / 'duplicate-entry.ggb'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('geogebra.xml', f'<geogebra><construction>{points[0]}</construction></geogebra>')
        with pytest.warns(UserWarning, match='Duplicate name'):
            archive.writestr('geogebra.xml', f'<geogebra><construction>{points[1]}</construction></geogebra>')
    assert_rejected_artifact(path)


@pytest.mark.parametrize('error_type,message', [
    (NotImplementedError, 'That compression method is not supported'),
    (RuntimeError, "File 'geogebra.xml' is encrypted, password required for extraction"),
    (zlib.error, 'Error -3 while decompressing data: invalid block type'),
], ids=['unsupported_compression', 'encrypted_entry', 'damaged_deflate_stream'])
def test_entry_decode_failures_are_custom_grade_zero_not_run_exceptions(tmp_path, monkeypatch,
                                                                       error_type, message):
    path = tmp_path / 'decode-failure.ggb'
    save_xml(path, f'<geogebra><construction>{GOOD_POINT}</construction></geogebra>')
    original_open = zipfile.ZipFile.open

    def fail_read(archive, name, mode='r', *args, **kwargs):
        if mode == 'r':
            raise error_type(message)
        return original_open(archive, name, mode, *args, **kwargs)

    # The archive and central directory are real and small. Only the documented
    # entry decoding failure is injected, independently of a compression backend.
    monkeypatch.setattr(zipfile.ZipFile, 'open', fail_read)
    assert_rejected_artifact(path)


def test_internal_entity_dtd_cannot_define_an_accepted_construction(tmp_path):
    path = tmp_path / 'entity-defined.ggb'
    # A tiny internal entity supplies a coordinate; no external I/O, recursive
    # expansion or large payload is needed to exercise ElementTree's DTD support.
    xml = ('<!DOCTYPE geogebra [<!ENTITY coordinate "1">]>'
           '<geogebra><construction><element type="point" label="P1">'
           '<coords x="&coordinate;" y="2" z="1"/>'
           '</element></construction></geogebra>')
    save_xml(path, xml)
    assert_rejected_artifact(path)


def test_standard_geogebra_utf8_bom_and_non_target_text_remain_valid(tmp_path):
    path = tmp_path / 'standard.ggb'
    xml = ('\ufeff<?xml version="1.0" encoding="UTF-8"?>'
           '<geogebra format="5.0" version="5.4.925.0" '
           'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="ggb.xsd">'
           '<construction><element type="text" label="caption"><value val="中文测试"/></element>'
           + GOOD_POINT + '</construction></geogebra>')
    save_xml(path, xml)
    assert grade_saved_point(path, terminal=True)['custom_score'] == 1
