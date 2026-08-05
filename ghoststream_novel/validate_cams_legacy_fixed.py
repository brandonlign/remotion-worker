#!/usr/bin/env python3
from pathlib import Path

path = Path(__file__).with_name("validate_cams_legacy.py")
source = path.read_text()
old = '    members=frame.loc[m["strict_member"]].copy()\n'
new = '    frame["orbit_d"] = m["orbit_d"]\n    members=frame.loc[m["strict_member"]].copy()\n'
if old not in source:
    raise SystemExit("Expected member selection line not found")
source = source.replace(old, new, 1)
source = source.replace('    frame["orbit_d"]=m["orbit_d"]; members[cols].to_csv(OUT/"cams_candidate_members.csv",index=False)\n',
                        '    members[cols].to_csv(OUT/"cams_candidate_members.csv",index=False)\n', 1)
namespace = {"__name__": "__main__", "__file__": str(path)}
exec(compile(source, str(path), "exec"), namespace)
