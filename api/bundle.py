"""Model bundle: Model A (XGBoost + isotonic + conformal) and Model B (PyTorch MLP on NNPA).

RealBundle loads the artifacts described in CONTRACTS.md §2. StubBundle is a transparent hand-written
heuristic so the API and dashboard work before the models exist; every response says "stub".
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

import numpy as np

from data.features import DISASTER_CONTEXT, MODEL_A_FEATURES, MODEL_B_FEATURES

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = Path(os.environ.get("NYAYA_ARTIFACTS", ROOT / "artifacts"))


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def conformal_set(p_fraud: float, qhat: float | None) -> list[str]:
    if qhat is None:
        return ["legit"] if p_fraud < 0.5 else ["fraud"]
    s = []
    if p_fraud <= qhat:
        s.append("legit")
    if 1 - p_fraud <= qhat:
        s.append("fraud")
    return s or (["legit"] if p_fraud < 0.5 else ["fraud"])


def _top3(names, values, contribs) -> list[dict]:
    idx = np.argsort(-np.abs(contribs))[:3]
    return [{"feature": names[i], "value": float(values[i]), "contribution": round(float(contribs[i]), 4)}
            for i in idx]


class StubBundle:
    """Hand-set logistic scores. NOT a model; replaced as soon as artifacts/ exists."""

    version = "stub-0"
    mule_device = "none"
    a_features = MODEL_A_FEATURES
    W_A = {"orig_drained": 2.2, "new_device": 0.9, "is_night": 0.6, "geo_shift_km": 0.004,
           "amount_to_balance": 1.2, "type_code": 0.3}
    B_A = -4.0
    W_B = {"fan_in_15m": 0.15, "forward_within_10m_ratio": 2.5, "account_age_days": -0.02,
           "device_reuse_density": 0.5, "shared_subnet_count": 0.2, "mci": 2.0}
    B_B = -4.5

    def _a(self, row: dict, context: bool = True) -> tuple[float, list[dict]]:
        terms = {k: w * float(row.get(k, 0)) for k, w in self.W_A.items()}
        z = self.B_A + sum(terms.values())
        names = list(terms)
        return float(_sigmoid(z)), _top3(names, [row.get(k, 0) for k in names], np.array(list(terms.values())))

    def score(self, row: dict, recip: dict) -> dict:
        p, top = self._a(row)
        zb = self.B_B + sum(w * float(recip.get(k, 0)) for k, w in self.W_B.items())
        return {"p_fraud": round(p, 4), "p_fraud_raw": round(p, 4), "p_mule": round(float(_sigmoid(zb)), 4),
                "conformal_set": ["legit", "fraud"] if 0.3 < p < 0.7 else (["legit"] if p <= 0.3 else ["fraud"]),
                "contribs": top}

    def score_legacy_raw(self, row: dict) -> float:
        return self._a({**row, **{k: 0 for k in DISASTER_CONTEXT}})[0]

    def score_batch(self, a_rows, b_rows) -> dict:
        res = [self.score(a, b) for a, b in zip(a_rows.to_dict("records"), b_rows.to_dict("records"))]
        legacy = [self.score_legacy_raw(a) for a in a_rows.to_dict("records")]
        return {"p_fraud": np.array([r["p_fraud"] for r in res]), "p_mule": np.array([r["p_mule"] for r in res]),
                "conformal_set": [r["conformal_set"] for r in res], "p_legacy_raw": np.array(legacy)}

    legacy_threshold = None

    def info(self) -> dict:
        return {"model_version": self.version, "kind": "stub", "mule_device": self.mule_device}


class RealBundle:
    def __init__(self, artifacts: Path = ARTIFACTS, mule_device: str | None = None):
        import xgboost as xgb

        self.dir = Path(artifacts)
        meta = json.loads((self.dir / "model_a_meta.json").read_text())
        self.a_features = list(meta["features"])
        unknown = set(self.a_features) - set(MODEL_A_FEATURES)
        if unknown:
            raise ValueError(f"model_a features not in data/schema.md: {sorted(unknown)}")
        self.legacy_threshold = meta.get("legacy_threshold")
        self.booster = xgb.Booster()
        self.booster.load_model(str(self.dir / "model_a.json"))
        cal = json.loads((self.dir / "calibration.json").read_text())
        self.cal_x, self.cal_y = np.asarray(cal["x"], float), np.asarray(cal["y"], float)
        conf_path = self.dir / "conformal.json"
        self.qhat = json.loads(conf_path.read_text())["qhat"] if conf_path.exists() else None
        self._ctx_idx = [self.a_features.index(c) for c in DISASTER_CONTEXT if c in self.a_features]
        self.version_a = meta.get("version", "a?")
        self._load_mule(mule_device or os.environ.get("NYAYA_MULE_DEVICE", "auto"))
        self.version = f"{self.version_a}+{self.version_b}"

    def _load_mule(self, want: str):
        import torch
        from torch import nn

        self.torch = torch
        meta = json.loads((self.dir / "model_b_meta.json").read_text())
        if list(meta["features"]) != MODEL_B_FEATURES:
            raise ValueError("model_b_meta features must equal data/schema.md Model B order")
        self.b_mean = np.asarray(meta["mean"], np.float32)
        self.b_std = np.where(np.asarray(meta["std"], np.float32) == 0, 1, np.asarray(meta["std"], np.float32))
        self.version_b = meta.get("version", "b?")
        m = nn.Sequential(nn.Linear(7, 32), nn.ReLU(), nn.Linear(32, 16), nn.ReLU(), nn.Linear(16, 1))
        m.load_state_dict(torch.load(self.dir / "model_b.pt", map_location="cpu"))
        m.eval()
        nnpa = bool(getattr(torch, "nnpa", None) and torch.nnpa.is_available())
        self.mule_device = "nnpa" if (want == "nnpa" or (want == "auto" and nnpa)) else "cpu"
        self.mule = m.to(self.mule_device)

    def _dmatrix(self, X: np.ndarray):
        import xgboost as xgb

        return xgb.DMatrix(X, feature_names=self.a_features)

    def calibrate(self, p_raw):
        return np.interp(p_raw, self.cal_x, self.cal_y)

    def _mule_probs(self, B: np.ndarray) -> np.ndarray:
        torch = self.torch
        x = torch.from_numpy(((B - self.b_mean) / self.b_std).astype(np.float32)).to(self.mule_device)
        with torch.no_grad():
            out = self.mule(x).to("cpu").numpy().reshape(-1)
        return _sigmoid(out)

    def score(self, row: dict, recip: dict) -> dict:
        X = np.array([[float(row[f]) for f in self.a_features]], dtype=np.float32)
        dm = self._dmatrix(X)
        p_raw = float(self.booster.predict(dm)[0])
        contribs = self.booster.predict(dm, pred_contribs=True)[0][:-1]  # last column is the bias
        p = float(self.calibrate(p_raw))
        B = np.array([[float(recip[f]) for f in MODEL_B_FEATURES]], dtype=np.float32)
        return {"p_fraud": round(p, 4), "p_fraud_raw": round(p_raw, 4), "p_mule": round(float(self._mule_probs(B)[0]), 4),
                "conformal_set": conformal_set(p, self.qhat), "contribs": _top3(self.a_features, X[0], contribs)}

    def score_legacy_raw(self, row: dict) -> float:
        X = np.array([[0.0 if f in DISASTER_CONTEXT else float(row[f]) for f in self.a_features]], dtype=np.float32)
        return float(self.booster.predict(self._dmatrix(X))[0])

    def score_batch(self, a_rows, b_rows) -> dict:
        X = a_rows[self.a_features].to_numpy(np.float32)
        p = self.calibrate(self.booster.predict(self._dmatrix(X)))
        XL = X.copy()
        XL[:, self._ctx_idx] = 0
        return {"p_fraud": p, "p_mule": self._mule_probs(b_rows[MODEL_B_FEATURES].to_numpy(np.float32)),
                "conformal_set": [conformal_set(float(v), self.qhat) for v in p],
                "p_legacy_raw": self.booster.predict(self._dmatrix(XL))}

    def info(self) -> dict:
        return {"model_version": self.version, "kind": "real", "mule_device": self.mule_device,
                "conformal_qhat": self.qhat, "legacy_threshold": self.legacy_threshold,
                "artifacts": str(self.dir)}


def load_bundle(artifacts: Path = ARTIFACTS):
    """RealBundle if every artifact is present, else StubBundle (with the reason)."""
    need = ["model_a.json", "model_a_meta.json", "calibration.json", "model_b.pt", "model_b_meta.json"]
    missing = [n for n in need if not (Path(artifacts) / n).exists()]
    if missing:
        b = StubBundle()
        b.fallback_reason = f"missing artifacts: {missing}"
        return b
    t = time.perf_counter()
    b = RealBundle(artifacts)
    b.load_ms = round((time.perf_counter() - t) * 1000, 1)
    return b
