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
post = here / 'hifi-post.py'
post_ns = {'__name__': '__main__', '__file__': str(post)}
exec(compile(post.read_text(), str(post), 'exec'), post_ns, post_ns)
