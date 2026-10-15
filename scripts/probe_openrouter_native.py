"""Probe OpenRouter text, screenshot/tools, and preserved reasoning history."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.probe_native_provider import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main('openrouter'))
