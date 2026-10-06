#!/usr/bin/env bash
# Reuse the installed SDK runtime and the same OSWorld harness; select Qwen explicitly.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$project_root/scripts/run_osworld_glm.sh" \
    --config "$project_root/configs/osworld_qwen.json" "$@"
