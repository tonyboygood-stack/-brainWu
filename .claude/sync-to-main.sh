#!/bin/bash

# Read JSON input (Stop hook passes session data via stdin)
input=$(cat)

# Recursion guard
stop_hook_active=$(echo "$input" | jq -r '.stop_hook_active')
if [[ "$stop_hook_active" = "true" ]]; then
  exit 0
fi

# Must be in a git repo with a remote
if ! git rev-parse --git-dir >/dev/null 2>&1; then exit 0; fi
if [[ -z "$(git remote)" ]]; then exit 0; fi

# Only act if there are uncommitted changes or we're on a feature branch
current_branch=$(git branch --show-current)
if [[ -z "$current_branch" || "$current_branch" == "main" ]]; then exit 0; fi

# Don't merge if working tree is dirty
if ! git diff --quiet || ! git diff --cached --quiet; then exit 0; fi

# Check if feature branch has commits not yet in main
commits_ahead=$(git rev-list "main..$current_branch" --count 2>/dev/null) || commits_ahead=0
if [[ "$commits_ahead" -eq 0 ]]; then exit 0; fi

# Merge feature branch into main and push
git checkout main >/dev/null 2>&1
git pull origin main --quiet 2>/dev/null

if git merge "$current_branch" --no-edit --quiet 2>/dev/null; then
  if git push origin main --quiet 2>/dev/null; then
    echo "已將 $current_branch 的 $commits_ahead 個 commit 同步到 main 並推送。" >&2
  fi
fi

# Return to feature branch
git checkout "$current_branch" --quiet 2>/dev/null

exit 0
