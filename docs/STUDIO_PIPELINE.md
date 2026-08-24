# Telic Studio Pipeline

The VM controller is the control plane. This public repository is only the
opaque render worker.

## Ownership

1. The VM creates one job, private coordination issue, private source branch,
   and ChatGPT project chat.
2. ChatGPT researches the topic, writes the narration and metadata, and commits
   the private production manifests and Remotion source.
3. The worker receives only an opaque `jobId`, the exact private source SHA,
   and a revision through a `render/<job-id>` pull request.
4. The worker performs the requested private stage:
   - `voice-prep` generates Gemini narration and exact-script WhisperX timing;
   - `render-sequence` creates a private long-form window preview;
   - `render` restores the locked audio package, prepares the configured
     private composition, runs source checks, renders, and performs
     deterministic media QC.
5. The worker uploads the successful package to the channel-specific private
   Drive location. A full render includes `final.mp4` and `publish.json`.
6. The VM reviews the private output, closes the temporary render PR without
   merging it, and publishes through the channel's YouTube publisher. Once
   processing and the exact future schedule are verified, the private job is
   terminal; it does not wait for the video to become public.

Metadata-only finalization and non-canonical Short previews have separate
request files and workflows so they cannot masquerade as a canonical render.

## Source and composition contract

The private repository owns the composition, output name, preparation command,
checks, narration, assets, audio timing, and YouTube metadata through its
root-level `remotion-worker.json` and private `automation/current/` manifests.
The worker does not receive a composition name or video details in the public
request. Long-form requests use the private `CustomLongForm` contract and
sequence previews; short requests use the private short composition selected
by the source contract and channel stage.

## Voice and timing

Voice preparation uses the Gemini credential pool configured in the worker
secrets and the voice profile selected by the private source. The production
package must contain the exact narration, MP3 voiceover, alignment data, and
audio runtime. Exact-script forced alignment uses pinned WhisperX 3.8.6; the
worker fails rather than substituting proportional timing.

## Success contract

A worker stage succeeds only when its private preparation/render path, required
quality gates, and Drive delivery succeed. YouTube credentials and publication
state do not belong in this repository.

## Privacy and secrets

The public repository stores no topic, script, source list, narration,
metadata, private asset, credential, or rendered media. Logs must not print
private source content.

The worker uses:

- `SOURCE_REPOSITORY`
- `SOURCE_REPO_TOKEN`
- `RCLONE_CONFIG_B64`
- `GEMINI_API_KEYS_JSON` (preferred)
- `GEMINI_API_KEY` (single-key fallback)

The Drive credential must use exactly the `drive.file` OAuth scope. The VM
owns scheduling, recovery, Drive retrieval, YouTube upload, processing checks,
publication scheduling, and final verification.
