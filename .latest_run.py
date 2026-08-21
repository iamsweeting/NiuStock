# -*- coding: utf-8 -*-
"""临时：取最新 run id。"""
import sys

import requests

sys.path.insert(0, r"C:\Agent\integration\nstock")

r = requests.get("https://api.github.com/repos/iamsweeting/NiuStock/actions/runs",
                 headers={"User-Agent": "nstock-check"}, timeout=20)
d = r.json()
for w in d.get("workflow_runs", [])[:3]:
    print("id=%s status=%s conclusion=%s head=%s" % (
        w["id"], w["status"], w.get("conclusion"), w["head_sha"][:7]))
