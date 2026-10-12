"""Branch-checked Mini regression, using the original bounded validator/PID."""
import os
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def main(arguments=None):
    from scripts.osworld_native_experiment import require_mini_branch, require_scope
    require_scope(128 * 1024**2)
    require_mini_branch()
    args = sys.argv[1:] if arguments is None else arguments
    os.execv(sys.executable, [sys.executable, str(PROJECT / 'scripts/validate_cua.py'), *args])


if __name__ == '__main__':
    main()
