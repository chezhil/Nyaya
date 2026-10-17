"""Batch throughput of Model B (mule MLP) on CPU vs the Telum NNPA (plan #23). Run on the LinuxONE server:

    podman exec notebook python /home/ibm-user/shared/nyaya/deploy/bench_throughput.py
    # before Model B exists, time the architecture only (output is labelled as random weights):
    podman exec notebook python .../deploy/bench_throughput.py --random-weights

Writes artifacts/bench/throughput.json. Report only what this prints.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def build(artifacts: Path | str, random_weights: bool):
    import torch
    from torch import nn

    artifacts = Path(artifacts)
    if random_weights:
        torch.manual_seed(0)
    m = nn.Sequential(nn.Linear(7, 32), nn.ReLU(), nn.Linear(32, 16), nn.ReLU(), nn.Linear(16, 1))
    if random_weights:
        return m.eval(), "random weights (architecture timing only)"
    m.load_state_dict(torch.load(artifacts / "model_b.pt", map_location="cpu"))
    meta = json.loads((artifacts / "model_b_meta.json").read_text())
    return m.eval(), f"model_b {meta.get('version', '?')}"


def time_device(model, X, device: str, repeats: int, warmup: int) -> dict:
    import torch

    m = model.to(device)
    x_cpu = torch.from_numpy(X)
    lat = []
    out = None
    with torch.no_grad():
        for i in range(warmup + repeats):
            t = time.perf_counter()
            out = m(x_cpu.to(device)).to("cpu")  # include host<->device transfer: that is what the API pays
            dt = time.perf_counter() - t
            if i >= warmup:
                lat.append(dt)
    lat = np.array(lat)
    med = float(np.median(lat)) if len(lat) else 0.0
    p50 = round(float(np.percentile(lat, 50)) * 1000, 3) if len(lat) else 0.0
    p95 = round(float(np.percentile(lat, 95)) * 1000, 3) if len(lat) else 0.0
    dps = round(float(X.shape[0] / med), 1) if med > 0 else 0.0
    chk = round(float(out.sum()), 4) if out is not None else 0.0
    return {"device": device, "batch": int(X.shape[0]), "repeats": repeats,
            "p50_ms": p50,
            "p95_ms": p95,
            "decisions_per_s": dps,
            "output_checksum": chk}


def main(argv=None):
    import torch

    p = argparse.ArgumentParser()
    p.add_argument("--artifacts", type=Path, default=ROOT / "artifacts")
    p.add_argument("--batch", type=int, nargs="+", default=[1, 100, 10000])
    p.add_argument("--repeats", type=int, default=50)
    p.add_argument("--warmup", type=int, default=5)
    p.add_argument("--threads", type=int, default=3, help="CPU threads (the VM has 3 vCPUs)")
    p.add_argument("--random-weights", action="store_true")
    a = p.parse_args(argv)
    torch.set_num_threads(a.threads)
    model, label = build(a.artifacts, a.random_weights)
    nnpa = bool(getattr(torch, "nnpa", None) and torch.nnpa.is_available())
    devices = ["cpu"] + (["nnpa"] if nnpa else [])
    rng = np.random.default_rng(0)
    results = []
    for b in a.batch:
        X = rng.standard_normal((b, 7)).astype(np.float32)
        for d in devices:
            r = time_device(model, X, d, a.repeats, a.warmup)
            results.append(r)
            print(json.dumps(r))
    out = {"model": label, "machine": platform.machine(), "torch": torch.__version__, "nnpa_available": nnpa,
           "cpu_threads": a.threads, "results": results,
           "note": "Median-latency throughput incl. host-device transfer. NNPA rows only exist if measured."}
    if nnpa:
        diffs = {}
        X = rng.standard_normal((1000, 7)).astype(np.float32)
        with torch.no_grad():
            c = model.to("cpu")(torch.from_numpy(X)).numpy()
            n = model.to("nnpa")(torch.from_numpy(X).to("nnpa")).to("cpu").numpy()
        diffs["max_abs_logit_diff_cpu_vs_nnpa"] = float(np.abs(c - n).max())
        out.update(diffs)
    dest = a.artifacts / "bench"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "throughput.json").write_text(json.dumps(out, indent=2))
    print(f"wrote {dest / 'throughput.json'}")


if __name__ == "__main__":
    main()
