#!/usr/bin/env bash
# Install wiki-interest-research by symlinking it into agent skill folders.
# Usage: ./install.sh [--user | --project DIR] [--agents claude,agents]
#   claude -> .claude/skills (Claude Code, OpenCode)   agents -> .agents/skills (Codex, Gemini CLI, OpenCode, others)
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="$PWD"
AGENTS="claude,agents"
while [ $# -gt 0 ]; do
  case "$1" in
    --user) BASE="$HOME"; shift ;;
    --project) BASE="${2:?--project needs a directory}"; shift 2 ;;
    --agents) AGENTS="${2:?--agents needs a list}"; shift 2 ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
IFS=, read -r -a LIST <<< "$AGENTS"
for agent in "${LIST[@]}"; do
  case "$agent" in
    claude) DIR="$BASE/.claude/skills" ;;
    agents) DIR="$BASE/.agents/skills" ;;
    *) echo "unknown agent: $agent (use claude, agents)" >&2; exit 2 ;;
  esac
  LINK="$DIR/wiki-interest-research"
  if [ -e "$LINK" ] && [ ! -L "$LINK" ]; then
    echo "$LINK exists and is not a symlink; remove it first" >&2; exit 1
  fi
  mkdir -p "$DIR"
  ln -sfn "$SRC" "$LINK"
  echo "linked $LINK -> $SRC"
done
if command -v uv >/dev/null 2>&1; then
  (cd "$SRC" && uv sync --frozen --no-dev --quiet) && echo "dependencies installed"
else
  echo "uv is missing: curl -LsSf https://astral.sh/uv/install.sh | sh   (or: brew install uv)" >&2
fi
echo "optional: export WIR_CONTACT='<your e-mail or project URL>'  # sent to Wikimedia in the User-Agent"
