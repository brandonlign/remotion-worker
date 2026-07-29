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

The existing browser-created Telic folder cannot be used with this restricted scope because rclone did not create it. On the first successful upload, the worker automatically creates a visible folder named `Telic-Renders` in your Drive and places each job in a separate subfolder.

Confirm the remote is restricted and working:

```bash
rclone config show gdrive \
  --config "$HOME/.config/rclone/remotion-worker.conf"
rclone mkdir gdrive:Telic-Renders \
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

## 4. Add optional private preparation secrets

Telic render jobs that generate ElevenLabs narration during `prepareCommand` require the public worker repository secret `ELEVENLABS_API_KEY`. Paste the key directly into the encrypted Actions secret. Do not put it in `remotion-worker.json`, the render request, a source file, an issue, a pull request, or a workflow log.

The worker repository therefore uses these core secrets:

- `SOURCE_REPOSITORY`
- `SOURCE_REPO_TOKEN`
- `RCLONE_CONFIG_B64`

And this Telic narration secret when voiceover generation is enabled:

- `ELEVENLABS_API_KEY`

## 5. Submit a render request

Create an internal branch named `render/<opaque-job-id>`, update `jobs/request.json`, and open a pull request into `main`.

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

The worker creates `Telic-Renders/<jobId>` in Google Drive. A successful run contains:

- the full rendered MP4
- `review.mp4`
- `contact-sheet.jpg`
- sampled keyframes
- `media-metadata.json`
- `status.json`
- `checksums.txt`
- `private-build.log`

A failed render still uploads its private build log and exit code when the Drive upload configuration works.

## 7. Keep the public repository controlled

Do not grant untrusted users write access. The workflow rejects forked pull requests, but anyone with write access can create a same-repository `render/*` branch and trigger the configured secrets.
