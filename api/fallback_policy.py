"""Expected-harm decision table from the plan (§5.6). Used only until Kaustub's engine/ package lands.

One addition: a REVIEW whose amount fits inside the stipend cap would escrow nothing, so it is a RELEASE.
"""
from __future__ import annotations

import math

ENGINE_VERSION = "api-fallback"


def urgency(tx: dict, policy: dict) -> float:
    if tx.get("urgency") is not None:
        return float(tx["urgency"])
    return float(policy.get("urgency_by_category", {}).get(tx.get("merchant_category", "p2p"), 1.0))


def decide(scores: dict, tx: dict, policy: dict) -> dict:
    p = float(scores["p_fraud"])
    amount = float(tx["amount"])
    s = int(tx.get("severity_tier", 0)) if tx.get("in_disaster_zone") else 0
    h_fraud = p * amount
    h_hold = (1 - p) * float(policy["beta"]) * math.exp(float(policy["alpha"]) * s) * urgency(tx, policy)
    delta = h_fraud - h_hold
    tau = float(policy["tau"])
    if float(scores.get("p_mule", 0.0)) >= float(policy["theta_mule"]) or delta >= tau:
        decision, release_now = "HOLD", 0.0
    elif (len(scores.get("conformal_set", [])) > 1 or abs(delta) < tau) and amount > float(policy["stipend_cap"]):
        decision, release_now = "REVIEW", float(policy["stipend_cap"])
    else:
        decision, release_now = "RELEASE", amount
    return {"decision": decision, "release_now": round(release_now, 2), "escrow": round(amount - release_now, 2)
            if decision == "REVIEW" else 0.0, "harm_delta": round(delta, 2), "h_fraud": round(h_fraud, 2),
            "h_hold": round(h_hold, 2)}
