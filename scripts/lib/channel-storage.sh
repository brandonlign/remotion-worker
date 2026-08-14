#!/usr/bin/env bash
set -Eeuo pipefail

channel_id_from_job_id() {
  local job_id="$1"
  local channel_id="${job_id%%-*}"
  if [[ ! "$channel_id" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]]; then
    echo "Invalid channel id derived from job id: $job_id" >&2
    return 64
  fi
  printf '%s\n' "$channel_id"
}

channel_render_root() {
  local channel_id="$1"
  case "$channel_id" in
    telic)
      # Telic remains at its existing production path until the controller is
      # switched to the stable Drive folder ID and the folder is moved.
      printf '%s\n' 'Telic-Renders'
      ;;
    coffee)
      # Coffee is provisioned but controller-side production is disabled until
      # its publishing identity and production hub are complete.
      printf '%s\n' 'YouTube/Coffee/Renders'
      ;;
    *)
      echo "Unsupported render channel: $channel_id" >&2
      return 64
      ;;
  esac
}

render_root_for_job_id() {
  local job_id="$1"
  local channel_id
  channel_id="$(channel_id_from_job_id "$job_id")"
  channel_render_root "$channel_id"
}
