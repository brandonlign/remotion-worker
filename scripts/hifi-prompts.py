from pathlib import Path

root = Path('tools/telic-vnext')
prompts = root / 'channels/hifi/prompts'

files = {
'voice-stage.txt': '''HiFi Studio Short voice compatibility entrypoint.

Do not duplicate the shared voice-generation contract here. Read and follow:
- `tools/telic-vnext/universal/prompts/voice-stage.txt`
- `tools/telic-vnext/universal/CREATIVE_CORE.md`
- `tools/telic-vnext/channels/hifi/style.md`

Use the locked HiFi narration exactly as approved. The Universal Chatterbox voice profile is the default; HiFi does not maintain a separate TTS stack. Preserve intelligibility for product/model names, units, prices, and technical terms. If pronunciation is ambiguous, fix pronunciation without editorially rewriting the script. Do not add a fake broadcaster or luxury-ad cadence; the delivery should sound informed, conversational, and confident without overselling subjective claims.
''',
'visual-plan-stage.txt': '''Complete only visual planning for this existing HiFi Studio Short. Do not build, render, sound-design, QC, or publish.

Job: `{{JOB_ID}}`
Issue: {{ISSUE_URL}}
Source repo: `{{SOURCE_REPO}}`
Source branch: `agent/{{JOB_ID}}`

Before writes, fetch issue/comments and require the normal source/voice prerequisites. Read the locked narration/source package, `tools/telic-vnext/universal/CREATIVE_CORE.md`, `channels/hifi/style.md`, and `channels/hifi/research.md`.

Plan the strongest evidence or explanation for each narration beat. HiFi visuals should favor the exact product/revision, real internals, driver/crossover or circuit topology, manuals, patent/service drawings, traceable measurement plots, archival ads, room/system relationships, and direct A/B diagrams when those are what the narration is actually about. A beautiful unrelated listening room or close-up of a knob is not evidence.

For technical claims, make the causal relationship visible: for example impedance/phase versus amplifier demand, crossover topology versus driver handoff, cabinet/port geometry versus claimed behavior, or price jump versus the actual changed hardware/features. Use authored diagrams when the relationship is invisible; use real media when physical reality is the point. Keep graph axes, units, legends, and provenance readable enough that the visual does not imply more than the source supports.

Do not plan a spec-card slideshow, waveform wallpaper, generic luxury B-roll, repeated hero shots, decorative equalizers, or narration copied into sentences on screen. Exact model names, a decisive number, a comparison label, or a short quoted claim can appear when they materially orient the viewer. Every beat must newly reveal, compare, or explain something.

Create/update the normal `automation/current/visual-plan.json` contract with exact assets, provenance, beat purposes, review moments, and audio intent. Verify every external asset is truthful to the exact model/claim and has a usable crop. Re-fetch issue/comments, commit, post exactly `TELIC_STAGE: visual_plan_ready`, then stop.
''',
'composition-stage.txt': '''Complete only private Remotion composition construction for this existing HiFi Studio Short. Do not final-render, specialized sound-design, creative-QC, or publish.

Job: `{{JOB_ID}}`
Issue: {{ISSUE_URL}}
Source repo: `{{SOURCE_REPO}}`
Worker: `{{WORKER_REPO}}`
Source branch: `agent/{{JOB_ID}}`
Render branch: `render/{{JOB_ID}}`
Publish at: `{{PUBLISH_AT}}`

Before writes, fetch issue/comments. Require `source_committed`, `voice_ready`, and `visual_plan_ready`; stop if this or a later stage is already complete or the job is terminal.

Read `tools/telic-vnext/universal/CREATIVE_CORE.md`, `channels/hifi/style.md`, and the locked source/voice/visual-plan artifacts. Facts, narration, timing, required evidence, and visual purposes are locked. Build with shared Remotion primitives as Lego pieces, not as scene templates.

Make the exact equipment the visual subject whenever physical design matters. For engineering beats, combine real product imagery with small authored overlays, cutaways, signal paths, dimensions, or measurement traces instead of replacing the object with generic cards. When comparing products or price tiers, keep comparison dimensions consistent and visually honest. Never animate a measurement or diagram in a way that implies an unsupported causal or audible claim.

Visual progression is a hard gate: each narration beat must produce a new useful state, relationship, piece of evidence, or comparison. A slow zoom on the same speaker, amplifier, knob, listening room, or graph is not progression. Do not repeat product photography just because it is attractive. Use exact media, meaningful crops, diagrams, archival material, or a different explanatory medium.

Text is purposeful, not automatic. Use exact model/revision names, concise labels, prices/units, short attributed claims, or comparison dimensions when they help orientation. Do not create headline/subhead/body card stacks, spec walls, decorative captions, or sentence-level transcription.

Create/replace only the normal composition contract files required by the pipeline. HiFi inherits Universal voice/audio defaults; do not require a channel-local `audio-library.json`. Preserve required audio intent for the later sound-design stage without pretending the composition pass is a sound demo.

Run focused syntax/type/lint, timing, asset, and source checks. Inspect chronological review states, especially the opening and every explanatory transition. Reject generic luxury-room filler, waveform/equalizer wallpaper, repeated hero shots, unreadable graph axes, ambiguous product variants, or any frame that could belong to an unrelated audio video after swapping labels. Re-fetch issue/comments, commit, post exactly `TELIC_STAGE: composition_ready`, then stop.
''',
'sound-design-stage.txt': '''Complete only sound design for this existing HiFi Studio Short after composition is ready. Do not change locked narration or use audio effects to imply a product sounds a certain way.

Read the current composition/audio intent, `tools/telic-vnext/universal/CREATIVE_CORE.md`, and `channels/hifi/style.md`. HiFi inherits the Universal shared SFX pool and defaults to no music unless the job explicitly carries approved music intent. Do not depend on a channel-local audio library.

Use SFX sparingly for real editorial events: a cut, reveal, mechanical action, diagram transition, comparison switch, or other motion that benefits from an audible accent. Avoid constant clicks, synthetic UI beeps, decorative whooshes, or “premium” ambience. Never use an unverified recording as though it demonstrates the reviewed speaker/headphone/amplifier. Narration remains dominant and intelligible.

Inspect the complete Short with audio, fix event timing and levels, update the normal audio-design contract, run audio/runtime checks, re-fetch issue/comments, commit, post exactly `TELIC_STAGE: sound_design_ready`, then stop.
''',
'qc-stage.txt': '''Perform only final creative/technical QC for this existing HiFi Studio Short. Do not publish.

Read `tools/telic-vnext/universal/CREATIVE_CORE.md`, `channels/hifi/style.md`, `channels/hifi/research.md`, the locked source package, composition/audio contracts, and current issue/comments. Review the complete assembled Short with sound rather than judging isolated frames.

Hard HiFi checks: exact product/revision imagery is not mislabeled; price/date context is not misleading; specifications and measurement graphs retain correct units/axes; manufacturer claims and reviewer impressions are not presented as measured fact; the edit never invents first-person listening/testing; disputed audiophile claims remain qualified; attractive B-roll has not displaced the actual evidence; and the video does not imply the viewer can reliably hear a hardware difference through an uncontrolled YouTube playback chain.

Creative checks: the opening establishes the specific object/tension quickly; every explanatory beat materially changes what the viewer sees or understands; real-media reuse is intentional; graphs/diagrams are phone-readable; text is purposeful; there is no spec-card slideshow, generic luxury montage, waveform wallpaper, repeated knob B-roll, dead visual hold, or generic AI-explainer layout. Fix substantive defects and rerun checks rather than accepting technical validity as completion.

When the normal QC contract is genuinely satisfied, post exactly the stage marker required by the controller and stop. Do not publish from this stage.
''',
'long-voice-stage.txt': '''HiFi Studio long-form voice compatibility entrypoint.

Read and follow all canonical files before generating voice:
- `tools/telic-vnext/universal/prompts/long-voice-stage.txt`
- `tools/telic-vnext/universal/CREATIVE_CORE.md`
- `tools/telic-vnext/universal/format/long.md`
- `tools/telic-vnext/channels/hifi/style.md`

Universal owns generation, segmentation, validation, and artifacts. HiFi adds only delivery taste: informed enthusiast, natural pace, clean pronunciation of exact model names/units, no luxury-ad affectation, no fake excitement, and no vocal implication of firsthand listening when the script does not contain real firsthand evidence.
''',
'long-visual-plan-stage.txt': '''HiFi Studio long-form visual-plan compatibility entrypoint.

Do not duplicate the production contract here. Read and follow:
- `tools/telic-vnext/universal/prompts/long-visual-plan-stage.txt`
- `tools/telic-vnext/universal/CREATIVE_CORE.md`
- `tools/telic-vnext/universal/format/long.md`
- `tools/telic-vnext/channels/hifi/style.md`
- `tools/telic-vnext/channels/hifi/research.md`

Universal owns the schema, windowing, procedure, provenance, and quality floor. HiFi-specific planning should prioritize exact equipment/revisions, real internals, manuals/service/patent drawings, traceable measurement plots, archival ads, system diagrams, and authored causal/comparison graphics. Product beauty shots and listening rooms are context, not default evidence. A graph is useful only if its axes, units, source, and relationship to the narration are legible and honest. Do not create `visual-system.json`, nested scene schemas, spec-card templates, waveform wallpaper, or repeated hero-shot holds.
''',
'long-visual-build-stage.txt': '''HiFi Studio long-form visual-build compatibility entrypoint.

Read and follow:
- `tools/telic-vnext/universal/prompts/long-visual-build-stage.txt`
- `tools/telic-vnext/universal/CREATIVE_CORE.md`
- `tools/telic-vnext/universal/format/long.md`
- `tools/telic-vnext/channels/hifi/style.md`

Universal owns build procedure, window contracts, validation, and the rule not to render individual windows. HiFi adds subject-specific taste: make exact products and evidence unmistakable; distinguish model revisions; keep graphs/units readable; use internals/diagrams to explain mechanisms; and use archival product material when history matters. Do not substitute generic listening rooms, knobs, equalizer/waveform graphics, or luxury textures for missing evidence. Shared primitives are tools, not a visual template.
''',
'long-sound-design-stage.txt': '''HiFi Studio long-form sound-design compatibility entrypoint.

Read and follow:
- `tools/telic-vnext/universal/prompts/long-sound-design-stage.txt`
- `tools/telic-vnext/universal/CREATIVE_CORE.md`
- `tools/telic-vnext/channels/hifi/style.md`

Universal owns the audio procedure and contracts. HiFi defaults to Universal shared SFX and no music unless the job explicitly approves music. Use sound to support edits, physical actions, reveals, comparison switches, and explanatory motion—not to manufacture a “premium” atmosphere. Never present an unverified clip or processed sample as a trustworthy demonstration of a component's sound. Keep narration dominant.
''',
'long-assembly-stage.txt': '''HiFi Studio long-form assembly compatibility entrypoint.

Read and follow:
- `tools/telic-vnext/universal/prompts/long-assembly-stage.txt`
- `tools/telic-vnext/universal/CREATIVE_CORE.md`
- `tools/telic-vnext/universal/format/long.md`
- `tools/telic-vnext/channels/hifi/style.md`

Universal owns assembly, render, validation, and artifact contracts. HiFi adds no alternate renderer. During the assembled-preview check, specifically catch mislabeled product variants, unreadable measurement plots, repeated beauty-shot filler, or an edit that accidentally implies a listening test the production never performed.
''',
'long-metadata-stage.txt': '''HiFi Studio long-form metadata compatibility entrypoint.

Read and follow:
- `tools/telic-vnext/universal/prompts/long-metadata-stage.txt`
- `tools/telic-vnext/universal/CREATIVE_CORE.md`
- `tools/telic-vnext/channels/hifi/packaging.md`
- `tools/telic-vnext/channels/hifi/style.md`

Universal owns metadata procedure and validation. HiFi packaging should foreground the exact product/category and concrete tension—price versus benefit, old versus new, reputation versus evidence, engineering tradeoff, or system decision. Exact model names matter. Do not use “best,” “legendary,” “overpriced,” “giant-killer,” or similar certainty unless the researched video earns it. Avoid titles that are merely generic hi-fi education or luxury aspiration.
''',
'long-qc-stage.txt': '''HiFi Studio long-form QC compatibility entrypoint.

Read and follow:
- `tools/telic-vnext/universal/prompts/long-qc-stage.txt`
- `tools/telic-vnext/universal/CREATIVE_CORE.md`
- `tools/telic-vnext/universal/format/long.md`
- `tools/telic-vnext/channels/hifi/style.md`
- `tools/telic-vnext/channels/hifi/research.md`

Universal owns complete assembled-preview review, technical validation, creative iteration, and the `TELIC_CREATIVE_REVIEW` contract. HiFi adds hard domain checks: exact model/revision identity, honest price/date context, legible measurement axes/units, correct separation of measured facts from manufacturer/reviewer claims, no invented listening authority, no laundering of disputed audiophile claims into fact, and no implication that an uncontrolled YouTube playback sample proves component sound. Reject spec-card slideshows, luxury-room filler, repeated hero/knob shots, waveform wallpaper, and long visually static holds. Fix meaningful defects before declaring QC complete.
''',
}

for name, text in files.items():
    path = prompts / name
    if not path.exists():
        raise SystemExit(f'Expected migrated HiFi stage prompt missing: {path}')
    path.write_text(text)
