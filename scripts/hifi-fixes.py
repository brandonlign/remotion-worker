from pathlib import Path

root = Path('tools/telic-vnext')
prompts = root / 'channels/hifi/prompts'

# Channel wrappers keep the channel-specific delivery/QC taste, while retaining the small
# worker-isolation contract that the current controller expects in worker-using entrypoints.
voice = prompts / 'voice-stage.txt'
s = voice.read_text()
s = s.replace(
    'Use the locked HiFi narration exactly as approved.',
    'Job: `{{JOB_ID}}`. Worker branch: `render/{{JOB_ID}}`; `jobs/request.json.jobId` must be exactly `{{JOB_ID}}`. Never reuse, modify, reset, or close another job\'s worker branch/PR or request.\n\nUse the locked HiFi narration exactly as approved.',
)
voice.write_text(s)

long_voice = prompts / 'long-voice-stage.txt'
s = long_voice.read_text()
insert = "Worker branch: `render/{{JOB_ID}}`. `jobs/request.json.jobId` must be exactly `{{JOB_ID}}`. Never reuse, modify, reset, or close another job's worker branch/PR or request.\n\n"
needle = 'Universal owns generation, segmentation, validation, and artifacts.'
if needle not in s:
    raise SystemExit('Unexpected HiFi long voice wrapper shape.')
s = s.replace(needle, insert + needle)
long_voice.write_text(s)

qc = prompts / 'qc-stage.txt'
s = qc.read_text()
needle = 'Read `tools/telic-vnext/universal/CREATIVE_CORE.md`'
insert = "Render branch: `render/{{JOB_ID}}`. `jobs/request.json.jobId` must belong exactly to `{{JOB_ID}}`; same-job finalize requests remain job-scoped. Never reuse, modify, reset, or close another job's worker branch/PR or request.\n\n"
if needle not in s:
    raise SystemExit('Unexpected HiFi Short QC wrapper shape.')
s = s.replace(needle, insert + needle)
qc.write_text(s)

# The title-normalization unit test is identity-agnostic; migrate the literal identity fully.
auth_test = root / 'test/youtube-channel-auth-helper.test.mjs'
s = auth_test.read_text()
s = s.replace('HiFi Explained Media', 'HiFi Studio Media').replace('HiFi Explained', 'HiFi Studio')
auth_test.write_text(s)

# Universal owns the generic reconstructability requirement. If an older migrated root contract
# duplicated that exact assertion against channel style, remove only the duplicate while preserving
# the Creative Core assertion as the hard cross-channel quality gate.
root_contract = Path('scripts/autopilot/editorial-visuals-contract.test.mjs')
s = root_contract.read_text()
core_assert = "assert.match(creativeCore, /Every visual should be reconstructable by a human editor from the cited source material/);"
if core_assert not in s:
    raise SystemExit('Universal reconstructability assertion is missing; refusing to weaken the contract.')
s = s.replace("  assert.match(hifiStyle, /Every visual should be reconstructable by a human editor from the cited source material/);\n", '')
root_contract.write_text(s)
