#!/usr/bin/env bash
# Install the shared skill set into every skill project under the parent directory.
#
#   - The remote skills are installed with the `skills` CLI, which writes the
#     universal `.agents/skills/` copy, the per-agent directories, and the
#     `skills-lock.json` entry.
#   - designing-workflow-skills (this repository) is linked rather than copied,
#     so every project sees edits to it immediately.
#
# Project roots are discovered, not hard-coded, so a newly added project is
# picked up automatically. Re-running is idempotent: it refreshes the remote
# skills and re-points the symlinks.
#
# Usage: scripts/install-fanout.sh [--dry-run]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE_SKILL="$ROOT/workflow-skills"
LINK_NAME="designing-workflow-skills"
ALL_AGENTS='*'
DRY_RUN=""
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

REMOTE_SKILLS=(
  "199-biotechnologies/github-optimization-skill:github-optimization"
  "199-biotechnologies/humanise-text-skill:humanise-text"
)

# A project root either is a skill itself or is a directory of skills. Both get
# the shared set installed at that root, where every agent discovers it.
discover_targets() {
  local dir child
  for dir in "$ROOT"/*/; do
    dir="${dir%/}"
    [ -d "$dir" ] || continue
    if [ -f "$dir/SKILL.md" ] || [ -d "$dir/skills" ]; then
      printf '%s\n' "$dir"
      continue
    fi
    # A container of project roots, such as projects/.
    for child in "$dir"/*/; do
      child="${child%/}"
      [ -d "$child" ] || continue
      if compgen -G "$child/*/SKILL.md" >/dev/null || [ -f "$child/SKILL.md" ]; then
        printf '%s\n' "$child"
      fi
    done
  done
}

relpath() {
  python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$1" "$2"
}

# The CLI copies a local source; replace each copy with a live symlink so edits
# to this repository are visible without reinstalling.
link_local_skill() {
  local project="$1" parent link
  for parent in "$project/.agents/skills" "$project/agent/skills"; do
    [ -d "$parent" ] || continue
    link="$parent/$LINK_NAME"
    if [ -e "$link" ] && [ ! -L "$link" ]; then
      rm -rf "$link"
    fi
    ln -sfn "$(relpath "$SOURCE_SKILL" "$parent")" "$link"
  done
}

install_skill() {
  local project="$1" source="$2" skill="$3" attempt
  # A concurrent edit to a local source can make one copy pass fail, so retry
  # before reporting. </dev/null keeps the CLI from consuming the caller's
  # stdin, which the discovery loop below reads from.
  for attempt in 1 2 3; do
    if ( cd "$project" && npx --yes skills add "$source" \
           --skill "$skill" --agent "$ALL_AGENTS" --yes >/dev/null 2>&1 </dev/null ); then
      return 0
    fi
    sleep 1
  done
  return 1
}

# Trust the resulting tree, not the installer's exit code.
verify_project() {
  local project="$1" skill missing=""
  for skill in "${REMOTE_SKILLS[@]##*:}" "$LINK_NAME"; do
    if [ "$skill" = "$LINK_NAME" ] && [ "$project" = "$SOURCE_SKILL" ]; then
      continue
    fi
    [ -e "$project/.agents/skills/$skill/SKILL.md" ] || missing="$missing $skill(.agents)"
    [ -e "$project/.claude/skills/$skill/SKILL.md" ] || missing="$missing $skill(.claude)"
  done
  if [ -n "$missing" ]; then
    echo "    INCOMPLETE:$missing"
    return 1
  fi
}

failures=0
while IFS= read -r project; do
  echo "==> ${project#"$ROOT"/}"
  if [ -n "$DRY_RUN" ]; then
    continue
  fi

  for entry in "${REMOTE_SKILLS[@]}"; do
    install_skill "$project" "${entry%%:*}" "${entry##*:}" || true
  done

  # The source repository already is the skill; it needs no link to itself.
  if [ "$project" != "$SOURCE_SKILL" ]; then
    install_skill "$project" "$SOURCE_SKILL" "$LINK_NAME" || true
    link_local_skill "$project"
  fi

  verify_project "$project" || failures=$((failures + 1))
done < <(discover_targets)

if [ "$failures" -gt 0 ]; then
  echo "incomplete in $failures project(s)"
  exit 1
fi
echo "done"
