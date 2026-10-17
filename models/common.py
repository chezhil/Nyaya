"""Shared helpers for model training: paths, seeded splits, metrics. Run on the LinuxONE server only."""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("NYAYA_DATA", Path.home() / "shared" / "data"))
ARTIFACTS = Path(os.environ.get("NYAYA_ARTIFACTS", ROOT / "artifacts"))
SEED = 7


def split_indices(strata: pd.Series, fractions: dict[str, float], seed: int = SEED) -> dict[str, np.ndarray]:
    """Seeded split of row positions, stratified by `strata` so every split sees every population."""
    rng = np.random.default_rng(seed)
    names = list(fractions)
    out = {n: [] for n in names}
    for _, pos in pd.Series(np.arange(len(strata))).groupby(strata.to_numpy()):
        pos = rng.permutation(pos.to_numpy())
        cuts = (np.cumsum([fractions[n] for n in names]) * len(pos)).astype(int)
        cuts[-1] = len(pos)
        start = 0
        for n, c in zip(names, cuts):
            out[n].append(pos[start:c])
            start = c
    return {n: np.sort(np.concatenate(v)) for n, v in out.items()}


def brier(y, p) -> float:
    y, p = np.asarray(y, float), np.asarray(p, float)
    return float(np.mean((p - y) ** 2))


def reliability(y, p, bins: int = 10) -> list[dict]:
    """Equal-width reliability table: mean predicted vs observed rate per bin (empty bins skipped)."""
    y, p = np.asarray(y, float), np.asarray(p, float)
    idx = np.minimum((p * bins).astype(int), bins - 1)
    rows = []
    for b in range(bins):
        m = idx == b
        if m.any():
            rows.append({"bin": b, "n": int(m.sum()), "mean_pred": float(p[m].mean()), "observed": float(y[m].mean())})
    return rows


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2))
