"""Sensitivity run for the HOLD threshold (tau) and the REVIEW band (tau_review) on held-out data.

    python -m engine.tune [--data ~/shared/data] [--artifacts ~/shared/nyaya/artifacts] [--tag v1]

Scores the held-out test split of Model A (the same seeded split models/train_a.py uses, so no row was seen in
training or calibration) and replays the engine for a grid of (tau, tau_review). Everything is computed from the
saved models; nothing here is hand-set. Writes <artifacts>/engine_tune.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from api.bundle import RealBundle
from data.features import tx_features_frame
from engine import decide
from models.common import ARTIFACTS, DATA_DIR, split_indices, write_json
from models.train_a import FRACTIONS

ROOT = Path(__file__).resolve().parent.parent
TAUS = [250, 500, 1000, 2000, 5000]
TAU_REVIEWS = [0, 250, 500, 1000, 2500, 5000]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=DATA_DIR)
    ap.add_argument("--artifacts", type=Path, default=ARTIFACTS)
    ap.add_argument("--tag", default="v1")
    args = ap.parse_args()

    df = pd.read_csv(args.data / f"nyaya_{args.tag}.csv.gz")
    rc = pd.read_csv(args.data / f"recipients_{args.tag}.csv.gz")
    sp = split_indices(df["population"].astype(str) + "|" + df["is_fraud"].astype(str), FRACTIONS)["test"]
    df, rc = df.iloc[sp].reset_index(drop=True), rc.iloc[sp].reset_index(drop=True)
    bundle = RealBundle(args.artifacts, mule_device="cpu")
    s = bundle.score_batch(tx_features_frame(df), rc)
    policy = json.loads((ROOT / "api" / "policy_defaults.json").read_text())
    rows = df.to_dict("records")
    scores = [{"p_fraud": float(p), "p_mule": float(m), "conformal_set": cs}
              for p, m, cs in zip(s["p_fraud"], s["p_mule"], s["conformal_set"])]
    amount, fraud = df["amount"].to_numpy(), df["is_fraud"].to_numpy() == 1
    pop = df["population"].to_numpy()
    cap = float(policy["stipend_cap"])

    def run(tau: float, tau_review: float) -> dict:
        pol = {**policy, "tau": tau, "tau_review": tau_review}
        dec = np.array([decide(sc, r, pol)["decision"] for sc, r in zip(scores, rows)])
        # Money that reaches a fraudster: full amount on RELEASE, only the stipend on REVIEW, nothing on HOLD.
        leaked = np.where(dec == "RELEASE", amount, np.where(dec == "REVIEW", np.minimum(amount, cap), 0.0))
        out = {"tau": tau, "tau_review": tau_review,
               "fraud_leakage_inr": float(leaked[fraud].sum()), "fraud_total_inr": float(amount[fraud].sum()),
               "fraud_hold_rate": float((dec[fraud] == "HOLD").mean()),
               "legit_hold_rate": float((dec[~fraud] == "HOLD").mean()),
               "legit_review_rate": float((dec[~fraud] == "REVIEW").mean())}
        for p in ("displaced", "normal", "ato", "syndicate"):
            m = pop == p
            out[f"{p}_hold"] = float((dec[m] == "HOLD").mean())
            out[f"{p}_review"] = float((dec[m] == "REVIEW").mean())
        return out

    results = [run(t, r) for t in TAUS for r in TAU_REVIEWS]
    base = run(policy["tau"], policy["tau"])
    write_json(args.artifacts / "engine_tune.json", {"rows_scored": int(len(df)), "plan_default": base, "grid": results})
    cols = ["tau", "tau_review", "fraud_leakage_inr", "fraud_hold_rate", "legit_hold_rate", "legit_review_rate",
            "displaced_hold", "displaced_review", "ato_hold", "syndicate_hold"]
    pd.set_option("display.width", 220)
    print(f"held-out rows: {len(df)}  fraud total Rs {base['fraud_total_inr']:,.0f}")
    print("plan default (tau = tau_review = %g):" % policy["tau"])
    print(pd.DataFrame([base])[cols].round(4).to_string(index=False))
    print(pd.DataFrame(results)[cols].round(4).to_string(index=False))


if __name__ == "__main__":
    main()
