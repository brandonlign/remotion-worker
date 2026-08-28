from pathlib import Path

root = Path('tools/telic-vnext')
prompts = root / 'channels/hifi/prompts'

# Ideation references and calibration language are contractually explicit.
p = prompts / 'long-ideation-stage.txt'
s = p.read_text()
s = s.replace('`prompts/long-good-ideas.md`', '`tools/telic-vnext/channels/hifi/prompts/long-good-ideas.md`')
s = s.replace('Generate fresh candidates independently;', 'Generate fresh candidates independently every run;')
s = s.replace('not a queue, backlog, or preapproved topic pool.', 'not a queue, backlog, or preapproved topic pool. They are not a backlog or preapproved topic pool.')
p.write_text(s)

p = prompts / 'source-stage.txt'
s = p.read_text().replace('Generate fresh candidates independently;', 'Generate fresh candidates independently every run;')
s = s.replace('not a queue, backlog, or preapproved topic pool.', 'not a queue, backlog, or preapproved topic pool. They are not a backlog or preapproved topic pool.')
p.write_text(s)

for name in ['short-good-ideas.md', 'long-good-ideas.md']:
    p = prompts / name
    s = p.read_text()
    s = s.replace('not a queue, backlog, or preapproved topic pool.', 'not a queue, backlog, or preapproved topic pool. This is not a backlog or preapproved topic pool. Generate fresh candidates independently every run.')
    p.write_text(s)

# Keep the useful legacy epistemic distinction, expressed for audio research.
p = root / 'channels/hifi/research.md'
s = p.read_text()
s += '\n## Evidence labels\nUse “Observed/official fact” for directly documented facts. Never turn editorial inference into fake firsthand experience; listening impressions remain attributed impressions unless the production actually performed and documented the listening test.\n'
p.write_text(s)

# Packaging has channel-specific decision and image-truth constraints.
p = root / 'channels/hifi/packaging.md'
s = p.read_text()
s += '\nWrite for a buyer or enthusiast seeking a decisive advantage, explanation, or tradeoff—not generic luxury aspiration. Keep physical products plausible: do not distort proportions, controls, driver count, connector layout, finish, or model-defining geometry merely to make a thumbnail more dramatic.\n'
p.write_text(s)

# Case-sensitive legacy QC contract expects the channel key spelling.
p = prompts / 'qc-stage.txt'
s = p.read_text().replace('HiFi-accuracy', 'hifi-accuracy')
p.write_text(s)

# The old Coffee visual/foley assertions became nonsense under mechanical renaming. Preserve the
# quality gates but point them at genuine HiFi anti-template and physical-action rules instead.
p = root / 'test/viewer-value-simplification.test.mjs'
s = p.read_text()
s = s.replace('/brown\\/tan card, hifi-bag silhouette, or cream inset-panel composition/', '/waveform wallpaper, luxury-room filler, and spec-card slideshows/')
s = s.replace('/tactile and active around real physical hifi actions/', '/switches, relays, knobs, connectors, record cueing, cabinet interactions/')
p.write_text(s)

# Sparse unprovisioned HiFi source profile intentionally omits raw audio overrides.
p = root / 'test/channel-override-minimality.test.mjs'
s = p.read_text().replace('assert.equal(profile.audio.mastering, undefined);', 'assert.equal(profile.audio?.mastering, undefined);')
p.write_text(s)
