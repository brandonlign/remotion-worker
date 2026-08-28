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

long_build = prompts / 'long-visual-build-stage.txt'
s = long_build.read_text()
needle = 'Universal owns build procedure, window contracts, validation, and the rule not to render individual windows.'
insert = "Job: `{{JOB_ID}}`. Worker branch: `render/{{JOB_ID}}`; `jobs/request.json.jobId` must be exactly `{{JOB_ID}}`. Never reuse, modify, reset, or close another job's worker branch/PR or request.\n\n"
if needle not in s:
    raise SystemExit('Unexpected HiFi long visual-build wrapper shape.')
s = s.replace(needle, insert + needle)
long_build.write_text(s)

long_qc = prompts / 'long-qc-stage.txt'
s = long_qc.read_text()
needle = 'Universal owns complete assembled-preview review, technical validation, creative iteration, and the `TELIC_CREATIVE_REVIEW` contract.'
insert = "Job: `{{JOB_ID}}`. Render branch: `render/{{JOB_ID}}`; `jobs/request.json.jobId` must belong exactly to `{{JOB_ID}}`; same-job finalize requests remain job-scoped. Never reuse, modify, reset, or close another job's worker branch/PR or request.\n\n"
if needle not in s:
    raise SystemExit('Unexpected HiFi long-QC wrapper shape.')
s = s.replace(needle, insert + needle)
long_qc.write_text(s)

# The title-normalization unit test is identity-agnostic; migrate the literal identity fully.
auth_test = root / 'test/youtube-channel-auth-helper.test.mjs'
s = auth_test.read_text()
s = s.replace('HiFi Explained Media', 'HiFi Studio Media').replace('HiFi Explained', 'HiFi Studio')
auth_test.write_text(s)
