"""Cyclone Replay: the same synthetic stream decided by the legacy engine and by NYAYA, hour by hour."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from data.features import MODEL_B_FEATURES, tx_features_frame
from data.generate import GenConfig, generate


def legacy_threshold(bundle, scored_legacy: np.ndarray, tx) -> tuple[float, str]:
    """Raw-score threshold at 1% FPR. From model_a_meta.json if Kaustub set it, else computed live on this
    stream's legitimate payments outside the disaster zone (what a peacetime-tuned engine would use)."""
    thr = getattr(bundle, "legacy_threshold", None)
    if thr is not None:
        return float(thr), "model_a_meta.json"
    mask = (tx["is_fraud"].to_numpy() == 0) & (tx["in_disaster_zone"].to_numpy() == 0)
    if mask.sum() == 0:
        mask = tx["is_fraud"].to_numpy() == 0
    if mask.sum() == 0:
        mask = np.ones(len(tx), dtype=bool)
    return float(np.quantile(scored_legacy[mask], 0.99)), "computed: 99th percentile of legit peacetime scores"


def _counters(df, release_col: str, decision_col: str) -> dict:
    victims = df["population"] == "displaced"
    fraud = df["is_fraud"] == 1
    rel = df[release_col]
    n_v = int(victims.sum())
    zero = int((victims & (rel <= 0)).sum())
    return {
        "payments": int(len(df)),
        "holds": int((df[decision_col] == "HOLD").sum()),
        "reviews": int((df[decision_col] == "REVIEW").sum()),
        "releases": int((df[decision_col] == "RELEASE").sum()),
        "victim_payments": n_v,
        "victims_left_zero": zero,
        "victims_left_zero_pct": round(100 * zero / n_v, 2) if n_v else 0.0,
        "victims_frozen_full": int((victims & (df[decision_col] == "HOLD")).sum()),
        "emergency_cash_inr": round(float(rel[victims].sum()), 2),
        "fraud_payments": int(fraud.sum()),
        "fraud_leaked_inr": round(float(rel[fraud].sum()), 2),
        "fraud_stopped_inr": round(float((df["amount"] - rel)[fraud].sum()), 2),
    }


def run_replay(bundle, decide, policy: dict, per_hour: int = 50, seed: int = 11, variant: str = "base") -> dict:
    t = time.perf_counter()
    hours = 72
    total = per_hour * hours
    cfg = GenConfig(n_normal=int(total * 0.72), n_displaced=int(total * 0.20), n_syndicate=int(total * 0.04),
                    seed=seed, variant=variant, n_merchants=600)
    tx, _ = generate(cfg)
    gen_ms = (time.perf_counter() - t) * 1000

    t1 = time.perf_counter()
    A = tx_features_frame(tx)
    s = bundle.score_batch(A, tx[MODEL_B_FEATURES])
    thr, thr_src = legacy_threshold(bundle, s["p_legacy_raw"], tx)
    tx = tx.assign(p_fraud=s["p_fraud"], p_mule=s["p_mule"], p_legacy_raw=s["p_legacy_raw"])
    tx["legacy_decision"] = np.where(tx["p_legacy_raw"] >= thr, "HOLD", "RELEASE")
    tx["legacy_release"] = np.where(tx["legacy_decision"] == "HOLD", 0.0, tx["amount"])
    dec, rel = [], []
    for rec, cs in zip(tx[["amount", "severity_tier", "in_disaster_zone", "merchant_category", "p_fraud",
                           "p_mule"]].to_dict("records"), s["conformal_set"]):
        d = decide({"p_fraud": rec["p_fraud"], "p_mule": rec["p_mule"], "conformal_set": cs}, rec, policy)
        dec.append(d["decision"])
        rel.append(d["release_now"])
    tx["nyaya_decision"] = dec
    tx["nyaya_release"] = rel
    score_ms = (time.perf_counter() - t1) * 1000

    tx["replay_hour"] = ((tx["ts"] - tx["ts"].min()) // 3600).astype(int).clip(0, hours - 1)
    sev = json.loads(Path(cfg.scenario).read_text())["severity_by_hour"]
    grouped = {int(h): g for h, g in tx.groupby("replay_hour")}
    by_hour = []
    for h in range(hours):
        g = grouped.get(h)
        if g is not None and len(g) > 0:
            c_leg = _counters(g, "legacy_release", "legacy_decision")
            c_nya = _counters(g, "nyaya_release", "nyaya_decision")
        else:
            c_leg = _counters(tx.iloc[0:0], "legacy_release", "legacy_decision")
            c_nya = _counters(tx.iloc[0:0], "nyaya_release", "nyaya_decision")
        by_hour.append({
            "hour": h,
            "severity": int(sev[h]) if h < len(sev) else 0,
            "legacy": c_leg,
            "nyaya": c_nya,
        })
    victims = tx["population"] == "displaced"
    mule_flag = tx["p_mule"] >= float(policy["theta_mule"])
    return {
        "scenario": "Chennai cyclone (synthetic preset)",
        "config": {"per_hour": per_hour, "seed": seed, "variant": variant, "rows": int(len(tx))},
        "model_version": bundle.info()["model_version"],
        "legacy": {"threshold": round(thr, 6), "threshold_source": thr_src,
                   "definition": "same Model A without disaster context, HOLD above the 1% FPR threshold"},
        "hours": by_hour,
        "totals": {"legacy": _counters(tx, "legacy_release", "legacy_decision"),
                   "nyaya": _counters(tx, "nyaya_release", "nyaya_decision"),
                   "nyaya_victim_zero_with_mule_flag": int((victims & (tx["nyaya_release"] <= 0) & mule_flag).sum())},
        "timing_ms": {"generate": round(gen_ms, 1), "score_and_decide": round(score_ms, 1),
                      "per_payment_us": round(1000 * score_ms / max(1, len(tx)), 1)},
    }
