"""Model A: XGBoost -> isotonic calibration -> split conformal. Writes the CONTRACTS.md section 2 artifacts.

Run on the LinuxONE server (inside the `notebook` container):
    python -m models.train_a [--out artifacts] [--data ~/shared/data] [--tag v1]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, roc_auc_score

from data.features import DISASTER_CONTEXT, MODEL_A_FEATURES, tx_features_frame
from models.common import ARTIFACTS, DATA_DIR, SEED, brier, reliability, split_indices, write_json

VERSION = "A-xgb-iso-1"
ALPHA = 0.1
FRACTIONS = {"train": 0.6, "val": 0.1, "iso": 0.1, "conf": 0.1, "test": 0.1}
PARAMS = {
    "objective": "binary:logistic", "eval_metric": "aucpr", "max_depth": 5, "eta": 0.08, "subsample": 0.8,
    "colsample_bytree": 0.8, "min_child_weight": 3, "tree_method": "hist", "seed": SEED, "nthread": 3,
}


def conformal_qhat(p_fraud: np.ndarray, y: np.ndarray, alpha: float = ALPHA) -> float:
    """Split conformal, score = 1 - p(true label). qhat = ceil((n+1)(1-alpha))/n empirical quantile."""
    scores = np.where(y == 1, 1.0 - p_fraud, p_fraud)
    n = len(scores)
    level = min(1.0, np.ceil((n + 1) * (1 - alpha)) / n)
    return float(np.quantile(scores, level, method="higher"))


def conformal_sets(p: np.ndarray, qhat: float) -> np.ndarray:
    """Same rule as api.bundle.conformal_set, vectorised: 'legit', 'fraud', 'both' or 'empty'."""
    legit, fraud = p <= qhat, (1 - p) <= qhat
    return np.where(legit & fraud, "both", np.where(legit, "legit", np.where(fraud, "fraud", "empty")))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ARTIFACTS)
    ap.add_argument("--data", type=Path, default=DATA_DIR)
    ap.add_argument("--tag", default="v2")
    args = ap.parse_args()

    df = pd.read_csv(args.data / f"nyaya_{args.tag}.csv.gz")
    X, y = tx_features_frame(df), df["is_fraud"].to_numpy()
    sp = split_indices(df["population"].astype(str) + "|" + df["is_fraud"].astype(str), FRACTIONS)
    d = {k: (X.iloc[v], y[v]) for k, v in sp.items()}

    dtrain = xgb.DMatrix(d["train"][0], d["train"][1], feature_names=MODEL_A_FEATURES)
    dval = xgb.DMatrix(d["val"][0], d["val"][1], feature_names=MODEL_A_FEATURES)
    booster = xgb.train(PARAMS, dtrain, num_boost_round=600, evals=[(dval, "val")],
                        early_stopping_rounds=30, verbose_eval=False)

    def raw(Xs):
        dm = xgb.DMatrix(Xs, feature_names=MODEL_A_FEATURES)
        return booster.predict(dm, iteration_range=(0, booster.best_iteration + 1))

    # Legacy baseline: same model with the disaster context zeroed, threshold at 1% FPR on PEACETIME validation
    # negatives (legitimate payments outside any disaster zone). A legacy engine is tuned on normal traffic; taking
    # the quantile over all negatives let context-blind scores of displaced victims inflate it (0.34 on v2), which
    # made the baseline catch almost no syndicate payments.
    Xv = d["val"][0]
    Xv_leg = Xv.copy()
    Xv_leg[DISASTER_CONTEXT] = 0
    peace_neg = (np.asarray(d["val"][1]) == 0) & (Xv["in_disaster_zone"].to_numpy() == 0)
    legacy_threshold = float(np.quantile(raw(Xv_leg)[peace_neg], 0.99))

    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw(d["iso"][0]), d["iso"][1])

    def cal(Xs):
        return np.interp(raw(Xs), iso.X_thresholds_, iso.y_thresholds_)

    qhat = conformal_qhat(cal(d["conf"][0]), d["conf"][1])

    Xt, yt = d["test"]
    p_raw, p_cal = raw(Xt), cal(Xt)
    sets = conformal_sets(p_cal, qhat)
    covered = np.where(yt == 1, (sets == "fraud") | (sets == "both"), (sets == "legit") | (sets == "both"))
    pop = df["population"].iloc[sp["test"]].to_numpy()
    legacy_flag = raw(Xt.assign(**{c: 0 for c in DISASTER_CONTEXT})) >= legacy_threshold
    metrics = {
        "version": VERSION, "rows": int(len(df)), "split_sizes": {k: int(len(v)) for k, v in sp.items()},
        "best_iteration": int(booster.best_iteration),
        "test": {
            "pr_auc": float(average_precision_score(yt, p_cal)), "roc_auc": float(roc_auc_score(yt, p_cal)),
            "brier_raw": brier(yt, p_raw), "brier_calibrated": brier(yt, p_cal),
            "fraud_rate": float(yt.mean()),
            "conformal": {"alpha": ALPHA, "qhat": qhat, "coverage": float(covered.mean()),
                          "share_both": float((sets == "both").mean()), "share_empty": float((sets == "empty").mean())},
            "reliability_raw": reliability(yt, p_raw), "reliability_calibrated": reliability(yt, p_cal),
        },
        "legacy": {"threshold": legacy_threshold,
                   "flag_rate_by_population": {p: float(legacy_flag[pop == p].mean()) for p in sorted(set(pop))}},
        "by_population_mean_p_fraud": {p: float(p_cal[pop == p].mean()) for p in sorted(set(pop))},
    }

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(out / "model_a.json"))
    write_json(out / "model_a_meta.json", {"version": VERSION, "features": MODEL_A_FEATURES,
                                          "legacy_threshold": legacy_threshold})
    write_json(out / "calibration.json", {"x": iso.X_thresholds_.tolist(), "y": iso.y_thresholds_.tolist()})
    write_json(out / "conformal.json", {"qhat": qhat, "alpha": ALPHA})
    write_json(out / "metrics_a.json", metrics)
    t = metrics["test"]
    print(f"Model A {VERSION}: PR-AUC {t['pr_auc']:.4f}  Brier raw {t['brier_raw']:.5f} -> cal {t['brier_calibrated']:.5f}  "
          f"conformal coverage {t['conformal']['coverage']:.3f} (target {1 - ALPHA})  qhat {qhat:.4f}")
    print("legacy flag rate by population:", metrics["legacy"]["flag_rate_by_population"])
    print("mean calibrated p_fraud by population:", metrics["by_population_mean_p_fraud"])
    print("wrote", out)


if __name__ == "__main__":
    main()
