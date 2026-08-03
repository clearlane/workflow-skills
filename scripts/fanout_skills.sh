#!/usr/bin/env bash
# Install the shared skill set into every skill project under Development/skills.
#
#   - github-optimization and humanise-text are installed from GitHub via the
#     `skills` CLI, which writes the universal `.agents/skills/` copy plus the
#     per-agent directories and updates `skills-lock.json`.
#   - designing-workflow-skills (this repository) is linked, not copied, so
#     every project sees edits immediately.
#
# Idempotent: re-running refreshes the remote skills and re-points the symlinks.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE_SKILL="$ROOT/workflow-skills"
LINK_NAME="designing-workflow-skills"
ALL_AGENTS='*'

REMOTE_SKILLS=(
  "199-biotechnologies/github-optimization-skill:github-optimization"
  "199-biotechnologies/humanise-text-skill:humanise-text"
)

# Every directory that is a project root for skill discovery.
TARGETS=(
  accounting
  auto-listing
  budibase
  chronologie
  convex-native
  email-task-manager
  issue-management
  klarc-task-orchestrator
  lean-refactor
  mailbox
  multica
  ontologist
  scrum
  seo-checklist-maintainer
  shadcnblocks
  sign-document
  suivi-temps
  voxel-builder
  workflow-skills
  wpdev-plugin
  projects/company-builder
  projects/dashboards
  projects/myproof
  projects/paperclip-app
  projects/wordpress-seo
  projects/wordpress
)

relpath() {
  python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$1" "$2"
}

link_local_skill() {
  local project="$1" parent
  # Agent directories the CLI materialises a real skill folder into.
  for parent in "$project/.agents/skills" "$project/agent/skills"; do
    [ -d "$parent" ] || continue
    local link="$parent/$LINK_NAME"
    [ -L "$link" ] || [ ! -e "$link" ] || rm -rf "$link"
    ln -sfn "$(relpath "$SOURCE_SKILL" "$parent")" "$link"
  done
}

for target in "${TARGETS[@]}"; do
  project="$ROOT/$target"
  if [ ! -d "$project" ]; then
    echo "skip (missing): $target"
    continue
  fi
  echo "==> $target"
  for entry in "${REMOTE_SKILLS[@]}"; do
    ( cd "$project" && npx --yes skills add "${entry%%:*}" \
        --skill "${entry##*:}" --agent "$ALL_AGENTS" --yes >/dev/null 2>&1 ) \
      || echo "    FAILED: ${entry##*:}"
  done

  if [ "$project" != "$SOURCE_SKILL" ]; then
    ( cd "$project" && npx --yes skills add "$SOURCE_SKILL" \
        --skill "$LINK_NAME" --agent "$ALL_AGENTS" --yes >/dev/null 2>&1 ) \
      || echo "    FAILED: $LINK_NAME"
    # The CLI copies local sources; replace the copy with a live symlink.
    link_local_skill "$project"
  fi
done

echo "done"
