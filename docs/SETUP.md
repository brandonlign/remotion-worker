# Setup

## 1. Configure the private source repository

Add `remotion-worker.json` to the root of the private Remotion repository. Start from `examples/remotion-worker.json` and adjust the composition ID or output name if needed.

The source repository must have a lockfile compatible with its install command. The current default expects npm and `package-lock.json`.

Use the optional `prepareCommand` for trusted private build-time work that must happen before checks and rendering, such as generating narration into a local asset path.

## 2. Create a read-only private-repository token

Create a fine-grained personal access token with:

- Repository access: only the private Remotion source repository
- Repository contents: read-only
- All other repository and account permissions: no access

Store it as the public worker repository secret `SOURCE_REPO_TOKEN`.

Also add:

- `SOURCE_REPOSITORY`: the private repository in `owner/name` form

## 3. Create the least-privilege Google Drive rclone secret

The worker deliberately rejects full-Drive credentials. Its `gdrive` remote must use the `drive.file` OAuth scope, which lets rclone read and modify only files and folders that rclone itself creates. It cannot view or edit unrelated files already in your Drive.

Create a dedicated rclone configuration on a trusted computer:

```bash
rclone config --config "$HOME/.config/rclone/remotion-worker.conf"
```

Choose:

- New remote
- Remote name: `gdrive`
- Storage: Google Drive
- OAuth scope: `drive.file` — access only to files created by rclone
- Authorize the Google account where the renders should appear
- Do not configure a Shared Drive

Do not choose the default full-access `drive` scope. The upload script checks the configuration and refuses to run unless the scope is exactly `drive.file`.

The existing browser-created render folders cannot be used with this restricted scope unless they were created by this rclone remote. The worker routes jobs by their immutable channel prefix and creates the required path on first upload:

- Telic: `YouTube/Telic/Telic-Renders/<jobId>`
- Coffee: `YouTube/Coffee/Renders/<jobId>`

Confirm the remote is restricted and working:

```bash
rclone config show gdrive \
  --config "$HOME/.config/rclone/remotion-worker.conf"
rclone mkdir gdrive:YouTube/Telic/Telic-Renders \
  --config "$HOME/.config/rclone/remotion-worker.conf"
rclone lsd gdrive: \
  --config "$HOME/.config/rclone/remotion-worker.conf"
```

The displayed `gdrive` configuration should contain:

```text
scope = drive.file
```

Encode the dedicated configuration as one line without printing it:

```bash
base64 -i "$HOME/.config/rclone/remotion-worker.conf" \
  | tr -d '\n' \
  | pbcopy
```

Store the clipboard value as the repository secret `RCLONE_CONFIG_B64`.

The configuration contains a renewable Google OAuth token. Treat it like a password. Do not commit it, paste it into issues, or expose it in workflow logs.

## 4. Add the private voice-preparation secrets

For automatic Telic narration, create an encrypted repository secret named `GEMINI_API_KEYS_JSON`. Its value must be a JSON array of Google AI Studio API keys:

```json
["first-api-key", "second-api-key", "third-api-key"]
```

Use keys from projects that have access to Gemini 3.1 Flash TTS Preview. The private source removes duplicate entries, deterministically spreads different jobs across the pool, and rotates to the next credential when a key is rejected or returns a quota-exhaustion response. A maximum of 50 keys is accepted.

The older `GEMINI_API_KEY` secret remains supported as a single-key fallback. When `GEMINI_API_KEYS_JSON` is present, the pool takes precedence. Keep `GEMINI_API_KEY` during migration, then remove it after a successful pooled-key voice-preparation run if desired.

The private source currently locks production narration to:

- model: `gemini-3.1-flash-tts-preview`
- voice: `Iapetus`
- output: mono MP3 at 44.1 kHz and 128 kbps
- timing: pinned WhisperX 3.8.6 forced alignment of the exact script to the finished audio

The first voice-preparation run installs the pinned WhisperX environment and downloads the default English wav2vec2 alignment model. The worker caches both for later jobs. No Hugging Face token is required for the default English alignment path.

Voice preparation refuses proportional timing. It must produce character timestamps for the exact narration, cover at least 98.5% of letters and digits, and pass confidence and leading/trailing-edge checks. A failure preserves private diagnostics in Drive and stops the job before custom composition work.

The keys are exposed only to the trusted private voice-preparation process. The logs and metadata may identify only a numeric credential slot, never a key value. Do not put credentials in `remotion-worker.json`, the render request, a source file, an issue, a pull request, or a workflow log.

The worker repository therefore uses these secrets:

- `SOURCE_REPOSITORY`
- `SOURCE_REPO_TOKEN`
- `RCLONE_CONFIG_B64`
- `GEMINI_API_KEYS_JSON` — preferred credential pool
- `GEMINI_API_KEY` — optional single-key fallback

## 5. Submit a render request

Create an internal branch named `render/<opaque-job-id>`, update `jobs/request.json`, and open a pull request into `main`. `Worker CI` validates the request-only diff without secrets; after it passes, the trusted `workflow_run` render job checks out worker code from `main` and extracts only the request JSON from the exact PR commit.

Example:

```json
{
  "jobId": "telic-20260728-001",
  "sourceSha": "0123456789abcdef0123456789abcdef01234567",
  "revision": 1
}
```

Requirements:

- `jobId`: 6-64 lowercase letters, numbers, or hyphens
- `sourceSha`: the complete 40-character private-source commit SHA
- `revision`: positive integer

The public manifest intentionally contains no topic, script, asset name, composition ID, or output filename. Those stay in the private source repository.

## 6. Retrieve results

The worker creates the channel-specific `<jobId>` folder in Google Drive. A successful voice-preparation package contains:

- `voiceover.mp3`
- `alignment.json` with character and word timing plus alignment quality metrics
- `audio-runtime.json` with exact beat frames
- `narration.txt`
- `status.json`
- `checksums.txt`
- `private-voice.log`

A successful render package contains the full rendered MP4, review MP4, contact sheet, keyframes, metadata, checksums, and private build log. A failed stage still uploads its private diagnostic package when the Drive configuration works.

## 7. Keep the public repository controlled

Do not grant untrusted users write access. The workflow rejects forked pull requests, but anyone with write access can create a same-repository `render/*` branch and trigger the configured secrets.
