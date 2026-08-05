# Telic Studio Pipeline

The VM controller is the control plane. This public repository is only the opaque render worker.

## Ownership

1. The VM creates one job, private issue, private source branch, and ChatGPT project chat.
2. ChatGPT researches and commits four private manifests on `agent/<job-id>`.
3. The worker receives only `jobId`, the exact private source SHA, and `revision` through `render/<job-id>`.
4. The worker generates voiceover, validates source, renders `AutoShort`, runs autonomous QC, and uploads the private package to `Telic-Renders/<job-id>`.
5. A successful package contains `final.mp4` and `publish.json`.
6. The worker closes its temporary PR without merging.
7. The VM downloads the package and publishes through its logged-in YouTube Studio session.

## Success contract

A worker run succeeds only when rendering, autonomous quality review, and Drive delivery succeed. YouTube credentials and publication do not belong in this repository.

## Privacy

The public repository stores no topic, script, source list, narration, metadata, private asset, credential, or render. Logs must not print private source content.

## Required secrets

- `SOURCE_REPOSITORY`
- `SOURCE_REPO_TOKEN`
- `RCLONE_CONFIG_B64`
- `ELEVENLABS_API_KEYS_JSON` or the supported fallback
- `OPENAI_API_KEY`

The VM owns scheduling, recovery, Drive retrieval, YouTube upload, processing checks, publication scheduling, and final verification.
