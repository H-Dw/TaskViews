#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
osworld_home="${OSWORLD_HOME:-$HOME/osworld2}"
osworld_repo="${OSWORLD_REPO:-$osworld_home/OSWorld-V2}"
agent_venv="${UI_KOBE_GLM_VENV:-$HOME/.local/share/ui-kobe-glm/venv}"
if test -f "$osworld_home/env.sh"; then source "$osworld_home/env.sh"; fi
export PYTHONPATH="$project_root:$osworld_repo${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
exec nice -n 10 ionice -c 2 -n 7 "$osworld_repo/.venv/bin/python" -m ui_kobe.osworld.runner \
    --osworld-root "$osworld_repo" --agent-python "$agent_venv/bin/python" \
    --config "$project_root/configs/osworld_glm.json" "$@"
