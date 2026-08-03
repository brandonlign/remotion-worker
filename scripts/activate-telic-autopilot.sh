#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY="brandonlign/remotion-worker"
SOURCE_REPOSITORY="brandonlign/remotion-video"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOKEN_FILE="$HOME/.config/telic/youtube-refresh-token"

cleanup() {
  unset AUTOPILOT_GITHUB_TOKEN OPENAI_API_KEY YOUTUBE_CLIENT_ID YOUTUBE_CLIENT_SECRET
  rm -f "$TOKEN_FILE"
}
trap cleanup EXIT

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "$1 is required." >&2
    exit 1
  fi
}

read_hidden() {
  local variable_name="$1"
  local prompt="$2"
  local value=""
  read -r -s -p "$prompt: " value
  echo
  if [ -z "$value" ]; then
    echo "$prompt cannot be empty." >&2
    exit 1
  fi
  printf -v "$variable_name" '%s' "$value"
}

latest_dispatch_run() {
  local workflow="$1"
  local started_at="$2"
  local run_id=""
  for attempt in $(seq 1 30); do
    local runs_json
    runs_json="$(gh run list \
      --repo "$REPOSITORY" \
      --workflow "$workflow" \
      --event workflow_dispatch \
      --branch main \
      --limit 20 \
      --json databaseId,createdAt)"
    run_id="$(printf '%s' "$runs_json" | jq -r --arg started "$started_at" '[.[] | select(.createdAt >= $started)] | first | .databaseId // empty')"
    if [ -n "$run_id" ]; then
      printf '%s' "$run_id"
      return 0
    fi
    sleep 2
  done
  return 1
}

require_command gh
require_command node
require_command jq

gh auth status >/dev/null
if ! gh repo view "$REPOSITORY" >/dev/null 2>&1; then
  echo "The current GitHub login cannot access $REPOSITORY." >&2
  exit 1
fi

cat <<'TEXT'
Telic needs one new fine-grained GitHub token covering both repositories:
  - brandonlign/remotion-video
  - brandonlign/remotion-worker
Repository permissions:
  - Contents: Read and write
  - Pull requests: Read and write
  - Actions: Read-only
No account-wide permissions are required.
TEXT

read_hidden AUTOPILOT_GITHUB_TOKEN "Paste that fine-grained GitHub token"
read_hidden OPENAI_API_KEY "Paste the OpenAI API key with billing enabled"
read_hidden YOUTUBE_CLIENT_ID "Paste the Google OAuth desktop client ID"
read_hidden YOUTUBE_CLIENT_SECRET "Paste the Google OAuth desktop client secret"

printf '%s' "$SOURCE_REPOSITORY" | gh secret set SOURCE_REPOSITORY --repo "$REPOSITORY"
printf '%s' "$AUTOPILOT_GITHUB_TOKEN" | gh secret set SOURCE_REPO_WRITE_TOKEN --repo "$REPOSITORY"
printf '%s' "$AUTOPILOT_GITHUB_TOKEN" | gh secret set WORKER_TOKEN --repo "$REPOSITORY"
printf '%s' "$OPENAI_API_KEY" | gh secret set OPENAI_API_KEY --repo "$REPOSITORY"
printf '%s' "$YOUTUBE_CLIENT_ID" | gh secret set YOUTUBE_CLIENT_ID --repo "$REPOSITORY"
printf '%s' "$YOUTUBE_CLIENT_SECRET" | gh secret set YOUTUBE_CLIENT_SECRET --repo "$REPOSITORY"

gh variable set AUTOPILOT_KILL_SWITCH --body "0" --repo "$REPOSITORY"
gh variable set AUTOPUBLISH_ENABLED --body "1" --repo "$REPOSITORY"

export YOUTUBE_CLIENT_ID YOUTUBE_CLIENT_SECRET
node "$ROOT/scripts/create-youtube-refresh-token.mjs"
if [ ! -s "$TOKEN_FILE" ]; then
  echo "The YouTube refresh-token helper did not create $TOKEN_FILE." >&2
  exit 1
fi
gh secret set YOUTUBE_REFRESH_TOKEN --repo "$REPOSITORY" < "$TOKEN_FILE"
rm -f "$TOKEN_FILE"
unset YOUTUBE_CLIENT_ID YOUTUBE_CLIENT_SECRET AUTOPILOT_GITHUB_TOKEN OPENAI_API_KEY

preflight_started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
gh workflow run autopilot-preflight.yml --repo "$REPOSITORY" --ref main
preflight_run="$(latest_dispatch_run autopilot-preflight.yml "$preflight_started")" || {
  echo "The Telic preflight run did not appear." >&2
  exit 1
}
echo "Watching Telic preflight run $preflight_run..."
gh run watch "$preflight_run" --repo "$REPOSITORY" --compact --exit-status

activation_started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
gh workflow run activate-autopilot.yml --repo "$REPOSITORY" --ref main
activation_run="$(latest_dispatch_run activate-autopilot.yml "$activation_started")" || {
  echo "The activation workflow did not appear." >&2
  exit 1
}

echo
echo "Telic activation is now running entirely in GitHub Actions."
echo "You may turn off this computer."
echo "Activation run: https://github.com/$REPOSITORY/actions/runs/$activation_run"
echo "The recurring schedule will enable itself only if the full forced video publishes successfully."
