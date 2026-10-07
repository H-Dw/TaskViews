import json
import os
from pathlib import Path

import pytest

from scripts import validate_cua


def test_exec_chain_restores_deleted_cwd_without_spawning_a_second_interpreter(monkeypatch, tmp_path):
    state = tmp_path / 'state.json'
    state.write_text(json.dumps({'official_repo': str(tmp_path), 'dev_site_packages': None}))
    removed = tmp_path / 'removed'
    removed.mkdir()
    monkeypatch.chdir(removed)
    removed.rmdir()
    with pytest.raises(FileNotFoundError):
        os.getcwd()
    pid = os.getpid()
    class Handoff(Exception):
        pass
    def execute(program, command, environment):
        assert os.getpid() == pid and Path.cwd() == validate_cua.PROJECT
        assert command[-1] == '--worker' and environment['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] == '1'
        raise Handoff
    monkeypatch.setattr(validate_cua.os, 'execve', execute)
    with pytest.raises(Handoff):
        validate_cua._next(state, worker=True)
