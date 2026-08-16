#!/usr/bin/env python3
"""Run the novel search with a corrected global alternating-night split."""
from pathlib import Path

path = Path(__file__).with_name("run_novel_search.py")
source = path.read_text()
old = '''        ordered_nights = {value: index for index, value in enumerate(sorted(unique_nights.tolist()))}
        split_a_members = np.asarray([ordered_nights[value] % 2 == 0 for value in member_nights])
        split_a_all = np.asarray([ordered_nights.get(value, 0) % 2 == 0 for value in nights])
'''
new = '''        global_night_order = {value: index for index, value in enumerate(sorted(np.unique(nights).tolist()))}
        split_a_all = np.asarray([global_night_order[value] % 2 == 0 for value in nights])
        split_a_members = split_a_all[members]
'''
if old not in source:
    raise SystemExit("Expected observing-night split block not found")
source = source.replace(old, new)
namespace = {"__name__": "__main__", "__file__": str(path)}
exec(compile(source, str(path), "exec"), namespace)
