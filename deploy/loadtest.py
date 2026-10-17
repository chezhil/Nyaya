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
import http.client
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import numpy as np
import pandas as pd

FIELDS = ["sender_id", "recipient_id", "type", "amount", "oldbalanceOrg", "newbalanceOrig", "oldbalanceDest",
          "newbalanceDest", "hour", "geo_shift_km", "new_device", "merchant_category", "in_disaster_zone",
          "severity_tier"]

_tls = threading.local()


def _get_connection(url: str) -> tuple[http.client.HTTPConnection, str]:
    parsed = urlparse(url)
    if not hasattr(_tls, "conn") or getattr(_tls, "host", None) != parsed.netloc:
        if parsed.scheme == "https":
            _tls.conn = http.client.HTTPSConnection(parsed.netloc, timeout=30)
        else:
            _tls.conn = http.client.HTTPConnection(parsed.netloc, timeout=30)
        _tls.host = parsed.netloc
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return _tls.conn, path


def post(url: str, body: dict) -> tuple[float, int]:
    t = time.perf_counter()
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "Connection": "keep-alive"}
    code = 0
    try:
        conn, path = _get_connection(url)
        conn.request("POST", path, body=data, headers=headers)
        resp = conn.getresponse()
        resp.read()
        code = resp.status
    except Exception:
        try:
            if hasattr(_tls, "conn"):
                _tls.conn.close()
                del _tls.conn
        except Exception:
            pass
        code = 0
    return (time.perf_counter() - t) * 1000, code


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--data", required=True)
    p.add_argument("--n", type=int, default=2000)
    p.add_argument("--concurrency", type=int, default=8)
    a = p.parse_args(argv)
    df = pd.read_csv(a.data, nrows=a.n)
    present_fields = [f for f in FIELDS if f in df.columns]
    bodies = [{k: (v.item() if hasattr(v, "item") else v) for k, v in r.items()} for r in df[present_fields].to_dict("records")]
    url = a.url.rstrip("/") + "/api/v1/evaluate"
    t = time.perf_counter()
    with ThreadPoolExecutor(a.concurrency) as ex:
        res = list(ex.map(lambda b: post(url, b), bodies))
    wall = time.perf_counter() - t
    lat = np.array([r[0] for r in res]) if len(res) else np.array([0.0])
    codes = pd.Series([r[1] for r in res]).value_counts().to_dict() if len(res) else {}
    out = {"requests": len(res), "concurrency": a.concurrency, "status_codes": codes,
           "throughput_rps": round(len(res) / wall, 1) if wall > 0 else 0.0,
           "client_ms": {q: round(float(np.percentile(lat, int(q[1:]))), 2) for q in ("p50", "p95", "p99")}
           if len(res) else {"p50": 0.0, "p95": 0.0, "p99": 0.0}}
    try:
        with urllib.request.urlopen(a.url.rstrip("/") + "/api/v1/system", timeout=10) as r:
            out["server_latency_ms"] = json.load(r).get("latency_ms")
    except Exception as e:
        out["server_latency_ms"] = None
        out["server_status"] = f"unreachable: {e}"
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
