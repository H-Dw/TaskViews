"""The explicitly pinned OSWorld code remains external and unmodified."""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

OFFICIAL_COMMIT = "3d778a3c9a34a079316f70df023b166700445792"
CRITICAL_PATHS = ("mm_agents/qwen/images.py", "mm_agents/qwen/actions.py", "mm_agents/qwen/parser.py",
                  "mm_agents/qwen/prompts.py", "mm_agents/qwen/history.py", "lib_run_single.py",
                  "scripts/python/run_multienv_qwen.py", "desktop_env/desktop_env.py",
                  "desktop_env/controllers/python.py")


def verify_official_base(repo):
    repo = Path(repo).resolve()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    if head != OFFICIAL_COMMIT:
        raise RuntimeError("Use the declared official OSWorld commit: " + OFFICIAL_COMMIT)
    result = {}
    for relative in CRITICAL_PATHS:
        actual = (repo / relative).read_bytes()
        original = subprocess.check_output(["git", "show", f"{OFFICIAL_COMMIT}:{relative}"], cwd=repo)
        if actual != original:
            raise RuntimeError("Official execution/evaluation source changed: " + relative)
        result[relative] = hashlib.sha256(actual).hexdigest()
    return {"commit": head, "critical_sha256": result, "unchanged": True}
