#!/usr/bin/env bash
# Run in WSL. This creates only the agent venv; OSWorld and its environment stay untouched.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
agent_venv="${UI_KOBE_GLM_VENV:-$HOME/.local/share/ui-kobe-glm/venv}"
uv_cmd="${UV_BIN:-$HOME/.local/bin/uv}"
if ! test -x "$uv_cmd"; then uv_cmd="$(command -v uv)"; fi
if ! test -x "$agent_venv/bin/python"; then
    "$uv_cmd" venv --python python3.12 "$agent_venv"
fi
"$uv_cmd" pip install --python "$agent_venv/bin/python" -e "${project_root}[glm]" 'openai==2.26.0'
printf 'Agent Python ready: %s\n' "$agent_venv/bin/python"
