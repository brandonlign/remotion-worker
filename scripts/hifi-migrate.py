from pathlib import Path
import json
import re
import shutil

root = Path('tools/telic-vnext')
coffee = root / 'channels/coffee'
hifi = root / 'channels/hifi'
if not coffee.exists():
    raise SystemExit('Expected channels/coffee on source main; source state changed.')
if hifi.exists():
    raise SystemExit('channels/hifi already exists; inspect newest source state instead of overwriting it.')

shutil.copytree(coffee, hifi)
shutil.rmtree(coffee)

# First migrate identity/path references. Editorial files below are then rewritten deliberately.
for p in hifi.rglob('*'):
    if not p.is_file():
        continue
    text = p.read_text()
    text = text.replace('Coffee Explained', 'HiFi Studio').replace('Coffee Production Hub', 'HiFi Studio Production Hub')
    text = text.replace('COFFEE', 'HIFI').replace('Coffee', 'HiFi').replace('coffee', 'hifi')
    p.write_text(text)

channel = {
    'id': 'hifi',
    'displayName': 'HiFi Studio',
    'storage': {'driveRoot': 'YouTube/HiFi Studio/Renders'},
    'chatgpt': {'projectUrl': None},
    'publishing': {
        'profileKey': 'hifi',
        'expectedChannelTitle': 'HiFi Studio',
        'tokenPath': '~/.config/telic-vnext/publishers/hifi/youtube-publisher-token.json',
    },
    'instructions': {
        'sourceName': 'HiFi Studio Production Hub',
        'sourceFileId': None,
        'shared': ['Visual Identity', 'Audio', 'Quality Control', 'Lessons'],
        'short': ['HiFi Shorts Playbook', 'HiFi Shorts Script Writing'],
        'long': ['HiFi Long Form Playbook', 'HiFi Long Form Script Writing'],
    },
    # Do not enable until Drive/ChatGPT/instruction/auth provisioning is complete.
    'production': {'enabled': False},
}
(hifi / 'channel.json').write_text(json.dumps(channel, indent=2) + '\n')

profile = {
    'topicPolicy': {
        'allow': [
            'Specific hi-fi and premium audio gear: speakers, amplifiers, DACs, streamers, turntables, cartridges, headphones, source components, and complete systems.',
            'Evidence-backed comparisons, rankings, value thresholds, upgrade paths, system-matching decisions, and explanations of what a higher price actually buys.',
            'Legendary or timeless audio equipment when the story explains why the design mattered, what tradeoff it solved, why it endured, or what a listener or buyer should conclude today.',
            'Engineering and measurement stories when they connect directly to a real product, audible consequence, setup decision, or disputed audiophile claim.',
            'Iconic systems, rare gear, design failures, and category turning points with enough documentation and real imagery to support a concrete story.',
        ],
        'deny': [
            'Generic music news, artist coverage, playlists, or listening content with no gear or sound-reproduction thesis.',
            'Luxury lifestyle montages whose only appeal is expensive equipment, glowing knobs, or status.',
            'Unsupported subjective sound-quality claims, fake consensus, or first-person listening, testing, or ownership claims that did not actually happen.',
            'Spec-sheet recitations, generic what-is-a-DAC explainers, and technical trivia with no consequential product or listener payoff.',
            'Pseudoscientific accessory, cable, burn-in, or tweak claims stated as established fact when evidence is disputed or absent.',
            'Best, worst, value, or buying claims without a defensible comparison set and current-enough evidence.',
        ],
    },
}
(hifi / 'source-profile.json').write_text(json.dumps(profile, indent=2) + '\n')

(hifi / 'style.md').write_text('''# HiFi Studio Channel Additions

Universal production and creative rules apply unless this file says otherwise.

## Identity
HiFi Studio is about great sound through specific, consequential audio gear: timeless components, iconic systems, meaningful comparisons, engineering tradeoffs, and evidence-backed buying or upgrade decisions.

## Editorial taste
- Start with a specific product, system, tradeoff, or decision. Avoid vague “world of hi-fi” framing.
- Expensive is not automatically better. Explain what changes, what does not, where diminishing returns begin, and who actually benefits.
- Separate measurable facts, manufacturer claims, reviewer impressions, community consensus, and subjective listening language. Attribute each appropriately.
- Never claim first-person listening, testing, ownership, or an A/B comparison unless it actually happened and is documented.
- Engineering and history earn screen time only when they explain why a component behaves differently, why a design mattered, or what the viewer should conclude.
- Prefer exact model names and distinguish revisions, generations, regional variants, and original versus current pricing.

## Visual taste
Favor real product photography and footage, manuals, service diagrams, cutaways, driver/crossover or amplifier topology, measurement plots, archival advertising, patent drawings, room/system diagrams, and period context. Avoid generic speaker silhouettes, endless knob B-roll, waveform wallpaper, luxury-room filler, and spec-card slideshows.

## Audio claims
YouTube compression, the viewer's playback chain, and uncontrolled listening conditions make “hear the difference” demonstrations weak evidence by default. Do not promise an audible A/B unless the methodology can actually support the claim. Narration remains the authority; music and SFX support the edit without pretending to demonstrate equipment sound.
''')

(hifi / 'research.md').write_text('''# HiFi Studio Research Additions

Use the Universal research procedure plus these channel rules.

Prefer primary material for hard facts: manufacturer manuals and archives, service manuals, patents, engineering papers, standards, launch literature, and contemporaneous documentation. For measurements, prefer sources that publish methodology and traceable results. Use reputable reviews for attributed listening impressions, never as objective proof of sound quality.

For every important claim, classify it as specification, measurement, engineering inference, historical fact, manufacturer claim, reviewer impression, price/value judgment, or disputed audiophile claim. Do not silently move a claim from one category into another.

Verify exact model/revision, release period, original MSRP where available, meaningful current price when the script makes a present-day value claim, and whether similarly named regional versions differ. Historical prices should not be compared naively across decades when inflation or market position matters.

When measurements and listening reports disagree, preserve the disagreement rather than manufacturing a single verdict. Never infer audible superiority from one metric alone. Never present cables, burn-in, isolation devices, power conditioning, or other contested tweaks as settled unless strong evidence supports the specific claim.

Collect visual evidence while researching: product shots, internals, diagrams, measurement plots, manuals, ads, patents, and period images that can prove or explain the story on screen.
''')

(hifi / 'packaging.md').write_text('''# HiFi Studio Packaging Additions

Package the concrete tension, not “a video about audio.” Strong titles usually contain a recognizable product/category, a meaningful comparison, a surprising engineering consequence, a price/value question, or a durable verdict.

Avoid unsupported superlatives and fake certainty. Exact model names matter. “Legendary,” “best,” “overpriced,” “giant-killer,” and similar language must be earned by evidence in the video.

Thumbnails should usually center one or two specific objects and one obvious conflict or question. Avoid collages of many components, waveform graphics, walls of specs, and generic luxury listening rooms.
''')

(hifi / 'prompts/short-good-ideas.md').write_text('''# Example Good Ideas

These are taste calibration, not a backlog.

- The speaker spec that tells you almost nothing about how hard it is to drive
- What spending $1,000 more on an amplifier can actually change — and what it cannot
- Why this 40-year-old speaker design is still copied
- The upgrade that matters before replacing your speakers
- A famous hi-fi feature that is mostly solving the wrong problem
''')
(hifi / 'prompts/long-good-ideas.md').write_text('''# Example Good Ideas

These are taste calibration, not a backlog or preapproved topics.

- The speakers that changed what “high-end” meant — and which ideas survived
- Where amplifier diminishing returns actually begin
- The engineering tradeoff behind an iconic speaker that competitors still cannot avoid
- If I were building a serious two-channel system from zero, where the money should go first
- Vintage icon versus modern replacement: what forty years of engineering actually bought
- The measurements audiophiles argue about — and which ones really constrain a system
''')

(hifi / 'prompts/source-stage.txt').write_text('''Create only the private source package for the next HiFi Studio Short. Do not render or publish.

Job: `{{JOB_ID}}`
Issue: {{ISSUE_URL}}
Source repo: `{{SOURCE_REPO}}`
Worker: `{{WORKER_REPO}}`
Source branch: `agent/{{JOB_ID}}`
Publish at: `{{PUBLISH_AT}}`

Before writes, fetch issue/comments. Stop if the job is terminal, superseded, already source-complete, or belongs to another channel.

This is HIFI STUDIO. Read the current channel instructions plus `channels/hifi/style.md`, `research.md`, `packaging.md`, `prompts/short-good-ideas.md`, and `source-profile.json` from current main.

Generate several fresh candidates internally. Favor one specific product, comparison, engineering tradeoff, upgrade decision, price/value threshold, misunderstood spec, iconic design choice, or evidence-backed audiophile claim. The viewer should know what object or decision the Short is about almost immediately. Reject generic audio trivia, vague luxury content, pure music coverage, unsupported “sounds better” claims, and ideas whose only hook is jargon.

Pressure-test the winner for recognizability, one clear payoff, visual proof, sourceability, evergreen usefulness, and whether the useful answer fits the Short runtime. Separate measurements and hard facts from attributed listening impressions. Never fabricate auditioning, testing, ownership, consensus, or subjective experience.

Research only what this Short needs, preferring primary documentation and traceable measurements for hard claims. Verify exact model/revision and current price when price is part of the premise. If a claim is disputed, say so rather than laundering it into fact.

Write for spoken clarity. Open on the specific object/tension, build one causal or comparative thread, translate technical detail into a listener/buyer consequence, and deliver the promised answer without padding. Do not turn the script into a spec sheet.

Create/update the normal private source contract under `automation/current`, including at minimum `job.json`, `youtube.json`, `narration.txt`, and `dispatch.json`. Record `channelId: "hifi"` wherever supported. Run source-contract checks, fetch outputs back, verify channel identity and evidence-safe language, re-fetch issue/comments, commit, post exactly `TELIC_STAGE: source_committed`, then stop.
''')

(hifi / 'prompts/long-ideation-stage.txt').write_text('''Complete only ideation for the next HiFi Studio long-form video.

Job: `{{JOB_ID}}`
Issue: {{ISSUE_URL}}
Source branch: `agent/{{JOB_ID}}`

Before writes, fetch issue/comments. Stop if this or any later long-form stage is complete or the job is terminal.

Read HiFi Studio channel instructions plus `channels/hifi/style.md`, `packaging.md`, `prompts/long-good-ideas.md`, and `source-profile.json` from current main. Example Good Ideas are taste calibration, never a backlog. Used Topics remains the hard duplicate ledger.

Generate 8-12 serious concepts internally. Draw from HiFi-native archetypes: iconic component/design stories with a present-day consequence; famous product versus successor/alternative; what a price jump actually buys; diminishing-return thresholds; system matching and bottlenecks; where to spend first when building or upgrading; misunderstood measurements/specs; engineering tradeoffs that created a recognizable product behavior; evidence-backed myths or contested claims; rare or failed gear whose design teaches something consequential.

Do not default to a Telic-style company documentary or a generic shopping list. A HiFi Studio long should revolve around specific equipment and a real tension: design versus consequence, price versus benefit, measurement versus claim, old versus new, component versus system, or reputation versus evidence.

For each finalist, silently test at least two title directions and one thumbnail conflict. Prefer ideas with a recognizable object/category, a clear viewer question, enough evidence and visual material for 8-12 minutes, multiple meaningful turns rather than padding, and a conclusion that can be defended without pretending we personally listened to the gear.

Reject generic “what is X” education, spec recitations, luxury-room tours, unsupported subjective rankings, broad history without a thesis, and topics whose core answer is too small for long form. Engineering/history should deepen the central tension, not become detached exposition.

Choose the concept with the best combination of click promise, HiFi relevance, evidence path, visual richness, evergreen durability, and substantive payoff. Create only `automation/current/long-idea.json` with the chosen topic, central question/tension, viewer payoff, why it deserves long form, likely narrative turns/comparison dimensions, expected takeaway, likely real-world visuals, claim risks/disputed areas, exclusions, and runtime bounds. Fetch it back, recheck issue/comments, commit, post exactly `TELIC_STAGE: long_ideation_ready`, then stop.
''')

(hifi / 'prompts/long-research-stage.txt').write_text('''Execute only long_research for this HiFi Studio long-form job. First read the Universal long-research procedure, then apply `channels/hifi/research.md`, `style.md`, the chosen `automation/current/long-idea.json`, and current issue/comments.

Research the exact products, revisions, engineering claims, measurements, history, prices, and comparisons needed to answer the chosen question. Prefer primary documentation for hard facts and traceable measurement sources for measured performance. Use reviews only as attributed listening impressions unless they independently document hard facts.

Build explicit evidence for both the strongest case and strongest caveat. Distinguish specification, measurement, manufacturer claim, engineering inference, reviewer impression, community consensus, and disputed audiophile claim. Verify model variants and dates. If price/value matters, establish relevant original/current price context. If evidence conflicts, preserve the conflict.

Collect sourceable visual evidence alongside prose research: exact product imagery, internals, diagrams, measurements, manuals, ads, patents, and historical context. Never invent listening experience or infer sound quality from a single metric.

Produce the normal long-research artifacts required by the Universal procedure, verify every consequential factual/numerical/comparative claim has a defensible source path, commit, post exactly `TELIC_STAGE: long_research_ready`, then stop.
''')

(hifi / 'prompts/long-script-stage.txt').write_text('''Execute only long_script for this HiFi Studio long-form job. Read the Universal long-script procedure, current long idea/research artifacts, `channels/hifi/style.md`, `research.md`, `packaging.md`, and issue/comments before writing.

The script should feel like an enthusiast who understands the engineering, not a catalog and not a generic documentary. Put the specific product/system/tension on stage early. Build through consequential turns: what people expect, what the design actually does, what the evidence shows, what tradeoff appears, and what that means for the listener, buyer, or enthusiast.

Technical detail must cash out into a real consequence. Explain one mechanism at a time in plain language, then return to the object and thesis. Use exact model names where ambiguity matters, but do not drown narration in specifications.

Keep epistemic categories honest. State measurements and documented facts directly when supported. Attribute manufacturer claims and reviewer listening descriptions. Make clear when a point is an engineering inference or a disputed audiophile belief. Never write `I heard`, `we tested`, `I owned`, or equivalent firsthand experience unless the job contains real evidence that it happened.

Do not force a buyer verdict if the story is really about an iconic design or engineering tradeoff; do not force a history lesson if the viewer came for a buying/system decision. Follow the chosen long-idea promise. Preserve meaningful uncertainty instead of faking certainty for a cleaner ending.

Write narration with varied pacing and natural transitions. Avoid repeated claim-number-caveat templates, fake drama, generic pivots, and summary sections that merely restate every prior point. The ending should resolve the opening question with the strongest defensible conclusion.

Create/update the normal Universal long-script artifacts, verify script claims against research, verify no fabricated listening authority, verify the promised idea is actually answered, commit, post exactly `TELIC_STAGE: long_script_ready`, then stop.
''')

# HiFi uses Universal audio until/unless a channel-specific library is deliberately provisioned.
for name in ['audio-ingest.json', 'audio-library.json']:
    (hifi / name).unlink(missing_ok=True)

# Permit a real but unprovisioned channel manifest; readiness will report exactly what is missing.
reg = root / 'src/channel-registry.mjs'
reg_text = reg.read_text()
old = "  const {projectUrl, projectId} = validateProjectUrl(chatgpt.projectUrl ?? chatgpt.project);"
new = "  const projectRef = chatgpt.projectUrl ?? chatgpt.project;\n  const {projectUrl, projectId} = projectRef == null ? {projectUrl: null, projectId: null} : validateProjectUrl(projectRef);"
if reg_text.count(old) != 1:
    raise SystemExit('Channel registry project validation changed; refusing blind patch.')
reg.write_text(reg_text.replace(old, new))

# A music folder is only a production requirement when the active channel profile actually uses music.
reg_text = reg.read_text()
old = "  requireValue(channel.storage?.musicFolderId, 'storage.musicFolderId');"
new = "  if (channel.production?.sourceProfile?.audio?.musicMode !== 'none') requireValue(channel.storage?.musicFolderId, 'storage.musicFolderId');"
if reg_text.count(old) != 1:
    raise SystemExit('Channel registry music readiness changed; refusing blind patch.')
reg.write_text(reg_text.replace(old, new))

# Replace Coffee identity in cross-channel tests, then make the HiFi setup test explicitly model staged provisioning.
coffee_test = root / 'test/coffee-channel-setup.test.mjs'
hifi_test = root / 'test/hifi-channel-setup.test.mjs'
if not coffee_test.exists():
    raise SystemExit('Expected coffee-channel-setup.test.mjs.')
for p in (root / 'test').glob('*.test.mjs'):
    s = p.read_text()
    if 'coffee' in s.lower():
        s = s.replace('Coffee Explained', 'HiFi Studio').replace('COFFEE', 'HIFI').replace('Coffee', 'HiFi').replace('coffee', 'hifi')
        p.write_text(s)
coffee_test.rename(hifi_test)

# Replace the old setup test with focused assertions matching the actual scaffold and inherited Universal policy.
hifi_test.write_text('''import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {loadChannelRegistry} from '../src/channel-registry.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROMPTS = path.resolve(HERE, '../channels/hifi/prompts');
const expectedPrompts = [
  'source-stage.txt', 'voice-stage.txt', 'visual-plan-stage.txt', 'composition-stage.txt', 'sound-design-stage.txt', 'qc-stage.txt',
  'long-ideation-stage.txt', 'long-research-stage.txt', 'long-script-stage.txt', 'long-voice-stage.txt', 'long-visual-plan-stage.txt',
  'long-visual-build-stage.txt', 'long-sound-design-stage.txt', 'long-assembly-stage.txt', 'long-metadata-stage.txt', 'long-qc-stage.txt',
];

test('HiFi is the only non-Telic channel module and is explicitly staged for provisioning', async () => {
  const registry = await loadChannelRegistry({channels: {enabled: ['telic']}});
  assert.deepEqual(Object.keys(registry.all).sort(), ['hifi', 'telic']);
  const hifi = registry.all.hifi;
  assert.equal(hifi.displayName, 'HiFi Studio');
  assert.equal(hifi.production.enabled, false);
  assert.equal(hifi.scheduling.enabled, false);
  assert.equal(hifi.storage.driveRoot, 'YouTube/HiFi Studio/Renders');
  assert.equal(hifi.publishing.expectedChannelTitle, 'HiFi Studio');
  assert.equal(hifi.publishing.tokenPath, '~/.config/telic-vnext/publishers/hifi/youtube-publisher-token.json');
  assert.equal(hifi.production.sourceProfile.id, 'hifi');
  assert.equal(hifi.production.sourceProfile.voice.provider, 'chatterbox');
  assert.equal(hifi.production.sourceProfile.audio.musicMode, 'none');
  assert.match(hifi.production.promptDirectoryPath, /channels\\/hifi\\/prompts$/);
  assert.equal(registry.readiness.hifi.ready, false);
  for (const missing of ['storage.renderFolderId', 'storage.productionFolderId', 'storage.sourceAssetsFolderId', 'chatgpt.projectUrl', 'chatgpt.projectId', 'instructions.sourceFileId']) {
    assert.ok(registry.readiness.hifi.missing.includes(missing), `expected provisioning requirement ${missing}`);
  }
  assert.equal(registry.readiness.hifi.missing.includes('storage.musicFolderId'), false);
});

test('HiFi prompt pack covers every installed Short and long creative stage', async () => {
  const names = (await fs.readdir(PROMPTS)).sort();
  for (const expected of expectedPrompts) assert.ok(names.includes(expected), `missing HiFi prompt ${expected}`);
  for (const expected of expectedPrompts) {
    const source = await fs.readFile(path.join(PROMPTS, expected), 'utf8');
    assert.match(source, /HiFi/i);
  }
});

test('HiFi editorial prompts are materially channel-specific rather than Telic aliases', async () => {
  const idea = await fs.readFile(path.join(PROMPTS, 'long-ideation-stage.txt'), 'utf8');
  const research = await fs.readFile(path.join(PROMPTS, 'long-research-stage.txt'), 'utf8');
  const script = await fs.readFile(path.join(PROMPTS, 'long-script-stage.txt'), 'utf8');
  assert.match(idea, /diminishing-return|system matching|measurement versus claim/i);
  assert.match(research, /manufacturer manuals|traceable measurement|reviewer impression/i);
  assert.match(script, /enthusiast who understands the engineering|firsthand experience/i);
  assert.doesNotMatch(idea + research + script, /coffee|espresso|grinder|brewing/i);
});
''')

# Ensure the real second channel, not a made-up fixture channel, proves channel-neutral native preflight behavior.
p = root / 'test/native-visual-plan-preflight.test.mjs'
s = p.read_text().replace('coffee-test-preflight', 'hifi-test-preflight').replace("channelId: 'coffee'", "channelId: 'hifi'")
p.write_text(s)

# Auth helper should validate the actual second channel ID/title.
p = root / 'test/youtube-channel-auth-helper.test.mjs'
s = p.read_text().replace("['coffee']", "['hifi']").replace('Coffee Explained Media', 'HiFi Studio Media').replace('Coffee Explained', 'HiFi Studio')
p.write_text(s)

# No Coffee channel or reference should remain in current vNext source/tests/docs.
leftovers = []
for p in root.rglob('*'):
    if p.is_file():
        try:
            body = p.read_text()
        except UnicodeDecodeError:
            continue
        if 'coffee' in p.name.lower() or 'coffee' in body.lower():
            leftovers.append(str(p))
if leftovers:
    raise SystemExit('Coffee residue remains:\n' + '\n'.join(leftovers))
