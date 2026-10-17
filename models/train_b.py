"""Model B: PyTorch MLP 7->32->16->1 (mule ring), trained on CPU; inference checked on NNPA vs CPU.

    python -m models.train_b [--out artifacts] [--data ~/shared/data] [--tag v1]
Use `import torch` only (never `import torch_nnpa`).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import average_precision_score, roc_auc_score
from torch import nn

from data.features import MODEL_B_FEATURES
from models.common import ARTIFACTS, DATA_DIR, SEED, brier, reliability, split_indices, write_json

VERSION = "B-mlp-1"
FRACTIONS = {"train": 0.7, "val": 0.15, "test": 0.15}


def build() -> nn.Sequential:
    return nn.Sequential(nn.Linear(7, 32), nn.ReLU(), nn.Linear(32, 16), nn.ReLU(), nn.Linear(16, 1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ARTIFACTS)
    ap.add_argument("--data", type=Path, default=DATA_DIR)
    ap.add_argument("--tag", default="v1")
    ap.add_argument("--epochs", type=int, default=60)
    args = ap.parse_args()

    torch.manual_seed(SEED)
    np.random.seed(SEED)
    df = pd.read_csv(args.data / f"recipients_{args.tag}.csv.gz")
    X = df[MODEL_B_FEATURES].to_numpy(np.float32)
    y = df["is_mule_recipient"].to_numpy(np.float32)
    strata = df["population"].astype(str) + "|" + df["variant"].astype(str) + "|" + df["is_mule_recipient"].astype(str)
    sp = split_indices(strata, FRACTIONS)
    mean, std = X[sp["train"]].mean(0), X[sp["train"]].std(0)
    std = np.where(std == 0, 1.0, std).astype(np.float32)
    t = {k: (torch.from_numpy((X[v] - mean) / std), torch.from_numpy(y[v])) for k, v in sp.items()}

    model = build()
    opt = torch.optim.Adam(model.parameters(), lr=3e-3, weight_decay=1e-5)
    loss_fn = nn.BCEWithLogitsLoss()
    g = torch.Generator().manual_seed(SEED)
    best, best_state, bad, epoch = -1.0, None, 0, 0
    for epoch in range(args.epochs):
        model.train()
        perm = torch.randperm(len(t["train"][0]), generator=g)
        for i in range(0, len(perm), 512):
            b = perm[i:i + 512]
            opt.zero_grad()
            loss_fn(model(t["train"][0][b]).squeeze(1), t["train"][1][b]).backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            pv = torch.sigmoid(model(t["val"][0]).squeeze(1)).numpy()
        ap_val = average_precision_score(t["val"][1].numpy(), pv)
        if ap_val > best + 1e-5:
            best, bad = ap_val, 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= 8:
                break
    model.load_state_dict(best_state)
    model.eval()

    with torch.no_grad():
        p_cpu = torch.sigmoid(model(t["test"][0]).squeeze(1)).numpy()
    yt = t["test"][1].numpy()
    pop = df["population"].iloc[sp["test"]].to_numpy()

    nnpa = bool(getattr(torch, "nnpa", None) and torch.nnpa.is_available())
    nnpa_check = {"available": nnpa}
    if nnpa:
        m2 = build()
        m2.load_state_dict(best_state)
        m2 = m2.eval().to("nnpa")
        with torch.no_grad():
            p_n = torch.sigmoid(m2(t["test"][0].to("nnpa")).to("cpu").squeeze(1)).numpy()
        nnpa_check.update({"max_abs_diff_vs_cpu": float(np.abs(p_n - p_cpu).max()),
                           "pr_auc_nnpa": float(average_precision_score(yt, p_n))})

    metrics = {
        "version": VERSION, "rows": int(len(df)), "split_sizes": {k: int(len(v)) for k, v in sp.items()},
        "epochs_run": epoch + 1, "val_pr_auc": float(best),
        "test": {"pr_auc": float(average_precision_score(yt, p_cpu)), "roc_auc": float(roc_auc_score(yt, p_cpu)),
                 "brier": brier(yt, p_cpu), "positive_rate": float(yt.mean()),
                 "reliability": reliability(yt, p_cpu),
                 "mean_p_mule_by_population": {p: float(p_cpu[pop == p].mean()) for p in sorted(set(pop))},
                 "flag_rate_at_0.8_by_population": {p: float((p_cpu[pop == p] >= 0.8).mean()) for p in sorted(set(pop))}},
        "nnpa": nnpa_check,
    }
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    torch.save(best_state, out / "model_b.pt")
    write_json(out / "model_b_meta.json", {"version": VERSION, "features": MODEL_B_FEATURES,
                                          "mean": mean.tolist(), "std": std.tolist()})
    write_json(out / "metrics_b.json", metrics)
    print(f"Model B {VERSION}: test PR-AUC {metrics['test']['pr_auc']:.4f}  Brier {metrics['test']['brier']:.5f}  "
          f"epochs {epoch + 1}  NNPA {nnpa_check}")
    print("flag rate @0.8 by population:", metrics["test"]["flag_rate_at_0.8_by_population"])
    print("wrote", out)


if __name__ == "__main__":
    main()
