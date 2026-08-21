# -*- coding: utf-8 -*-
"""临时：后台监控 GitHub Actions 构建进度（每 90s 轮询，终态退出）。"""
import sys
import time

import requests

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "32502737410"
URL = "https://api.github.com/repos/iamsweeting/NiuStock/actions/runs/%s" % RUN_ID
HEADERS = {"User-Agent": "nstock-watch", "Accept": "application/vnd.github+json"}


def main():
    start = time.time()
    while time.time() - start < 10800:
        try:
            r = requests.get(URL, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                w = r.json()
                st = w.get("status")
                conc = w.get("conclusion")
                print("[watch] status=%s conclusion=%s elapsed=%.0fs" % (
                    st, conc, time.time() - start), flush=True)
                if st == "completed":
                    print("[watch] FINAL conclusion=%s" % conc, flush=True)
                    return 0
        except Exception as e:  # noqa: BLE001
            print("[watch] poll error: %s" % e, flush=True)
        time.sleep(90)
    print("[watch] TIMEOUT after 3h", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
