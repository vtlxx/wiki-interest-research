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
DIRS=()
for agent in "${LIST[@]}"; do   # check everything before changing anything
  case "$agent" in
    claude) DIR="$BASE/.claude/skills" ;;
    agents) DIR="$BASE/.agents/skills" ;;
    *) echo "unknown agent: $agent (use claude, agents)" >&2; exit 2 ;;
  esac
  if [ -e "$DIR/wiki-interest-research" ] && [ ! -L "$DIR/wiki-interest-research" ]; then
    echo "$DIR/wiki-interest-research exists and is not a symlink; remove it first" >&2; exit 1
  fi
  DIRS+=("$DIR")
done
for DIR in "${DIRS[@]}"; do
  mkdir -p "$DIR"
  ln -sfn "$SRC" "$DIR/wiki-interest-research"
  echo "linked $DIR/wiki-interest-research -> $SRC"
done
if command -v uv >/dev/null 2>&1; then
  if (cd "$SRC" && uv sync --frozen --no-dev --quiet); then
    echo "dependencies installed"
  else
    echo "uv sync failed; the first wir command will retry it" >&2
  fi
else
  echo "uv is missing: curl -LsSf https://astral.sh/uv/install.sh | sh   (or: brew install uv)" >&2
fi
echo "optional: export WIR_CONTACT='<your e-mail or project URL>'  # sent to Wikimedia in the User-Agent"
