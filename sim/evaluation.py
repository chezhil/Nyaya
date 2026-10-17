"""Reproducible NYAYA evaluation suite, baselines, sensitivity and red-team runs."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from data.features import MODEL_B_FEATURES, tx_features_frame
from models.common import SEED, split_indices

SUITE_COUNTS = {"normal": 7_500, "displaced": 1_800, "syndicate": 700}
REDTEAM_VARIANTS = ("smurf", "device_spoof", "slow_drip")
DEFAULT_TAGS = {
    "smurf": "redteam_smurf",
    "device_spoof": "redteam_device_spoof",
    "slow_drip": "redteam_slow_drip",
}


def _data_dir(params: dict) -> Path:
    return Path(params.get("data_dir") or os.environ.get("NYAYA_DATA", Path.home() / "shared" / "data"))


def _read_payments(params: dict, tag: str | None = None) -> pd.DataFrame:
    tag = tag or str(params.get("tag", "v2"))
    path = _data_dir(params) / f"nyaya_{tag}.csv.gz"
    if not path.exists():
        raise FileNotFoundError(f"evaluation data not found: {path}")
    return pd.read_csv(path)


def _test_positions(df: pd.DataFrame) -> np.ndarray:
    fractions = _train_a_fractions()
    strata = df["population"].astype(str) + "|" + df["is_fraud"].astype(str)
    return split_indices(strata, fractions, seed=SEED)["test"]


def _train_a_fractions() -> dict[str, float]:
    """Read the authoritative split fractions without importing training dependencies."""
    path = Path(__file__).resolve().parents[1] / "models" / "train_a.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "FRACTIONS" for t in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, dict) and "test" in value:
                return {str(k): float(v) for k, v in value.items()}
    raise RuntimeError(f"FRACTIONS not found in {path}")


def _average_precision(y_true, scores) -> float:
    """Binary average precision, equivalent to sklearn's non-interpolated AP."""
    y = np.asarray(y_true, dtype=int)
    p = np.asarray(scores, dtype=float)
    positives = int(y.sum())
    if positives == 0:
        raise ValueError("PR-AUC is undefined without positive rows")
    order = np.argsort(-p, kind="mergesort")
    y = y[order]
    distinct = np.r_[np.flatnonzero(np.diff(p[order])), len(y) - 1]
    tp = np.cumsum(y)[distinct]
    fp = 1 + distinct - tp
    precision = tp / (tp + fp)
    recall = tp / positives
    return float(np.sum(np.diff(np.r_[0.0, recall]) * precision))


def _fixed_sample(df: pd.DataFrame, counts: dict[str, int], seed: int, *, held_out: bool = True) -> pd.DataFrame:
    """Sample unique population rows, optionally restricted to Model A's test split."""
    test = df.iloc[_test_positions(df)] if held_out else df
    rng = np.random.default_rng(seed)
    chosen: list[np.ndarray] = []
    for population, count in counts.items():
        positions = np.flatnonzero(test["population"].to_numpy() == population)
        if len(positions) < count:
            raise ValueError(
                f"{'held-out test split' if held_out else 'dataset'} has {len(positions)} {population!r} rows; "
                f"{count} unique rows are required"
            )
        chosen.append(rng.choice(positions, size=count, replace=False))
    order = rng.permutation(np.concatenate(chosen))
    return test.iloc[order].reset_index(drop=True)


def _suite_frame(params: dict, counts: dict[str, int], seed: int) -> tuple[pd.DataFrame, str]:
    """Sample the independent evaluation file; never silently fall back to training data."""
    suite_tag = params.get("suite_tag", "eval")
    if not suite_tag:
        raise ValueError("suite_tag is required for evaluation; use pareto for held-out sensitivity")
    df = _read_payments(params, str(suite_tag))
    return _fixed_sample(df, counts, seed, held_out=False), f"independent file {suite_tag}"


def _require_real_bundle(ctx) -> None:
    info = ctx.bundle.info() if hasattr(ctx.bundle, "info") else {}
    if info.get("kind") != "real":
        raise RuntimeError("evaluation requires trained Model A and Model B artifacts; StubBundle results are refused")
    threshold = getattr(ctx.bundle, "legacy_threshold", None)
    if threshold is None:
        raise RuntimeError("model_a_meta.json does not contain legacy_threshold")


def _score(ctx, df: pd.DataFrame) -> dict:
    a_rows = tx_features_frame(df)
    b_rows = df[MODEL_B_FEATURES]
    result = ctx.bundle.score_batch(a_rows, b_rows)
    required = {"p_fraud", "p_mule", "conformal_set", "p_legacy_raw"}
    missing = required - set(result)
    if missing:
        raise ValueError(f"bundle.score_batch missing keys: {sorted(missing)}")
    return result


def _decisions(ctx, df: pd.DataFrame, scores: dict, policy: dict) -> pd.DataFrame:
    rows = []
    p_fraud = np.asarray(scores["p_fraud"], dtype=float)
    p_mule = np.asarray(scores["p_mule"], dtype=float)
    sets = scores["conformal_set"]
    for i, tx in enumerate(df.to_dict("records")):
        score = {"p_fraud": float(p_fraud[i]), "p_mule": float(p_mule[i]), "conformal_set": list(sets[i])}
        rows.append(ctx.decide(score, tx, policy))
    return pd.DataFrame(rows)


def _baseline_decisions(df: pd.DataFrame, legacy_scores: np.ndarray, threshold: float, cap: float | None) -> pd.DataFrame:
    hold = np.asarray(legacy_scores, dtype=float) >= float(threshold)
    if cap is not None:
        waived = (df["in_disaster_zone"].to_numpy() == 1) & (df["amount"].to_numpy(float) <= float(cap))
        hold &= ~waived
    amount = df["amount"].to_numpy(float)
    return pd.DataFrame({
        "decision": np.where(hold, "HOLD", "RELEASE"),
        "release_now": np.where(hold, 0.0, amount),
        "escrow": np.zeros(len(df), dtype=float),
    })


def _expected_harm(df: pd.DataFrame, decisions: pd.DataFrame, policy_decisions: pd.DataFrame) -> float:
    """Expected harm of the selected action, using the engine's calibrated harm terms.

    RELEASE incurs expected fraud loss. HOLD incurs expected legitimate-customer
    harm. REVIEW scales both terms by the immediately released/escrowed shares.
    """
    amount = df["amount"].to_numpy(float)
    safe_amount = np.where(amount > 0, amount, 1.0)
    released = decisions["release_now"].to_numpy(float) / safe_amount
    withheld = 1.0 - released
    h_fraud = policy_decisions["h_fraud"].to_numpy(float)
    h_hold = policy_decisions["h_hold"].to_numpy(float)
    return float(np.sum(released * h_fraud + withheld * h_hold))


def _ratio(values: Iterable[float]) -> float | None:
    vals = np.asarray(list(values), dtype=float)
    if vals.size == 0 or np.any(~np.isfinite(vals)):
        return None
    lo, hi = float(vals.min()), float(vals.max())
    if lo == 0:
        return 1.0 if hi == 0 else None
    return hi / lo


def _fairness(df: pd.DataFrame, decisions: pd.DataFrame) -> dict:
    """Two views. `all_payments` (as first built) mixes in fraud from compromised accounts, whose owners skew
    low-income, so it partly measures who gets defrauded. `legitimate_only` is false-positive parity: how often
    honest payers in each band are frozen or reviewed, the usual fairness test for a fraud model."""
    out = _fairness_rates(df, decisions)
    if "is_fraud" in df.columns:
        legit = (df["is_fraud"].to_numpy() == 0)
        out["legitimate_only"] = _fairness_rates(df[legit].reset_index(drop=True),
                                                 decisions[legit].reset_index(drop=True))
    return out


def _fairness_rates(df: pd.DataFrame, decisions: pd.DataFrame) -> dict:
    audit = pd.DataFrame({
        "band": df["sender_income_band"].fillna("").astype(str),
        "decision": decisions["decision"].astype(str),
    })
    audit = audit[audit["band"].isin(["low", "mid", "high"])]
    bands = {}
    for band in ("low", "mid", "high"):
        part = audit[audit["band"] == band]
        bands[band] = {
            "n": int(len(part)),
            "freeze_rate": float((part["decision"] == "HOLD").mean()) if len(part) else None,
            "review_rate": float((part["decision"] == "REVIEW").mean()) if len(part) else None,
        }
    freeze_ratio = _ratio(v["freeze_rate"] for v in bands.values() if v["freeze_rate"] is not None)
    review_ratio = _ratio(v["review_rate"] for v in bands.values() if v["review_rate"] is not None)
    return {
        "by_sender_income_band": bands,
        "max_min_freeze_ratio": freeze_ratio,
        "max_min_review_ratio": review_ratio,
        "target_max_ratio": 1.25,
        "target_met": freeze_ratio is not None and review_ratio is not None
        and freeze_ratio <= 1.25 and review_ratio <= 1.25,
        "note": "sender_income_band is used only after scoring, for audit aggregation",
    }


def _metrics(df: pd.DataFrame, decisions: pd.DataFrame, policy_decisions: pd.DataFrame, scores: dict) -> dict:
    displaced = df["population"].to_numpy() == "displaced"
    fraud = df["is_fraud"].to_numpy(int) == 1
    mule = df["is_mule_recipient"].to_numpy(int)
    released = decisions["release_now"].to_numpy(float)
    amounts = df["amount"].to_numpy(float)
    d_count = int(displaced.sum())
    victims_zero = int(np.sum(displaced & (released <= 0)))
    conformal = scores["conformal_set"]
    covered = [(("fraud" if y else "legit") in set(s)) for y, s in zip(fraud, conformal)]
    return {
        "rows": int(len(df)),
        "victims_left_with_zero": victims_zero,
        "victims_left_with_zero_rate": float(victims_zero / d_count) if d_count else None,
        "victim_freeze_rate": float(np.mean(decisions.loc[displaced, "decision"] == "HOLD")) if d_count else None,
        "emergency_cash_availability": float(released[displaced].sum() / amounts[displaced].sum())
        if d_count and amounts[displaced].sum() else None,
        "fraud_leakage_rupees": float(released[fraud].sum()),
        "total_expected_harm_rupees": _expected_harm(df, decisions, policy_decisions),
        "pr_auc_model_a": _average_precision(fraud.astype(int), scores["p_fraud"]),
        "pr_auc_model_b": _average_precision(mule, scores["p_mule"]),
        "conformal_coverage": float(np.mean(covered)),
    }


def _evaluate_suite(ctx, df: pd.DataFrame, policy: dict, naive_cap: float) -> dict:
    scores = _score(ctx, df)
    nyaya = _decisions(ctx, df, scores, policy)
    legacy = _baseline_decisions(df, scores["p_legacy_raw"], ctx.bundle.legacy_threshold, cap=None)
    naive = _baseline_decisions(df, scores["p_legacy_raw"], ctx.bundle.legacy_threshold, cap=naive_cap)
    return {
        "scores": scores,
        "nyaya_decisions": nyaya,
        "results": {
            "nyaya": _metrics(df, nyaya, nyaya, scores),
            "legacy": _metrics(df, legacy, nyaya, scores),
            "naive_relaxed": _metrics(df, naive, nyaya, scores),
        },
    }


def _legacy_diagnostics(df: pd.DataFrame, legacy_scores, threshold: float) -> dict:
    """Is the legacy baseline's behaviour real or an artefact? Score range per population against its threshold."""
    s = np.asarray(legacy_scores, float)
    out = {"threshold": float(threshold), "score_min": float(s.min()), "score_max": float(s.max()),
           "threshold_above_max": bool(threshold > s.max()), "by_population": {}}
    for pop in sorted(df["population"].unique()):
        v = s[df["population"].to_numpy() == pop]
        out["by_population"][pop] = {
            "n": int(v.size), "flag_rate": float((v >= threshold).mean()),
            "q50": float(np.quantile(v, .5)), "q90": float(np.quantile(v, .9)), "q99": float(np.quantile(v, .99)),
            "max": float(v.max()), "share_saturated_ge_0.999": float((v >= 0.999).mean())}
    return out


def _zone_rule_audit(ctx, params: dict, policy: dict) -> dict:
    """Account takeovers in the whole independent file, decided with the zone rule on and off. Takeovers that
    spoof a disaster zone can reach only REVIEW (stipend released) when the rule is on: a policy cost, measured."""
    tag = str(params.get("suite_tag", "eval"))
    df = _read_payments(params, tag)
    ato = df[df["population"] == "ato"].reset_index(drop=True)
    if ato.empty:
        return {"source": tag, "rows": 0}
    scores = _score(ctx, ato)
    spoofed = ato["in_disaster_zone"].to_numpy() == 1
    amount = ato["amount"].to_numpy(float)
    out = {"source": f"independent file {tag}, all population == 'ato' rows", "rows": int(len(ato)),
           "spoofed_zone_rows": int(spoofed.sum()), "fraud_total_rupees": float(amount.sum())}
    for rule in (False, True):
        dec = _decisions(ctx, ato, scores, {**policy, "zone_hold_needs_mule": rule})
        released = dec["release_now"].to_numpy(float)
        d = dec["decision"].to_numpy()
        out[f"zone_rule_{'on' if rule else 'off'}"] = {
            "hold_rate": float((d == "HOLD").mean()), "review_rate": float((d == "REVIEW").mean()),
            "release_rate": float((d == "RELEASE").mean()),
            "leakage_rupees": float(released.sum()),
            "spoofed_zone_hold_rate": float((d[spoofed] == "HOLD").mean()) if spoofed.any() else None,
            "spoofed_zone_leakage_rupees": float(released[spoofed].sum()),
        }
    return out


def simulate(ctx, params: dict) -> dict:
    """Run the fixed 10,000-row independent suite and all headline audits."""
    _require_real_bundle(ctx)
    params = dict(params or {})
    seed = int(params.get("seed", SEED))
    df, source = _suite_frame(params, SUITE_COUNTS, seed)
    policy = {**ctx.policy, **dict(params.get("policy", {}))}
    naive_cap = float(params.get("naive_amount_cap", policy["stipend_cap"]))
    evaluated = _evaluate_suite(ctx, df, policy, naive_cap)
    return {
        "suite": {"seed": seed, "source": source, "counts": SUITE_COUNTS, "rows": len(df)},
        "policy": policy,
        "baselines": {
            "legacy": {"threshold": float(ctx.bundle.legacy_threshold), "disaster_context_zeroed": True},
            "naive_relaxed": {"legacy_threshold": float(ctx.bundle.legacy_threshold), "amount_cap": naive_cap},
        },
        "metrics": evaluated["results"],
        "fairness": _fairness(df, evaluated["nyaya_decisions"]),
        "legacy_diagnostics": _legacy_diagnostics(df, evaluated["scores"]["p_legacy_raw"],
                                                  float(ctx.bundle.legacy_threshold)),
        "ato_zone_rule_audit": _zone_rule_audit(ctx, params, policy),
        "model": ctx.bundle.info(),
    }


def _grid(params: dict, name: str, current: float, multipliers: tuple[float, ...]) -> list[float]:
    supplied = params.get(f"{name}_values")
    values = supplied if supplied is not None else [current * m for m in multipliers]
    return sorted({float(v) for v in values})


def pareto(ctx, params: dict) -> dict:
    """Sweep policy parameters and identify regions where NYAYA loses to a baseline."""
    _require_real_bundle(ctx)
    params = dict(params or {})
    sample_counts = params.get("counts", SUITE_COUNTS)
    df = _fixed_sample(_read_payments(params), {k: int(v) for k, v in sample_counts.items()},
                       int(params.get("seed", SEED)))
    source = f"models.train_a test split ({params.get('tag', 'v2')})"
    base = {**ctx.policy, **dict(params.get("policy", {}))}
    grids = {
        "alpha": _grid(params, "alpha", float(base["alpha"]), (0.5, 0.75, 1.0, 1.25, 1.5)),
        "beta": _grid(params, "beta", float(base["beta"]), (0.5, 0.75, 1.0, 1.25, 1.5)),
        "tau": _grid(params, "tau", float(base["tau"]), (0.5, 0.75, 1.0, 1.25, 1.5)),
        "tau_review": _grid(params, "tau_review", float(base.get("tau_review", base["tau"])),
                            (0.5, 0.75, 1.0, 1.25, 1.5)),
        "theta_mule": _grid(params, "theta_mule", float(base["theta_mule"]), (0.75, 0.875, 1.0, 1.1, 1.18)),
    }
    scores = _score(ctx, df)
    reference_decisions = _decisions(ctx, df, scores, base)
    cap = float(params.get("naive_amount_cap", base["stipend_cap"]))
    legacy = _baseline_decisions(df, scores["p_legacy_raw"], ctx.bundle.legacy_threshold, None)
    naive = _baseline_decisions(df, scores["p_legacy_raw"], ctx.bundle.legacy_threshold, cap)
    references = {
        "legacy": _metrics(df, legacy, reference_decisions, scores),
        "naive_relaxed": _metrics(df, naive, reference_decisions, scores),
    }
    points = []
    for name, values in grids.items():
        for value in values:
            policy = {**base, name: value}
            decisions = _decisions(ctx, df, scores, policy)
            metrics = _metrics(df, decisions, decisions, scores)
            point_references = {
                "legacy": _metrics(df, legacy, decisions, scores),
                "naive_relaxed": _metrics(df, naive, decisions, scores),
            }
            loses = [
                baseline for baseline, result in point_references.items()
                if metrics["total_expected_harm_rupees"] > result["total_expected_harm_rupees"]
            ]
            points.append({"parameter": name, "value": value, "metrics": metrics,
                           "baselines": point_references, "loses_to": loses})
    return {"suite_rows": len(df), "suite_source": source, "base_policy": base, "grids": grids,
            "baselines": references, "points": points}


def _variant_detection(ctx, df: pd.DataFrame, policy: dict, variant: str) -> dict:
    test = df
    target = test[(test["population"] == "syndicate") & (test["variant"] == variant)].reset_index(drop=True)
    if target.empty:
        raise ValueError(f"evaluation data contains no syndicate rows for variant {variant!r}")
    scores = _score(ctx, target)
    decisions = _decisions(ctx, target, scores, policy)
    detected = decisions["decision"].isin(["HOLD", "REVIEW"])

    original = np.asarray(scores["p_mule"], float)
    drops = {}
    for feature in MODEL_B_FEATURES:
        perturbed = target.copy()
        perturbed[feature] = float(test.loc[test["is_mule_recipient"] == 0, feature].median())
        changed = np.asarray(_score(ctx, perturbed)["p_mule"], float)
        drops[feature] = float(np.mean(original - changed))
    strongest = max(drops, key=drops.get)
    return {
        "variant": variant,
        "rows": len(target),
        "detection_rate": float(detected.mean()),
        "hold_rate": float((decisions["decision"] == "HOLD").mean()),
        "review_rate": float((decisions["decision"] == "REVIEW").mean()),
        "mean_p_mule": float(original.mean()),
        "strongest_remaining_feature": strongest,
        "mean_p_mule_drop_when_neutralized": drops[strongest],
        "feature_neutralization_drops": drops,
    }


def redteam(ctx, params: dict) -> dict:
    """Evaluate independent adaptive syndicate datasets generated by data.generate."""
    _require_real_bundle(ctx)
    params = dict(params or {})
    policy = {**ctx.policy, **dict(params.get("policy", {}))}
    tags = {**DEFAULT_TAGS, **dict(params.get("tags", {}))}
    base_df = _read_payments(params, str(params.get("base_tag", params.get("suite_tag", "eval"))))
    base_variant = str(params.get("base_variant", "base"))
    base = _variant_detection(ctx, base_df, policy, base_variant)
    results = []
    for variant in REDTEAM_VARIANTS:
        item = _variant_detection(ctx, _read_payments(params, tags[variant]), policy, variant)
        item["detection_change_vs_base"] = item["detection_rate"] - base["detection_rate"]
        item["nyaya_weakens"] = item["detection_rate"] < base["detection_rate"]
        results.append(item)
    return {"policy": policy, "base": base, "variants": results, "model": ctx.bundle.info()}


def write_result(path: Path, result: dict) -> None:
    """Write an explicitly requested runtime result; generated files remain untracked."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2))
