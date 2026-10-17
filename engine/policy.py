"""Expected-harm decision policy (plan section 5.6).

    H_F = P(fraud) * amount                                   expected loss if we let it through
    H_H = (1 - P(fraud)) * beta * exp(alpha * S) * urgency    expected harm of blocking a legitimate payer
    delta = H_F - H_H

    HOLD    P(mule) >= theta_mule, or delta >= tau
    REVIEW  not HOLD, and (conformal set is {legit, fraud} or |delta| < tau): pay the stipend now, escrow the rest
    RELEASE otherwise

S is the zone severity tier (0 outside a declared zone). A REVIEW whose amount already fits inside the stipend
cap would escrow nothing, so it is a RELEASE.
"""
from __future__ import annotations

import math

ENGINE_VERSION = "engine-1"


def urgency(tx: dict, policy: dict) -> float:
    if tx.get("urgency") is not None:
        return float(tx["urgency"])
    return float(policy.get("urgency_by_category", {}).get(tx.get("merchant_category", "p2p"), 1.0))


def severity(tx: dict) -> int:
    return int(tx.get("severity_tier", 0) or 0) if tx.get("in_disaster_zone") else 0


def harms(p_fraud: float, tx: dict, policy: dict) -> tuple[float, float]:
    """(H_F, H_H) in rupees."""
    h_fraud = p_fraud * float(tx["amount"])
    h_hold = (1.0 - p_fraud) * float(policy["beta"]) * math.exp(float(policy["alpha"]) * severity(tx)) * urgency(tx, policy)
    return h_fraud, h_hold


def decide(scores: dict, tx: dict, policy: dict) -> dict:
    p = float(scores["p_fraud"])
    amount = float(tx["amount"])
    h_fraud, h_hold = harms(p, tx, policy)
    delta = h_fraud - h_hold
    tau = float(policy["tau"])
    cap = float(policy["stipend_cap"])
    uncertain = len(scores.get("conformal_set", [])) > 1

    if float(scores.get("p_mule", 0.0)) >= float(policy["theta_mule"]) or delta >= tau:
        decision, release_now = "HOLD", 0.0
    elif (uncertain or abs(delta) < tau) and amount > cap:
        decision, release_now = "REVIEW", cap
    else:
        decision, release_now = "RELEASE", amount
    escrow = round(amount - release_now, 2) if decision == "REVIEW" else 0.0
    return {"decision": decision, "release_now": round(release_now, 2), "escrow": escrow,
            "harm_delta": round(delta, 2), "h_fraud": round(h_fraud, 2), "h_hold": round(h_hold, 2)}
