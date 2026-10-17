"""Load test for POST /api/v1/evaluate using payments from the generated data (stdlib only).

    podman exec notebook python /home/ibm-user/shared/nyaya/deploy/loadtest.py --url http://host.containers.internal:8000 \
        --data /home/ibm-user/shared/data/nyaya_v1.csv.gz --n 2000 --concurrency 8

Prints client-side p50/p95/p99 and throughput, plus the server's own latency stats from /api/v1/system.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

FIELDS = ["sender_id", "recipient_id", "type", "amount", "oldbalanceOrg", "newbalanceOrig", "oldbalanceDest",
          "newbalanceDest", "hour", "geo_shift_km", "new_device", "merchant_category", "in_disaster_zone",
          "severity_tier"]


def post(url: str, body: dict) -> tuple[float, int]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    return (time.perf_counter() - t) * 1000, code


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--data", required=True)
    p.add_argument("--n", type=int, default=2000)
    p.add_argument("--concurrency", type=int, default=8)
    a = p.parse_args(argv)
    df = pd.read_csv(a.data, nrows=a.n)
    bodies = [{k: (v.item() if hasattr(v, "item") else v) for k, v in r.items()} for r in df[FIELDS].to_dict("records")]
    url = a.url.rstrip("/") + "/api/v1/evaluate"
    t = time.perf_counter()
    with ThreadPoolExecutor(a.concurrency) as ex:
        res = list(ex.map(lambda b: post(url, b), bodies))
    wall = time.perf_counter() - t
    lat = np.array([r[0] for r in res])
    codes = pd.Series([r[1] for r in res]).value_counts().to_dict()
    out = {"requests": len(res), "concurrency": a.concurrency, "status_codes": codes,
           "throughput_rps": round(len(res) / wall, 1),
           "client_ms": {q: round(float(np.percentile(lat, int(q[1:]))), 2) for q in ("p50", "p95", "p99")}}
    with urllib.request.urlopen(a.url.rstrip("/") + "/api/v1/system", timeout=10) as r:
        out["server_latency_ms"] = json.load(r).get("latency_ms")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
