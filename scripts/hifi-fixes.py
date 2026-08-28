from pathlib import Path
import re

root = Path('tools/telic-vnext')
prompts = root / 'channels/hifi/prompts'

# Preserve exact job isolation in worker-using compatibility entrypoints.
voice = prompts / 'voice-stage.txt'
s = voice.read_text()
s = s.replace(
    'Use the locked HiFi narration exactly as approved.',
    'Job: `{{JOB_ID}}`. Worker branch: `render/{{JOB_ID}}`; `jobs/request.json.jobId` must be exactly `{{JOB_ID}}`. Never reuse, modify, reset, or close another job\'s worker branch/PR or request.\n\nUse the locked HiFi narration exactly as approved.',
)
voice.write_text(s)

long_voice = prompts / 'long-voice-stage.txt'
s = long_voice.read_text()
needle = 'Universal owns generation, segmentation, validation, and artifacts.'
insert = "Worker branch: `render/{{JOB_ID}}`. `jobs/request.json.jobId` must be exactly `{{JOB_ID}}`. Never reuse, modify, reset, or close another job's worker branch/PR or request.\n\n"
if needle not in s:
    raise SystemExit('Unexpected HiFi long voice wrapper shape.')
long_voice.write_text(s.replace(needle, insert + needle))

# Short ideation remains channel-specific, but it must explicitly use the channel calibration set
# with the same anti-queue semantics shared by both channels.
source = prompts / 'source-stage.txt'
s = source.read_text()
s = s.replace('`prompts/short-good-ideas.md`', '`tools/telic-vnext/channels/hifi/prompts/short-good-ideas.md`')
calibration = ('Example Good Ideas are positive taste calibration, not a queue, backlog, or preapproved topic pool. '
               'Generate fresh candidates independently; an empty Example Good Ideas list is not an error.\n\n')
needle = 'Generate several fresh candidates internally.'
if needle not in s:
    raise SystemExit('Unexpected HiFi Short source prompt shape.')
s = s.replace(needle, calibration + needle)
source.write_text(s)

long_idea = prompts / 'long-ideation-stage.txt'
s = long_idea.read_text()
old = 'Example Good Ideas are taste calibration, never a backlog. Used Topics remains the hard duplicate ledger.'
new = ('Example Good Ideas are positive taste calibration, not a queue, backlog, or preapproved topic pool. '
       'Generate fresh candidates independently; an empty Example Good Ideas list is not an error. Used Topics remains the hard duplicate ledger.')
if old not in s:
    raise SystemExit('Unexpected HiFi long ideation calibration sentence.')
long_idea.write_text(s.replace(old, new))

for name in ['short-good-ideas.md', 'long-good-ideas.md']:
    p = prompts / name
    s = p.read_text()
    lines = s.splitlines()
    # Keep the examples, replace only the calibration statement.
    for i, line in enumerate(lines):
        if line.startswith('These are taste calibration'):
            lines[i] = 'These are positive taste calibration, not a queue, backlog, or preapproved topic pool.'
            break
    else:
        raise SystemExit(f'Calibration sentence missing in {p}')
    p.write_text('\n'.join(lines) + '\n')

# Long research/script wrappers name the Universal owner explicitly and retain the adaptive
# production-complexity contract used by the shared window planner.
long_research = prompts / 'long-research-stage.txt'
s = long_research.read_text()
s = s.replace('First read the Universal long-research procedure', 'First read `tools/telic-vnext/universal/prompts/long-research-stage.txt`')
long_research.write_text(s)

long_script = prompts / 'long-script-stage.txt'
s = long_script.read_text()
needle = 'Create/update the normal Universal long-script artifacts'
insert = ('For each meaningful script section, label `visualComplexity` as `simple`, `standard`, or `complex`. '
          'This is production complexity, not importance; it helps the content-driven adaptive window planner allocate build scope.\n\n')
if needle not in s:
    raise SystemExit('Unexpected HiFi long script shape.')
long_script.write_text(s.replace(needle, insert + needle))

# Short visual planning/composition keep the existing hard viewer-value invariants while applying
# HiFi-specific evidence choices.
plan = prompts / 'visual-plan-stage.txt'
s = plan.read_text()
needle = 'Plan the strongest evidence or explanation for each narration beat.'
insert = ('Asset specificity is a hard gate. Prefer no image over a generic one. In the opening 1–3 seconds, establish the exact object and tension, then progress toward the payoff. '
          'Avoid repeated dominant layouts and do not end on a generic summary card. If the same meaning survives with words removed, remove them.\n\n')
if needle not in s:
    raise SystemExit('Unexpected HiFi visual-plan shape.')
plan.write_text(s.replace(needle, insert + needle))

composition = prompts / 'composition-stage.txt'
s = composition.read_text()
needle = 'Visual progression is a hard gate:'
replacement = ('Semantic visual progression is a hard gate: inspect the start, middle, and end of every meaningful sequence. '
               'Zooming, panning, pulsing, relabeling, or cosmetically rearranging essentially the same state does not count as progression. '
               'Reject text-led decks and repeated dominant layouts.\n\nVisual progression is a hard gate:')
if needle not in s:
    raise SystemExit('Unexpected HiFi composition shape.')
composition.write_text(s.replace(needle, replacement))

# Short QC inherits the mature preview/correction discipline rather than inventing a second loop.
qc = prompts / 'qc-stage.txt'
s = qc.read_text()
needle = 'Read `tools/telic-vnext/universal/CREATIVE_CORE.md`'
isolation = "Render branch: `render/{{JOB_ID}}`. `jobs/request.json.jobId` must belong exactly to `{{JOB_ID}}`; same-job finalize requests remain job-scoped. Never reuse, modify, reset, or close another job's worker branch/PR or request.\n\n"
if needle not in s:
    raise SystemExit('Unexpected HiFi Short QC wrapper shape.')
s = s.replace(needle, isolation + needle)
needle = 'Hard HiFi checks:'
loop = ('Do not render speculative variants. There is no small arbitrary preview-attempt cap. '
        'Never perform two consecutive corrective full renders without an intervening preview-clean source. '
        'Do not fail merely because an arbitrary render-count limit elapsed. '
        'Review frames/contact sheets and exact review-moment stills are diagnostics; use targeted stills only for a concrete crop, readability, first-frame, transition, HiFi-accuracy, or sync question.\n\n')
if needle not in s:
    raise SystemExit('Unexpected HiFi Short QC hard-check section.')
qc.write_text(s.replace(needle, loop + needle))

# Thin canonical long wrappers: Universal owns procedure; HiFi adds only domain taste and exact
# worker isolation where the controller contract requires it.
(prompts / 'long-visual-build-stage.txt').write_text('''HiFi Studio long-form visual-build compatibility entrypoint.\n\nJob: `{{JOB_ID}}`. Worker branch: `render/{{JOB_ID}}`; `jobs/request.json.jobId` must be exactly `{{JOB_ID}}`. Never reuse, modify, reset, or close another job's worker branch/PR or request.\n\nDo not duplicate the shared procedure. Read and follow:\n- `tools/telic-vnext/universal/prompts/long-visual-build-stage.txt`\n- `tools/telic-vnext/universal/CREATIVE_CORE.md`\n- `tools/telic-vnext/universal/format/long.md`\n- `tools/telic-vnext/channels/hifi/style.md`\n\nUniversal owns window/build/validation behavior. HiFi adds only subject taste: exact products and revisions, legible measurement axes/units, truthful internals/diagrams, and archival product material when history matters. Do not substitute generic listening rooms, knobs, waveform/equalizer graphics, or luxury textures for evidence. Shared primitives are tools, not templates.\n''')

(prompts / 'long-sound-design-stage.txt').write_text('''HiFi Studio long-form sound-design compatibility entrypoint.\n\nDo not duplicate the shared procedure. Read and follow:\n- `tools/telic-vnext/universal/prompts/long-sound-design-stage.txt`\n- `tools/telic-vnext/universal/CREATIVE_CORE.md`\n- `tools/telic-vnext/universal/format/long.md`\n- `tools/telic-vnext/channels/hifi/style.md`\n\nUniversal owns editing SFX, timing, mixing, and validation; shared editing SFX belong in the Universal library. HiFi-specific physical Foley may support visible actions such as a switch, relay, knob detent, record cue, connector, cabinet interaction, or mechanical reveal when the exact action warrants it. Event density must remain motivated. Never use an unverified recording as a trustworthy demonstration of a component's sound; narration stays dominant.\n''')

(prompts / 'long-qc-stage.txt').write_text('''HiFi Studio long-form QC compatibility entrypoint.\n\nJob: `{{JOB_ID}}`. Render branch: `render/{{JOB_ID}}`; `jobs/request.json.jobId` must belong exactly to `{{JOB_ID}}`; same-job finalize requests remain job-scoped. Never reuse, modify, reset, or close another job's worker branch/PR or request.\n\nDo not duplicate the shared procedure. Read and follow:\n- `tools/telic-vnext/universal/prompts/long-qc-stage.txt`\n- `tools/telic-vnext/universal/CREATIVE_CORE.md`\n- `tools/telic-vnext/universal/format/long.md`\n- `tools/telic-vnext/channels/hifi/style.md`\n- `tools/telic-vnext/channels/hifi/research.md`\n\nUniversal owns complete-preview review, technical validation, creative iteration, and `TELIC_CREATIVE_REVIEW`. HiFi adds domain checks: exact model/revision identity, honest price/date context, readable measurement axes/units, measured facts separated from manufacturer/reviewer claims, no invented listening authority, no disputed claim laundered into fact, and no implication that uncontrolled YouTube playback proves component sound.\n''')

# Style carries only channel taste, including anti-template and physical-audio additions that are
# genuinely subject-specific rather than duplicated Universal editing rules.
style = root / 'channels/hifi/style.md'
s = style.read_text()
s += '''\n## Whole-video variation\nRepeated story objects are fine; repeated dominant layouts are not. Revisit a product when the story needs it, but change the evidence, relationship, crop, scale, context, or explanatory medium rather than replaying the same composition.\n\n## Physical sound\nHiFi-specific physical Foley can make real visible equipment actions tactile—switches, relays, knobs, connectors, record cueing, cabinet interactions—while event density must remain motivated. Shared transition/editing SFX remain Universal.\n'''
style.write_text(s)

# Packaging remains a substantive channel taste layer and preserves thumbnail conflict discipline.
packaging = root / 'channels/hifi/packaging.md'
s = packaging.read_text()
s = s.replace('one obvious conflict or question', 'one obvious comparison/verdict conflict or question')
s += '''\nA package should answer why this exact object or decision matters now. Price-led packaging needs the comparison basis in the researched video; vintage-versus-modern packaging needs the relevant successor or alternative; measurement-led packaging should expose the disputed implication rather than merely displaying a graph. Prefer one legible product relationship over a collage. The thumbnail can simplify, but it may not silently change model revision, scale, measured result, or the direction of the video's conclusion.\n\nFor exploratory long-form packaging, test different viewer promises rather than cosmetic wording variants. One direction may foreground value, another the engineering surprise, another the reputation-versus-evidence tension. Whichever wins must be supported by the finished script and should still make sense to a viewer who does not already know audiophile terminology.\n'''
packaging.write_text(s)

# Identity-normalization test: migrate the escaped NBSP fixture as well as ordinary literals.
auth_test = root / 'test/youtube-channel-auth-helper.test.mjs'
s = auth_test.read_text()
s = s.replace('HiFi\\u00a0Explained', 'HiFi\\u00a0Studio')
s = s.replace('HiFi Explained Media', 'HiFi Studio Media').replace('HiFi Explained', 'HiFi Studio')
auth_test.write_text(s)

# HiFi is intentionally present but not production-enabled before external provisioning. Update the
# two legacy tests that previously assumed every built-in channel was already provisioned.
minimality = root / 'test/channel-override-minimality.test.mjs'
s = minimality.read_text()
# Raw manifests: Telic remains a pure delta; HiFi has one explicit safety delta.
s = s.replace('for (const manifest of [telicRaw, hifiRaw]) {', 'for (const manifest of [telicRaw]) {')
needle = '  for (const profile of [telicProfileRaw, hifiProfileRaw]) {'
if needle not in s:
    raise SystemExit('Migrated channel minimality profile loop not found.')
s = s.replace(needle, "  assert.deepEqual(hifiRaw.production, {enabled: false});\n  for (const profile of [telicProfileRaw, hifiProfileRaw]) {")
s = s.replace('assert.equal(registry.readiness.hifi.ready, true);', 'assert.equal(registry.readiness.hifi.ready, false);')
s = s.replace("assert.equal(hifi.production.runner, 'native-vnext');", "assert.equal(hifi.production.runner, 'native-vnext');\n  assert.equal(hifi.production.enabled, false);")
# The old Coffee source-profile assertions describe a deleted channel. Replace that trailing block
# with inheritance/readiness checks for the deliberately sparse HiFi profile.
pattern = r"\n  assert\.deepEqual\(hifi\.production\.sourceProfile\.short, \{.*?assert\.equal\(hifi\.production\.sourceProfile\.audio\.mastering\.targetIntegratedLufs, -16\);"
replacement = """
  assert.equal(hifi.production.sourceProfile.topicPolicy.allow.length > 0, true);
  assert.equal(hifi.production.sourceProfile.topicPolicy.deny.length > 0, true);
  assert.equal(hifi.production.sourceProfile.voice.provider, 'chatterbox');
  assert.equal(hifi.production.sourceProfile.audio.mastering.targetIntegratedLufs, -16);
  assert.equal(registry.readiness.hifi.ready, false);"""
s, count = re.subn(pattern, replacement, s, count=1, flags=re.S)
if count != 1:
    raise SystemExit('Old migrated HiFi source-profile block not found in minimality test.')
minimality.write_text(s)

native = root / 'test/native-no-legacy-runtime.test.mjs'
s = native.read_text()
pattern = r"test\('every production channel declares native vNext ownership'.*?\n\}\);"
replacement = """test('every channel uses native vNext ownership while provisioning gates production', async () => {
  const registry = await loadChannelRegistry({channels: {enabled: ['telic']}});
  assert.equal(registry.enabled.telic.production.runner, 'native-vnext');
  assert.equal(registry.enabled.telic.production.enabled, true);
  assert.deepEqual(registry.enabled.telic.production.compatibility.configOverlay, {});
  assert.equal(registry.all.hifi.production.runner, 'native-vnext');
  assert.equal(registry.all.hifi.production.enabled, false);
  assert.deepEqual(registry.all.hifi.production.compatibility.configOverlay, {});
  assert.equal(registry.readiness.hifi.ready, false);
});"""
s, count = re.subn(pattern, replacement, s, count=1, flags=re.S)
if count != 1:
    raise SystemExit('Native ownership test block not found.')
native.write_text(s)
