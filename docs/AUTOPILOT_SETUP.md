# Telic Autopilot Setup

This repository is the public cloud runner. It stores only generic workflow code and opaque render requests. Telic topics, scripts, sources, narration, metadata, private assets, and renders remain in the private source repository or Google Drive.

## 1. Rotate exposed credentials

Before activation, rotate any credential that has ever appeared in a document, chat, repository, issue, workflow log, or screenshot. Remove raw credentials from the Telic Production Hub. Store replacements only as encrypted repository secrets.

## 2. Google Cloud and YouTube

1. Create or select a Google Cloud project.
2. Enable the YouTube Data API v3.
3. Configure the OAuth consent screen for the Telic channel owner.
4. Create an OAuth client of type **Web application**.
5. Add this exact authorized redirect URI:

   `http://localhost:8080/oauth2callback`

6. Export the client credentials for one local command:

   ```bash
   export YOUTUBE_CLIENT_ID='replace-me'
   export YOUTUBE_CLIENT_SECRET='replace-me'
   node scripts/create-youtube-refresh-token.mjs
   ```

7. Sign into the Google account that owns Telic and approve the `youtube.upload` scope.
8. The helper saves the refresh token to `~/.config/telic/youtube-refresh-token` with owner-only permissions.
9. Add that file's content as the repository secret `YOUTUBE_REFRESH_TOKEN`, then delete the local file.

The refresh token enables unattended access after the one-time consent flow. YouTube does not support ordinary channel automation through a service account.

New or unaudited YouTube API projects may be restricted to private uploads. Complete Google's YouTube API audit before relying on scheduled public publication.

## 3. Fine-grained GitHub tokens

Create repository-scoped fine-grained tokens rather than broad classic tokens.

### `SOURCE_REPO_WRITE_TOKEN`

Repository: `brandonlign/remotion-video`

Permission:

- Contents: read and write

Purpose: the public scheduler checks out the private control plane, commits the generated private job and state, and pushes the exact source commit used for rendering.

### `WORKER_TOKEN`

Repository: `brandonlign/remotion-worker`

Permissions:

- Contents: read and write
- Pull requests: read and write

Purpose: creates an opaque `render/<job-id>` branch and temporary draft PR. This must be a real fine-grained token. GitHub events created with the workflow's built-in `GITHUB_TOKEN` do not start another workflow.

Keep the existing read-only `SOURCE_REPO_TOKEN` for the render workflow. Do not replace it with the write token.

## 4. Public worker secrets

Existing render secrets:

- `SOURCE_REPOSITORY` = `brandonlign/remotion-video`
- `SOURCE_REPO_TOKEN`
- `RCLONE_CONFIG_B64`
- `ELEVENLABS_API_KEYS_JSON`, or the existing single-key fallback

New autopilot secrets:

- `SOURCE_REPO_WRITE_TOKEN`
- `WORKER_TOKEN`
- `OPENAI_API_KEY`
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`

Repository variables:

- `AUTOPILOT_KILL_SWITCH=1` during setup
- `AUTOPUBLISH_ENABLED=0` during setup

## 5. Safe activation order

1. Merge the private control-plane changes while `automation/config.json` remains disabled.
2. Merge the public worker changes with both repository variables still disabled.
3. Add and verify every secret.
4. Set `AUTOPUBLISH_ENABLED=1` but keep `AUTOPILOT_KILL_SWITCH=1`.
5. Run **Telic autopilot** manually with `force=true`.
6. Verify the private source commit, render check, YouTube video ID, processing success, future schedule, complete Drive package, and closed temporary render PR.
7. Set `AUTOPILOT_KILL_SWITCH=0`.
8. Change `automation/config.json` to `"enabled": true` in the private repository.

The default configuration publishes Monday, Wednesday, and Friday at 6:00 PM America/New_York and caps output at three videos per week.

## 6. Emergency stop

Set this public worker repository variable:

```text
AUTOPILOT_KILL_SWITCH=1
```

The next scheduler run exits before generating or committing a job. Existing videos already accepted by YouTube must be managed in YouTube Studio.

## 7. External failure modes

The system does not depend on a personal laptop after activation, but no third-party pipeline is immortal. It can stop because of revoked OAuth consent, invalidated tokens, exhausted credits, billing failures, quota limits, API changes, provider outages, GitHub enforcement, Google enforcement, or loss of account access. Keep recovery access to the GitHub, Google, OpenAI, ElevenLabs, and Drive accounts.
