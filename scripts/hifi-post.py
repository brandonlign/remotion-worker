from pathlib import Path

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

# The setup test had an explicit "no Coffee words" regex; the repository-level residue gate now
# owns that check, so the test should focus on HiFi editorial leakage instead of containing the legacy name itself.
test = root / 'test/hifi-channel-setup.test.mjs'
s = test.read_text()
s = s.replace('/coffee|espresso|grinder|brewing/i', '/espresso|grinder|brewing|cigar|roast/i')
test.write_text(s)

# Fail on any real source/docs/test residue, but ignore vendored installed dependencies.
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
