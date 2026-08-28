from pathlib import Path

here = Path(__file__).resolve().parent
migrate = here / 'hifi-migrate.py'
source = migrate.read_text()
marker = '# No Coffee channel or reference should remain in current vNext source/tests/docs.'
head, sep, _ = source.partition(marker)
if not sep:
    raise SystemExit('Expected final Coffee-residue marker in hifi-migrate.py; harness shape changed.')
ns = {'__name__': '__main__', '__file__': str(migrate)}
exec(compile(head, str(migrate), 'exec'), ns, ns)

for script_name in ['hifi-prompts.py', 'hifi-post.py', 'hifi-fixes.py', 'hifi-last.py']:
    script = here / script_name
    script_ns = {'__name__': '__main__', '__file__': str(script)}
    exec(compile(script.read_text(), str(script), 'exec'), script_ns, script_ns)
