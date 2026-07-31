#!/usr/bin/env python3
import json
from gmn_python_api import data_directory as dd
from gmn_python_api import meteor_trajectory_reader as reader

frame = reader.read_data(dd.get_monthly_file_content_by_date("2025-06"), output_camel_case=True).reset_index(drop=False)
print(json.dumps({"rows": len(frame), "columns": list(map(str, frame.columns))}, indent=2))
