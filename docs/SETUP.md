# Setup

## 1. Configure the private source repository

Add `remotion-worker.json` to the root of the private Remotion repository. Start from `examples/remotion-worker.json` and adjust the composition ID or output name if needed.

The source repository must have a lockfile compatible with its install command. The current default expects npm and `package-lock.json`.

## 2. Create a read-only private-repository token

Create a fine-grained personal access token with:

- Repository access: only the private Remotion source repository
- Repository contents: read-only
- All other repository and account permissions: no access

Store it as the public worker repository secret `SOURCE_REPO_TOKEN`.

Also add:

- `SOURCE_REPOSITORY`: the private repository in `owner/name` form
- `DRIVE_FOLDER_ID`: the destination Google Drive folder ID

## 3. Create the Google Drive rclone secret

The workflow uploads with an rclone remote named `gdrive`. Create the remote on a trusted computer:

```bash
rclone config
```

Choose Google Drive, name the remote `gdrive`, and authorize the Google account that owns or can write to the destination folder.

Confirm access:

```bash
rclone lsd gdrive:
```

Encode the complete rclone configuration as one line.

macOS:

```bash
base64 -i "$HOME/.config/rclone/rclone.conf" | tr -d '\n'
```

Linux:

```bash
base64 -w 0 "$HOME/.config/rclone/rclone.conf"
```

Store that value as the repository secret `RCLONE_CONFIG_B64`.

The rclone configuration contains a renewable Google OAuth token. Treat it like a password. Do not commit it, paste it into issues, or expose it in workflow logs.

## 4. Submit a render request

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

## 5. Retrieve results

The worker creates a Drive subfolder named after `jobId`. A successful run contains:

- the full rendered MP4
- `review.mp4`
- `contact-sheet.jpg`
- sampled keyframes
- `media-metadata.json`
- `status.json`
- `checksums.txt`
- `private-build.log`

A failed render still uploads its private build log and exit code when the Drive upload configuration works.

## 6. Keep the public repository controlled

Do not grant untrusted users write access. The workflow rejects forked pull requests, but anyone with write access can create a same-repository `render/*` branch and trigger the configured secrets.
