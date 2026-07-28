# Remotion Worker

A public GitHub Actions worker that renders an exact commit from an authorized private Remotion repository and sends the result to private Google Drive storage.

The public repository contains only rendering, validation, review-asset, and packaging infrastructure. It does not store private scripts, source assets, voiceovers, or rendered videos.

## What it does

1. Accepts an owner-created render request containing an opaque job ID and a private source commit SHA.
2. Checks out the private source with a repository-scoped, read-only token.
3. Installs dependencies, runs the source project's checks, and renders the configured Remotion composition.
4. Creates a compressed review MP4, contact sheet, keyframes, metadata, checksums, and a private build log.
5. Uploads the complete result through a least-privilege Google Drive credential that can access only files and folders created by this rclone remote.
6. Publishes no render artifact and no detailed private build output in the public repository.

## Trigger model

Render jobs run only for pull requests whose branch:

- belongs to this repository, not a fork; and
- starts with `render/`; and
- changes `jobs/request.json`.

This lets an authorized GitHub/ChatGPT workflow create a render request through an internal branch and pull request while preventing forked pull requests from receiving repository secrets.

## Required private-source file

The private Remotion repository must contain `remotion-worker.json`. See [`docs/PRIVATE_SOURCE_CONTRACT.md`](docs/PRIVATE_SOURCE_CONTRACT.md) and [`examples/remotion-worker.json`](examples/remotion-worker.json).

## Setup

See [`docs/SETUP.md`](docs/SETUP.md). The worker requires three GitHub Actions secrets:

- `SOURCE_REPOSITORY`
- `SOURCE_REPO_TOKEN`
- `RCLONE_CONFIG_B64`

## Security

The upload script rejects any rclone configuration whose `gdrive` remote does not use the exact `drive.file` OAuth scope. This prevents the worker from reading or modifying unrelated files already in the connected Google Drive account.

See [`SECURITY.md`](SECURITY.md). In particular, keep write access to this public repository limited: anyone who can create a same-repository `render/*` branch can cause the workflow to use its configured secrets.
