"""Keep process-wide actor configuration from leaking between test cases."""
import os

import pytest


@pytest.fixture(autouse=True)
def restore_actor_environment():
    # configure_profile intentionally writes os.environ in production. Snapshot
    # instead of clearing it so tests of invalid inherited settings still work.
    before = {k: v for k, v in os.environ.items() if k.startswith('UI_KOBE_')}
    yield
    for key in set(before) | {k for k in os.environ if k.startswith('UI_KOBE_')}:
        if key in before:
            os.environ[key] = before[key]
        else:
            os.environ.pop(key, None)
