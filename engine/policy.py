"""Expected-harm decision policy (plan section 5.6).

    H_F = P(fraud) * amount                                   expected loss if we let it through
    H_H = (1 - P(fraud)) * beta * exp(alpha * S) * urgency    expected harm of blocking a legitimate payer
    delta = H_F - H_H

    HOLD    P(mule) >= theta_mule, or delta >= tau
    REVIEW  not HOLD, and (conformal set is not a single label (both or empty) or delta > -tau_review): pay the stipend now, escrow the rest
            (tau_review defaults to tau, which is the plan's |delta| < tau band; it can be set lower to narrow it)
    RELEASE otherwise

S is the zone severity tier (0 outside a declared zone). A REVIEW whose amount already fits inside the stipend
cap would escrow nothing, so it is a RELEASE.
"""
from __future__ import annotations

import math

ENGINE_VERSION = "engine-1"


def urgency(tx: dict, policy: dict) -> float:
    if tx.get("urgency") is not None:
        try:
            u = float(tx["urgency"])
            if not math.isnan(u) and u > 0:
                return u
        except (ValueError, TypeError):
            pass
    cats = policy.get("urgency_by_category") or {}
    cat = tx.get("merchant_category") or "p2p"
    try:
        return float(cats.get(cat, 1.0) or 1.0)
    except (ValueError, TypeError):
        return 1.0


def severity(tx: dict) -> int:
    if not tx.get("in_disaster_zone"):
        return 0
    try:
        s = int(float(tx.get("severity_tier", 0) or 0))
        return max(0, min(5, s))
    except (ValueError, TypeError, OverflowError):
        return 0


def harms(p_fraud: float, tx: dict, policy: dict) -> tuple[float, float]:
    """(H_F, H_H) in rupees."""
    p_clamped = max(0.0, min(1.0, p_fraud))
    amount = max(0.0, float(tx.get("amount", 0.0) or 0.0))
    beta = max(0.0, float(policy.get("beta", 300.0)))
    h_fraud = p_clamped * amount
    h_hold = (1.0 - p_clamped) * beta * math.exp(float(policy["alpha"]) * severity(tx)) * urgency(tx, policy)
    return h_fraud, h_hold


def decide(scores: dict, tx: dict, policy: dict) -> dict:
    p = float(scores["p_fraud"])
    p_mule = float(scores.get("p_mule", 0.0) or 0.0)
    amount = max(0.0, float(tx.get("amount", 0.0) or 0.0))

    # Fail-safe check: corrupted or NaN scores must never silently trigger RELEASE
    if math.isnan(p) or math.isnan(p_mule) or math.isnan(amount) or math.isinf(p) or p < 0.0:
        if math.isnan(p) or math.isnan(p_mule) or p > 0.5 or math.isinf(p):
            decision, release_now = "HOLD", 0.0
        else:
            decision, release_now = "HOLD", 0.0
        return {"decision": decision, "release_now": 0.0, "escrow": 0.0,
                "harm_delta": 0.0, "h_fraud": 0.0, "h_hold": 0.0}

    h_fraud, h_hold = harms(p, tx, policy)
    delta = h_fraud - h_hold
    tau = float(policy["tau"])
    tau_review = float(policy.get("tau_review", tau))  # plan: |delta| < tau, i.e. tau_review == tau
    cap = float(policy["stipend_cap"])
    
    # Safe conformal set handling (supports None, list, set, tuple, and duplicate labels)
    raw_cset = scores.get("conformal_set")
    cset = list(raw_cset) if raw_cset is not None else ["legit"]
    uncertain = len(set(cset)) != 1  # {legit, fraud} or empty = unsure

    if p_mule >= float(policy["theta_mule"]) or delta >= tau:
        decision, release_now = "HOLD", 0.0
    elif (uncertain or delta > -tau_review) and amount > cap:
        decision, release_now = "REVIEW", cap
    else:
        decision, release_now = "RELEASE", amount
    escrow = round(amount - release_now, 2) if decision == "REVIEW" else 0.0
    return {"decision": decision, "release_now": round(release_now, 2), "escrow": escrow,
            "harm_delta": round(delta, 2), "h_fraud": round(h_fraud, 2), "h_hold": round(h_hold, 2)}
