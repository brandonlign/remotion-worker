from pathlib import Path
import re

root = Path('tools/telic-vnext')

# Coffee used to be a first-class second channel outside channels/coffee too.
# These are controller/docs/helper references, so migrate the actual supported identity.
files = [
    root / 'ops-agent.mjs',
    root / 'README.md',
    root / 'guarded-ops-activate.sh',
    root / 'src/control-sync.mjs',
    root / 'bin/authorize-drive.mjs',
    root / 'bin/schedule-existing-youtube.mjs',
]
for p in files:
    if not p.exists():
        raise SystemExit(f'Expected legacy Coffee reference file missing: {p}')
    s = p.read_text()
    s = s.replace('Coffee Explained', 'HiFi Studio').replace('COFFEE', 'HIFI').replace('Coffee', 'HiFi').replace('coffee', 'hifi')
    p.write_text(s)

# Root CI has a cross-channel visual contract outside tools/telic-vnext. Keep it checking the actual
# two-channel architecture rather than a deleted channel, and assert HiFi-specific visual taste.
visual_contract = Path('scripts/autopilot/editorial-visuals-contract.test.mjs')
if not visual_contract.exists():
    raise SystemExit('Expected root editorial visual contract test missing.')
s = visual_contract.read_text()
s = s.replace('coffeePlanEntry', 'hifiPlanEntry').replace('coffeeBuildEntry', 'hifiBuildEntry').replace('coffeeStyle', 'hifiStyle')
s = s.replace('channels/coffee/', 'channels/hifi/')
s = s.replace('// Coffee inherits the same quality floor and lean planning while keeping practical buyer/enthusiast taste.', '// HiFi inherits the same quality floor and lean planning while keeping audio-product/engineering taste.')
s = s.replace('/channels\\/coffee\\/style\\.md/', '/channels\\/hifi\\/style\\.md/')
s = s.replace("assert.match(hifiStyle, /coffee buyers and enthusiasts/);", "assert.match(hifiStyle, /great sound through specific, consequential audio gear/i);")
s = s.replace("assert.match(hifiStyle, /Repeated story objects are fine; repeated dominant layouts are not/);", "assert.match(hifiStyle, /exact model names/i);")
s = s.replace("assert.match(hifiStyle, /Never imply first-person tasting/);", "assert.match(hifiStyle, /Never claim first-person listening/i);")
visual_contract.write_text(s)

# Registry regression: the second channel exists but is deliberately not production-ready until
# the real Drive/ChatGPT/instruction IDs are supplied. Do not preserve fake legacy IDs in tests.
p = root / 'test/channel-registry.test.mjs'
s = p.read_text()
pattern = r"test\('HiFi is provisioned, isolated, production-ready, and unscheduled'.*?\n\}\);\n"
replacement = """test('HiFi is isolated, unscheduled, and explicitly awaiting provisioning', async () => {
  const registry = await loadChannelRegistry({channels: {enabled: ['telic']}});
  assert.equal(registry.enabled.hifi, undefined);
  assert.equal(registry.all.hifi.production.enabled, false);
  assert.equal(registry.all.hifi.scheduling.enabled, false);
  assert.equal(registry.all.hifi.chatgpt.projectUrl, null);
  assert.equal(registry.all.hifi.storage.driveRoot, 'YouTube/HiFi Studio/Renders');
  assert.equal(registry.all.hifi.publishing.profileKey, 'hifi');
  assert.equal(registry.all.hifi.publishing.expectedChannelTitle, 'HiFi Studio');
  assert.equal(registry.all.hifi.publishing.tokenPath, '~/.config/telic-vnext/publishers/hifi/youtube-publisher-token.json');
  assert.equal(registry.readiness.hifi.ready, false);
  for (const missing of ['storage.renderFolderId', 'storage.productionFolderId', 'storage.sourceAssetsFolderId', 'chatgpt.projectUrl', 'chatgpt.projectId', 'instructions.sourceFileId']) {
    assert.ok(registry.readiness.hifi.missing.includes(missing), `expected ${missing}`);
  }
});
"""
s2, count = re.subn(pattern, replacement, s, count=1, flags=re.S)
if count != 1:
    raise SystemExit('Expected migrated HiFi registry test block was not found exactly once.')
p.write_text(s2)

# The setup test had an explicit legacy-name regex; the repository-level residue gate owns that check.
test = root / 'test/hifi-channel-setup.test.mjs'
s = test.read_text()
s = s.replace('/coffee|espresso|grinder|brewing/i', '/espresso|grinder|brewing|cigar|roast/i')
test.write_text(s)

# Fail on any real vNext source/docs/test residue, but ignore vendored installed dependencies.
leftovers = []
for p in root.rglob('*'):
    if not p.is_file() or 'node_modules' in p.parts:
        continue
    try:
        body = p.read_text()
    except UnicodeDecodeError:
        continue
    if 'coffee' in p.name.lower() or 'coffee' in body.lower():
        leftovers.append(str(p))
if leftovers:
    raise SystemExit('Coffee residue remains after controller cleanup:\n' + '\n'.join(leftovers))
